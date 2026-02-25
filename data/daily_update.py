"""Daily Pattern Update Pipeline — incremental close matrix + RS + screener + fwd returns.

Runs at 20:15 Mon-Fri (after the 20:00 features rebuild):
  1. Extend pit_close_matrix with latest trading day(s) from yfinance
  1.5. Self-Healing: Sanitize close matrix (Phase 8 P0)
  2. Recompute PIT RS matrices from extended close matrix
  3. Refresh screener DB snapshot
  4. Rollover forward returns (backfill NaN horizons now that future data exists)

Uses the existing price_cache.parquet (built by build_features.py) as the primary
data source, with yfinance incremental download as fallback for new dates.

[VERIFIED: PIPELINE_V2] — designed to run after nightly Parquet rebuild
"""

import logging
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
PRICE_CACHE_PATH = DATA_DIR / "pattern_data" / "features" / "price_cache.parquet"

# PIT matrix paths (same as analysis/pit_rs.py)
PIT_CLOSE_PATH = DATA_DIR / "pit_close_matrix.parquet"
PIT_RS_PATH = DATA_DIR / "pit_rs_matrix.parquet"
PIT_PCTILE_PATH = DATA_DIR / "pit_rs_percentile.parquet"

# Forward returns path
FWD_RETURNS_PATH = DATA_DIR / "pattern_data" / "features" / "forward_returns.parquet"
FWD_HORIZONS = {"d3": 3, "d7": 7, "d21": 21, "d90": 90, "d180": 180}

# Phase 8 P0: Self-Healing Pipeline
ANOMALY_THRESHOLD = 0.15  # [HYPOTHESIS] |daily_change| > 15% → anomaly (excludes ex-div/IPO)
HEALED_EVENTS_FILE = DATA_DIR / "self_healed_events.json"


def sanitize_close_matrix(close_matrix: pd.DataFrame) -> dict:
    """Phase 8 P0: Detect and fix anomalies in close matrix.

    Architect directive:
    - |Change| > 15% AND NOT (ex-dividend or IPO) → MARK_ANOMALY
    - Retry yfinance 1x for anomalous data
    - Pipeline Monitor: "Self-Healed Events" counter

    [HYPOTHESIS: ANOMALY_THRESHOLD = 15%]

    Returns:
        {"anomalies_found": int, "healed": int, "flagged": int, "details": list}
    """
    import json

    if close_matrix is None or close_matrix.empty:
        return {"anomalies_found": 0, "healed": 0, "flagged": 0, "details": []}

    # Compute daily returns
    returns = close_matrix.pct_change()
    last_row = returns.iloc[-1] if len(returns) > 1 else pd.Series(dtype=float)

    anomalies = []
    healed = 0
    flagged = 0

    for stock_code in last_row.index:
        change = last_row[stock_code]
        if pd.isna(change):
            continue

        if abs(change) <= ANOMALY_THRESHOLD:
            continue

        # Potential anomaly detected
        is_legit = _check_legitimate_move(stock_code, change)

        if is_legit:
            logger.debug("Sanitizer: %s moved %.1f%% — legitimate (ex-div/IPO/limit)", stock_code, change * 100)
            continue

        # Try to heal: re-fetch from yfinance
        logger.warning("Sanitizer: %s anomaly detected (%.1f%%), attempting heal...", stock_code, change * 100)
        healed_price = _attempt_heal(stock_code)

        detail = {
            "stock_code": stock_code,
            "date": str(close_matrix.index[-1].date()) if hasattr(close_matrix.index[-1], 'date') else str(close_matrix.index[-1]),
            "original_change_pct": round(change * 100, 1),
            "action": "unknown",
        }

        if healed_price is not None:
            old_price = float(close_matrix[stock_code].iloc[-1])
            new_change = (healed_price / float(close_matrix[stock_code].iloc[-2]) - 1) if len(close_matrix) > 1 else 0

            if abs(new_change) <= ANOMALY_THRESHOLD:
                # Healed: update the matrix
                close_matrix.at[close_matrix.index[-1], stock_code] = healed_price
                healed += 1
                detail["action"] = "healed"
                detail["healed_price"] = healed_price
                logger.info("Sanitizer: %s healed (%.1f → %.1f)", stock_code, old_price, healed_price)
            else:
                # Same anomalous value after retry → real dramatic move, flag for review
                flagged += 1
                detail["action"] = "flagged"
                logger.info("Sanitizer: %s confirmed dramatic move (%.1f%%), flagging", stock_code, new_change * 100)
        else:
            flagged += 1
            detail["action"] = "flagged"
            logger.warning("Sanitizer: %s heal failed, flagging for review", stock_code)

        anomalies.append(detail)

    # Save healed events counter
    if anomalies:
        _update_healed_counter(anomalies)

    total = len(anomalies)
    logger.info("Sanitizer: %d anomalies found, %d healed, %d flagged", total, healed, flagged)
    return {"anomalies_found": total, "healed": healed, "flagged": flagged, "details": anomalies}


def _check_legitimate_move(stock_code: str, change: float) -> bool:
    """Check if a large price move is legitimate (ex-dividend, IPO, limit).

    Architect: "If |Change|>15% AND Not (IPO or Ex-dividend) → MARK_ANOMALY"
    """
    # TW stock limit: ±10% for regular stocks. IPO first 5 days no limit.
    # Ex-dividend can cause >10% gap

    try:
        # Check 1: Is it at/near the limit? (9.5% to 10.5% range = likely limit hit)
        if 0.095 <= abs(change) <= 0.105:
            return True  # Likely at limit up/down

        # Check 2: Check for recent dividend (ex-dividend causes gap)
        from data.fetcher import get_stock_data
        df = get_stock_data(stock_code, period_days=10)
        if df is not None and len(df) >= 2:
            # If volume is normal and the drop matches typical dividend patterns
            # Dividends in TW typically cause 2-8% drops
            if -0.20 < change < -0.02:
                # Could be ex-dividend — check if volume is normal (not panic)
                avg_vol = float(df["volume"].iloc[-5:].mean()) if len(df) >= 5 else float(df["volume"].mean())
                last_vol = float(df["volume"].iloc[-1])
                if last_vol < avg_vol * 3:  # Not a panic dump
                    return True  # Likely ex-dividend

        return False
    except Exception:
        return False  # Can't verify → treat as anomaly


def _attempt_heal(stock_code: str) -> float | None:
    """Re-fetch latest price from yfinance as heal attempt (max 1 retry).

    Architect: "Retry = 1, 防止無限循環"
    """
    try:
        import yfinance as yf
        ticker = yf.Ticker(f"{stock_code}.TW")
        hist = ticker.history(period="5d", auto_adjust=True)
        if hist is not None and not hist.empty:
            return float(hist["Close"].iloc[-1])

        # Try TPEX suffix
        ticker = yf.Ticker(f"{stock_code}.TWO")
        hist = ticker.history(period="5d", auto_adjust=True)
        if hist is not None and not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return None


def _update_healed_counter(anomalies: list[dict]):
    """Update the self-healed events JSON counter for Pipeline Monitor."""
    import json

    counter = {"total_healed": 0, "total_flagged": 0, "events": []}
    if HEALED_EVENTS_FILE.exists():
        try:
            counter = json.loads(HEALED_EVENTS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

    for a in anomalies:
        if a["action"] == "healed":
            counter["total_healed"] = counter.get("total_healed", 0) + 1
        elif a["action"] == "flagged":
            counter["total_flagged"] = counter.get("total_flagged", 0) + 1

    # Keep last 50 events
    counter.setdefault("events", [])
    counter["events"].extend(anomalies)
    counter["events"] = counter["events"][-50:]
    counter["last_run"] = datetime.now().isoformat()

    HEALED_EVENTS_FILE.write_text(json.dumps(counter, ensure_ascii=False, indent=2), encoding="utf-8")


def extend_close_matrix() -> dict:
    """Extend pit_close_matrix.parquet with latest dates from price_cache.

    Strategy:
      1. Load existing close matrix (wide: date × stocks)
      2. Load price_cache.parquet (long: date, stock_code, close, ...)
      3. Pivot price_cache to wide format
      4. Find new dates not in existing matrix
      5. Append new dates and save

    Returns:
        {"new_dates": int, "total_dates": int, "total_stocks": int}
    """
    t0 = time.time()

    # Load existing close matrix
    if PIT_CLOSE_PATH.exists():
        existing = pd.read_parquet(PIT_CLOSE_PATH)
        existing.index = pd.to_datetime(existing.index)
        logger.info("Existing close matrix: %d dates × %d stocks", len(existing), len(existing.columns))
    else:
        logger.warning("No existing close matrix found — will build from price_cache only")
        existing = pd.DataFrame()

    # Load price_cache (long format from build_features.py)
    if not PRICE_CACHE_PATH.exists():
        logger.warning("price_cache.parquet not found — trying yfinance incremental")
        return _yf_incremental_update(existing)

    cache = pd.read_parquet(PRICE_CACHE_PATH)
    cache["date"] = pd.to_datetime(cache["date"])

    # Pivot to wide format (date × stock_code → close)
    cache_wide = cache.pivot_table(index="date", columns="stock_code", values="close")
    cache_wide = cache_wide.sort_index()
    logger.info("Price cache: %d dates × %d stocks", len(cache_wide), len(cache_wide.columns))

    if existing.empty:
        # No existing matrix — use the full price cache
        merged = cache_wide
        new_dates = len(merged)
    else:
        # Find new dates
        existing_dates = set(existing.index)
        cache_dates = set(cache_wide.index)
        new_date_set = cache_dates - existing_dates

        if not new_date_set:
            # No new dates — try yfinance for today specifically
            logger.info("Price cache has no new dates — trying yfinance for latest")
            return _yf_incremental_update(existing)

        new_dates = len(new_date_set)
        logger.info("Found %d new dates in price_cache", new_dates)

        # Merge: union of stocks, keep existing data, add new date rows
        all_stocks = sorted(set(existing.columns) | set(cache_wide.columns))
        merged = existing.reindex(columns=all_stocks)

        for date in sorted(new_date_set):
            if date in cache_wide.index:
                row = cache_wide.loc[date]
                for col in row.index:
                    if col in merged.columns:
                        merged.loc[date, col] = row[col]

        merged = merged.sort_index()

    # Save updated matrix
    PIT_CLOSE_PATH.parent.mkdir(parents=True, exist_ok=True)
    merged.to_parquet(PIT_CLOSE_PATH)

    elapsed = time.time() - t0
    result = {
        "new_dates": new_dates,
        "total_dates": len(merged),
        "total_stocks": len(merged.columns),
        "elapsed_s": round(elapsed, 1),
    }
    logger.info("Close matrix updated: +%d dates → %d × %d (%.1fs)",
                new_dates, result["total_dates"], result["total_stocks"], elapsed)
    return result


def _yf_incremental_update(existing: pd.DataFrame) -> dict:
    """Fallback: download only the latest 5 trading days from yfinance.

    This is much faster than a full rebuild — only fetches the latest data.
    """
    if existing.empty:
        logger.error("Cannot do incremental update without existing close matrix")
        return {"new_dates": 0, "error": "no_existing_matrix"}

    try:
        import yfinance as yf
    except ImportError:
        logger.error("yfinance not installed")
        return {"new_dates": 0, "error": "yfinance_not_installed"}

    t0 = time.time()
    latest_existing = existing.index.max()
    logger.info("Latest date in close matrix: %s", latest_existing.strftime("%Y-%m-%d"))

    # Download last 10 calendar days to ensure we get latest trading days
    start = (latest_existing - timedelta(days=2)).strftime("%Y-%m-%d")
    end = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    # Use existing stock codes with .TW suffix
    stock_codes = list(existing.columns)
    # Load ticker cache for .TW/.TWO resolution
    from analysis.pit_rs import _build_yf_tickers
    yf_tickers = _build_yf_tickers(stock_codes)
    ticker_to_code = {}
    for code, ticker in zip(stock_codes, yf_tickers):
        ticker_to_code[ticker] = code

    new_dates_added = 0
    BATCH_SIZE = 200

    for batch_idx in range(0, len(yf_tickers), BATCH_SIZE):
        batch = yf_tickers[batch_idx:batch_idx + BATCH_SIZE]
        try:
            data = yf.download(
                batch,
                start=start,
                end=end,
                auto_adjust=True,
                progress=False,
                threads=True,
            )
            if data.empty:
                continue

            if len(batch) == 1:
                ticker = batch[0]
                code = ticker_to_code.get(ticker, ticker.split(".")[0])
                if "Close" in data.columns:
                    for date, val in data["Close"].dropna().items():
                        date = pd.Timestamp(date)
                        if date not in existing.index and code in existing.columns:
                            existing.loc[date, code] = val
                            new_dates_added = max(new_dates_added, 1)
            else:
                if "Close" in data.columns.get_level_values(0):
                    close_df = data["Close"]
                    for date in close_df.index:
                        date = pd.Timestamp(date)
                        if date not in existing.index:
                            for ticker_col in close_df.columns:
                                code = ticker_to_code.get(ticker_col, ticker_col.split(".")[0])
                                val = close_df.loc[date, ticker_col]
                                if pd.notna(val) and code in existing.columns:
                                    existing.loc[date, code] = val
                            new_dates_added += 1
        except Exception as e:
            logger.warning("yf batch %d failed: %s", batch_idx // BATCH_SIZE + 1, e)

        if batch_idx + BATCH_SIZE < len(yf_tickers):
            time.sleep(0.3)

    if new_dates_added > 0:
        existing = existing.sort_index()
        existing.to_parquet(PIT_CLOSE_PATH)

    elapsed = time.time() - t0
    result = {
        "new_dates": new_dates_added,
        "total_dates": len(existing),
        "total_stocks": len(existing.columns),
        "elapsed_s": round(elapsed, 1),
        "source": "yfinance_incremental",
    }
    logger.info("yfinance incremental: +%d dates (%.1fs)", new_dates_added, elapsed)
    return result


def recompute_rs_matrices() -> dict:
    """Recompute PIT RS matrices from the (freshly extended) close matrix.

    Loads pit_close_matrix.parquet and runs the full RS computation pipeline.
    This is fast (~5-10s) since it's purely vectorized math on the matrix.

    Returns:
        {"rs_dates": int, "rs_stocks": int, "elapsed_s": float}
    """
    from analysis.pit_rs import (
        compute_pit_rs_matrix,
        compute_pit_percentiles,
        PIT_RS_CACHE_PATH,
        PIT_PCTILE_CACHE_PATH,
    )

    t0 = time.time()

    if not PIT_CLOSE_PATH.exists():
        logger.error("No close matrix found — cannot compute RS")
        return {"error": "no_close_matrix"}

    close_matrix = pd.read_parquet(PIT_CLOSE_PATH)
    close_matrix.index = pd.to_datetime(close_matrix.index)

    rs_matrix = compute_pit_rs_matrix(close_matrix)
    pctile_matrix = compute_pit_percentiles(rs_matrix)

    # Save
    PIT_RS_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    rs_matrix.astype("float32").to_parquet(PIT_RS_CACHE_PATH)
    pctile_matrix.astype("float32").to_parquet(PIT_PCTILE_CACHE_PATH)

    elapsed = time.time() - t0
    result = {
        "rs_dates": len(rs_matrix),
        "rs_stocks": len(rs_matrix.columns),
        "elapsed_s": round(elapsed, 1),
    }
    logger.info("RS matrices recomputed: %d dates × %d stocks (%.1fs)",
                result["rs_dates"], result["rs_stocks"], elapsed)
    return result


def refresh_screener_db() -> dict:
    """Refresh the screener SQLite snapshot with latest data.

    Uses batch-optimized refresh from analysis/financial_screener.py.

    Returns:
        {"stocks_updated": int, "elapsed_s": float}
    """
    t0 = time.time()

    try:
        from analysis.financial_screener import refresh_screening_data
        result = refresh_screening_data()
        elapsed = time.time() - t0
        return {
            "stocks_updated": result.get("rows", 0),
            "status": result.get("status", "unknown"),
            "elapsed_s": round(elapsed, 1),
        }
    except Exception as e:
        logger.error("Screener refresh failed: %s", e)
        return {"error": str(e), "elapsed_s": round(time.time() - t0, 1)}


def rollover_forward_returns() -> dict:
    """Backfill NaN forward returns using the updated close matrix.

    forward_returns.parquet has horizons {d3, d7, d21, d90, d180} but many
    recent dates have NaN because future prices didn't exist at build time.
    Now that pit_close_matrix is extended, we can fill those gaps.

    Optimization: only scans rows from the last 250 trading days (covers d180
    horizon with margin). Computes fresh returns from close matrix, then fills
    NaN cells via vectorized merge. Typical daily run: <5s.

    Returns:
        {"filled": int, "total_nan_before": int, "elapsed_s": float}
    """
    t0 = time.time()

    if not FWD_RETURNS_PATH.exists():
        logger.warning("forward_returns.parquet not found — skipping rollover")
        return {"error": "no_forward_returns_file"}

    if not PIT_CLOSE_PATH.exists():
        logger.warning("pit_close_matrix not found — skipping rollover")
        return {"error": "no_close_matrix"}

    # Load forward returns (long format: date, stock_code, d3, d7, d21, d90, d180)
    fwd = pd.read_parquet(FWD_RETURNS_PATH)
    fwd["date"] = pd.to_datetime(fwd["date"])
    horizon_cols = [c for c in fwd.columns if c.startswith("d") and c in FWD_HORIZONS]

    # Only scan rows whose returns could have newly matured.
    # d180 is the longest horizon, so only dates within last 200 trading days
    # (~280 calendar days) could possibly have new data.
    cutoff = fwd["date"].max() - pd.Timedelta(days=280)
    recent_mask = fwd["date"] >= cutoff
    recent_nan_mask = recent_mask & fwd[horizon_cols].isna().any(axis=1)
    nan_count = int(fwd.loc[recent_nan_mask, horizon_cols].isna().sum().sum())

    if nan_count == 0:
        logger.info("No recent NaN forward returns to fill")
        return {"filled": 0, "total_nan_before": 0, "elapsed_s": 0.0}

    # Load close matrix (wide: date × stock)
    cm = pd.read_parquet(PIT_CLOSE_PATH)
    cm.index = pd.to_datetime(cm.index)
    cm = cm.sort_index()

    # Compute fresh forward returns from close matrix for all stocks at once
    # Build a long-format DataFrame matching fwd structure
    fresh_rows = []
    cm_stocks = set(cm.columns)
    target_stocks = fwd.loc[recent_nan_mask, "stock_code"].unique()
    logger.info("Rolling forward returns: %d NaN cells across %d stocks", nan_count, len(target_stocks))

    for code in target_stocks:
        if code not in cm_stocks:
            continue
        prices = cm[code].dropna().sort_index()
        if len(prices) < 5:
            continue

        for col, days in FWD_HORIZONS.items():
            returns = prices.shift(-days) / prices - 1.0
            valid = returns.dropna()
            for date, val in valid.items():
                fresh_rows.append((date, code, col, val))

    if not fresh_rows:
        logger.info("No fresh returns computed")
        return {"filled": 0, "total_nan_before": nan_count, "elapsed_s": round(time.time() - t0, 1)}

    # Build lookup: (date, stock_code) → {col: val}
    lookup = {}
    for date, code, col, val in fresh_rows:
        key = (date, code)
        if key not in lookup:
            lookup[key] = {}
        lookup[key][col] = val

    # Fill NaN cells
    filled = 0
    nan_indices = fwd.index[recent_nan_mask].tolist()
    for idx in nan_indices:
        row = fwd.loc[idx]
        key = (row["date"], row["stock_code"])
        if key not in lookup:
            continue
        fresh = lookup[key]
        for col in horizon_cols:
            if pd.isna(row[col]) and col in fresh:
                fwd.at[idx, col] = fresh[col]
                filled += 1

    if filled > 0:
        fwd.to_parquet(FWD_RETURNS_PATH, index=False)

    elapsed = time.time() - t0
    result = {
        "filled": filled,
        "total_nan_scanned": nan_count,
        "elapsed_s": round(elapsed, 1),
    }
    logger.info("Forward returns rollover: filled %d of %d NaN cells (%.1fs)",
                filled, nan_count, elapsed)
    return result


def run_daily_update() -> dict:
    """Run the complete daily update pipeline.

    Steps (sequential, each depends on the previous):
      1. Extend close matrix with latest prices
      1.5. Self-Healing: Sanitize close matrix (Phase 8 P0)
      2. Recompute RS matrices
      3. Refresh screener DB
      4. Rollover forward returns (backfill NaN with new close data)
      5. Realize active signals (P3: backfill actual T+5/T+10/T+21 returns)
      6. Update trailing stops for active signals (P6-P0: R86 → LINE)
      7. Auto-Sim: screener → find_similar_dual → LINE Notify (P2-B)
      8. Weekly audit (Saturday only): drift detection + LINE report (P3)

    Returns:
        Summary dict with results from each step.
    """
    logger.info("=" * 60)
    logger.info("Daily Update Pipeline — starting")
    logger.info("=" * 60)

    t0 = time.time()
    results = {}

    # Step 1: Extend close matrix
    logger.info("[Step 1/9] Extending close matrix...")
    try:
        results["close_matrix"] = extend_close_matrix()
    except Exception as e:
        logger.error("Close matrix update failed: %s", e, exc_info=True)
        results["close_matrix"] = {"error": str(e)}

    # Step 1.5: Sanitize close matrix (Phase 8 P0: Self-Healing)
    logger.info("[Step 1.5/9] Running data sanitizer...")
    try:
        if PIT_CLOSE_PATH.exists():
            cm = pd.read_parquet(PIT_CLOSE_PATH)
            cm.index = pd.to_datetime(cm.index)
            sanitize_result = sanitize_close_matrix(cm)
            results["sanitizer"] = {
                "anomalies_found": sanitize_result["anomalies_found"],
                "healed": sanitize_result["healed"],
                "flagged": sanitize_result["flagged"],
            }
            # If any data was healed, re-save the matrix
            if sanitize_result["healed"] > 0:
                cm.to_parquet(PIT_CLOSE_PATH)
                logger.info("Close matrix re-saved after %d heals", sanitize_result["healed"])
        else:
            results["sanitizer"] = {"skipped": "no close matrix"}
    except Exception as e:
        logger.error("Data sanitizer failed: %s", e, exc_info=True)
        results["sanitizer"] = {"error": str(e)}

    # Step 2: Recompute RS matrices
    logger.info("[Step 2/9] Recomputing RS matrices...")
    try:
        results["rs_matrices"] = recompute_rs_matrices()
    except Exception as e:
        logger.error("RS recompute failed: %s", e, exc_info=True)
        results["rs_matrices"] = {"error": str(e)}

    # Step 3: Refresh screener DB
    logger.info("[Step 3/9] Refreshing screener DB...")
    try:
        results["screener"] = refresh_screener_db()
    except Exception as e:
        logger.error("Screener refresh failed: %s", e, exc_info=True)
        results["screener"] = {"error": str(e)}

    # Step 4: Rollover forward returns
    logger.info("[Step 4/9] Rolling forward returns...")
    try:
        results["forward_returns"] = rollover_forward_returns()
    except Exception as e:
        logger.error("Forward returns rollover failed: %s", e, exc_info=True)
        results["forward_returns"] = {"error": str(e)}

    # Step 5: Realize active signals (P3: backfill actual returns)
    logger.info("[Step 5/9] Realizing active signals...")
    try:
        from analysis.signal_log import realize_signals
        results["signal_realization"] = realize_signals()
    except Exception as e:
        logger.error("Signal realization failed: %s", e, exc_info=True)
        results["signal_realization"] = {"error": str(e)}

    # Step 6: Update trailing stops for active signals (P6-P0: R86 integration)
    logger.info("[Step 6/9] Updating trailing stops...")
    try:
        from analysis.signal_log import update_trailing_stops, format_active_signals_line
        trail_result = update_trailing_stops()
        results["trailing_stops"] = {
            "updated": trail_result["updated"],
            "errors": trail_result["errors"],
        }
        # Send active signals LINE notification if there are tracked positions
        active_stops = trail_result.get("active_stops", [])
        if active_stops:
            trail_msg = format_active_signals_line(active_stops)
            if trail_msg:
                try:
                    from backend.scheduler import _send_notification
                    _send_notification(trail_msg)
                    results["trailing_stops"]["notification_sent"] = True
                except Exception:
                    results["trailing_stops"]["notification_sent"] = False
    except Exception as e:
        logger.error("Trailing stops update failed: %s", e, exc_info=True)
        results["trailing_stops"] = {"error": str(e)}

    # Step 7: Auto-Sim Pipeline (P2-B: screener → find_similar_dual → LINE Notify)
    logger.info("[Step 7/9] Running Auto-Sim Pipeline...")
    try:
        from analysis.auto_sim import run_auto_sim, send_auto_sim_notification
        sim_result = run_auto_sim()
        results["auto_sim"] = {
            "candidates_found": sim_result["candidates_found"],
            "simulated": sim_result["simulated"],
            "signals_sent": len(sim_result["top_signals"]),
            "elapsed_s": sim_result["elapsed_s"],
        }
        # Send LINE notification if there are signals
        if sim_result["top_signals"]:
            sent = send_auto_sim_notification(sim_result)
            results["auto_sim"]["notification_sent"] = sent
    except Exception as e:
        logger.error("Auto-Sim failed: %s", e, exc_info=True)
        results["auto_sim"] = {"error": str(e)}

    # Step 8: Weekly audit (Saturday only — P3: drift detection)
    if datetime.now().weekday() == 5:  # Saturday
        logger.info("[Step 8/9] Running weekly drift audit (Saturday)...")
        try:
            from analysis.drift_detector import run_weekly_audit, send_weekly_audit_notification
            audit = run_weekly_audit()
            results["weekly_audit"] = {
                "in_bounds_rate": audit.get("in_bounds", {}).get("in_bounds_rate"),
                "z_score_alarm": audit.get("z_score", {}).get("alarm", False),
                "risk_flag_changed": audit.get("risk_flag_changed", False),
                "post_mortem_needed": audit.get("post_mortem", {}).get("needed", False),
            }
            send_weekly_audit_notification(audit)
        except Exception as e:
            logger.error("Weekly audit failed: %s", e, exc_info=True)
            results["weekly_audit"] = {"error": str(e)}
    else:
        logger.info("[Step 8/9] Skipping weekly audit (not Saturday)")

    total_elapsed = time.time() - t0
    results["total_elapsed_s"] = round(total_elapsed, 1)
    results["timestamp"] = datetime.now().isoformat()

    logger.info("=" * 60)
    logger.info("Daily Update Pipeline — completed in %.1fs", total_elapsed)
    logger.info("Results: %s", results)
    logger.info("=" * 60)

    return results


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    import sys
    sys.path.insert(0, str(PROJECT_ROOT))

    result = run_daily_update()
    print("\n=== Daily Update Summary ===")
    for key, val in result.items():
        print(f"  {key}: {val}")
