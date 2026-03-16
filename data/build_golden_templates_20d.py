"""20-Dimension Golden Template Library Builder.

Builds golden templates using only the 20 OHLCV-derived technical features
from build_daily_features.py (close-only matrix).

Reuses dedup/cap/consistency logic from golden_template_builder.py.

Output:
    data/pattern_data/features/golden_templates_20d.parquet
    data/pattern_data/features/golden_templates_20d_norms.npy
    data/pattern_data/features/golden_templates_20d_metadata.json

Usage:
    python data/build_golden_templates_20d.py
"""

import json
import logging
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from data.build_daily_features import (
    TECH_FEATURE_COLS,
    build_daily_features,
    PIT_CLOSE_PATH,
    OUTPUT_FILE as DAILY_FEATURES_FILE,
)
from analysis.golden_template_builder import (
    DEFAULT_D30_THRESHOLD,
    DEFAULT_COOLDOWN_DAYS,
    DEFAULT_MAX_PER_STOCK,
    FORWARD_DAYS,
    FORWARD_LABELS,
    _compute_forward_returns_batch,
    _dedup_per_stock,
    _cap_per_stock,
    compute_consistency,
)

# --- Paths ---
FEATURES_DIR = PROJECT_ROOT / "data" / "pattern_data" / "features"
OUTPUT_PARQUET = FEATURES_DIR / "golden_templates_20d.parquet"
OUTPUT_NORMS = FEATURES_DIR / "golden_templates_20d_norms.npy"
OUTPUT_META = FEATURES_DIR / "golden_templates_20d_metadata.json"


def build_golden_templates_20d(
    features_parquet: str = None,
    close_matrix_parquet: str = None,
    output_parquet: str = None,
    d30_threshold: float = DEFAULT_D30_THRESHOLD,
    cooldown_days: int = DEFAULT_COOLDOWN_DAYS,
    max_per_stock: int = DEFAULT_MAX_PER_STOCK,
) -> dict:
    """Build golden template library using only 20 technical features.

    Pipeline:
      1. Load/compute all-dates features (20 close-only technical)
      2. Load close matrix for forward returns
      3. Compute forward returns for all (stock, date) pairs
      4. Filter D30 >= threshold
      5. Remove zero-feature rows
      6. Per-stock cooldown dedup
      7. Per-stock cap (top by consistency)
      8. Save golden_templates_20d.parquet + norms + metadata

    Args:
        features_parquet: Path to precomputed daily_features.parquet.
            If None, builds from pit_close_matrix.parquet (all dates).
        close_matrix_parquet: Path to pit_close_matrix.parquet.
        output_parquet: Path to save golden templates.
        d30_threshold: Minimum D30 forward return threshold.
        cooldown_days: Per-stock dedup window.
        max_per_stock: Max templates per stock.

    Returns:
        dict with build metadata.
    """
    t0 = time.time()

    cm_path = Path(close_matrix_parquet) if close_matrix_parquet else PIT_CLOSE_PATH
    out_parquet = Path(output_parquet) if output_parquet else OUTPUT_PARQUET

    # Step 1: Get features for ALL dates (not just latest)
    feat_path = Path(features_parquet) if features_parquet else DAILY_FEATURES_FILE
    if feat_path.exists():
        logger.info("Loading precomputed features from %s", feat_path)
        df = pd.read_parquet(feat_path)
        df["date"] = pd.to_datetime(df["date"])
    else:
        logger.info("Daily features not found, building from close matrix...")
        build_daily_features(latest_only=False)
        df = pd.read_parquet(DAILY_FEATURES_FILE)
        df["date"] = pd.to_datetime(df["date"])

    total_rows = len(df)
    available_features = [c for c in TECH_FEATURE_COLS if c in df.columns]
    logger.info("Features: %d rows, %d stocks, %d features",
                total_rows, df["stock_code"].nunique(), len(available_features))

    # Step 2: Load close matrix
    if not cm_path.exists():
        raise FileNotFoundError(f"Close matrix not found: {cm_path}")
    logger.info("Loading close matrix from %s", cm_path)
    close_matrix = pd.read_parquet(cm_path)
    close_matrix.index = pd.to_datetime(close_matrix.index)

    # Step 3: Compute forward returns
    logger.info("Computing forward returns for %d rows...", len(df))
    fwd = _compute_forward_returns_batch(
        df["stock_code"].values,
        df["date"].values,
        close_matrix,
    )
    for i, label in enumerate(FORWARD_LABELS):
        df[label] = fwd[:, i]

    # Step 4: Filter D30 >= threshold
    candidates = df[df["fwd_d30"] >= d30_threshold].copy()
    n_candidates = len(candidates)
    logger.info(
        "D30 >= %.0f%%: %d candidates (%.2f%%)",
        d30_threshold * 100, n_candidates,
        100 * n_candidates / max(total_rows, 1),
    )

    if n_candidates == 0:
        logger.warning("No candidates found with D30 >= %.0f%%", d30_threshold * 100)
        return {"status": "empty", "total_candidates": 0}

    # Step 5: Remove zero-feature rows
    feature_matrix = candidates[available_features].fillna(0).values
    row_sums = np.abs(feature_matrix).sum(axis=1)
    nonzero_mask = row_sums > 1e-6
    n_zero = int((~nonzero_mask).sum())
    candidates = candidates[nonzero_mask].copy()
    logger.info("Removed %d zero-feature rows, remaining: %d", n_zero, len(candidates))

    # Step 6: Per-stock cooldown dedup
    candidates = _dedup_per_stock(candidates, cooldown_days)
    n_after_dedup = len(candidates)
    logger.info("After %d-day cooldown dedup: %d templates", cooldown_days, n_after_dedup)

    # Compute consistency
    candidates["consistency"] = candidates.apply(
        lambda r: compute_consistency(r["fwd_d7"], r["fwd_d14"], r["fwd_d30"], r["fwd_d90"]),
        axis=1,
    )

    # Step 7: Per-stock cap
    candidates = _cap_per_stock(candidates, max_per_stock)
    n_after_cap = len(candidates)
    logger.info("After per-stock cap (%d): %d templates", max_per_stock, n_after_cap)

    # Build template_id
    candidates = candidates.sort_values(["stock_code", "date"]).reset_index(drop=True)
    candidates["template_id"] = np.arange(len(candidates), dtype=np.uint32)

    # Extract feature matrix and compute norms
    template_matrix = candidates[available_features].fillna(0).values.astype(np.float32)
    norms = np.linalg.norm(template_matrix, axis=1).astype(np.float32)
    norms[norms < 1e-10] = 1.0

    # Save outputs
    out_parquet.parent.mkdir(parents=True, exist_ok=True)

    save_cols = (
        ["template_id", "stock_code", "date"]
        + FORWARD_LABELS
        + ["consistency"]
        + available_features
    )
    candidates[save_cols].to_parquet(out_parquet, index=False)
    logger.info("Saved: %s (%d templates)", out_parquet, len(candidates))

    np.save(OUTPUT_NORMS, norms)
    logger.info("Saved: %s", OUTPUT_NORMS)

    # Build metadata
    elapsed = time.time() - t0
    stocks_represented = candidates["stock_code"].nunique()
    build_meta = {
        "built_at": pd.Timestamp.now().isoformat(),
        "variant": "20d_technical_close_only",
        "feature_count": len(available_features),
        "features": available_features,
        "d30_threshold": d30_threshold,
        "cooldown_days": cooldown_days,
        "max_per_stock": max_per_stock,
        "total_rows_in_features": total_rows,
        "total_candidates": n_candidates,
        "after_zero_filter": n_candidates - n_zero,
        "after_dedup": n_after_dedup,
        "after_cap": n_after_cap,
        "stocks_represented": int(stocks_represented),
        "avg_templates_per_stock": round(n_after_cap / max(stocks_represented, 1), 1),
        "elapsed_s": round(elapsed, 1),
    }

    with open(OUTPUT_META, "w", encoding="utf-8") as f:
        json.dump(build_meta, f, indent=2, default=str)
    logger.info("Saved: %s", OUTPUT_META)

    logger.info(
        "20D Golden template build complete: %d templates, %d stocks, %.1fs",
        n_after_cap, stocks_represented, elapsed,
    )
    return build_meta


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    print("Building 20-dimension golden templates...")
    result = build_golden_templates_20d()
    print(json.dumps(result, indent=2, default=str))
