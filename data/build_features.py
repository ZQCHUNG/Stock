"""Local Feature Engineering Script

Processes 8 raw JSON data sources → 65 features per (stock, date) → Parquet output.
Runs entirely on local machine — no Colab needed.

Design changes from Gemini Wall Street Trader debate (R88):
- 65 features across 6 dimensions (upgraded from 60 in R88.7 Phase 12)
- Brokerage dimension: 14 features from broker_features.py engine (R88.7 Method C)
- T+n date filtering: monthly revenue T+11, quarterly financials T+46
- regime_tag column for regime-aware similarity filtering
- Attention dimension: 7 features (upgraded from 2) — [CONVERGED 2026-02-19]
  - attention_index_7d, attention_spike, source_diversity, news_velocity,
    polarity_filter, news_recency, co_occurrence_score
  - NaN for stocks without news (not 0) — sparsity protection
  - Google News RSS + cnyes dual-source

Usage:
    python data/build_features.py

Output:
    data/pattern_data/features/features_all.parquet
    data/pattern_data/features/forward_returns.parquet
    data/pattern_data/features/feature_metadata.json
"""

import json
import os
import re
import sys
import warnings
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

# Ensure project root in path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

warnings.filterwarnings("ignore")

# --- Config ---
DATA_ROOT = PROJECT_ROOT / "data" / "pattern_data" / "raw"
OUTPUT_DIR = PROJECT_ROOT / "data" / "pattern_data" / "features"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PRICE_CACHE = OUTPUT_DIR / "price_cache.parquet"
START_DATE = "2020-01-01"


def parse_number(s: str) -> float:
    """Parse number string with commas and signs."""
    if not s or s == "--" or s == "-":
        return 0.0
    cleaned = str(s).replace(",", "").replace("&nbsp;", "").replace("\xa0", "").strip()
    if not cleaned or cleaned == "-":
        return 0.0
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


# ============================================================
# 1. Discover Stock Universe
# ============================================================
def discover_stock_codes() -> list[str]:
    """Extract all 4-digit stock codes from institutional daily files."""
    codes = set()
    inst_dir = DATA_ROOT / "institutional"
    # Sample first 5 files from each market
    for pattern in ["twse_*.json", "tpex_*.json"]:
        for f in sorted(inst_dir.glob(pattern))[:5]:
            with open(f, "r", encoding="utf-8") as fp:
                d = json.load(fp)
            for row in d.get("data", []):
                code = row[0].strip()
                if re.match(r"^\d{4}$", code):
                    codes.add(code)
    return sorted(codes)


# ============================================================
# 2. Fetch Price Data (OHLCV)
# ============================================================
def fetch_price_single(code: str):
    """Fetch OHLCV for a single stock."""
    import yfinance as yf

    try:
        ticker = f"{code}.TW"
        df = yf.download(ticker, start=START_DATE, auto_adjust=True, progress=False)
        if df.empty:
            ticker = f"{code}.TWO"
            df = yf.download(ticker, start=START_DATE, auto_adjust=True, progress=False)
        if df.empty:
            return None
        # Flatten MultiIndex columns from yfinance
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0].lower() for c in df.columns]
        else:
            df.columns = [c.lower() for c in df.columns]
        # De-duplicate columns (yfinance sometimes returns duplicates)
        df = df.loc[:, ~df.columns.duplicated()]
        needed = ["open", "high", "low", "close", "volume"]
        if not all(c in df.columns for c in needed):
            return None
        df = df[needed].copy()
        df["stock_code"] = code
        df.index.name = "date"
        return df.reset_index()
    except Exception:
        return None


def fetch_all_prices(codes: list[str], max_workers: int = 8) -> pd.DataFrame:
    """Fetch prices for all stocks with threading."""
    if PRICE_CACHE.exists():
        print(f"  Loading cached prices from {PRICE_CACHE}")
        return pd.read_parquet(PRICE_CACHE)

    results = []
    failed = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_price_single, c): c for c in codes}
        for i, future in enumerate(as_completed(futures)):
            code = futures[future]
            df = future.result()
            if df is not None and len(df) > 100:
                results.append(df)
            else:
                failed.append(code)
            if (i + 1) % 100 == 0:
                print(f"    Fetched {i+1}/{len(codes)} ({len(results)} success, {len(failed)} failed)")

    prices = pd.concat(results, ignore_index=True)
    prices["date"] = pd.to_datetime(prices["date"])
    prices.to_parquet(PRICE_CACHE, index=False)
    print(f"  Saved price cache: {len(results)} stocks, {len(prices)} rows")
    return prices


# ============================================================
# 3. Technical Features (20)
# ============================================================
def compute_technical_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute 20 technical features for a single stock's OHLCV data."""
    df = df.sort_values("date").copy()
    c = df["close"]
    h = df["high"]
    l = df["low"]
    o = df["open"]
    v = df["volume"].astype(float)

    df["ret_1d"] = c.pct_change(1)
    df["ret_5d"] = c.pct_change(5)
    df["ret_20d"] = c.pct_change(20)

    df["ma5_ratio"] = c / c.rolling(5).mean()
    df["ma20_ratio"] = c / c.rolling(20).mean()
    df["ma60_ratio"] = c / c.rolling(60).mean()

    bb_mid = c.rolling(20).mean()
    bb_std = c.rolling(20).std()
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std
    df["bb_position"] = (c - bb_lower) / (bb_upper - bb_lower)

    delta = c.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(span=14, adjust=False).mean()
    avg_loss = loss.ewm(span=14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi_14"] = (100 - 100 / (1 + rs)) / 100

    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    df["macd_hist"] = (macd_line - signal_line) / c

    low_14 = l.rolling(14).min()
    high_14 = h.rolling(14).max()
    df["kd_k"] = (c - low_14) / (high_14 - low_14).replace(0, np.nan)
    df["kd_d"] = df["kd_k"].rolling(3).mean()

    tr = pd.concat(
        [h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1
    ).max(axis=1)
    df["atr_pct"] = tr.rolling(14).mean() / c

    df["vol_ratio_5"] = v / v.rolling(5).mean().replace(0, np.nan)
    df["vol_ratio_20"] = v / v.rolling(20).mean().replace(0, np.nan)

    hl_range = h - l
    df["high_low_range"] = hl_range / c
    df["close_vs_high"] = (c - l) / hl_range.replace(0, np.nan)

    df["gap_pct"] = (o - c.shift(1)) / c.shift(1)

    def rolling_slope(s, w=20):
        x = np.arange(w, dtype=float)
        x -= x.mean()
        return s.rolling(w).apply(
            lambda y: np.polyfit(x, y, 1)[0] if len(y) == w else np.nan, raw=True
        )

    df["trend_slope_20"] = rolling_slope(c, 20) / c
    df["volatility_20"] = df["ret_1d"].rolling(20).std()
    df["rs_rating"] = np.nan  # Filled later

    return df


# ============================================================
# 4. Institutional Features (15)
# ============================================================
def load_institutional_data() -> pd.DataFrame:
    """Parse TWSE + TPEX institutional daily files."""
    inst_dir = DATA_ROOT / "institutional"
    rows = []

    for f in sorted(inst_dir.glob("*.json")):
        parts = f.stem.split("_")
        if len(parts) != 2:
            continue
        market, date_str = parts
        date = pd.Timestamp(f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}")

        with open(f, "r", encoding="utf-8") as fp:
            d = json.load(fp)

        for row in d.get("data", []):
            code = row[0].strip()
            if not re.match(r"^\d{4}$", code):
                continue
            if market == "twse":
                foreign_net = parse_number(row[4]) + parse_number(row[7]) if len(row) > 7 else 0
                trust_net = parse_number(row[10]) if len(row) > 10 else 0
                dealer_net = parse_number(row[11]) if len(row) > 11 else 0
                total_net = parse_number(row[18]) if len(row) > 18 else 0
            else:
                foreign_net = parse_number(row[4]) + parse_number(row[7]) if len(row) > 7 else 0
                trust_net = parse_number(row[10]) if len(row) > 10 else 0
                dealer_net = parse_number(row[11]) if len(row) > 11 else 0
                total_net = parse_number(row[-1]) if len(row) > 18 else 0

            rows.append({
                "date": date, "stock_code": code,
                "foreign_net": foreign_net, "trust_net": trust_net,
                "dealer_net": dealer_net, "total_net": total_net,
            })

    return pd.DataFrame(rows)


def load_margin_data() -> pd.DataFrame:
    """Parse margin daily files."""
    margin_dir = DATA_ROOT / "margin"
    rows = []

    for f in sorted(margin_dir.glob("*.json")):
        parts = f.stem.split("_")
        if len(parts) != 2:
            continue
        _, date_str = parts
        date = pd.Timestamp(f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}")

        with open(f, "r", encoding="utf-8") as fp:
            d = json.load(fp)

        for row in d.get("data", []):
            code = row[0].strip()
            if not re.match(r"^\d{4}$", code):
                continue
            margin_balance = parse_number(row[6]) if len(row) > 6 else 0
            short_balance = parse_number(row[14]) if len(row) > 14 else 0
            margin_util = parse_number(row[8]) if len(row) > 8 else 0

            rows.append({
                "date": date, "stock_code": code,
                "margin_balance": margin_balance,
                "short_balance": short_balance,
                "margin_utilization": margin_util / 100.0,
            })

    return pd.DataFrame(rows)


def load_tdcc_data() -> pd.DataFrame:
    """Parse TDCC (集保) FinMind data files."""
    tdcc_dir = DATA_ROOT / "tdcc"
    rows = []

    for f in sorted(tdcc_dir.glob("finmind_*.json")):
        with open(f, "r", encoding="utf-8") as fp:
            d = json.load(fp)
        stock_id = d.get("stock_id", "")
        if not re.match(r"^\d{4}$", stock_id):
            continue
        for item in d.get("data", []):
            rows.append({
                "date": pd.Timestamp(item["date"]),
                "stock_code": stock_id,
                "foreign_holding_ratio": item.get("ForeignInvestmentSharesRatio", 0) / 100.0,
            })

    return pd.DataFrame(rows)


def load_broker_features_v2() -> pd.DataFrame:
    """Compute 14 brokerage features from monthly + daily broker data.

    Uses broker_features.py engine for full 14-feature computation.
    Monthly data provides the historical backbone; daily data overlays when available.

    Features computed:
    - broker_hhi_daily, broker_top3_pct, broker_hhi_delta (concentration)
    - broker_net_buy_ratio, broker_spread, broker_net_momentum_5d (flow)
    - broker_purity_score, broker_foreign_pct, branch_overlap_count (smart money)
    - daily_net_buy_volatility, broker_turnover_chg (volatility)
    - broker_consistency_streak (persistence)
    - broker_price_divergence (divergence)
    - broker_winner_momentum (winner Tier 1)
    """
    from analysis.broker_features import (
        parse_daily_brokers, compute_broker_features, BROKER_FEATURE_NAMES,
    )
    from analysis.winner_registry import load_registry, WINNER_OUTPUT_PATH

    # Load winner registry for purity_score and winner_momentum
    registry = load_registry(WINNER_OUTPUT_PATH)
    tier1_codes = set()
    for code, info in registry.items():
        if isinstance(info, dict) and info.get("tier") == 1:
            tier1_codes.add(code)

    broker_dir = DATA_ROOT / "broker"
    daily_dir = DATA_ROOT / "broker_daily"
    rows = []

    # --- Process monthly broker files ---
    # Group files by stock_code for sequential processing (prev_hhi, streak chaining)
    monthly_files = defaultdict(list)
    for f in sorted(broker_dir.glob("*.json")):
        parts = f.stem.split("_")
        if len(parts) != 2:
            continue
        code, ym = parts
        if not re.match(r"^\d{4}$", code):
            continue
        year = int(ym[:4])
        month = int(ym[4:6])
        if month == 12:
            date = pd.Timestamp(f"{year}-{month}-31")
        else:
            date = pd.Timestamp(f"{year}-{month+1}-01") - pd.Timedelta(days=1)
        monthly_files[code].append((date, f))

    total_processed = 0
    for code in sorted(monthly_files.keys()):
        files = sorted(monthly_files[code], key=lambda x: x[0])
        prev_hhi = None
        prev_turnover = None
        streak = 0

        for date, filepath in files:
            with open(filepath, "r", encoding="utf-8") as fp:
                raw = json.load(fp)

            parsed = parse_daily_brokers(raw)
            features = compute_broker_features(
                parsed,
                prev_hhi=prev_hhi,
                prev_turnover=prev_turnover,
                lookback_streak=streak,
                winner_registry=registry,
                tier1_codes=tier1_codes,
            )

            row = {"date": date, "stock_code": code}
            row.update(features)
            rows.append(row)

            # Chain for next month
            prev_hhi = features.get("broker_hhi_daily")
            all_brokers = parsed["buy_brokers"] + parsed["sell_brokers"]
            prev_turnover = sum(b["buy"] + b["sell"] for b in all_brokers)
            streak = int(features.get("broker_consistency_streak", 0))

        total_processed += 1
        if total_processed % 500 == 0:
            print(f"    {total_processed} stocks processed (monthly broker)")

    print(f"  Monthly broker: {len(rows)} rows from {total_processed} stocks")

    # --- Process daily broker files (overlay) ---
    daily_count = 0
    if daily_dir.exists():
        daily_files = defaultdict(list)
        for f in sorted(daily_dir.glob("*.json")):
            parts = f.stem.split("_")
            if len(parts) != 2:
                continue
            code, ds = parts
            if not re.match(r"^\d{4}$", code):
                continue
            date = pd.Timestamp(f"{ds[:4]}-{ds[4:6]}-{ds[6:8]}")
            daily_files[code].append((date, f))

        for code in sorted(daily_files.keys()):
            files = sorted(daily_files[code], key=lambda x: x[0])
            for date, filepath in files:
                with open(filepath, "r", encoding="utf-8") as fp:
                    raw = json.load(fp)
                parsed = parse_daily_brokers(raw)
                features = compute_broker_features(
                    parsed,
                    winner_registry=registry,
                    tier1_codes=tier1_codes,
                )
                row = {"date": date, "stock_code": code}
                row.update(features)
                rows.append(row)
                daily_count += 1

        print(f"  Daily broker: {daily_count} rows")

    if not rows:
        return pd.DataFrame(columns=["date", "stock_code"] + BROKER_FEATURE_NAMES)

    df = pd.DataFrame(rows)
    # Daily data takes precedence over monthly (drop monthly duplicates for same date)
    df = df.sort_values(["stock_code", "date"]).drop_duplicates(
        subset=["stock_code", "date"], keep="last"
    )
    return df


def compute_institutional_features(prices, inst, margin, tdcc):
    """Merge institutional sources and compute 11 features (broker separated to brokerage dim)."""
    df = prices[["date", "stock_code", "volume"]].copy()
    df = df.sort_values(["stock_code", "date"])

    df = df.merge(inst, on=["date", "stock_code"], how="left")

    vol = df["volume"].replace(0, np.nan)
    df["inst_foreign_net"] = df["foreign_net"] / vol
    df["inst_trust_net"] = df["trust_net"] / vol
    df["inst_dealer_net"] = df["dealer_net"] / vol
    df["inst_total_net"] = df["total_net"] / vol
    df["inst_5d_sum"] = df.groupby("stock_code")["inst_total_net"].transform(
        lambda x: x.rolling(5, min_periods=1).sum()
    )

    df = df.merge(
        margin[["date", "stock_code", "margin_balance", "short_balance", "margin_utilization"]],
        on=["date", "stock_code"], how="left",
    )
    df["margin_balance_chg"] = df.groupby("stock_code")["margin_balance"].transform(lambda x: x.pct_change())
    df["short_balance_chg"] = df.groupby("stock_code")["short_balance"].transform(lambda x: x.pct_change())

    df = df.merge(tdcc[["date", "stock_code", "foreign_holding_ratio"]], on=["date", "stock_code"], how="left")
    df["foreign_holding_ratio"] = df.groupby("stock_code")["foreign_holding_ratio"].transform(lambda x: x.ffill())

    df["tdcc_retail_chg"] = -df.groupby("stock_code")["foreign_holding_ratio"].transform(lambda x: x.diff())
    df["tdcc_big_chg"] = df.groupby("stock_code")["foreign_holding_ratio"].transform(lambda x: x.diff())
    df["tdcc_concentration"] = df["foreign_holding_ratio"]

    df = df.drop(
        columns=["volume", "foreign_net", "trust_net", "dealer_net", "total_net",
                 "margin_balance", "short_balance", "foreign_holding_ratio"],
        errors="ignore",
    )
    return df


# ============================================================
# 5. Industry Features (5)
# ============================================================
def load_industry_mapping():
    """Load industry chain mapping."""
    industry_dir = DATA_ROOT / "industry"
    mapping = {}
    chains = {}

    for f in sorted(industry_dir.glob("ic_chain_*.json")):
        with open(f, "r", encoding="utf-8") as fp:
            d = json.load(fp)
        chain_code = d.get("chain_code", "")
        chain_name = d.get("chain_name", "")
        stock_codes = d.get("stock_codes", [])
        chains[chain_code] = stock_codes

        for i, code in enumerate(stock_codes):
            pos = i / max(len(stock_codes) - 1, 1)
            mapping[code] = {
                "chain_code": chain_code,
                "chain_name": chain_name,
                "industry_chain_pos": pos,
            }

    return mapping, chains


def compute_industry_features(prices, industry_mapping):
    """Compute 5 industry features."""
    df = prices[["date", "stock_code", "close"]].copy()
    df = df.sort_values(["stock_code", "date"])

    df["ret_20d_raw"] = df.groupby("stock_code")["close"].transform(lambda x: x.pct_change(20))
    df["chain_code"] = df["stock_code"].map(lambda c: industry_mapping.get(c, {}).get("chain_code", "UNKNOWN"))
    df["industry_chain_pos"] = df["stock_code"].map(
        lambda c: industry_mapping.get(c, {}).get("industry_chain_pos", 0.5)
    )

    sector_rs = df.groupby(["date", "chain_code"])["ret_20d_raw"].median().reset_index()
    sector_rs.columns = ["date", "chain_code", "sector_momentum"]
    df = df.merge(sector_rs, on=["date", "chain_code"], how="left")

    df["sector_rs"] = df.groupby("date")["sector_momentum"].rank(pct=True)
    df["peer_alpha"] = df["ret_20d_raw"] / df["sector_momentum"].replace(0, np.nan)
    df["peer_alpha"] = df["peer_alpha"].clip(-5, 5)

    chain_counts = df.groupby(["date", "chain_code"])["stock_code"].transform("count")
    total_counts = df.groupby("date")["stock_code"].transform("count")
    df["sector_concentration"] = chain_counts / total_counts

    return df[["date", "stock_code", "sector_rs", "peer_alpha", "sector_momentum",
               "industry_chain_pos", "sector_concentration"]].copy()


# ============================================================
# 6. Fundamental Features (8)
# ============================================================
def load_financials_data():
    fin_dir = DATA_ROOT / "financials"
    rows = []
    for f in sorted(fin_dir.glob("balance_sheet_*.json")):
        with open(f, "r", encoding="utf-8") as fp:
            d = json.load(fp)
        stock_id = d.get("stock_id", "")
        if not re.match(r"^\d{4}$", stock_id):
            continue
        for item in d.get("data", []):
            rows.append({
                "date": pd.Timestamp(item["date"]),
                "stock_code": stock_id,
                "type": item.get("type", ""),
                "value": item.get("value", 0),
            })
    return pd.DataFrame(rows)


def load_revenue_data():
    rev_dir = DATA_ROOT / "revenue"
    rows = []
    # BUG FIX: Read BOTH sii (上市) and otc (上櫃) — was missing sii entirely
    for f in sorted(rev_dir.glob("*.json")):
        stem = f.stem
        if not (stem.startswith("sii_") or stem.startswith("otc_")):
            continue
        with open(f, "r", encoding="utf-8") as fp:
            d = json.load(fp)
        year = d.get("year_minguo", 0) + 1911
        month = d.get("month", 0)
        if month == 12:
            date = pd.Timestamp(f"{year}-{month}-31")
        else:
            date = pd.Timestamp(f"{year}-{month+1}-01") - pd.Timedelta(days=1)
        for item in d.get("data", []):
            code = item.get("code", "").strip()
            if not re.match(r"^\d{4}$", code):
                continue
            # BUG FIX: yoy_pct field is mislabeled (contains revenue number).
            # Compute YoY manually from revenue and prev_year for safety.
            rev = parse_number(item.get("revenue", "0"))
            prev_yr = parse_number(item.get("prev_year", "0"))
            yoy = (rev - prev_yr) / prev_yr if prev_yr != 0 else 0.0
            rows.append({
                "date": date, "stock_code": code,
                "revenue_yoy": yoy,
                "revenue_mom": parse_number(item.get("mom_pct", "0")) / 100.0,
            })
    return pd.DataFrame(rows)


def compute_fundamental_features(prices, financials_raw, revenue):
    """Compute 8 fundamental features with strict T+n point-in-time filtering.

    T+n rules [CONVERGED with Gemini Wall Street Trader]:
    - Quarterly financials: T+46 (45-day delay + 1-day buffer)
    - Monthly revenue: T+11 (10th of next month + 1-day buffer)
    - PE/PB Feature Leakage fix: EPS denominator aligned with T+n
    """
    useful_types = {
        "ReturnOnEquity": "roe",
        "EarningsPerShare": "eps",
        "PriceEarningRatio": "pe_ratio",
        "PriceBookRatio": "pb_ratio",
        "OperatingProfitMargin": "operating_margin",
        "OperatingProfitMargin_per": "operating_margin",
        "DebtRatio": "debt_ratio",
        "DebtRatio_per": "debt_ratio",
    }

    fin = financials_raw[financials_raw["type"].isin(useful_types.keys())].copy()
    fin["feature"] = fin["type"].map(useful_types)

    fin_pivot = fin.pivot_table(
        index=["stock_code", "date"], columns="feature", values="value", aggfunc="first"
    ).reset_index()
    fin_pivot = fin_pivot.sort_values(["stock_code", "date"])

    # T+46: Quarterly financials available 46 days after quarter end
    fin_pivot["available_date"] = fin_pivot["date"] + pd.Timedelta(days=46)

    if "eps" in fin_pivot.columns:
        fin_pivot["eps_yoy"] = fin_pivot.groupby("stock_code")["eps"].transform(lambda x: x.pct_change(4))
    else:
        fin_pivot["eps_yoy"] = np.nan

    for col in ["roe", "pe_ratio", "pb_ratio", "operating_margin", "debt_ratio"]:
        if col not in fin_pivot.columns:
            fin_pivot[col] = np.nan

    for col in ["roe", "operating_margin", "debt_ratio"]:
        if col in fin_pivot.columns:
            fin_pivot[col] = fin_pivot[col] / 100.0

    fin_pivot["pe_percentile"] = fin_pivot.groupby("available_date")["pe_ratio"].rank(pct=True)

    base = prices[["date", "stock_code"]].copy().sort_values(["stock_code", "date"])

    # Merge financials using available_date (T+46) instead of report date
    fin_cols_sel = ["available_date", "stock_code", "eps_yoy", "roe", "pe_percentile", "pb_ratio", "operating_margin", "debt_ratio"]
    fin_select = fin_pivot[[c for c in fin_cols_sel if c in fin_pivot.columns]].copy()
    fin_select = fin_select.rename(columns={"available_date": "date"})
    base = base.merge(fin_select, on=["date", "stock_code"], how="left")

    # T+11: Monthly revenue available 11 days after month end
    revenue_t = revenue.copy()
    revenue_t["date"] = revenue_t["date"] + pd.Timedelta(days=11)
    base = base.merge(revenue_t[["date", "stock_code", "revenue_yoy", "revenue_mom"]], on=["date", "stock_code"], how="left")

    fund_feature_cols = ["eps_yoy", "roe", "revenue_yoy", "revenue_mom", "pe_percentile", "pb_ratio", "operating_margin", "debt_ratio"]
    for col in fund_feature_cols:
        if col not in base.columns:
            base[col] = np.nan
        base[col] = base.groupby("stock_code")[col].transform(lambda x: x.ffill())

    return base[["date", "stock_code"] + fund_feature_cols]


# ============================================================
# 7. Attention Features (7) — upgraded from 2 → 7
# [CONVERGED — Gemini Wall Street Trader 2026-02-19]
# 7 features: attention_index_7d, attention_spike, source_diversity,
#   news_velocity, polarity_filter, news_recency, co_occurrence_score
# NaN handling: stocks without news → NaN (not 0) to avoid sparsity clustering
# Polarity Filter: 3-state (Breaking/Growth=+1, Risk/Legal=-1, Neutral=0)
# Co-occurrence: articles mentioning >10 stocks discarded (大雜燴 filter)
# ============================================================

# Polarity keywords — reused from analysis/report/news.py
# [CONVERGED] Gemini: "Don't call it sentiment. Call it Polarity Filter."
_POLARITY_POSITIVE = [
    "營收成長", "獲利", "專利", "合作", "得獎", "突破", "上漲",
    "利多", "看好", "買進", "目標價", "新高", "擴產", "訂單",
    "法說會", "轉盈", "認證", "通過", "上調", "強勁",
    "獲獎", "勇奪", "榮獲", "授權", "簽約", "雙增", "轉機",
    "upgrade", "buy", "beat", "record", "growth", "profit", "launch",
    "surge", "rally", "boost", "strong", "outperform",
]
_POLARITY_NEGATIVE = [
    "虧損", "下跌", "衰退", "利空", "看壞", "下調",
    "減資", "裁員", "違約", "訴訟", "調查局", "警示", "跌停",
    "下修", "疲弱", "負債", "停工", "召回", "掏空", "背信",
    "downgrade", "sell", "miss", "loss", "decline",
    "fall", "drop", "warning", "lawsuit", "bearish", "default",
]
# [CONVERGED — Gemini Wall Street Trader 2026-02-19 R6]
# Removed: 「調查」→ 99.9% are "Factset 最新調查" (analyst surveys), not legal
# Removed: 「賣出」→ overlaps with institutional dimension (籌碼面已有精確數字)
# Removed: 「風險」→ too broad (每篇新聞都有「投資風險」disclaimer)
# Removed: 「cut」→ ambiguous (price cut vs layoff cut)
# Added: 「調查局」→ actual legal investigation
# Added: 「掏空」「背信」→ corporate fraud (Gemini mandate: capture non-structural risk)


# [CONVERGED — Gemini 2026-02-19 R4]
# Filter out "result" articles that describe what happened rather than causing it.
# "盤後解析" type articles: polarity_filter would tag as negative, but it's a result, not a cause.
_NOISE_TITLE_KEYWORDS = [
    "盤後", "整理", "摘要", "名單", "一覽", "排行", "漲跌停",
    "收盤揭示", "成交量排行", "三大法人", "投資股市買賣超",
]


def _is_noise_article(title: str) -> bool:
    """Check if article title suggests it's a summary/recap, not an event source."""
    return any(kw in title for kw in _NOISE_TITLE_KEYWORDS)


def load_news_data():
    """Load news data from both cnyes and Google News RSS sources.

    Returns DataFrame with columns: date, stock_code, news_count, source,
    title, co_mentioned (list of other stocks in same article).
    """
    news_dir = DATA_ROOT / "news"
    rows = []

    # --- Source 1: cnyes (existing) ---
    for f in sorted(news_dir.glob("cnyes_*.json")):
        parts = f.stem.split("_")
        if len(parts) < 3:
            continue
        date_str = parts[1]
        date = pd.Timestamp(f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}")

        with open(f, "r", encoding="utf-8") as fp:
            d = json.load(fp)

        for article in d.get("data", []):
            title = str(article.get("title", ""))
            content = str(article.get("content", ""))
            # Use stock field if available (more reliable), fallback to regex
            stock_list = article.get("stock", [])
            if stock_list:
                codes = set(c for c in stock_list if re.match(r"^\d{4}$", str(c)))
            else:
                codes = set(re.findall(r"(?:TWS:|TWG:)(\d{4})", content))
                codes.update(re.findall(r"\((\d{4})-TW\)", content))

            # [CONVERGED — Gemini] Discard 大雜燴 articles (>10 stocks)
            if len(codes) > MAX_STOCKS_PER_ARTICLE:
                continue

            # [CONVERGED — Gemini R4] Filter noise articles (盤後/摘要/名單)
            if _is_noise_article(title):
                continue

            for code in codes:
                other_codes = sorted(codes - {code})
                rows.append({
                    "date": date,
                    "stock_code": code,
                    "source": "cnyes",
                    "title": title[:200],
                    "co_mentioned": other_codes,
                })

    # --- Source 2: Google News RSS ---
    for f in sorted(news_dir.glob("google_news_gnews_*.json")):
        with open(f, "r", encoding="utf-8") as fp:
            d = json.load(fp)

        query_stock = d.get("query_stock", "")
        for article in d.get("data", []):
            title = str(article.get("title", ""))
            pub_ts = article.get("publishAt")
            if pub_ts:
                date = pd.Timestamp(datetime.fromtimestamp(pub_ts).strftime("%Y-%m-%d"))
            else:
                continue

            source_name = article.get("source", "google_news")
            codes = set(article.get("stock_codes", []))
            if query_stock and query_stock not in codes:
                codes.add(query_stock)

            # [CONVERGED — Gemini] Discard 大雜燴 articles
            if len(codes) > MAX_STOCKS_PER_ARTICLE:
                continue

            # [CONVERGED — Gemini R4] Filter noise articles
            if _is_noise_article(title):
                continue

            for code in codes:
                other_codes = sorted(codes - {code})
                rows.append({
                    "date": date,
                    "stock_code": code,
                    "source": source_name,
                    "title": title[:200],
                    "co_mentioned": other_codes,
                })

    if not rows:
        return pd.DataFrame(columns=["date", "stock_code", "source", "title", "co_mentioned"])

    df = pd.DataFrame(rows)
    # Deduplicate: same stock + same date + same title → keep first
    df = df.drop_duplicates(subset=["date", "stock_code", "title"], keep="first")
    return df


# Max stocks per article for co_occurrence — [CONVERGED — Gemini]
MAX_STOCKS_PER_ARTICLE = 10


def _compute_polarity(title: str) -> int:
    """Compute polarity filter: +1 (Breaking/Growth), -1 (Risk/Legal), 0 (Neutral).

    [CONVERGED — Gemini] "Don't call it sentiment, call it Polarity Filter."
    Three-state classification using keyword dictionary.
    """
    title_lower = title.lower()
    pos = sum(1 for kw in _POLARITY_POSITIVE if kw in title_lower)
    neg = sum(1 for kw in _POLARITY_NEGATIVE if kw in title_lower)
    if pos > neg:
        return 1
    elif neg > pos:
        return -1
    return 0


def compute_attention_features(prices, news):
    """Compute 7 attention features.

    [CONVERGED — Gemini Wall Street Trader 2026-02-19]
    7 features across 6 signal types:
    1. attention_index_7d — 量 (7-day rolling news count)
    2. attention_spike — 量突變 (today / 30d avg)
    3. source_diversity — 廣度 (unique sources in 7d)
    4. news_velocity — 加速度 (today count - yesterday count)
    5. polarity_filter — 三態極性 (keyword-based: +1/0/-1)
    6. news_recency — 時效性 (days since last article, 0=today)
    7. co_occurrence_score — 共現頻率 (articles with other stocks / total articles)

    NaN handling: stocks without ANY news data → NaN for all features.
    This prevents sparsity-driven clustering distortion [CONVERGED — Gemini Rebuttal B].
    """
    base = prices[["date", "stock_code"]].copy().sort_values(["stock_code", "date"])

    if len(news) == 0:
        # No news at all — all features are NaN
        for col in ["attention_index_7d", "attention_spike", "source_diversity",
                     "news_velocity", "polarity_filter", "news_recency",
                     "co_occurrence_score"]:
            base[col] = np.nan
        return base

    # --- Pre-aggregate news by (stock, date) ---
    # Count articles per stock per day
    news_daily = news.groupby(["stock_code", "date"]).agg(
        news_count=("title", "count"),
        unique_sources=("source", "nunique"),
        avg_polarity=("title", lambda titles: np.mean([_compute_polarity(t) for t in titles])),
        has_co_mention=("co_mentioned", lambda cms: np.mean([1 if len(c) > 0 else 0 for c in cms])),
    ).reset_index()

    # Track which stocks have ANY news data
    stocks_with_news = set(news["stock_code"].unique())

    # Merge
    base = base.merge(news_daily, on=["date", "stock_code"], how="left")

    # For stocks WITH news data: fill missing days with 0 (they exist in news universe)
    # For stocks WITHOUT any news: keep NaN (they're not in the news universe)
    has_news_mask = base["stock_code"].isin(stocks_with_news)
    for col in ["news_count", "unique_sources", "avg_polarity", "has_co_mention"]:
        base.loc[has_news_mask, col] = base.loc[has_news_mask, col].fillna(0)
        # Stocks without news: remain NaN

    # --- Feature 1: attention_index_7d (rolling 7d sum) ---
    base["attention_index_7d"] = base.groupby("stock_code")["news_count"].transform(
        lambda x: x.rolling(7, min_periods=1).sum() if x.notna().any() else x
    )

    # --- Feature 2: attention_spike (today / 30d avg) ---
    avg_30d = base.groupby("stock_code")["news_count"].transform(
        lambda x: x.rolling(30, min_periods=1).mean() if x.notna().any() else x
    )
    base["attention_spike"] = base["news_count"] / avg_30d.replace(0, np.nan)

    # --- Feature 3: source_diversity (rolling 7d unique sources) ---
    base["source_diversity"] = base.groupby("stock_code")["unique_sources"].transform(
        lambda x: x.rolling(7, min_periods=1).max() if x.notna().any() else x
    )

    # --- Feature 4: news_velocity (delta: today - yesterday) ---
    base["news_velocity"] = base.groupby("stock_code")["news_count"].transform(
        lambda x: x.diff() if x.notna().any() else x
    )

    # --- Feature 5: polarity_filter (rolling 7d average polarity) ---
    base["polarity_filter"] = base.groupby("stock_code")["avg_polarity"].transform(
        lambda x: x.rolling(7, min_periods=1).mean() if x.notna().any() else x
    )

    # --- Feature 6: news_recency (days since last article) ---
    # For each stock, compute days since last non-zero news day
    def _compute_recency(group):
        if group["news_count"].isna().all():
            return pd.Series(np.nan, index=group.index)
        last_news_day = pd.NaT
        recency = []
        for idx, row in group.iterrows():
            if row["news_count"] > 0:
                last_news_day = row["date"]
                recency.append(0)
            elif pd.notna(last_news_day):
                days = (row["date"] - last_news_day).days
                recency.append(min(days, 30))  # Cap at 30
            else:
                recency.append(np.nan)
        return pd.Series(recency, index=group.index)

    base["news_recency"] = base.groupby("stock_code", group_keys=False).apply(_compute_recency)

    # --- Feature 7: co_occurrence_score ---
    # [CONVERGED — Gemini] "大哥帶小弟" asymmetric dependence
    # co_occurrence = articles_with_other_stocks / total_articles
    base["co_occurrence_score"] = base.groupby("stock_code")["has_co_mention"].transform(
        lambda x: x.rolling(7, min_periods=1).mean() if x.notna().any() else x
    )

    # Clean up temp columns
    out_cols = ["date", "stock_code", "attention_index_7d", "attention_spike",
                "source_diversity", "news_velocity", "polarity_filter",
                "news_recency", "co_occurrence_score"]
    return base[out_cols]


# ============================================================
# 8. RS Rating vs TAIEX
# ============================================================
def compute_rs_rating(prices):
    import yfinance as yf

    taiex = yf.download("^TWII", start=START_DATE, auto_adjust=True, progress=False)
    taiex.columns = [c.lower() if isinstance(c, str) else c[0].lower() for c in taiex.columns]
    taiex = taiex[["close"]].rename(columns={"close": "taiex_close"})
    taiex.index.name = "date"
    taiex = taiex.reset_index()
    taiex["date"] = pd.to_datetime(taiex["date"])
    taiex["taiex_ret_63"] = taiex["taiex_close"].pct_change(63)

    df = prices[["date", "stock_code", "close"]].copy().sort_values(["stock_code", "date"])
    df["stock_ret_63"] = df.groupby("stock_code")["close"].transform(lambda x: x.pct_change(63))
    df = df.merge(taiex[["date", "taiex_ret_63"]], on="date", how="left")
    df["rs_raw"] = df["stock_ret_63"] - df["taiex_ret_63"]
    df["rs_rating"] = df.groupby("date")["rs_raw"].rank(pct=True)

    return df[["date", "stock_code", "rs_rating"]]


# ============================================================
# Main Pipeline
# ============================================================
def main():
    print("=" * 60)
    print("Pattern Feature Engineering — Local Build")
    print("=" * 60)

    # Check data sources
    print("\n[1/11] Checking data sources...")
    for src in ["broker", "broker_daily", "institutional", "financials", "margin", "tdcc", "revenue", "news", "industry"]:
        p = DATA_ROOT / src
        n = len(list(p.glob("*.json"))) if p.exists() else 0
        print(f"  {src}: {n} files")

    # Discover stocks
    print("\n[2/11] Discovering stock universe...")
    codes = discover_stock_codes()
    print(f"  Found {len(codes)} stock codes")

    # Fetch prices
    print("\n[3/11] Fetching price data...")
    prices = fetch_all_prices(codes)
    print(f"  Prices: {len(prices)} rows, {prices['stock_code'].nunique()} stocks")

    # Technical features
    print("\n[4/11] Computing technical features...")
    tech_cols = [
        "ret_1d", "ret_5d", "ret_20d", "ma5_ratio", "ma20_ratio", "ma60_ratio",
        "bb_position", "rsi_14", "macd_hist", "kd_k", "kd_d", "atr_pct",
        "vol_ratio_5", "vol_ratio_20", "high_low_range", "close_vs_high",
        "gap_pct", "trend_slope_20", "volatility_20", "rs_rating",
    ]
    tech_results = []
    stock_groups = list(prices.groupby("stock_code"))
    for i, (code, group) in enumerate(stock_groups):
        tech_results.append(compute_technical_features(group))
        if (i + 1) % 200 == 0:
            print(f"    {i+1}/{len(stock_groups)} stocks processed")
    tech_all = pd.concat(tech_results, ignore_index=True)

    # RS Rating
    print("\n[5/11] Computing RS Rating...")
    rs_df = compute_rs_rating(prices)
    tech_all = tech_all.drop(columns=["rs_rating"], errors="ignore")
    tech_all = tech_all.merge(rs_df, on=["date", "stock_code"], how="left")

    # Institutional (11 features — broker separated to brokerage dim)
    print("\n[6/11] Loading institutional data...")
    inst_df = load_institutional_data()
    margin_df = load_margin_data()
    tdcc_df = load_tdcc_data()
    print(f"  Institutional: {len(inst_df)} rows")
    print(f"  Margin: {len(margin_df)} rows")
    print(f"  TDCC: {len(tdcc_df)} rows")

    inst_cols = [
        "inst_foreign_net", "inst_trust_net", "inst_dealer_net", "inst_total_net",
        "inst_5d_sum", "margin_balance_chg", "short_balance_chg", "margin_utilization",
        "tdcc_retail_chg", "tdcc_big_chg", "tdcc_concentration",
    ]
    inst_features = compute_institutional_features(prices, inst_df, margin_df, tdcc_df)

    # Brokerage (14 features — R88.7 upgrade from 4)
    print("\n[6.5/11] Loading brokerage features (14-feature engine)...")
    from analysis.broker_features import BROKER_FEATURE_NAMES
    broker_cols = list(BROKER_FEATURE_NAMES)
    broker_features = load_broker_features_v2()
    print(f"  Broker features: {len(broker_features)} rows, {broker_features['stock_code'].nunique()} stocks")

    # Industry
    print("\n[7/11] Computing industry features...")
    industry_mapping, chains = load_industry_mapping()
    industry_cols = ["sector_rs", "peer_alpha", "sector_momentum", "industry_chain_pos", "sector_concentration"]
    industry_features = compute_industry_features(prices, industry_mapping)
    print(f"  {len(industry_mapping)} stocks in {len(chains)} chains")

    # Fundamental
    print("\n[8/11] Computing fundamental features...")
    financials_raw = load_financials_data()
    revenue_df = load_revenue_data()
    fund_cols = ["eps_yoy", "roe", "revenue_yoy", "revenue_mom", "pe_percentile", "pb_ratio", "operating_margin", "debt_ratio"]
    fund_features = compute_fundamental_features(prices, financials_raw, revenue_df)

    # Attention (renamed from News)
    print("\n[9/11] Computing attention features...")
    news_df = load_news_data()
    attention_cols = [
        "attention_index_7d", "attention_spike", "source_diversity",
        "news_velocity", "polarity_filter", "news_recency", "co_occurrence_score",
    ]
    attention_features = compute_attention_features(prices, news_df)

    # ===== MERGE ALL =====
    print("\n[10/11] Merging all features...")
    ALL_FEATURE_COLS = tech_cols + inst_cols + broker_cols + industry_cols + fund_cols + attention_cols
    assert len(ALL_FEATURE_COLS) == 65, f"Expected 65 features, got {len(ALL_FEATURE_COLS)}"

    merged = tech_all[["date", "stock_code"] + tech_cols].copy()
    merged = merged.merge(inst_features[["date", "stock_code"] + inst_cols], on=["date", "stock_code"], how="left")

    # Brokerage: merge + forward-fill (monthly data → daily)
    merged = merged.merge(broker_features[["date", "stock_code"] + broker_cols], on=["date", "stock_code"], how="left")
    for col in broker_cols:
        merged[col] = merged.groupby("stock_code")[col].transform(lambda x: x.ffill())

    merged = merged.merge(industry_features[["date", "stock_code"] + industry_cols], on=["date", "stock_code"], how="left")
    merged = merged.merge(fund_features[["date", "stock_code"] + fund_cols], on=["date", "stock_code"], how="left")
    merged = merged.merge(attention_features[["date", "stock_code"] + attention_cols], on=["date", "stock_code"], how="left")

    # Add regime_tag column for filtering (not part of similarity features)
    # [CONVERGED] Gemini: regime_tag for same-regime filtering
    print("  Computing regime_tag...")
    import yfinance as yf
    taiex = yf.download("^TWII", start=START_DATE, auto_adjust=True, progress=False)
    taiex.columns = [c.lower() if isinstance(c, str) else c[0].lower() for c in taiex.columns]
    taiex = taiex[["close"]].rename(columns={"close": "taiex_close"})
    taiex.index.name = "date"
    taiex = taiex.reset_index()
    taiex["date"] = pd.to_datetime(taiex["date"])
    taiex["ma200"] = taiex["taiex_close"].rolling(200).mean()
    # bull=1 (above MA200), bear=-1 (below MA200)
    taiex["regime_tag"] = np.where(taiex["taiex_close"] > taiex["ma200"], 1, -1)
    merged = merged.merge(taiex[["date", "regime_tag"]], on="date", how="left")
    merged["regime_tag"] = merged["regime_tag"].fillna(0).astype(int)

    print(f"  Merged shape: {merged.shape}")
    print(f"  Stocks: {merged['stock_code'].nunique()}")

    # Z-Score Normalize (rolling 252d)
    # [CONVERGED — Gemini 2026-02-19] Attention features use NaN-aware handling:
    # Stocks WITHOUT news data keep NaN (not 0) to prevent sparsity clustering.
    # Non-attention features fill NaN → 0 as before.
    print("\n  Z-score normalizing (rolling 252d)...")
    merged = merged.sort_values(["stock_code", "date"])

    # Track which (stock, row) had NaN attention BEFORE normalization
    # These are stocks genuinely outside the news universe
    attention_nan_mask = merged[attention_cols].isna().all(axis=1)

    for col in ALL_FEATURE_COLS:
        merged[col] = merged[col].replace([np.inf, -np.inf], np.nan)
        grouped = merged.groupby("stock_code")[col]
        rolling_mean = grouped.transform(lambda x: x.rolling(252, min_periods=60).mean())
        rolling_std = grouped.transform(lambda x: x.rolling(252, min_periods=60).std())
        merged[col] = (merged[col] - rolling_mean) / rolling_std.replace(0, np.nan)
        merged[col] = merged[col].clip(-5, 5)

    # Fill NaN → 0 for non-attention features
    non_attention_cols = [c for c in ALL_FEATURE_COLS if c not in attention_cols]
    merged[non_attention_cols] = merged[non_attention_cols].fillna(0)

    # For attention features: fill NaN → 0 only for stocks IN news universe
    # Stocks outside news universe: keep NaN
    for col in attention_cols:
        merged.loc[~attention_nan_mask, col] = merged.loc[~attention_nan_mask, col].fillna(0)

    # Forward returns
    print("\n[11/11] Computing forward returns...")
    price_lookup = prices[["date", "stock_code", "close"]].sort_values(["stock_code", "date"])
    horizons = {"d3": 3, "d7": 7, "d21": 21, "d90": 90, "d180": 180}
    for name, days in horizons.items():
        price_lookup[name] = price_lookup.groupby("stock_code")["close"].transform(
            lambda x: x.shift(-days) / x - 1
        )
    fwd_returns = price_lookup[["date", "stock_code"] + list(horizons.keys())].copy()

    # ===== SAVE (Atomic Swap) =====
    # [CONVERGED — Wall Street Trader 2026-02-18]
    # "先生成 temp parquet，確認大小與行數誤差在 ±5% 以內，再 mv 替換正式檔案。
    # 防止 rebuild 到一半失敗，導致舊數據也毀損。"
    print("\n  Saving outputs (atomic swap)...")
    features_out = merged[["date", "stock_code", "regime_tag"] + ALL_FEATURE_COLS]

    features_temp = OUTPUT_DIR / "features_all_temp.parquet"
    features_final = OUTPUT_DIR / "features_all.parquet"
    returns_temp = OUTPUT_DIR / "forward_returns_temp.parquet"
    returns_final = OUTPUT_DIR / "forward_returns.parquet"

    features_out.to_parquet(features_temp, index=False)
    fwd_returns.to_parquet(returns_temp, index=False)
    print(f"    features_all_temp.parquet: {features_out.shape}")
    print(f"    forward_returns_temp.parquet: {fwd_returns.shape}")

    # Validate temp files before swap
    swap_ok = True
    if features_final.exists():
        prev_size = features_final.stat().st_size
        new_size = features_temp.stat().st_size
        prev_rows = len(pd.read_parquet(features_final, columns=["stock_code"]))
        new_rows = len(features_out)
        size_ratio = new_size / prev_size if prev_size > 0 else 1.0
        row_ratio = new_rows / prev_rows if prev_rows > 0 else 1.0
        print(f"    Validation: size {prev_size/1e6:.1f}MB→{new_size/1e6:.1f}MB "
              f"({size_ratio:.2f}x), rows {prev_rows}→{new_rows} ({row_ratio:.2f}x)")

        if abs(size_ratio - 1.0) > 0.05 or abs(row_ratio - 1.0) > 0.05:
            print(f"    ⚠️ VALIDATION FAILED: deviation > ±5%. Keeping old file.")
            print(f"    Temp files preserved for inspection.")
            swap_ok = False

    # Build swap report [CONVERGED — Wall Street Trader 2026-02-19]
    swap_report = {
        "timestamp": datetime.now().isoformat(),
        "swap_ok": swap_ok,
        "new_file_size_mb": round(features_temp.stat().st_size / 1e6, 2) if features_temp.exists() else 0,
        "new_row_count": len(features_out),
        "new_stock_count": int(features_out["stock_code"].nunique()),
    }
    if features_final.exists() and swap_ok is not None:
        swap_report["old_file_size_mb"] = round(prev_size / 1e6, 2) if 'prev_size' in dir() else None
        swap_report["old_row_count"] = prev_rows if 'prev_rows' in dir() else None
        swap_report["size_ratio"] = round(size_ratio, 4) if 'size_ratio' in dir() else None
        swap_report["row_ratio"] = round(row_ratio, 4) if 'row_ratio' in dir() else None
        swap_report["row_count_delta"] = new_rows - prev_rows if 'prev_rows' in dir() and 'new_rows' in dir() else None

    if swap_ok:
        # Atomic swap: remove old, rename temp → final
        if features_final.exists():
            features_final.unlink()
        features_temp.rename(features_final)
        if returns_final.exists():
            returns_final.unlink()
        returns_temp.rename(returns_final)
        print(f"    ✅ Atomic swap complete")
        swap_report["result"] = "swapped"
    else:
        # Keep temp files for debugging, don't overwrite production
        print(f"    ❌ Swap aborted. Temp files: {features_temp.name}, {returns_temp.name}")
        swap_report["result"] = "aborted"

    # --- Night Watchman: Post-Swap Health Check ---
    # [CONVERGED — Wall Street Trader 2026-02-19]
    # Verify data freshness + brokerage dimension vitality after swap
    health = {}
    if swap_ok:
        final_df = features_out  # already in memory
        latest_date = str(final_df["date"].max())[:10]
        health["latest_date"] = latest_date

        # Check brokerage non-zero rate
        brok_cols_check = [c for c in broker_cols if c in final_df.columns]
        if brok_cols_check:
            latest_rows = final_df[final_df["date"] == final_df["date"].max()]
            brok_data = latest_rows[brok_cols_check]
            total_cells = brok_data.shape[0] * brok_data.shape[1]
            nonzero_cells = int((brok_data != 0).sum().sum()) if total_cells > 0 else 0
            health["brokerage_nonzero_rate"] = round(nonzero_cells / total_cells, 4) if total_cells > 0 else 0
            health["brokerage_stocks_with_data"] = int((brok_data != 0).any(axis=1).sum())
            health["brokerage_total_stocks"] = len(latest_rows)
            health["brokerage_features_checked"] = len(brok_cols_check)
        else:
            health["brokerage_nonzero_rate"] = 0
            health["brokerage_warning"] = "no brokerage columns found"

        all_ok = health.get("brokerage_nonzero_rate", 0) > 0.01
        health["status"] = "HEALTHY" if all_ok else "WARNING"
        print(f"    Health: {health['status']} | Latest: {latest_date} | "
              f"Brokerage non-zero: {health.get('brokerage_nonzero_rate', 0):.1%}")

    swap_report["health_check"] = health

    # Save swap report for Joe to review stability
    swap_report_path = OUTPUT_DIR / "swap_report.json"
    with open(swap_report_path, "w", encoding="utf-8") as fp:
        json.dump(swap_report, fp, indent=2, ensure_ascii=False)
    print(f"    Swap report saved: {swap_report_path.name}")

    metadata = {
        "dimensions": {
            "technical": {"features": tech_cols, "count": len(tech_cols), "description": "技術面 — 價量衍生指標"},
            "institutional": {"features": inst_cols, "count": len(inst_cols), "description": "籌碼面 — 法人/融資融券/集保"},
            "brokerage": {"features": broker_cols, "count": len(broker_cols), "description": "分點面 — 14特徵分點基因譜 (R88.7)"},
            "industry": {"features": industry_cols, "count": len(industry_cols), "description": "產業面 — 族群強弱/供應鏈"},
            "fundamental": {"features": fund_cols, "count": len(fund_cols), "description": "基本面 — 財報/營收/估值 (T+46/T+11)"},
            "attention": {"features": attention_cols, "count": len(attention_cols), "description": "關注度 — 7維媒體注意力 (量/速/廣/時/性/連)"},
        },
        "all_features": ALL_FEATURE_COLS,
        "total_features": len(ALL_FEATURE_COLS),
        "extra_columns": ["regime_tag"],
        "forward_return_horizons": list(horizons.keys()),
        "normalization": "rolling_zscore_252d",
        "feature_weights": {
            "atr_pct": 1.5,
            "vol_ratio_20": 1.5,
        },
        "t_plus_n": {
            "quarterly_financials": 46,
            "monthly_revenue": 11,
        },
        "created_at": datetime.now().isoformat(),
        "stock_count": int(features_out["stock_code"].nunique()),
        "date_range": [str(features_out["date"].min()), str(features_out["date"].max())],
    }
    with open(OUTPUT_DIR / "feature_metadata.json", "w", encoding="utf-8") as fp:
        json.dump(metadata, fp, indent=2, ensure_ascii=False)

    # Summary
    print("\n" + "=" * 60)
    print("DONE!")
    print("=" * 60)
    for dim, info in metadata["dimensions"].items():
        print(f"  {dim}: {info['count']} features — {info['description']}")
    print(f"  Total: {metadata['total_features']} features")
    print(f"  Stocks: {metadata['stock_count']}")
    print(f"  Date range: {metadata['date_range']}")
    print(f"\nOutput files:")
    for f in OUTPUT_DIR.glob("*"):
        if f.suffix in [".parquet", ".json"]:
            size_mb = f.stat().st_size / 1024 / 1024
            print(f"  {f.name}: {size_mb:.1f} MB")


if __name__ == "__main__":
    main()
