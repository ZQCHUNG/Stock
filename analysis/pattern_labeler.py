"""Pattern Labeler — Phase 2: Historical Winner DNA 標記

[CONVERGED — Wall Street Trader + Architect Critic APPROVED]

Scans historical price data to identify "super stock" episodes and extracts
their 65-feature DNA at the Epiphany Point (起漲點).

Labeling Strategy (CTO Hybrid C+B — Gene Mutation Driven):
  1. Find stocks achieving [HYPOTHESIS: SUPER_STOCK_TARGET]:
     - 3-month (63 trading days) gain > 50%
     - 1-year (252 trading days) gain > 100%
  2. Trace back 21 days before the move starts → Epiphany Point
  3. Extract 65-feature vector from features_all.parquet
  4. Compute Gene Mutation Δ_div at that point
  5. Label control group: similar feature profile but failed (d90 < 0)

Output: winner_dna_samples.parquet
  - stock_code, epiphany_date, peak_date, label (winner/loser)
  - 65 feature columns (Z-score normalized)
  - forward returns at multiple horizons
  - gene_mutation_delta (broker vs technical divergence)
  - regime_context (MA200 above/below)
"""

import json
import logging
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

_logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FEATURES_DIR = PROJECT_ROOT / "data" / "pattern_data" / "features"
FEATURES_FILE = FEATURES_DIR / "features_all.parquet"
FORWARD_RETURNS_FILE = FEATURES_DIR / "forward_returns.parquet"
PRICE_CACHE_FILE = FEATURES_DIR / "price_cache.parquet"
METADATA_FILE = FEATURES_DIR / "feature_metadata.json"
OUTPUT_FILE = FEATURES_DIR / "winner_dna_samples.parquet"

# ---------------------------------------------------------------------------
# Configuration — all thresholds labeled per Architect Critic mandate
# ---------------------------------------------------------------------------

LABELER_CONFIG = {
    # [HYPOTHESIS: SUPER_STOCK_TARGET] — Trader proposed, Architect labeled
    "gain_3mo_threshold": 0.50,       # 3-month gain > 50%
    "gain_1yr_threshold": 1.00,       # 1-year gain > 100%

    # Epiphany Point lookback
    "epiphany_lookback_days": 21,     # Days before move start to capture DNA

    # Rolling window for finding the move start
    "move_start_window": 63,          # ~3 months trading days

    # Minimum data requirements
    "min_history_days": 252,          # Need at least 1 year of data

    # Control group (loser) criteria
    "loser_d90_threshold": 0.0,       # d90 return < 0% = loser

    # Forward return horizons to compute
    "forward_horizons": [7, 21, 30, 60, 90, 180, 365],

    # Gene Mutation dimensions
    "technical_features": None,       # Loaded from metadata
    "brokerage_features": None,       # Loaded from metadata
}


# ---------------------------------------------------------------------------
# Load metadata
# ---------------------------------------------------------------------------

def _load_metadata() -> dict:
    """Load feature metadata."""
    if not METADATA_FILE.exists():
        raise FileNotFoundError(f"Metadata not found: {METADATA_FILE}")
    with open(METADATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _get_dimension_features(metadata: dict, dimension: str) -> list[str]:
    """Get feature names for a specific dimension."""
    return metadata["dimensions"].get(dimension, {}).get("features", [])


# ---------------------------------------------------------------------------
# Phase 2a: Find Super Stock Episodes
# ---------------------------------------------------------------------------

def find_super_stock_episodes(
    price_df: pd.DataFrame,
    config: Optional[dict] = None,
) -> pd.DataFrame:
    """Scan price history to find stocks with explosive moves.

    [HYPOTHESIS: SUPER_STOCK_TARGET] — Thresholds are human-defined targets,
    not statistically derived. Pending sensitivity test.

    Args:
        price_df: DataFrame with columns [stock_code, date, close]
        config: Override LABELER_CONFIG params

    Returns:
        DataFrame with columns:
          stock_code, peak_date, trough_date, epiphany_date,
          gain_3mo, gain_1yr, max_drawdown_before_peak
    """
    cfg = dict(LABELER_CONFIG)
    if config:
        cfg.update(config)

    gain_3mo_thresh = cfg["gain_3mo_threshold"]
    gain_1yr_thresh = cfg["gain_1yr_threshold"]
    epiphany_days = cfg["epiphany_lookback_days"]
    min_history = cfg["min_history_days"]
    move_window = cfg["move_start_window"]

    episodes = []
    stock_codes = price_df["stock_code"].unique()
    _logger.info("Scanning %d stocks for super stock episodes...", len(stock_codes))

    for code in stock_codes:
        stock_data = price_df[price_df["stock_code"] == code].sort_values("date")
        if len(stock_data) < min_history:
            continue

        dates = stock_data["date"].values
        closes = stock_data["close"].values

        # Sliding window: for each point, check if it's a local trough
        # followed by 50%+ gain in 3 months and 100%+ in 1 year
        for i in range(min_history, len(closes) - move_window):
            current_price = closes[i]
            if current_price <= 0:
                continue

            # Look forward: max price in next 63 days (3 months)
            end_3mo = min(i + move_window, len(closes))
            max_3mo = np.max(closes[i:end_3mo])
            gain_3mo = (max_3mo / current_price) - 1.0

            if gain_3mo < gain_3mo_thresh:
                continue

            # Look forward: max price in next 252 days (1 year)
            end_1yr = min(i + 252, len(closes))
            max_1yr = np.max(closes[i:end_1yr])
            gain_1yr = (max_1yr / current_price) - 1.0

            if gain_1yr < gain_1yr_thresh:
                continue

            # Found a super stock episode!
            # Find the peak date (max price within 1 year)
            peak_offset = np.argmax(closes[i:end_1yr])
            peak_idx = i + peak_offset
            peak_date = dates[peak_idx]

            # Find the trough (move start) — the lowest point
            # within `move_window` days before the current point
            trough_start = max(0, i - move_window)
            trough_offset = np.argmin(closes[trough_start:i + 1])
            trough_idx = trough_start + trough_offset
            trough_date = dates[trough_idx]
            trough_price = closes[trough_idx]

            # Epiphany Point: `epiphany_days` before the trough
            epiphany_idx = max(0, trough_idx - epiphany_days)
            epiphany_date = dates[epiphany_idx]

            # Max drawdown before peak (from epiphany to peak)
            if peak_idx > epiphany_idx:
                segment = closes[epiphany_idx:peak_idx + 1]
                running_max = np.maximum.accumulate(segment)
                drawdowns = (segment - running_max) / running_max
                max_dd = float(np.min(drawdowns))
            else:
                max_dd = 0.0

            episodes.append({
                "stock_code": code,
                "epiphany_date": pd.Timestamp(epiphany_date),
                "trough_date": pd.Timestamp(trough_date),
                "peak_date": pd.Timestamp(peak_date),
                "trough_price": float(trough_price),
                "peak_price": float(closes[peak_idx]),
                "gain_3mo": round(gain_3mo, 4),
                "gain_1yr": round(gain_1yr, 4),
                "max_drawdown_before_peak": round(max_dd, 4),
                "label": "winner",
            })

    # Deduplicate: same stock within 60 days → keep the one with highest gain
    result = pd.DataFrame(episodes)
    if result.empty:
        _logger.warning("No super stock episodes found!")
        return result

    result = result.sort_values("gain_1yr", ascending=False)
    result = _deduplicate_episodes(result, gap_days=60)

    _logger.info("Found %d super stock episodes across %d unique stocks",
                 len(result), result["stock_code"].nunique())
    return result


def _deduplicate_episodes(df: pd.DataFrame, gap_days: int = 60) -> pd.DataFrame:
    """Remove duplicate episodes: same stock within gap_days → keep best."""
    if df.empty:
        return df

    kept = []
    for code in df["stock_code"].unique():
        stock_eps = df[df["stock_code"] == code].sort_values("epiphany_date")
        last_date = None
        for _, row in stock_eps.iterrows():
            if last_date is None or (row["epiphany_date"] - last_date).days > gap_days:
                kept.append(row)
                last_date = row["epiphany_date"]

    return pd.DataFrame(kept).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Phase 2b: Extract Feature DNA at Epiphany Points
# ---------------------------------------------------------------------------

def extract_epiphany_features(
    episodes: pd.DataFrame,
    features_df: pd.DataFrame,
    metadata: dict,
) -> pd.DataFrame:
    """Extract 65-feature DNA vector at each Epiphany Point.

    For each episode, finds the closest available feature date to the
    epiphany_date and extracts the full feature vector.

    Args:
        episodes: DataFrame from find_super_stock_episodes()
        features_df: features_all.parquet loaded as DataFrame
        metadata: Feature metadata dict

    Returns:
        Episodes enriched with 65 feature columns + gene_mutation_delta
    """
    all_features = metadata["all_features"]
    tech_features = _get_dimension_features(metadata, "technical")
    broker_features = _get_dimension_features(metadata, "brokerage")

    enriched_rows = []
    matched = 0
    missed = 0

    for _, episode in episodes.iterrows():
        code = episode["stock_code"]
        target_date = episode["epiphany_date"]

        # Find feature row closest to epiphany_date (within ±5 trading days)
        stock_features = features_df[features_df["stock_code"] == code]
        if stock_features.empty:
            missed += 1
            continue

        # Find closest date
        date_diffs = (stock_features["date"] - target_date).abs()
        min_diff_idx = date_diffs.idxmin()
        min_diff_days = date_diffs.loc[min_diff_idx].days

        if abs(min_diff_days) > 5:
            missed += 1
            continue

        feature_row = stock_features.loc[min_diff_idx]
        actual_date = feature_row["date"]

        # Extract feature vector
        row_data = episode.to_dict()
        row_data["feature_date"] = actual_date
        row_data["regime_context"] = int(feature_row.get("regime_tag", 0))

        for feat in all_features:
            row_data[feat] = float(feature_row.get(feat, np.nan))

        # Compute Gene Mutation Δ_div [VERIFIED: GENE_MUTATION_SCANNER]
        # Δ_div = mean(brokerage features) - mean(technical features)
        tech_vals = [float(feature_row.get(f, np.nan)) for f in tech_features]
        broker_vals = [float(feature_row.get(f, np.nan)) for f in broker_features]

        tech_mean = np.nanmean(tech_vals) if tech_vals else 0.0
        broker_mean = np.nanmean(broker_vals) if broker_vals else 0.0

        row_data["gene_mutation_delta"] = round(broker_mean - tech_mean, 4)
        row_data["tech_score"] = round(tech_mean, 4)
        row_data["broker_score"] = round(broker_mean, 4)

        enriched_rows.append(row_data)
        matched += 1

    _logger.info("Feature extraction: %d matched, %d missed (no feature data)",
                 matched, missed)

    return pd.DataFrame(enriched_rows)


# ---------------------------------------------------------------------------
# Phase 2c: Compute Forward Returns at Multiple Horizons
# ---------------------------------------------------------------------------

def compute_forward_returns(
    episodes: pd.DataFrame,
    price_df: pd.DataFrame,
    horizons: Optional[list[int]] = None,
) -> pd.DataFrame:
    """Compute forward returns from each epiphany_date at multiple horizons.

    Args:
        episodes: DataFrame with stock_code and epiphany_date
        price_df: DataFrame with [stock_code, date, close]
        horizons: List of forward-looking days [7, 21, 30, 60, 90, 180, 365]

    Returns:
        Episodes enriched with fwd_Xd columns
    """
    if horizons is None:
        horizons = LABELER_CONFIG["forward_horizons"]

    # Build price lookup: {(stock_code, date) → close}
    price_lookup = {}
    for _, row in price_df.iterrows():
        key = (row["stock_code"], pd.Timestamp(row["date"]))
        price_lookup[key] = row["close"]

    # Build sorted date arrays per stock for nearest-date lookup
    stock_dates = {}
    for code in price_df["stock_code"].unique():
        stock_data = price_df[price_df["stock_code"] == code].sort_values("date")
        stock_dates[code] = stock_data[["date", "close"]].values

    result = episodes.copy()

    for horizon in horizons:
        col_name = f"fwd_{horizon}d"
        returns = []

        for _, row in result.iterrows():
            code = row["stock_code"]
            base_date = pd.Timestamp(row["epiphany_date"])

            if code not in stock_dates:
                returns.append(np.nan)
                continue

            dates_closes = stock_dates[code]
            dates = pd.DatetimeIndex([pd.Timestamp(d) for d in dates_closes[:, 0]])

            # Find base price (closest to epiphany_date)
            base_idx = _find_nearest_date_idx(dates, base_date, max_gap=5)
            if base_idx is None:
                returns.append(np.nan)
                continue

            base_price = float(dates_closes[base_idx, 1])

            # Find forward price
            target_date = base_date + pd.Timedelta(days=int(horizon * 1.5))  # Rough calendar days
            fwd_idx = _find_nearest_date_idx(
                dates, base_date + pd.Timedelta(days=horizon),
                max_gap=10, search_start=base_idx
            )

            if fwd_idx is None or base_price <= 0:
                returns.append(np.nan)
                continue

            fwd_price = float(dates_closes[fwd_idx, 1])
            fwd_return = (fwd_price / base_price) - 1.0
            returns.append(round(fwd_return, 6))

        result[col_name] = returns

    # Also compute max drawdown in first 30 days
    max_dds = []
    for _, row in result.iterrows():
        code = row["stock_code"]
        base_date = pd.Timestamp(row["epiphany_date"])

        if code not in stock_dates:
            max_dds.append(np.nan)
            continue

        dates_closes = stock_dates[code]
        dates = pd.DatetimeIndex([pd.Timestamp(d) for d in dates_closes[:, 0]])

        base_idx = _find_nearest_date_idx(dates, base_date, max_gap=5)
        if base_idx is None:
            max_dds.append(np.nan)
            continue

        # Next 30 trading days
        end_idx = min(base_idx + 30, len(dates_closes))
        segment = dates_closes[base_idx:end_idx, 1].astype(float)

        if len(segment) < 2:
            max_dds.append(0.0)
            continue

        running_max = np.maximum.accumulate(segment)
        drawdowns = (segment - running_max) / running_max
        max_dds.append(round(float(np.min(drawdowns)), 6))

    result["max_drawdown_30d"] = max_dds

    return result


def _find_nearest_date_idx(
    dates: pd.DatetimeIndex,
    target: pd.Timestamp,
    max_gap: int = 5,
    search_start: int = 0,
) -> Optional[int]:
    """Find index of nearest date in sorted array."""
    if len(dates) == 0:
        return None

    # Binary search for nearest date
    subset = dates[search_start:]
    if len(subset) == 0:
        return None

    diffs = (subset - target).total_seconds()
    abs_diffs = np.abs(diffs)
    min_idx = int(np.argmin(abs_diffs))

    if abs_diffs[min_idx] > max_gap * 86400:  # max_gap days in seconds
        return None

    return search_start + min_idx


# ---------------------------------------------------------------------------
# Phase 2d: Build Control Group (Losers)
# ---------------------------------------------------------------------------

def build_control_group(
    features_df: pd.DataFrame,
    forward_returns_df: pd.DataFrame,
    winner_episodes: pd.DataFrame,
    metadata: dict,
    n_samples: int = 0,
    config: Optional[dict] = None,
) -> pd.DataFrame:
    """Build control group of "loser" cases — similar feature profile but failed.

    Strategy: Sample dates where stocks had similar feature profiles (high
    momentum indicators) but went on to lose money (d90 < 0).

    Args:
        features_df: Full feature DataFrame
        forward_returns_df: Forward returns DataFrame
        winner_episodes: Winner episodes (to avoid overlap)
        metadata: Feature metadata
        n_samples: Number of loser samples (0 = match winner count)
        config: Override config

    Returns:
        DataFrame of loser samples with same schema as winner episodes
    """
    cfg = dict(LABELER_CONFIG)
    if config:
        cfg.update(config)

    all_features = metadata["all_features"]
    tech_features = _get_dimension_features(metadata, "technical")
    broker_features = _get_dimension_features(metadata, "brokerage")

    if n_samples <= 0:
        n_samples = len(winner_episodes)

    # Merge features with forward returns
    merged = features_df.merge(
        forward_returns_df[["stock_code", "date", "d90"]],
        on=["stock_code", "date"],
        how="inner",
    )

    # Filter: stocks that looked "hot" (high technical momentum) but failed
    # Hot = ma20_ratio > 0.5σ AND vol_ratio_20 > 0.5σ (above average momentum)
    hot_mask = (
        (merged["ma20_ratio"] > 0.5) &
        (merged["vol_ratio_20"] > 0.5) &
        (merged["d90"] < cfg["loser_d90_threshold"]) &
        (merged["d90"].notna())
    )

    losers = merged[hot_mask].copy()
    if losers.empty:
        _logger.warning("No loser samples found!")
        return pd.DataFrame()

    # Exclude dates that overlap with winner episodes (±30 days)
    winner_keys = set()
    for _, w in winner_episodes.iterrows():
        code = w["stock_code"]
        ep_date = pd.Timestamp(w["epiphany_date"])
        for offset in range(-30, 31):
            winner_keys.add((code, ep_date + pd.Timedelta(days=offset)))

    loser_mask = losers.apply(
        lambda r: (r["stock_code"], pd.Timestamp(r["date"])) not in winner_keys,
        axis=1,
    )
    losers = losers[loser_mask]

    if len(losers) > n_samples:
        losers = losers.sample(n=n_samples, random_state=42)

    # Build loser rows matching winner schema
    loser_rows = []
    for _, row in losers.iterrows():
        data = {
            "stock_code": row["stock_code"],
            "epiphany_date": row["date"],
            "trough_date": row["date"],
            "peak_date": row["date"],
            "trough_price": np.nan,
            "peak_price": np.nan,
            "gain_3mo": np.nan,
            "gain_1yr": np.nan,
            "max_drawdown_before_peak": np.nan,
            "label": "loser",
            "feature_date": row["date"],
            "regime_context": int(row.get("regime_tag", 0)),
        }

        # Feature vector
        for feat in all_features:
            data[feat] = float(row.get(feat, np.nan))

        # Gene Mutation Δ_div
        tech_vals = [float(row.get(f, np.nan)) for f in tech_features]
        broker_vals = [float(row.get(f, np.nan)) for f in broker_features]
        tech_mean = np.nanmean(tech_vals) if tech_vals else 0.0
        broker_mean = np.nanmean(broker_vals) if broker_vals else 0.0

        data["gene_mutation_delta"] = round(broker_mean - tech_mean, 4)
        data["tech_score"] = round(tech_mean, 4)
        data["broker_score"] = round(broker_mean, 4)

        # Forward returns (use what's available in forward_returns)
        data["fwd_90d"] = float(row.get("d90", np.nan))
        data["max_drawdown_30d"] = np.nan  # Would need price data

        loser_rows.append(data)

    result = pd.DataFrame(loser_rows)
    _logger.info("Built control group: %d loser samples", len(result))
    return result


# ---------------------------------------------------------------------------
# Phase 2e: Super Stock Potential Flag
# ---------------------------------------------------------------------------

def compute_super_stock_flags(
    features_df: pd.DataFrame,
    metadata: dict,
    sigma_threshold: float = 2.0,
) -> pd.DataFrame:
    """Flag current stocks with super stock potential.

    A stock gets flagged when its Gene Mutation Δ_div exceeds ±2σ,
    indicating extreme divergence between broker activity and price action.

    [VERIFIED: GENE_MUTATION_SCANNER] — uses existing 1.5σ detection,
    upgraded to 2.0σ for super stock threshold per CTO mandate.

    Args:
        features_df: Current features DataFrame
        metadata: Feature metadata
        sigma_threshold: Z-score threshold for flagging (default 2.0)

    Returns:
        DataFrame with is_super_stock_potential flag and supporting metrics
    """
    tech_features = _get_dimension_features(metadata, "technical")
    broker_features = _get_dimension_features(metadata, "brokerage")

    # Get latest date only
    latest_date = features_df["date"].max()
    latest = features_df[features_df["date"] == latest_date].copy()

    if latest.empty:
        return pd.DataFrame()

    # Compute dimension scores
    tech_cols = [f for f in tech_features if f in latest.columns]
    broker_cols = [f for f in broker_features if f in latest.columns]

    latest["tech_score"] = latest[tech_cols].mean(axis=1)
    latest["broker_score"] = latest[broker_cols].mean(axis=1)
    latest["delta_div"] = latest["broker_score"] - latest["tech_score"]

    # Z-normalize across all stocks
    mean_delta = latest["delta_div"].mean()
    std_delta = latest["delta_div"].std()

    if std_delta > 1e-8:
        latest["delta_z"] = (latest["delta_div"] - mean_delta) / std_delta
    else:
        latest["delta_z"] = 0.0

    # Flag super stock potential
    latest["is_super_stock_potential"] = latest["delta_z"].abs() > sigma_threshold
    latest["mutation_type"] = latest["delta_z"].apply(
        lambda z: "stealth_accumulation" if z > sigma_threshold
        else ("deceptive_distribution" if z < -sigma_threshold else "normal")
    )

    result = latest[["stock_code", "date", "tech_score", "broker_score",
                      "delta_div", "delta_z", "is_super_stock_potential",
                      "mutation_type"]].copy()

    flagged = result[result["is_super_stock_potential"]].shape[0]
    _logger.info("Super stock flags: %d/%d stocks flagged (σ=%.1f)",
                 flagged, len(result), sigma_threshold)

    return result


# ---------------------------------------------------------------------------
# Main: Run Full Labeling Pipeline
# ---------------------------------------------------------------------------

def run_labeling_pipeline(
    config: Optional[dict] = None,
    save: bool = True,
) -> pd.DataFrame:
    """Run the complete Phase 2 labeling pipeline.

    1. Load price data and features
    2. Find super stock episodes
    3. Extract feature DNA at Epiphany Points
    4. Compute multi-horizon forward returns
    5. Build control group
    6. Save combined winner_dna_samples.parquet

    Args:
        config: Override LABELER_CONFIG params
        save: Whether to save output parquet

    Returns:
        Combined DataFrame of winners + losers
    """
    _logger.info("=" * 60)
    _logger.info("Phase 2: Historical Pattern Labeling Pipeline")
    _logger.info("=" * 60)

    # Load data
    _logger.info("Loading data...")
    if not FEATURES_FILE.exists():
        raise FileNotFoundError(f"Features not found: {FEATURES_FILE}")
    if not PRICE_CACHE_FILE.exists():
        raise FileNotFoundError(f"Price cache not found: {PRICE_CACHE_FILE}")

    features_df = pd.read_parquet(FEATURES_FILE)
    price_df = pd.read_parquet(PRICE_CACHE_FILE)
    metadata = _load_metadata()

    _logger.info("Loaded: %d feature rows, %d price rows, %d stocks",
                 len(features_df), len(price_df),
                 features_df["stock_code"].nunique())

    # Load forward returns if available
    fwd_returns_df = None
    if FORWARD_RETURNS_FILE.exists():
        fwd_returns_df = pd.read_parquet(FORWARD_RETURNS_FILE)
        _logger.info("Loaded forward returns: %d rows", len(fwd_returns_df))

    # Step 1: Find super stock episodes
    _logger.info("Step 1: Finding super stock episodes...")
    episodes = find_super_stock_episodes(price_df, config)

    if episodes.empty:
        _logger.warning("No episodes found. Check data or loosen thresholds.")
        return pd.DataFrame()

    _logger.info("Found %d winner episodes", len(episodes))

    # Step 2: Extract feature DNA
    _logger.info("Step 2: Extracting feature DNA at Epiphany Points...")
    winners = extract_epiphany_features(episodes, features_df, metadata)
    _logger.info("Enriched %d episodes with feature DNA", len(winners))

    # Step 3: Compute forward returns
    _logger.info("Step 3: Computing multi-horizon forward returns...")
    winners = compute_forward_returns(winners, price_df)

    # Step 4: Build control group
    _logger.info("Step 4: Building control group (losers)...")
    if fwd_returns_df is not None:
        losers = build_control_group(
            features_df, fwd_returns_df, winners, metadata, config=config
        )
    else:
        _logger.warning("No forward returns file — skipping control group")
        losers = pd.DataFrame()

    # Combine
    combined = pd.concat([winners, losers], ignore_index=True)
    _logger.info("Combined dataset: %d winners + %d losers = %d total",
                 len(winners), len(losers), len(combined))

    # Summary statistics
    if not combined.empty:
        _print_summary(combined)

    # Save
    if save and not combined.empty:
        combined.to_parquet(OUTPUT_FILE, index=False)
        _logger.info("Saved to: %s", OUTPUT_FILE)

    return combined


def _print_summary(df: pd.DataFrame):
    """Print summary statistics of the labeled dataset."""
    winners = df[df["label"] == "winner"]
    losers = df[df["label"] == "loser"]

    _logger.info("\n" + "=" * 60)
    _logger.info("LABELING SUMMARY")
    _logger.info("=" * 60)
    _logger.info("Winners: %d episodes across %d stocks",
                 len(winners), winners["stock_code"].nunique() if not winners.empty else 0)
    _logger.info("Losers:  %d samples", len(losers))

    if not winners.empty:
        _logger.info("\nWinner gain distribution:")
        _logger.info("  3-month gain: median=%.0f%%, mean=%.0f%%",
                     winners["gain_3mo"].median() * 100,
                     winners["gain_3mo"].mean() * 100)
        _logger.info("  1-year gain:  median=%.0f%%, mean=%.0f%%",
                     winners["gain_1yr"].median() * 100,
                     winners["gain_1yr"].mean() * 100)

        _logger.info("\nGene Mutation Δ_div at Epiphany Points:")
        if "gene_mutation_delta" in winners.columns:
            _logger.info("  Winners: mean=%.3f, std=%.3f",
                         winners["gene_mutation_delta"].mean(),
                         winners["gene_mutation_delta"].std())
        if not losers.empty and "gene_mutation_delta" in losers.columns:
            _logger.info("  Losers:  mean=%.3f, std=%.3f",
                         losers["gene_mutation_delta"].mean(),
                         losers["gene_mutation_delta"].std())

        # Regime distribution
        if "regime_context" in winners.columns:
            regime_counts = winners["regime_context"].value_counts()
            _logger.info("\nRegime context distribution (winners):")
            for regime, count in regime_counts.items():
                label = {1: "Bull", 0: "Sideways", -1: "Bear"}.get(regime, "?")
                _logger.info("  %s: %d (%.0f%%)",
                             label, count, count / len(winners) * 100)

    _logger.info("=" * 60)


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    result = run_labeling_pipeline()
    if not result.empty:
        print(f"\nDone! {len(result)} samples saved to {OUTPUT_FILE}")
    else:
        print("\nNo samples found. Check logs for details.")
