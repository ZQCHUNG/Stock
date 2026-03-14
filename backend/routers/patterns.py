"""Pattern matching & Winner DNA routes.

Split from analysis.py — similar-stocks, similar-history, winner-dna-match,
pattern-library, super-stock-flag endpoints.
"""

from fastapi import APIRouter, HTTPException, Query
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================
# R64: Similar Pattern Matching (DTW)
# ============================================================


@router.get("/{code}/similar-stocks")
def find_similar_stocks(
    code: str,
    window: int = Query(20, ge=5, le=120, description="比對天數 (20=月線, 60=季線)"),
    top_n: int = Query(10, ge=1, le=50),
    candidate_codes: str | None = Query(None, description="指定比對股票 (逗號分隔)"),
):
    """Find stocks with similar recent price patterns (DTW algorithm)"""
    from analysis.pattern_matcher import find_similar_stocks as _find
    try:
        codes = candidate_codes.split(",") if candidate_codes else None
        results = _find(code, window=window, top_n=top_n, candidate_codes=codes)
        return {"code": code, "window": window, "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{code}/similar-history")
def find_similar_in_history(
    code: str,
    window: int = Query(20, ge=5, le=120),
    search_code: str | None = Query(None, description="搜尋目標股票 (預設=自身歷史)"),
    lookback_days: int = Query(365, ge=60, le=1825),
):
    """Find similar pattern segments in history + subsequent price action"""
    from analysis.pattern_matcher import find_similar_pattern_in_history as _find
    try:
        results = _find(code, window=window, search_code=search_code,
                        lookback_days=lookback_days)
        return {"code": code, "window": window, "search_code": search_code or code,
                "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Winner DNA Library — Pattern Recognition Phase 2-3
# [CONVERGED — Wall Street Trader + Architect Critic APPROVED]
# ---------------------------------------------------------------------------


@router.get("/{code}/winner-dna-match")
def get_winner_dna_match(code: str):
    """Match stock against Winner DNA library — Phase 5 Two-Stage Matcher

    [OFFICIALLY APPROVED — Architect Critic Phase 4-5 Gate]
    Stage 1: k-NN (k=5) in reduced space
    Stage 2: Multi-scale DTW (60d + 20d) when price data available
    Failed Pattern warning: red warning if stock matches losers too
    """
    try:
        from analysis.winner_dna import (
            load_cluster_db,
            load_reducer,
            load_profiles_from_db,
            match_stock_to_dna,
            FEATURES_FILE,
            WINNER_DNA_FILE,
            PRICE_CACHE_FILE,
            _load_metadata,
        )
        from backend.dependencies import make_serializable
        import numpy as np
        import pandas as pd

        # Load cluster DB
        db = load_cluster_db()
        if db is None:
            return {"code": code, "status": "no_library",
                    "detail": "Winner DNA library not built yet. Run pattern_labeler.py + winner_dna.py"}

        # Load features for this stock
        if not FEATURES_FILE.exists():
            raise HTTPException(status_code=500, detail="Features file not found")

        features_df = pd.read_parquet(FEATURES_FILE)
        metadata = _load_metadata()
        all_features = metadata["all_features"]

        # Load reducer (persisted UMAP/PCA)
        reducer = load_reducer()
        if reducer is None:
            return {"code": code, "status": "no_reducer",
                    "detail": "Reducer not found. Rebuild DNA library."}

        # Load profiles
        profiles = load_profiles_from_db(db)

        # Load samples for k-NN (optional but recommended)
        samples_df = None
        samples_reduced = None
        samples_labels = None
        if WINNER_DNA_FILE.exists():
            samples_df = pd.read_parquet(WINNER_DNA_FILE)
            # Re-reduce samples through the same reducer
            feature_cols = [f for f in all_features if f in samples_df.columns]
            feature_matrix = samples_df[feature_cols].values.astype(np.float64)
            feature_matrix = np.nan_to_num(feature_matrix, nan=0.0)
            try:
                samples_reduced = reducer.transform(feature_matrix)
                # Assign labels based on cluster centroids (closest centroid)
                from analysis.winner_dna import _cosine_sim
                samples_labels = np.zeros(len(samples_df), dtype=int)
                for i in range(len(samples_df)):
                    best_sim = -1
                    for p in profiles:
                        centroid = np.array(p.centroid)
                        if len(centroid) == samples_reduced.shape[1]:
                            sim = _cosine_sim(samples_reduced[i], centroid)
                            if sim > best_sim:
                                best_sim = sim
                                samples_labels[i] = p.cluster_id
            except Exception as e:
                logger.debug(f"Optional operation failed: {e}")
                samples_df = None
                samples_reduced = None

        # Load price data for DTW Stage 2 (optional)
        price_df = None
        if PRICE_CACHE_FILE.exists():
            try:
                price_df = pd.read_parquet(PRICE_CACHE_FILE)
            except Exception as e:
                logger.debug(f"Optional cache operation failed: {e}")

        # Run Two-Stage Matcher
        result = match_stock_to_dna(
            code, features_df, profiles, reducer, all_features,
            samples_df=samples_df,
            samples_reduced=samples_reduced,
            samples_labels=samples_labels,
            price_df=price_df,
        )

        return make_serializable(result.to_dict())
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{code}/super-stock-flag")
def get_super_stock_flag(code: str):
    """Super stock potential flag — Gene Mutation delta_div > 2sigma

    [VERIFIED: GENE_MUTATION_SCANNER] — uses existing 1.5sigma detection,
    upgraded to 2.0sigma for super stock threshold.
    """
    try:
        from analysis.pattern_labeler import compute_super_stock_flags, _load_metadata
        import pandas as pd

        from analysis.winner_dna import FEATURES_FILE
        if not FEATURES_FILE.exists():
            raise HTTPException(status_code=500, detail="Features file not found")

        features_df = pd.read_parquet(FEATURES_FILE)
        metadata = _load_metadata()

        flags = compute_super_stock_flags(features_df, metadata)
        if flags.empty:
            return {"code": code, "status": "no_data"}

        stock_flag = flags[flags["stock_code"] == code]
        if stock_flag.empty:
            return {"code": code, "status": "not_found"}

        row = stock_flag.iloc[0]
        return {
            "code": code,
            "date": str(row["date"]),
            "is_super_stock_potential": bool(row["is_super_stock_potential"]),
            "mutation_type": row["mutation_type"],
            "delta_z": round(float(row["delta_z"]), 4),
            "tech_score": round(float(row["tech_score"]), 4),
            "broker_score": round(float(row["broker_score"]), 4),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pattern-library")
def get_pattern_library():
    """Phase 4: Pattern Performance DB — Winner DNA Library overview

    Returns cluster profiles with multi-horizon performance stats,
    recency-weighted stats, and confidence levels.
    """
    try:
        from analysis.winner_dna import load_cluster_db

        db = load_cluster_db()
        if db is None:
            return {"status": "no_library",
                    "detail": "Winner DNA library not built yet."}

        return {
            "status": "ok",
            "build_date": db.get("build_date", ""),
            "version": db.get("version", ""),
            "n_samples": db.get("n_samples", 0),
            "n_clusters": db.get("n_clusters", 0),
            "clusters": db.get("clusters", []),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
