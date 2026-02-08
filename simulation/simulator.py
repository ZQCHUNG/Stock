"""一個月模擬交易模組

使用最近一個月的資料，依策略訊號模擬每日進出場。
追蹤持倉、現金、總資產變化，輸出每日交易明細與績效報告。
"""

import math
import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from config import BACKTEST_PARAMS, RISK_PARAMS, TRADE_UNIT, STRATEGY_V4_PARAMS
from analysis.strategy import generate_signals
from analysis.strategy_v4 import generate_v4_signals


def _safe(val, default=0.0):
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return default
    return float(val)


@dataclass
class DailyRecord:
    """每日模擬紀錄"""
    date: pd.Timestamp
    close: float
    signal: str
    action: str  # "買入", "賣出", "持有", "空手觀望"
    shares: int
    cash: float
    position_value: float
    total_equity: float
    daily_pnl: float
    daily_return: float
    composite_score: float


@dataclass
class SimulationResult:
    """模擬結果"""
    daily_records: list[DailyRecord] = field(default_factory=list)
    trade_log: list[dict] = field(default_factory=list)

    # 期間績效
    initial_capital: float = 0.0
    final_equity: float = 0.0
    total_return: float = 0.0
    max_drawdown: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_commission: float = 0.0
    total_tax: float = 0.0


class MonthlySimulator:
    """一個月模擬交易器

    使用方式：
        sim = MonthlySimulator(initial_capital=1_000_000)
        result = sim.run(df)
    """

    def __init__(
        self,
        initial_capital: float | None = None,
        commission_rate: float | None = None,
        tax_rate: float | None = None,
    ):
        self.initial_capital = initial_capital or BACKTEST_PARAMS["initial_capital"]
        self.commission_rate = commission_rate or BACKTEST_PARAMS["commission_rate"]
        self.tax_rate = tax_rate or BACKTEST_PARAMS["tax_rate"]

    def run(self, df: pd.DataFrame, days: int = 30) -> SimulationResult:
        """執行模擬（v3：ATR 動態停損停利 + 部位管理 + 最短持有期）

        Args:
            df: 原始股價 DataFrame（需包含足夠的歷史資料供指標計算）
            days: 模擬交易天數（預設 30 個交易日）

        Returns:
            SimulationResult
        """
        # 先用全部資料算指標和訊號，再取最後 N 個交易日來模擬
        signals_df = generate_signals(df)
        sim_df = signals_df.tail(days)

        # 風控參數
        use_atr = RISK_PARAMS.get("use_atr_stops", False)
        stop_loss_pct = RISK_PARAMS.get("stop_loss", 0.07)
        trailing_stop_pct = RISK_PARAMS.get("trailing_stop", 0.05)
        atr_sl_mult = RISK_PARAMS.get("atr_stop_loss_mult", 3.0)
        atr_ts_mult = RISK_PARAMS.get("atr_trailing_mult", 2.5)
        max_position_pct = RISK_PARAMS.get("max_position_pct", 0.5)
        min_hold_days = RISK_PARAMS.get("min_hold_days", 0)

        cash = self.initial_capital
        position = 0
        entry_price = 0.0
        highest_since_entry = 0.0
        entry_atr = 0.0
        hold_day_count = 0
        prev_equity = self.initial_capital

        result = SimulationResult(initial_capital=self.initial_capital)
        total_commission = 0.0
        total_tax = 0.0

        for date, row in sim_df.iterrows():
            price = row["close"]
            high = row.get("high", price)
            signal = row["signal"]
            current_atr = row.get("atr", 0.0)
            action = ""
            trade_info = None

            # 更新持倉期間最高價
            if position > 0:
                highest_since_entry = max(highest_since_entry, high)
                hold_day_count += 1

            # ===== 風控檢查 =====
            force_sell = False
            exit_reason = ""

            if position > 0 and entry_price > 0:
                if hold_day_count <= min_hold_days:
                    pass  # 最短持有期未滿
                elif use_atr and entry_atr > 0:
                    # v3: ATR 動態停損停利
                    sl_distance = entry_atr * atr_sl_mult
                    ts_distance = entry_atr * atr_ts_mult
                    if price <= entry_price - sl_distance:
                        force_sell = True
                        exit_reason = "停損"
                    elif highest_since_entry > entry_price and \
                         price <= highest_since_entry - ts_distance:
                        force_sell = True
                        exit_reason = "移動停利"
                else:
                    # v2 fallback
                    if price <= entry_price * (1 - stop_loss_pct):
                        force_sell = True
                        exit_reason = "停損"
                    elif highest_since_entry > entry_price and \
                         price <= highest_since_entry * (1 - trailing_stop_pct):
                        force_sell = True
                        exit_reason = "移動停利"

            if force_sell and position > 0:
                revenue = position * price
                commission = revenue * self.commission_rate
                tax = revenue * self.tax_rate
                net_revenue = revenue - commission - tax
                cash += net_revenue

                pnl = (price - entry_price) * position - commission - tax
                total_commission += commission
                total_tax += tax

                action = f"賣出（{exit_reason}）"
                trade_info = {
                    "日期": date,
                    "動作": action,
                    "股數": position,
                    "價格": price,
                    "手續費": round(commission, 0),
                    "交易稅": round(tax, 0),
                    "損益": round(pnl, 0),
                }

                if pnl > 0:
                    result.winning_trades += 1
                else:
                    result.losing_trades += 1
                result.total_trades += 1

                position = 0
                entry_price = 0.0
                highest_since_entry = 0.0
                entry_atr = 0.0
                hold_day_count = 0

            # ===== 正常訊號交易 =====
            elif signal == "BUY" and position == 0:
                available = cash * max_position_pct
                max_shares = int(
                    available / (price * TRADE_UNIT * (1 + self.commission_rate))
                ) * TRADE_UNIT
                if max_shares >= TRADE_UNIT:
                    position = max_shares
                    cost = position * price
                    commission = cost * self.commission_rate
                    cash -= cost + commission
                    entry_price = price
                    entry_atr = current_atr  # v3: 記錄進場 ATR
                    hold_day_count = 0       # v3: 重置持有天數
                    highest_since_entry = high
                    total_commission += commission
                    action = "買入"
                    trade_info = {
                        "日期": date,
                        "動作": "買入",
                        "股數": position,
                        "價格": price,
                        "手續費": round(commission, 0),
                        "金額": round(cost + commission, 0),
                    }
                else:
                    action = "資金不足"

            elif signal == "SELL" and position > 0:
                # 訊號賣出
                revenue = position * price
                commission = revenue * self.commission_rate
                tax = revenue * self.tax_rate
                net_revenue = revenue - commission - tax
                cash += net_revenue

                pnl = (price - entry_price) * position - commission - tax
                total_commission += commission
                total_tax += tax

                action = "賣出（訊號）"
                trade_info = {
                    "日期": date,
                    "動作": action,
                    "股數": position,
                    "價格": price,
                    "手續費": round(commission, 0),
                    "交易稅": round(tax, 0),
                    "損益": round(pnl, 0),
                }

                if pnl > 0:
                    result.winning_trades += 1
                else:
                    result.losing_trades += 1
                result.total_trades += 1

                position = 0
                entry_price = 0.0
                highest_since_entry = 0.0
                entry_atr = 0.0
                hold_day_count = 0

            else:
                action = "持有" if position > 0 else "空手觀望"

            if trade_info:
                result.trade_log.append(trade_info)

            # 計算權益
            position_value = position * price
            equity = cash + position_value
            daily_pnl = equity - prev_equity
            daily_return = daily_pnl / prev_equity if prev_equity > 0 else 0

            result.daily_records.append(DailyRecord(
                date=date,
                close=price,
                signal=signal,
                action=action,
                shares=position,
                cash=round(cash, 0),
                position_value=round(position_value, 0),
                total_equity=round(equity, 0),
                daily_pnl=round(daily_pnl, 0),
                daily_return=daily_return,
                composite_score=row["composite_score"],
            ))

            prev_equity = equity

        # 計算最終績效
        if result.daily_records:
            result.final_equity = result.daily_records[-1].total_equity
            result.total_return = (result.final_equity - self.initial_capital) / self.initial_capital
            result.total_commission = total_commission
            result.total_tax = total_tax

            # 最大回撤
            equities = [r.total_equity for r in result.daily_records]
            peak = equities[0]
            max_dd = 0
            for eq in equities:
                if eq > peak:
                    peak = eq
                dd = (eq - peak) / peak
                if dd < max_dd:
                    max_dd = dd
            result.max_drawdown = max_dd

        return result


    def run_v4(self, df: pd.DataFrame, days: int = 30, params: dict | None = None) -> SimulationResult:
        """執行 v4 模擬（趨勢動量 + 支撐進場 + 移動停利停損）"""
        p = dict(STRATEGY_V4_PARAMS)
        if params:
            p.update(params)

        signals_df = generate_v4_signals(df, params=p)
        sim_df = signals_df.tail(days)

        tp_pct = p.get("take_profit_pct", 0.10)
        sl_pct = p.get("stop_loss_pct", 0.07)
        trailing_pct = p.get("trailing_stop_pct", 0.02)
        max_pos_pct = p.get("max_position_pct", 0.9)
        min_hold = p.get("min_hold_days", 5)

        cash = self.initial_capital
        position = 0
        entry_price = 0.0
        tp_price = 0.0
        sl_price = 0.0
        original_sl_price = 0.0
        highest_since_entry = 0.0
        hold_days = 0
        prev_equity = self.initial_capital

        result = SimulationResult(initial_capital=self.initial_capital)
        total_commission = 0.0
        total_tax = 0.0

        for date, row in sim_df.iterrows():
            price = row["close"]
            high = row.get("high", price)
            low = row.get("low", price)
            signal = row.get("v4_signal", "HOLD")
            action = ""
            trade_info = None

            if position > 0:
                highest_since_entry = max(highest_since_entry, high)
                hold_days += 1

                # 移動停利
                if trailing_pct > 0:
                    new_sl = highest_since_entry * (1 - trailing_pct)
                    if new_sl > sl_price:
                        sl_price = new_sl

            # ===== 出場檢查（用 high/low 偵測） =====
            force_sell = False
            exit_reason = ""
            exit_price = 0.0

            if position > 0 and hold_days >= min_hold:
                if tp_pct > 0 and high >= tp_price and low <= sl_price:
                    if price >= entry_price:
                        force_sell, exit_reason, exit_price = True, "停利", tp_price
                    else:
                        _reason = "移動停利" if sl_price > original_sl_price else "停損"
                        force_sell, exit_reason, exit_price = True, _reason, sl_price
                elif tp_pct > 0 and high >= tp_price:
                    force_sell, exit_reason, exit_price = True, "停利", tp_price
                elif low <= sl_price:
                    _reason = "移動停利" if sl_price > original_sl_price else "停損"
                    force_sell, exit_reason, exit_price = True, _reason, sl_price

            if force_sell and position > 0:
                revenue = position * exit_price
                commission = revenue * self.commission_rate
                tax = revenue * self.tax_rate
                cash += revenue - commission - tax

                pnl = (exit_price - entry_price) * position - commission - tax
                total_commission += commission
                total_tax += tax

                action = f"賣出（{exit_reason}）"
                trade_info = {
                    "日期": date, "動作": action, "股數": position,
                    "價格": exit_price, "手續費": round(commission, 0),
                    "交易稅": round(tax, 0), "損益": round(pnl, 0),
                }

                if pnl > 0:
                    result.winning_trades += 1
                else:
                    result.losing_trades += 1
                result.total_trades += 1

                position = 0
                entry_price = 0.0
                hold_days = 0

            # ===== 進場 =====
            elif signal == "BUY" and position == 0:
                available = cash * max_pos_pct
                max_shares = int(
                    available / (price * TRADE_UNIT * (1 + self.commission_rate))
                ) * TRADE_UNIT
                if max_shares >= TRADE_UNIT:
                    position = max_shares
                    cost = position * price
                    commission = cost * self.commission_rate
                    cash -= cost + commission
                    entry_price = price
                    highest_since_entry = high
                    hold_days = 0
                    tp_price = price * (1 + tp_pct) if tp_pct > 0 else float("inf")
                    sl_price = price * (1 - sl_pct)
                    original_sl_price = sl_price
                    total_commission += commission
                    action = "買入"
                    trade_info = {
                        "日期": date, "動作": "買入", "股數": position,
                        "價格": price, "手續費": round(commission, 0),
                        "金額": round(cost + commission, 0),
                    }
                else:
                    action = "資金不足"
            else:
                action = "持有" if position > 0 else "空手觀望"

            if trade_info:
                result.trade_log.append(trade_info)

            position_value = position * price
            equity = cash + position_value
            daily_pnl = equity - prev_equity
            daily_return = daily_pnl / prev_equity if prev_equity > 0 else 0

            score = _safe(row.get("adx", 0.0))

            result.daily_records.append(DailyRecord(
                date=date, close=price, signal=signal,
                action=action, shares=position,
                cash=round(cash, 0), position_value=round(position_value, 0),
                total_equity=round(equity, 0), daily_pnl=round(daily_pnl, 0),
                daily_return=daily_return, composite_score=score,
            ))

            prev_equity = equity

        # 計算最終績效
        if result.daily_records:
            result.final_equity = result.daily_records[-1].total_equity
            result.total_return = (result.final_equity - self.initial_capital) / self.initial_capital
            result.total_commission = total_commission
            result.total_tax = total_tax

            equities = [r.total_equity for r in result.daily_records]
            peak = equities[0]
            max_dd = 0
            for eq in equities:
                if eq > peak:
                    peak = eq
                dd = (eq - peak) / peak
                if dd < max_dd:
                    max_dd = dd
            result.max_drawdown = max_dd

        return result


def run_simulation(
    df: pd.DataFrame,
    initial_capital: float | None = None,
    days: int = 30,
) -> SimulationResult:
    """便捷函式：執行一個月模擬

    Args:
        df: 原始股價 DataFrame
        initial_capital: 初始資金
        days: 模擬天數

    Returns:
        SimulationResult
    """
    sim = MonthlySimulator(initial_capital=initial_capital)
    return sim.run(df, days=days)


def run_simulation_v4(
    df: pd.DataFrame,
    initial_capital: float | None = None,
    days: int = 30,
    params: dict | None = None,
) -> SimulationResult:
    """便捷函式：執行 v4 一個月模擬"""
    sim = MonthlySimulator(initial_capital=initial_capital)
    return sim.run_v4(df, days=days, params=params)


def simulation_to_dataframe(result: SimulationResult) -> pd.DataFrame:
    """將模擬結果轉為 DataFrame（方便顯示）"""
    records = []
    for r in result.daily_records:
        records.append({
            "日期": r.date,
            "收盤價": r.close,
            "訊號": r.signal,
            "動作": r.action,
            "持有股數": r.shares,
            "現金": r.cash,
            "持倉市值": r.position_value,
            "總權益": r.total_equity,
            "當日損益": r.daily_pnl,
            "當日報酬": f"{r.daily_return:.2%}",
            "綜合評分": round(r.composite_score, 3),
        })
    return pd.DataFrame(records)


def format_simulation_summary(result: SimulationResult) -> str:
    """格式化模擬摘要"""
    lines = [
        "=" * 50,
        "一個月模擬交易績效摘要",
        "=" * 50,
        f"初始資金:       ${result.initial_capital:>12,.0f}",
        f"最終權益:       ${result.final_equity:>12,.0f}",
        f"總報酬率:       {result.total_return:>12.2%}",
        f"最大回撤:       {result.max_drawdown:>12.2%}",
        f"交易次數:       {result.total_trades:>12d}",
        f"獲利次數:       {result.winning_trades:>12d}",
        f"虧損次數:       {result.losing_trades:>12d}",
        f"總手續費:       ${result.total_commission:>12,.0f}",
        f"總交易稅:       ${result.total_tax:>12,.0f}",
        "=" * 50,
    ]
    return "\n".join(lines)
