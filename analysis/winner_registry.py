"""
R88.7 Phase 3: Winner Branch Registry
分點勝率追蹤系統 — 識別具有跨產業選股能力的「真大戶」

Winner Score = Win_Rate × (Avg_Profit / |Avg_Loss|)
[CONVERGED] Trader requirement: Score > 1.1, n >= 15
[HYPOTHESIS] Bootstrap CI lower bound >= 0.8 (adjusted from 1.0 — too strict with monthly n)
[CONVERGED] Ghost Bias: 產業分散度 — 單一產業 > 60% 則打折

Data Flow:
    109K monthly broker files → extract top buy brokers
    → match with forward_returns.parquet D21
    → aggregate by broker_code → Winner Score + Bootstrap CI
    → Ghost Bias filter → winner_branches.json
"""
import json
import glob
import logging
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# --- PLACEHOLDER parameters ---
WINNER_SCORE_THRESHOLD = 1.1   # [PLACEHOLDER: WINNER_001] Trader suggested
WINNER_MIN_N = 15              # [PLACEHOLDER: WINNER_002] Trader suggested
# [CONVERGED] Trader: Tiered CI thresholds
TIER1_CI_LOWER = 1.0           # [CONVERGED: WINNER_003a] Sniper Ready — "鋼鐵核心"
TIER2_CI_LOWER = 0.7           # [CONVERGED: WINNER_003b] Observer — "觀察名單"
BOOTSTRAP_ITERATIONS = 1000    # [PLACEHOLDER: WINNER_004]
GHOST_BIAS_SECTOR_HHI = 0.50  # [PLACEHOLDER: WINNER_005] Max single-sector share
TOP_K_BUY_BROKERS = 5         # Extract top K buy brokers per file

# Paths
BROKER_MONTHLY_DIR = Path(__file__).parent.parent / "data" / "pattern_data" / "raw" / "broker"
BROKER_DAILY_DIR = Path(__file__).parent.parent / "data" / "pattern_data" / "raw" / "broker_daily"
FORWARD_RETURNS_PATH = Path(__file__).parent.parent / "data" / "pattern_data" / "features" / "forward_returns.parquet"
WINNER_OUTPUT_PATH = Path(__file__).parent.parent / "data" / "pattern_data" / "winner_branches.json"
INDUSTRY_DIR = Path(__file__).parent.parent / "data" / "pattern_data" / "raw" / "industry"


def _load_industry_chain_map() -> dict:
    """Load industry chain mapping: stock_code → chain_name."""
    chain_map = {}
    chain_files = glob.glob(str(INDUSTRY_DIR / "ic_chain_*.json"))
    for f in chain_files:
        try:
            d = json.load(open(f, encoding="utf-8"))
            name = d.get("chain_name", "unknown")
            for code in d.get("stock_codes", []):
                chain_map[code] = name
        except Exception:
            continue
    return chain_map


def _load_sector_mapping() -> dict:
    """Load L1 sector mapping from sector_mapping.py."""
    try:
        from data.sector_mapping import SECTOR_L1_GROUPS
        sector_map = {}
        for sector, stocks in SECTOR_L1_GROUPS.items():
            for code in stocks:
                sector_map[code] = sector
        return sector_map
    except ImportError:
        return {}


def _get_sector(stock_code: str, sector_map: dict, chain_map: dict) -> str:
    """Get sector for a stock, with fallback chain."""
    if stock_code in sector_map:
        return sector_map[stock_code]
    if stock_code in chain_map:
        return chain_map[stock_code]
    return "unknown"


def _is_summary_row(broker: dict) -> bool:
    """Check if a broker entry is a summary row."""
    name = broker.get("broker", "")
    return "合計" in name or "平均" in name


def _parse_lots(val) -> int:
    """Parse broker lot string to int."""
    if isinstance(val, (int, float)):
        return int(val)
    try:
        return int(str(val).replace(",", "").replace(" ", ""))
    except (ValueError, AttributeError):
        return 0


def _parse_month_end_date(end_date_str: str) -> Optional[str]:
    """Parse end_date string to YYYY-MM-DD format.

    Handles formats like '2025-1-31', '2025-01-31', '2025/1/31'.
    """
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            dt = datetime.strptime(end_date_str.strip(), fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    # Try splitting manually for flexible format
    try:
        parts = end_date_str.replace("/", "-").split("-")
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
        return f"{y:04d}-{m:02d}-{d:02d}"
    except Exception:
        return None


def scan_broker_buys(
    broker_dir: Path = BROKER_MONTHLY_DIR,
    top_k: int = TOP_K_BUY_BROKERS,
    mode: str = "monthly",
) -> list[dict]:
    """Scan all broker files and extract top buy broker instances.

    Returns list of dicts:
        {broker_code, broker_name, stock_code, date, net_lots, pct}
    """
    pattern = str(broker_dir / "*.json")
    files = glob.glob(pattern)
    logger.info(f"Scanning {len(files)} {mode} broker files from {broker_dir}")

    records = []
    errors = 0

    for filepath in files:
        try:
            data = json.load(open(filepath, encoding="utf-8"))
        except Exception:
            errors += 1
            continue

        stock_code = data.get("stock", "")
        end_date = data.get("end_date", "")
        date_str = _parse_month_end_date(end_date)
        if not date_str or not stock_code:
            continue

        buy_top = data.get("buy_top", [])
        broker_codes = data.get("broker_codes", [])

        # Extract top K buy brokers (skip summary rows)
        buy_idx = 0
        for i, b in enumerate(buy_top):
            if buy_idx >= top_k:
                break
            if _is_summary_row(b):
                continue

            broker_name = b.get("broker", "")
            net = _parse_lots(b.get("net", 0))
            pct_str = b.get("pct", "0%")
            try:
                pct = float(str(pct_str).replace("%", "").replace(",", "")) / 100
            except (ValueError, AttributeError):
                pct = 0.0

            # Get broker code (aligned with buy_top index, excluding summary)
            code = broker_codes[buy_idx] if buy_idx < len(broker_codes) else ""

            if net > 0 and code:
                records.append({
                    "broker_code": code,
                    "broker_name": broker_name,
                    "stock_code": stock_code,
                    "date": date_str,
                    "net_lots": net,
                    "pct": pct,
                })
            buy_idx += 1

    logger.info(f"Extracted {len(records)} buy instances ({errors} file errors)")
    return records


def build_forward_returns_index(
    fwd_path: Path = FORWARD_RETURNS_PATH,
) -> dict:
    """Build (stock_code, date) → {d7, d21, d90} lookup dict."""
    df = pd.read_parquet(fwd_path)
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")

    index = {}
    for row in df.itertuples(index=False):
        key = (row.stock_code, row.date)
        index[key] = {
            "d7": getattr(row, "d7", None),
            "d21": getattr(row, "d21", None),
            "d90": getattr(row, "d90", None),
        }
    logger.info(f"Forward returns index: {len(index)} entries")
    return index


def _find_closest_date(stock_code: str, target_date: str,
                       fwd_index: dict, max_offset: int = 5) -> Optional[str]:
    """Find closest available date in forward returns index."""
    from datetime import timedelta
    dt = datetime.strptime(target_date, "%Y-%m-%d")
    for offset in range(max_offset + 1):
        for delta in [0, -1, 1, -2, 2, -3, 3, -4, 4, -5]:
            if abs(delta) > offset:
                continue
            check = (dt + timedelta(days=delta)).strftime("%Y-%m-%d")
            if (stock_code, check) in fwd_index:
                return check
    return None


def compute_winner_scores(
    records: list[dict],
    fwd_index: dict,
    sector_map: dict,
    chain_map: dict,
    horizon: str = "d21",
    min_n: int = WINNER_MIN_N,
) -> dict:
    """Compute Winner Score for each broker code.

    Winner Score = Win_Rate × (Avg_Profit / |Avg_Loss|)
    [CONVERGED] Trader: "Risk-Adjusted Score"

    Returns:
        Dict of {broker_code: {score, win_rate, avg_profit, avg_loss, n, ...}}
    """
    # Group records by broker_code
    broker_data = {}
    matched = 0
    unmatched = 0

    for rec in records:
        code = rec["broker_code"]
        stock = rec["stock_code"]
        date = rec["date"]

        # Look up forward return
        fwd = fwd_index.get((stock, date))
        if fwd is None:
            # Try closest date (month-end might be off by 1-2 days)
            closest = _find_closest_date(stock, date, fwd_index)
            if closest:
                fwd = fwd_index[(stock, closest)]

        if fwd is None or fwd.get(horizon) is None:
            unmatched += 1
            continue

        ret = fwd[horizon]
        if np.isnan(ret):
            unmatched += 1
            continue

        matched += 1
        sector = _get_sector(stock, sector_map, chain_map)

        if code not in broker_data:
            broker_data[code] = {
                "broker_name": rec["broker_name"],
                "returns": [],
                "sectors": {},
                "stocks": set(),
            }

        broker_data[code]["returns"].append(ret)
        broker_data[code]["stocks"].add(stock)
        s_count = broker_data[code]["sectors"]
        s_count[sector] = s_count.get(sector, 0) + 1

    logger.info(f"Forward return match: {matched} matched, {unmatched} unmatched")

    # Compute scores
    results = {}
    for code, data in broker_data.items():
        returns = np.array(data["returns"])
        n = len(returns)

        if n < min_n:
            continue

        wins = returns[returns > 0]
        losses = returns[returns <= 0]

        win_rate = len(wins) / n
        avg_profit = float(np.mean(wins)) if len(wins) > 0 else 0.0
        avg_loss = float(np.mean(losses)) if len(losses) > 0 else -0.001  # Avoid div/0

        # Winner Score = WR × (AvgProfit / |AvgLoss|)
        if abs(avg_loss) > 1e-6:
            score = win_rate * (avg_profit / abs(avg_loss))
        else:
            score = win_rate * avg_profit * 100  # All wins, no losses

        # Sector diversification
        sectors = data["sectors"]
        total_trades = sum(sectors.values())
        sector_shares = {s: c / total_trades for s, c in sectors.items()}
        max_sector_share = max(sector_shares.values()) if sector_shares else 1.0
        sector_count = len(sectors)

        # Sector HHI
        sector_hhi = sum(s ** 2 for s in sector_shares.values())

        # Ghost Bias flag [CONVERGED]
        ghost_bias = max_sector_share > GHOST_BIAS_SECTOR_HHI

        results[code] = {
            "broker_name": data["broker_name"],
            "score": round(score, 4),
            "win_rate": round(win_rate, 4),
            "avg_profit": round(avg_profit, 6),
            "avg_loss": round(avg_loss, 6),
            "n": n,
            "unique_stocks": len(data["stocks"]),
            "sector_count": sector_count,
            "max_sector_share": round(max_sector_share, 4),
            "sector_hhi": round(sector_hhi, 4),
            "ghost_bias": ghost_bias,
            "sectors": {s: c for s, c in sorted(sectors.items(),
                                                 key=lambda x: -x[1])},
        }

    return results


def bootstrap_ci(
    returns: list[float],
    n_iterations: int = BOOTSTRAP_ITERATIONS,
    ci: float = 0.95,
    seed: int = 42,
) -> tuple[float, float]:
    """Compute bootstrap confidence interval for Winner Score.

    [HYPOTHESIS: WINNER_003] Trader: "Bootstrap CI 是護身符"
    Uses fixed seed for reproducibility across runs.

    Returns:
        (ci_lower, ci_upper) of Winner Score distribution.
    """
    returns = np.array(returns)
    n = len(returns)
    if n < 5:
        return (0.0, 0.0)

    rng = np.random.RandomState(seed)
    scores = []
    for _ in range(n_iterations):
        sample = rng.choice(returns, size=n, replace=True)
        wins = sample[sample > 0]
        losses = sample[sample <= 0]
        wr = len(wins) / n
        avg_p = np.mean(wins) if len(wins) > 0 else 0.0
        avg_l = np.mean(losses) if len(losses) > 0 else -0.001
        if abs(avg_l) > 1e-6:
            s = wr * (avg_p / abs(avg_l))
        else:
            s = wr * avg_p * 100
        scores.append(s)

    alpha = (1 - ci) / 2
    lower = float(np.percentile(scores, alpha * 100))
    upper = float(np.percentile(scores, (1 - alpha) * 100))
    return (round(lower, 4), round(upper, 4))


def build_registry(
    broker_dir: Path = BROKER_MONTHLY_DIR,
    fwd_path: Path = FORWARD_RETURNS_PATH,
    output_path: Path = WINNER_OUTPUT_PATH,
    horizon: str = "d21",
    min_n: int = WINNER_MIN_N,
    score_threshold: float = WINNER_SCORE_THRESHOLD,
    tier1_ci: float = TIER1_CI_LOWER,
    tier2_ci: float = TIER2_CI_LOWER,
    with_bootstrap: bool = True,
) -> dict:
    """Build complete Winner Branch Registry.

    Pipeline:
    1. Scan broker files → extract buy instances
    2. Match with forward returns
    3. Compute Winner Score per broker code
    4. (Optional) Bootstrap CI filtering
    5. Ghost Bias flagging
    6. Save to JSON

    Returns:
        Registry dict with winners and metadata.
    """
    logger.info("=== Building Winner Branch Registry ===")

    # Step 1: Load sector mappings
    sector_map = _load_sector_mapping()
    chain_map = _load_industry_chain_map()
    logger.info(f"Sector mapping: {len(sector_map)} L1, {len(chain_map)} chain")

    # Step 2: Scan broker files
    records = scan_broker_buys(broker_dir)
    if not records:
        logger.warning("No broker buy records found")
        return {"winners": {}, "metadata": {"error": "no_records"}}

    # Step 3: Build forward returns index
    fwd_index = build_forward_returns_index(fwd_path)

    # Step 4: Compute winner scores
    all_scores = compute_winner_scores(
        records, fwd_index, sector_map, chain_map,
        horizon=horizon, min_n=min_n,
    )
    logger.info(f"Computed scores for {len(all_scores)} broker codes (n >= {min_n})")

    # Step 5: Bootstrap CI (optional — slow for large datasets)
    if with_bootstrap:
        logger.info("Running Bootstrap CI...")
        # Re-scan to get per-broker returns for CI
        broker_returns = {}
        for rec in records:
            code = rec["broker_code"]
            stock = rec["stock_code"]
            date = rec["date"]
            fwd = fwd_index.get((stock, date))
            if fwd is None:
                closest = _find_closest_date(stock, date, fwd_index)
                if closest:
                    fwd = fwd_index[(stock, closest)]
            if fwd and fwd.get(horizon) is not None:
                ret = fwd[horizon]
                if not np.isnan(ret):
                    broker_returns.setdefault(code, []).append(ret)

        for code in all_scores:
            if code in broker_returns and len(broker_returns[code]) >= 5:
                # Per-broker deterministic seed for reproducibility
                seed = hash(code) % (2**31)
                ci_lo, ci_hi = bootstrap_ci(broker_returns[code], seed=seed)
                all_scores[code]["ci_lower"] = ci_lo
                all_scores[code]["ci_upper"] = ci_hi
            else:
                all_scores[code]["ci_lower"] = 0.0
                all_scores[code]["ci_upper"] = 0.0

    # Step 6: Tiered classification [CONVERGED with Trader]
    # Tier 1 (Sniper Ready): CI >= 1.0 — highest weight signals
    # Tier 2 (Observer): CI >= 0.7 — cross-validation only
    winners = {}
    filtered_by_score = 0
    filtered_by_ci = 0
    ghost_biased = 0
    tier1_count = 0
    tier2_count = 0

    for code, info in all_scores.items():
        if info["score"] < score_threshold:
            filtered_by_score += 1
            continue

        ci_lo = info.get("ci_lower", 0) if with_bootstrap else info["score"]

        if with_bootstrap and ci_lo < tier2_ci:
            filtered_by_ci += 1
            continue

        # Assign tier
        if ci_lo >= tier1_ci:
            info["tier"] = 1
            tier1_count += 1
        else:
            info["tier"] = 2
            tier2_count += 1

        if info["ghost_bias"]:
            ghost_biased += 1
            info["ghost_bias_discount"] = 0.5
        else:
            info["ghost_bias_discount"] = 1.0
        winners[code] = info

    logger.info(
        f"Winners: {len(winners)} (Tier 1: {tier1_count}, Tier 2: {tier2_count}) "
        f"(filtered: {filtered_by_score} by score, {filtered_by_ci} by CI, "
        f"{ghost_biased} ghost-biased)"
    )

    # Step 7: Build output
    registry = {
        "winners": winners,
        "metadata": {
            "total_broker_codes": len(all_scores),
            "winners_count": len(winners),
            "tier1_count": tier1_count,
            "tier2_count": tier2_count,
            "filtered_by_score": filtered_by_score,
            "filtered_by_ci": filtered_by_ci,
            "ghost_biased_count": ghost_biased,
            "horizon": horizon,
            "min_n": min_n,
            "score_threshold": score_threshold,
            "tier1_ci": tier1_ci,
            "tier2_ci": tier2_ci,
            "bootstrap_iterations": BOOTSTRAP_ITERATIONS if with_bootstrap else 0,
            "source_files": len(glob.glob(str(broker_dir / "*.json"))),
            "buy_instances": len(records),
            "built_at": datetime.now().isoformat(),
        },
    }

    # Save
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)
    logger.info(f"Saved registry to {output_path}")

    return registry


def load_registry(path: Path = WINNER_OUTPUT_PATH) -> dict:
    """Load pre-built Winner Branch Registry (all tiers)."""
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("winners", {})


def load_tier1_codes(path: Path = WINNER_OUTPUT_PATH) -> set:
    """Load only Tier 1 (Sniper Ready) broker codes.

    [CONVERGED] Trader: "只用那 3 家鋼鐵核心" for broker_winner_momentum.
    """
    winners = load_registry(path)
    return {code for code, info in winners.items() if info.get("tier") == 1}


def load_tier2_codes(path: Path = WINNER_OUTPUT_PATH) -> set:
    """Load Tier 2 (Observer) broker codes for cross-validation."""
    winners = load_registry(path)
    return {code for code, info in winners.items() if info.get("tier") == 2}


# --- CLI entry point ---
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(message)s",
                        stream=sys.stdout)
    # Force UTF-8 on Windows
    sys.stdout.reconfigure(encoding="utf-8")

    import argparse
    parser = argparse.ArgumentParser(description="Build Winner Branch Registry")
    parser.add_argument("--no-bootstrap", action="store_true",
                        help="Skip bootstrap CI (faster)")
    parser.add_argument("--horizon", default="d21",
                        choices=["d7", "d21", "d90"],
                        help="Forward return horizon")
    parser.add_argument("--min-n", type=int, default=WINNER_MIN_N)
    parser.add_argument("--threshold", type=float, default=WINNER_SCORE_THRESHOLD)
    args = parser.parse_args()

    registry = build_registry(
        horizon=args.horizon,
        min_n=args.min_n,
        score_threshold=args.threshold,
        with_bootstrap=not args.no_bootstrap,
    )

    meta = registry["metadata"]
    winners = registry["winners"]
    print(f"\n=== Winner Branch Registry ===")
    print(f"Source files: {meta['source_files']}")
    print(f"Buy instances: {meta['buy_instances']}")
    print(f"Broker codes evaluated: {meta['total_broker_codes']}")
    print(f"Winners: {meta['winners_count']}")
    print(f"Filtered by score: {meta['filtered_by_score']}")
    print(f"Filtered by CI: {meta['filtered_by_ci']}")
    print(f"Ghost-biased: {meta['ghost_biased_count']}")

    # Top 10 winners
    if winners:
        sorted_w = sorted(winners.items(), key=lambda x: -x[1]["score"])
        print(f"\nTop 10 Winners (horizon={args.horizon}):")
        print(f"{'Code':<12} {'Name':<16} {'Score':>7} {'WR':>6} {'N':>5} {'Sectors':>8} {'Ghost':>6}")
        print("-" * 65)
        for code, info in sorted_w[:10]:
            print(f"{code:<12} {info['broker_name'][:14]:<16} "
                  f"{info['score']:>7.3f} {info['win_rate']:>5.1%} "
                  f"{info['n']:>5} {info['sector_count']:>8} "
                  f"{'YES' if info['ghost_bias'] else 'no':>6}")
