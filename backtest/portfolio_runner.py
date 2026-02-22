"""Portfolio Backtester — Day-by-day multi-stock simulation

CTO R14.13 Phase B: Portfolio-level backtest with:
- Selection Priority: RS×0.5 + SQS×0.3 + RS_Momentum×0.2
- Position Sizing: Equal Weight (baseline) or Volatility-Adjusted Fixed Risk
- TAIEX Guard: 3-tier max positions based on MA200
- Crowdedness: Max 2 positions per sub-sector
- Hard Floor: ADV < 100 lots → excluded

Gemini conversation: ce94f8a78bb93401
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Optional
import warnings

from analysis.strategy_bold import (
    generate_bold_signals, compute_bold_exit,
    STRATEGY_BOLD_PARAMS,
)
from analysis.rs_scanner import compute_rs_ratio

warnings.filterwarnings("ignore")


# ============================================================
# Configuration
# ============================================================

PORTFOLIO_PARAMS = {
    # Capital & positions
    "initial_capital": 10_000_000,  # 10M NTD
    "max_positions": 10,
    "max_position_pct": 0.20,       # Max 20% per stock
    "min_position_ntd": 100_000,    # Min position size 100K NTD

    # Selection Priority weights (CTO approved)
    "rank_rs_weight": 0.5,          # RS Rating (120D)
    "rank_sqs_weight": 0.3,         # SQS (VCP Score)
    "rank_rs_momentum_weight": 0.2, # RS Momentum (5-day change)

    # SQS (Selection Quality Score) weights (CTO revised)
    "sqs_atr_weight": 0.4,         # (1 - ATR_tightness)
    "sqs_dryup_weight": 0.3,       # vol_dryup_count / 5
    "sqs_bb_weight": 0.2,          # (1 - BB_Width_Percentile)
    "sqs_vol_weight": 0.1,         # Volume Stability

    # Liquidity
    "adv_hard_floor_lots": 100,     # ADV < 100 lots → excluded
    "vol_stability_full_lots": 1000, # ADV >= 1000 → stability = 1.0

    # TAIEX Guard (3-tier)
    "taiex_guard_enabled": True,
    "taiex_ma200_full_slots": 10,   # > MA200: full deployment
    "taiex_ma200_cautious_slots": 5, # < MA200 but > 95%: cautious
    "taiex_ma200_defensive_slots": 3, # < 95% MA200: defensive
    "taiex_buffer_pct": 0.05,       # 5% buffer zone

    # Crowdedness
    "max_per_sector": 2,            # Max 2 positions per sub-sector

    # Position sizing mode
    "sizing_mode": "equal_weight",  # "equal_weight" or "vol_adjusted"
    "risk_per_trade": 0.008,        # [CTO R14.14v2] 0.8% of equity per trade
    "risk_per_trade_defensive": 0.004,  # [CTO R14.14v2] 0.4% when TAIEX < MA200

    # Lunger Filter (CTO R14.14v2 — DISABLED: Vol Gate is sufficient)
    "lunger_filter_enabled": False,     # [CTO APPROVED] Disabled — kills convexity
    "lunger_ma20_max_deviation": 0.15,  # Max 15% above MA20 at entry (if enabled)
    "lunger_dynamic_enabled": False,    # If True: max(12%, 2.5 * ATR_pct)
    "lunger_dynamic_floor": 0.12,       # Dynamic mode floor
    "lunger_dynamic_atr_mult": 2.5,     # Dynamic mode ATR multiplier

    # Volume Breakout Gate (CTO R14.14v2 — anti pts_abandon)
    "vol_breakout_gate_enabled": True,
    "vol_breakout_gate_ratio": 1.5,     # Breakout day volume > MA5_Vol × 1.5

    # Transaction costs (matching existing TRANSACTION_COST = 0.00785)
    "commission_rate": 0.001425,    # 0.1425% per side
    "tax_rate": 0.003,              # 0.3% sell tax
    "slippage": 0.001,              # 0.1% per side
}


@dataclass
class PortfolioTrade:
    """Single portfolio trade with metadata"""
    code: str
    name: str = ""
    date_open: str = ""
    date_close: str = ""
    price_open: float = 0.0
    price_close: float = 0.0
    shares: int = 0
    pnl: float = 0.0
    return_pct: float = 0.0
    exit_reason: str = ""
    entry_type: str = ""
    rank_score: float = 0.0
    rs_rating: float = 0.0
    sqs_score: float = 0.0
    sector: str = ""
    position_pct: float = 0.0  # % of equity at entry


@dataclass
class PortfolioResult:
    """Portfolio backtest result"""
    trades: list[PortfolioTrade] = field(default_factory=list)
    equity_curve: pd.DataFrame = field(default_factory=pd.DataFrame)

    # Performance
    total_return: float = 0.0
    annual_return: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    calmar_ratio: float = 0.0
    profit_factor: float = 0.0
    win_rate: float = 0.0
    total_trades: int = 0
    avg_return: float = 0.0
    avg_holding_days: float = 0.0

    # Portfolio stats
    max_positions_used: int = 0
    avg_positions: float = 0.0
    sector_concentration_max: float = 0.0
    taiex_guard_activations: int = 0

    params: dict = field(default_factory=dict)


# ============================================================
# SQS & Ranking
# ============================================================

def compute_sqs(atr_tightness: float, vol_dryup_count: int,
                bb_width_percentile: float, vol_stability: float,
                params: dict | None = None) -> float:
    """Compute Selection Quality Score (CTO revised formula)

    SQS = (1-ATR_t)×0.4 + (dryup/5)×0.3 + (1-BB_pct)×0.2 + Vol_S×0.1
    """
    p = params or PORTFOLIO_PARAMS
    score = (
        (1.0 - min(1.0, max(0.0, atr_tightness))) * p.get("sqs_atr_weight", 0.4) +
        min(1.0, vol_dryup_count / 5.0) * p.get("sqs_dryup_weight", 0.3) +
        (1.0 - min(1.0, max(0.0, bb_width_percentile))) * p.get("sqs_bb_weight", 0.2) +
        min(1.0, max(0.0, vol_stability)) * p.get("sqs_vol_weight", 0.1)
    )
    return round(score, 4)


def compute_rank_score(rs_rating: float, sqs: float, rs_momentum: float,
                       params: dict | None = None) -> float:
    """Compute Final Rank Score for candidate selection

    Final_Rank = RS×0.5 + SQS×0.3 + RS_Momentum×0.2
    """
    p = params or PORTFOLIO_PARAMS
    # Normalize RS to 0-1
    rs_norm = min(1.0, max(0.0, rs_rating / 100.0))
    # RS Momentum: normalize to 0-1 (clamp negative to 0)
    rs_mom_norm = min(1.0, max(0.0, rs_momentum))

    score = (
        rs_norm * p.get("rank_rs_weight", 0.5) +
        sqs * p.get("rank_sqs_weight", 0.3) +
        rs_mom_norm * p.get("rank_rs_momentum_weight", 0.2)
    )
    return round(score, 4)


# ============================================================
# TAIEX Guard
# ============================================================

def get_max_positions(taiex_price: float, taiex_ma200: float,
                      params: dict | None = None) -> int:
    """Determine max positions based on TAIEX vs MA200

    > MA200: full (10)
    < MA200 but > 95%: cautious (5)
    < 95% × MA200: defensive (3)
    """
    p = params or PORTFOLIO_PARAMS
    if not p.get("taiex_guard_enabled", True):
        return p.get("taiex_ma200_full_slots", 10)

    if np.isnan(taiex_price) or np.isnan(taiex_ma200) or taiex_ma200 <= 0:
        return p.get("taiex_ma200_full_slots", 10)

    buffer = p.get("taiex_buffer_pct", 0.05)
    if taiex_price >= taiex_ma200:
        return p.get("taiex_ma200_full_slots", 10)
    elif taiex_price >= taiex_ma200 * (1 - buffer):
        return p.get("taiex_ma200_cautious_slots", 5)
    else:
        return p.get("taiex_ma200_defensive_slots", 3)


# ============================================================
# Portfolio Backtester
# ============================================================

class PortfolioBacktester:
    """Day-by-day multi-stock portfolio simulation

    Workflow per day:
    1. Exit check for all held positions
    2. Generate signals for all stocks in universe
    3. Rank candidates by Final_Rank
    4. Apply TAIEX guard, crowdedness filter, ADV floor
    5. Allocate capital to top-N candidates
    """

    def __init__(self, params: dict | None = None):
        self.p = {**PORTFOLIO_PARAMS, **(params or {})}
        self.bold_params = {**STRATEGY_BOLD_PARAMS}

    def run(
        self,
        stock_data: dict[str, pd.DataFrame],
        stock_sectors: dict[str, str] | None = None,
        taiex_data: pd.DataFrame | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> PortfolioResult:
        """Run portfolio backtest

        Args:
            stock_data: {code: DataFrame with OHLCV} — all stocks, full history
            stock_sectors: {code: sector_name} — for crowdedness check
            taiex_data: DataFrame with TAIEX OHLCV (for TAIEX Guard)
            start_date: OOS start (only enter trades after this date)
            end_date: OOS end
        """
        p = self.p
        sectors = stock_sectors or {}

        # Step 1: Pre-compute signals for all stocks
        print("  Generating signals for all stocks...")
        signals_cache = {}
        for code, df in stock_data.items():
            try:
                sig_df = generate_bold_signals(df, params=self.bold_params)
                if sig_df is not None and len(sig_df) > 60:
                    signals_cache[code] = sig_df
            except Exception:
                continue
        print(f"  {len(signals_cache)} stocks with signals")

        # Step 2: Build common date index + pre-compute date lookups
        all_dates = set()
        # Pre-compute date string sets per stock for fast lookup
        stock_date_sets = {}  # {code: set of date_str}
        stock_date_to_idx = {}  # {code: {date_str: integer index}}
        for code, df in signals_cache.items():
            dates_str = df.index.strftime("%Y-%m-%d").tolist()
            all_dates.update(dates_str)
            stock_date_sets[code] = set(dates_str)
            stock_date_to_idx[code] = {d: i for i, d in enumerate(dates_str)}
        all_dates = sorted(all_dates)

        # Apply date filters
        if start_date:
            all_dates = [d for d in all_dates if d >= start_date]
        if end_date:
            all_dates = [d for d in all_dates if d <= end_date]

        if not all_dates:
            return PortfolioResult(params=p)

        # Step 3: Pre-compute TAIEX MA200
        taiex_ma200_cache = {}
        if taiex_data is not None and len(taiex_data) > 200:
            taiex_close = taiex_data["close"] if "close" in taiex_data.columns else taiex_data.get("Close", pd.Series())
            taiex_ma200 = taiex_close.rolling(200).mean()
            for date in taiex_close.index:
                d_str = str(date)[:10]
                if d_str in all_dates:
                    taiex_ma200_cache[d_str] = {
                        "price": float(taiex_close.loc[date]),
                        "ma200": float(taiex_ma200.loc[date]) if not np.isnan(taiex_ma200.loc[date]) else np.nan,
                    }

        # Step 4: Pre-compute RS for ranking (rolling 120D window)
        print("  Pre-computing RS rankings...")
        rs_cache = {}  # {code: {date_str: rs_value}}
        for code, df in signals_cache.items():
            rs_cache[code] = {}
            close = df["close"]
            for i in range(120, len(df)):
                date_str = str(df.index[i])[:10]
                if date_str not in all_dates:
                    continue
                # Simple RS: price / price_120d_ago
                p_now = close.iloc[i]
                p_120 = close.iloc[i - 120]
                p_20 = close.iloc[i - 20] if i >= 20 else p_now
                p_140 = close.iloc[i - 140] if i >= 140 else close.iloc[0]
                if p_120 > 0 and p_140 > 0:
                    base_ret = p_now / p_120
                    recent_ret = p_20 / p_140 if p_140 > 0 else 1.0
                    rs_val = (base_ret ** 0.6) * (recent_ret ** 0.4)
                    rs_cache[code][date_str] = rs_val

        # Compute RS percentile ranks per day
        rs_rank_cache = {}  # {date_str: {code: percentile_0_100}}
        for date_str in all_dates:
            day_rs = {}
            for code in signals_cache:
                if date_str in rs_cache.get(code, {}):
                    day_rs[code] = rs_cache[code][date_str]
            if len(day_rs) < 5:
                continue
            # Rank
            sorted_codes = sorted(day_rs.keys(), key=lambda c: day_rs[c])
            n = len(sorted_codes)
            rs_rank_cache[date_str] = {}
            for rank_idx, c in enumerate(sorted_codes):
                rs_rank_cache[date_str][c] = round(rank_idx / (n - 1) * 100, 1) if n > 1 else 50.0

        # Step 5: Day-by-day simulation
        print("  Running day-by-day simulation...")
        cash = float(p["initial_capital"])
        positions = {}  # {code: {shares, entry_price, entry_date, entry_atr, sector, peak_price, hold_days}}
        all_trades = []
        equity_history = []
        max_pos_used = 0
        total_pos_days = 0
        taiex_guard_count = 0

        adv_floor = p.get("adv_hard_floor_lots", 100)
        max_per_sector = p.get("max_per_sector", 2)

        # Track last known price per held stock
        last_known_price = {}  # {code: float}

        for day_idx, date_str in enumerate(all_dates):
            # --- A: Compute portfolio value ---
            port_value = cash
            for code, pos in positions.items():
                if date_str in stock_date_sets.get(code, set()):
                    idx = stock_date_to_idx[code][date_str]
                    current_price = float(signals_cache[code]["close"].iloc[idx])
                    last_known_price[code] = current_price
                    port_value += pos["shares"] * current_price
                elif code in last_known_price:
                    # Stock has no data today — use last known price
                    port_value += pos["shares"] * last_known_price[code]
                else:
                    # Fallback: use entry price
                    port_value += pos["shares"] * pos["entry_price"]

            equity_history.append({"date": date_str, "equity": port_value})
            total_pos_days += len(positions)
            max_pos_used = max(max_pos_used, len(positions))

            # --- B: Exit check for held positions ---
            codes_to_close = []
            for code, pos in positions.items():
                df = signals_cache[code]
                # Find this date in the stock's data (fast lookup)
                if date_str not in stock_date_sets.get(code, set()):
                    continue

                idx = stock_date_to_idx[code][date_str]
                row = df.iloc[idx]

                current_price = float(row["close"])
                current_high = float(row["high"]) if "high" in row else current_price
                current_low = float(row["low"]) if "low" in row else current_price
                current_atr = float(row.get("atr_20", 0)) if "atr_20" in df.columns else 0

                pos["hold_days"] += 1
                pos["peak_price"] = max(pos["peak_price"], current_high)

                # Get MA values for exit check
                _ma20 = float(row.get("ma20", np.nan)) if "ma20" in df.columns else None
                _ma5 = float(df["close"].rolling(5).mean().iloc[idx]) if idx >= 5 else None
                _ma10 = float(df["close"].rolling(10).mean().iloc[idx]) if idx >= 10 else None
                _vol_ma5 = float(df["volume"].rolling(5).mean().iloc[idx]) if idx >= 5 else None
                _vol_ma20 = float(df["volume"].rolling(20).mean().iloc[idx]) if idx >= 20 else None

                if _ma20 is not None and np.isnan(_ma20): _ma20 = None
                if _ma5 is not None and np.isnan(_ma5): _ma5 = None

                # MA slopes
                _ma20_slope = None
                if _ma20 is not None and idx >= 5:
                    _prev_ma20 = float(df["close"].rolling(20).mean().iloc[idx - 5]) if idx >= 25 else None
                    if _prev_ma20 and _prev_ma20 > 0:
                        _ma20_slope = (_ma20 / _prev_ma20 - 1)

                _ma200_slope = None
                if idx >= 220:
                    _ma200_now = float(df["close"].rolling(200).mean().iloc[idx])
                    _ma200_prev = float(df["close"].rolling(200).mean().iloc[idx - 20])
                    if _ma200_prev > 0 and not np.isnan(_ma200_now):
                        _ma200_slope = (_ma200_now / _ma200_prev - 1)

                exit_result = compute_bold_exit(
                    entry_price=pos["entry_price"],
                    current_price=current_price,
                    peak_price=pos["peak_price"],
                    current_atr=current_atr,
                    hold_days=pos["hold_days"],
                    params=self.bold_params,
                    ma200_slope=_ma200_slope,
                    entry_low=pos.get("entry_low"),
                    prev_day_low=pos.get("prev_day_low"),
                    current_ma20=_ma20,
                    ma20_slope=_ma20_slope,
                    current_vol_ma5=_vol_ma5,
                    current_vol_ma20=_vol_ma20,
                    current_ma5=_ma5,
                    current_ma10=_ma10,
                    entry_atr_tightness=pos.get("entry_atr"),
                )

                if exit_result["should_exit"]:
                    # Calculate PnL
                    exit_price = current_price
                    # Check if trail stop was hit intraday
                    trail_stop = exit_result.get("trailing_stop_price", 0)
                    if trail_stop > 0 and current_low <= trail_stop and trail_stop < current_price:
                        exit_price = trail_stop

                    gross_pnl = (exit_price - pos["entry_price"]) * pos["shares"]
                    # Costs: commission on both sides + tax on sell + slippage
                    entry_cost = pos["entry_price"] * pos["shares"] * (p["commission_rate"] + p["slippage"])
                    exit_cost = exit_price * pos["shares"] * (p["commission_rate"] + p["tax_rate"] + p["slippage"])
                    net_pnl = gross_pnl - entry_cost - exit_cost
                    return_pct = net_pnl / (pos["entry_price"] * pos["shares"])

                    trade = PortfolioTrade(
                        code=code,
                        name=stock_sectors.get(code, code) if stock_sectors else code,
                        date_open=pos["entry_date"],
                        date_close=date_str,
                        price_open=pos["entry_price"],
                        price_close=exit_price,
                        shares=pos["shares"],
                        pnl=net_pnl,
                        return_pct=return_pct,
                        exit_reason=exit_result["exit_reason"],
                        entry_type=pos.get("entry_type", ""),
                        rank_score=pos.get("rank_score", 0),
                        rs_rating=pos.get("rs_rating", 0),
                        sqs_score=pos.get("sqs_score", 0),
                        sector=pos.get("sector", ""),
                        position_pct=pos.get("position_pct", 0),
                    )
                    all_trades.append(trade)
                    cash += exit_price * pos["shares"] - exit_cost
                    codes_to_close.append(code)

            for code in codes_to_close:
                del positions[code]
                last_known_price.pop(code, None)

            # --- C: Check for end of period ---
            if day_idx == len(all_dates) - 1:
                # Close all remaining positions
                for code, pos in list(positions.items()):
                    df = signals_cache[code]
                    if date_str not in stock_date_sets.get(code, set()):
                        # Use last known price
                        close_price = last_known_price.get(code, pos["entry_price"])
                    else:
                        idx_c = stock_date_to_idx[code][date_str]
                        close_price = float(df["close"].iloc[idx_c])
                    gross_pnl = (close_price - pos["entry_price"]) * pos["shares"]
                    exit_cost = close_price * pos["shares"] * (p["commission_rate"] + p["tax_rate"] + p["slippage"])
                    entry_cost = pos["entry_price"] * pos["shares"] * (p["commission_rate"] + p["slippage"])
                    net_pnl = gross_pnl - entry_cost - exit_cost
                    return_pct = net_pnl / (pos["entry_price"] * pos["shares"])

                    all_trades.append(PortfolioTrade(
                        code=code, date_open=pos["entry_date"], date_close=date_str,
                        price_open=pos["entry_price"], price_close=close_price,
                        shares=pos["shares"], pnl=net_pnl, return_pct=return_pct,
                        exit_reason="end_of_period", entry_type=pos.get("entry_type", ""),
                        rank_score=pos.get("rank_score", 0),
                        rs_rating=pos.get("rs_rating", 0),
                        sector=pos.get("sector", ""),
                    ))
                    cash += close_price * pos["shares"] - exit_cost
                positions.clear()
                continue

            # --- D: Entry — find new candidates ---
            available_slots = p["max_positions"] - len(positions)

            # TAIEX Guard
            if date_str in taiex_ma200_cache:
                t = taiex_ma200_cache[date_str]
                max_slots = get_max_positions(t["price"], t["ma200"], p)
                if max_slots < p["max_positions"]:
                    taiex_guard_count += 1
                available_slots = min(available_slots, max_slots - len(positions))

            if available_slots <= 0:
                continue

            # Determine current risk regime (Volatility Scaling — CTO R14.14)
            is_defensive = False
            if date_str in taiex_ma200_cache:
                t = taiex_ma200_cache[date_str]
                if not np.isnan(t["ma200"]) and t["ma200"] > 0 and t["price"] < t["ma200"]:
                    is_defensive = True

            current_risk_per_trade = (
                p.get("risk_per_trade_defensive", 0.0025) if is_defensive
                else p.get("risk_per_trade", 0.005)
            )

            # Scan for BUY signals
            candidates = []
            held_codes = set(positions.keys())

            for code, df in signals_cache.items():
                if code in held_codes:
                    continue

                # Fast date lookup
                if date_str not in stock_date_sets.get(code, set()):
                    continue

                idx = stock_date_to_idx[code][date_str]
                row = df.iloc[idx]

                signal = row.get("bold_signal", "")
                if signal != "BUY":
                    continue

                # ADV Hard Floor
                if idx >= 20 and "volume" in df.columns:
                    adv_20 = float(df["volume"].iloc[max(0, idx-20):idx].mean()) / 1000  # lots
                    if adv_20 < adv_floor:
                        continue
                else:
                    continue

                # Lunger Filter (CTO R14.14v2) — skip if price too far above MA20
                if p.get("lunger_filter_enabled", True) and "ma20" in df.columns:
                    _ma20_val = float(row.get("ma20", np.nan))
                    if not np.isnan(_ma20_val) and _ma20_val > 0:
                        deviation = (float(row["close"]) - _ma20_val) / _ma20_val
                        # Dynamic threshold: max(floor, 2.5 * ATR_pct)
                        if p.get("lunger_dynamic_enabled", False):
                            _atr_val = float(row.get("atr_20", 0)) if "atr_20" in df.columns else 0
                            _atr_pct = _atr_val / float(row["close"]) if float(row["close"]) > 0 and _atr_val > 0 else 0.03
                            lunger_limit = max(
                                p.get("lunger_dynamic_floor", 0.12),
                                p.get("lunger_dynamic_atr_mult", 2.5) * _atr_pct
                            )
                        else:
                            lunger_limit = p.get("lunger_ma20_max_deviation", 0.15)
                        if deviation > lunger_limit:
                            continue

                # Volume Breakout Gate (CTO R14.14v2) — breakout day volume > MA5 × 1.5
                if p.get("vol_breakout_gate_enabled", True) and idx >= 5 and "volume" in df.columns:
                    _vol_today = float(row.get("volume", 0))
                    _vol_ma5 = float(df["volume"].iloc[max(0, idx-5):idx].mean())
                    _vol_ratio = p.get("vol_breakout_gate_ratio", 1.5)
                    if _vol_ma5 > 0 and _vol_today < _vol_ma5 * _vol_ratio:
                        continue

                # Get metrics for ranking
                atr_tight = float(row.get("bold_atr_tightness", 0.5))
                if np.isnan(atr_tight):
                    atr_tight = 0.5

                # Volume dryup count
                vol_dryup = 0
                if idx >= 5 and "volume" in df.columns:
                    vol_ma20 = df["volume"].rolling(20).mean()
                    threshold = vol_ma20.iloc[idx] * self.bold_params.get("vcp_vol_dryup_ratio", 0.5)
                    for j in range(max(0, idx - 5), idx):
                        if df["volume"].iloc[j] < threshold:
                            vol_dryup += 1

                # BB Width Percentile
                bb_width_pct = 0.5
                if "bb_upper" in df.columns and "bb_lower" in df.columns and "bb_middle" in df.columns:
                    bb_w = (df["bb_upper"] - df["bb_lower"]) / df["bb_middle"]
                    if idx >= 120:
                        current_bw = bb_w.iloc[idx]
                        hist_bw = bb_w.iloc[idx-120:idx]
                        if len(hist_bw) > 0 and not np.isnan(current_bw):
                            bb_width_pct = float((hist_bw < current_bw).sum() / len(hist_bw))

                # Volume Stability
                adv_lots = float(df["volume"].iloc[max(0, idx-20):idx].mean()) / 1000
                vol_stability = min(1.0, adv_lots / p.get("vol_stability_full_lots", 1000))

                # RS Rating
                rs_rating = rs_rank_cache.get(date_str, {}).get(code, 50.0)

                # RS Momentum (5-day change in RS rank)
                rs_momentum = 0.0
                if day_idx >= 5:
                    prev_date = all_dates[day_idx - 5]
                    prev_rs = rs_rank_cache.get(prev_date, {}).get(code, rs_rating)
                    rs_momentum = (rs_rating - prev_rs) / 100.0  # Normalize to 0-1 range
                    rs_momentum = max(0.0, rs_momentum)  # Only positive momentum

                # Compute SQS and Rank
                sqs = compute_sqs(atr_tight, vol_dryup, bb_width_pct, vol_stability, p)
                rank = compute_rank_score(rs_rating, sqs, rs_momentum, p)

                entry_type = str(row.get("bold_entry_type", ""))
                sector = sectors.get(code, "unknown")

                candidates.append({
                    "code": code,
                    "price": float(row["close"]),
                    "high": float(row.get("high", row["close"])),
                    "low": float(row.get("low", row["close"])),
                    "rank": rank,
                    "rs_rating": rs_rating,
                    "sqs": sqs,
                    "rs_momentum": rs_momentum,
                    "atr_tightness": atr_tight,
                    "entry_type": entry_type,
                    "sector": sector,
                    "adv_lots": adv_lots,
                    "volume": float(row.get("volume", 0)),
                })

            if not candidates:
                continue

            # Sort by rank (descending)
            candidates.sort(key=lambda c: c["rank"], reverse=True)

            # Apply crowdedness filter
            sector_count = {}
            for code, pos in positions.items():
                s = pos.get("sector", "unknown")
                sector_count[s] = sector_count.get(s, 0) + 1

            # Allocate to top candidates
            entries_today = 0
            for cand in candidates:
                if entries_today >= available_slots:
                    break

                # Crowdedness check
                cand_sector = cand["sector"]
                if sector_count.get(cand_sector, 0) >= max_per_sector:
                    continue

                # Position sizing
                equity = cash + sum(
                    pos["shares"] * cand.get("price", pos["entry_price"])
                    for pos in positions.values()
                )

                if p["sizing_mode"] == "equal_weight":
                    # Equal weight: divide equally among max positions
                    pos_size = min(
                        equity * p["max_position_pct"],
                        equity / p["max_positions"]
                    )
                else:
                    # Vol-adjusted: Fixed Risk (CTO R14.14)
                    # Shares = (Equity * Risk%) / (Entry - Stop)
                    # Stop = Entry × (1 - stop_pct), using disaster_stop_pct
                    stop_pct = self.bold_params.get("disaster_stop_pct", 0.15)
                    stop_distance = cand["price"] * stop_pct
                    if stop_distance > 0:
                        pos_size = (equity * current_risk_per_trade) / stop_distance * cand["price"]
                    else:
                        pos_size = equity / p["max_positions"]
                    pos_size = min(pos_size, equity * p["max_position_pct"])

                if pos_size < p["min_position_ntd"]:
                    continue
                if pos_size > cash:
                    pos_size = cash

                # Calculate shares (round to lot = 1000 shares)
                shares = int(pos_size / cand["price"] / 1000) * 1000
                if shares <= 0:
                    continue

                actual_cost = shares * cand["price"]
                entry_commission = actual_cost * (p["commission_rate"] + p["slippage"])

                if actual_cost + entry_commission > cash:
                    continue

                # Execute entry
                cash -= (actual_cost + entry_commission)
                positions[cand["code"]] = {
                    "shares": shares,
                    "entry_price": cand["price"],
                    "entry_date": date_str,
                    "entry_atr": cand["atr_tightness"],
                    "entry_type": cand["entry_type"],
                    "sector": cand_sector,
                    "peak_price": cand["high"],
                    "hold_days": 0,
                    "entry_low": cand["low"],
                    "prev_day_low": cand["low"],  # Simplified
                    "rank_score": cand["rank"],
                    "rs_rating": cand["rs_rating"],
                    "sqs_score": cand["sqs"],
                    "position_pct": actual_cost / equity if equity > 0 else 0,
                }
                sector_count[cand_sector] = sector_count.get(cand_sector, 0) + 1
                entries_today += 1

        # Step 6: Compute results
        eq_df = pd.DataFrame(equity_history)
        if len(eq_df) == 0:
            return PortfolioResult(params=p)

        eq_df["date"] = pd.to_datetime(eq_df["date"])
        eq_df = eq_df.set_index("date")

        daily_returns = eq_df["equity"].pct_change().dropna()
        total_return = (eq_df["equity"].iloc[-1] / eq_df["equity"].iloc[0]) - 1
        n_days = len(eq_df)
        annual_return = (1 + total_return) ** (252 / max(1, n_days)) - 1

        # Max drawdown
        running_max = eq_df["equity"].cummax()
        drawdown = (eq_df["equity"] - running_max) / running_max
        max_dd = float(drawdown.min())

        # Sharpe & Calmar
        if len(daily_returns) > 1 and daily_returns.std() > 0:
            sharpe = float(daily_returns.mean() / daily_returns.std() * np.sqrt(252))
        else:
            sharpe = 0.0
        calmar = annual_return / abs(max_dd) if max_dd < 0 else 0.0

        # Trade stats
        wins = [t for t in all_trades if t.return_pct > 0]
        losses = [t for t in all_trades if t.return_pct <= 0]
        win_rate = len(wins) / len(all_trades) * 100 if all_trades else 0
        pf = (sum(t.pnl for t in wins) / abs(sum(t.pnl for t in losses))
              if losses and sum(t.pnl for t in losses) != 0 else 0)
        avg_ret = np.mean([t.return_pct for t in all_trades]) if all_trades else 0

        avg_hold = np.mean([
            (pd.Timestamp(t.date_close) - pd.Timestamp(t.date_open)).days
            for t in all_trades if t.date_close and t.date_open
        ]) if all_trades else 0

        result = PortfolioResult(
            trades=all_trades,
            equity_curve=eq_df,
            total_return=round(total_return * 100, 2),
            annual_return=round(annual_return * 100, 2),
            max_drawdown=round(max_dd * 100, 2),
            sharpe_ratio=round(sharpe, 2),
            calmar_ratio=round(calmar, 2),
            profit_factor=round(pf, 2),
            win_rate=round(win_rate, 1),
            total_trades=len(all_trades),
            avg_return=round(avg_ret * 100, 2),
            avg_holding_days=round(avg_hold, 1),
            max_positions_used=max_pos_used,
            avg_positions=round(total_pos_days / max(1, n_days), 1),
            taiex_guard_activations=taiex_guard_count,
            params=p,
        )

        return result


def print_portfolio_report(result: PortfolioResult):
    """Print formatted portfolio backtest report"""
    print(f"\n{'='*70}")
    print(f"  PORTFOLIO BACKTEST REPORT")
    print(f"{'='*70}")
    print(f"  Total Return:      {result.total_return:+.2f}%")
    print(f"  Annual Return:     {result.annual_return:+.2f}%")
    print(f"  Max Drawdown:      {result.max_drawdown:.2f}%")
    print(f"  Sharpe Ratio:      {result.sharpe_ratio:.2f}")
    print(f"  Calmar Ratio:      {result.calmar_ratio:.2f}")
    print(f"  Profit Factor:     {result.profit_factor:.2f}")
    print(f"  Win Rate:          {result.win_rate:.1f}%")
    print(f"  Total Trades:      {result.total_trades}")
    print(f"  Avg Return:        {result.avg_return:+.2f}%")
    print(f"  Avg Hold Days:     {result.avg_holding_days:.1f}")
    print(f"  Max Positions:     {result.max_positions_used}")
    print(f"  Avg Positions:     {result.avg_positions:.1f}")
    print(f"  TAIEX Guard:       {result.taiex_guard_activations} activations")
    print(f"{'='*70}")

    if result.trades:
        # Entry type distribution
        from collections import Counter
        types = Counter(t.entry_type for t in result.trades)
        print("\nEntry Type Distribution:")
        for etype, count in types.most_common():
            type_trades = [t for t in result.trades if t.entry_type == etype]
            wr = sum(1 for t in type_trades if t.return_pct > 0) / len(type_trades) * 100
            avg = np.mean([t.return_pct for t in type_trades]) * 100
            print(f"  {etype or 'unknown'}: {count} trades, WR={wr:.0f}%, AvgRet={avg:+.1f}%")

        # Exit reason distribution
        reasons = Counter(t.exit_reason for t in result.trades)
        print("\nExit Reason Distribution:")
        for reason, count in reasons.most_common():
            reason_trades = [t for t in result.trades if t.exit_reason == reason]
            wr = sum(1 for t in reason_trades if t.return_pct > 0) / len(reason_trades) * 100
            avg = np.mean([t.return_pct for t in reason_trades]) * 100
            print(f"  {reason}: {count} trades, WR={wr:.0f}%, AvgRet={avg:+.1f}%")

        # Top 5 / Bottom 5 trades
        sorted_trades = sorted(result.trades, key=lambda t: t.return_pct, reverse=True)
        print("\nTop 5 Trades:")
        for t in sorted_trades[:5]:
            print(f"  {t.code} {t.date_open}→{t.date_close}: {t.return_pct*100:+.1f}% ({t.exit_reason})")
        print("\nBottom 5 Trades:")
        for t in sorted_trades[-5:]:
            print(f"  {t.code} {t.date_open}→{t.date_close}: {t.return_pct*100:+.1f}% ({t.exit_reason})")
