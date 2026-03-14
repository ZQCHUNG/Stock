"""Signal tracking & SQS scoring routes.

Split from analysis.py — signal-tracker/*, sqs, batch-sqs, sqs-distribution,
strategy-fitness endpoints.
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


# Pydantic models for request validation (Gemini R44)
class SqsStockItem(BaseModel):
    code: str = Field(..., min_length=4, max_length=6)
    strategy: str = Field(default="V4", pattern="^(V4|V5|Adaptive)$")
    maturity: str = "N/A"


class BatchSqsRequest(BaseModel):
    stocks: list[SqsStockItem] = Field(..., min_length=1, max_length=200)


# === Signal Tracker ===


@router.post("/signal-tracker/record")
def record_signals(max_workers: int = 4):
    """Record all BUY signals for today (Gemini R39: Forward Testing)"""
    from analysis.signal_tracker import record_daily_signals
    from backend.dependencies import make_serializable
    try:
        result = record_daily_signals(max_workers=max_workers)
        return make_serializable(result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/signal-tracker/fill")
def fill_returns(lookback_days: int = 10):
    """Backfill forward returns (1/3/5 day) for recorded signals"""
    from analysis.signal_tracker import fill_forward_returns
    from backend.dependencies import make_serializable
    try:
        result = fill_forward_returns(lookback_days=lookback_days)
        return make_serializable(result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/signal-tracker/performance")
def signal_performance(days: int = 30, strategy: str = "", code: str = ""):
    """Query signal forward performance"""
    from analysis.signal_tracker import get_signal_performance
    from backend.dependencies import make_serializable
    try:
        result = get_signal_performance(
            days=days,
            strategy=strategy or None,
            code=code or None,
        )
        return make_serializable(result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/signal-tracker/accuracy")
def signal_accuracy(days: int = 60):
    """Get strategy signal accuracy summary"""
    from analysis.signal_tracker import get_strategy_accuracy
    from backend.dependencies import make_serializable
    try:
        result = get_strategy_accuracy(days=days)
        return make_serializable(result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/signal-tracker/decay")
def signal_decay(days: int = 90):
    """Get signal decay curve (Gemini R40->R41: 1/3/5/10/20 day)

    Shows average return + EV at 1/3/5/10/20 days after signal, revealing signal lifespan.
    """
    from analysis.signal_tracker import get_signal_decay
    from backend.dependencies import make_serializable
    try:
        result = get_signal_decay(days=days)
        return make_serializable(result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/signal-tracker/{code}/summary")
def signal_stock_summary(code: str, days: int = 180):
    """Per-stock signal forward performance summary (Gemini R41: TechnicalView overlay)

    Returns strategy win rates, EV, average returns, and recent signals for this stock.
    """
    from analysis.signal_tracker import get_stock_signal_summary
    from backend.dependencies import make_serializable
    try:
        result = get_stock_signal_summary(code, days=days)
        return make_serializable(result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# === SQS (Signal Quality Score) ===


@router.get("/{code}/sqs")
def get_sqs(code: str):
    """Get Signal Quality Score for a stock (Gemini R42)

    Integrates fitness, regime, EV, sector heat, maturity into 0-100 score.
    """
    from analysis.scoring import compute_sqs_for_signal
    from analysis.strategy_v4 import get_v4_analysis
    from data.fetcher import get_stock_data
    from backend.dependencies import make_serializable
    try:
        df = get_stock_data(code, period_days=365)
        v4 = get_v4_analysis(df)
        signal_strategy = "V4" if v4.get("signal") == "BUY" else "Adaptive"
        maturity = v4.get("signal_maturity", "N/A")

        result = compute_sqs_for_signal(
            code=code,
            signal_strategy=signal_strategy,
            signal_maturity=maturity,
        )
        return make_serializable(result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/batch-sqs")
def batch_sqs(payload: BatchSqsRequest):
    """Batch SQS calculation (Gemini R42: Alpha Hunter SQS-Ledger)

    Accepts [{"code": "2330", "strategy": "V4", "maturity": "Structural Shift"}, ...]
    Returns SQS score for each stock.
    """
    from analysis.scoring import compute_sqs_for_signal
    from backend.dependencies import make_serializable
    try:
        stocks = payload.stocks
        results = {}
        for s in stocks:
            try:
                sqs = compute_sqs_for_signal(s.code, s.strategy, s.maturity)
                results[s.code] = sqs
            except Exception as e:
                logger.debug(f"Optional operation failed: {e}")
                results[s.code] = {"sqs": 50.0, "grade": "silver", "grade_label": "普通信號"}
        return make_serializable(results)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sqs-distribution")
def get_sqs_distribution():
    """Get SQS distribution for all current BUY signals + adaptive percentile grades (Gemini R43)"""
    from analysis.scoring import compute_sqs_for_signal, compute_sqs_distribution
    from backend.dependencies import make_serializable
    try:
        # Get current alpha hunter data for all BUY stocks
        from data.cache import get_cached_sector_heat
        alpha = get_cached_sector_heat()
        if not alpha or not alpha.get("sectors"):
            return {"count": 0, "error": "No alpha hunter data available"}

        all_stocks = []
        for sector in alpha["sectors"]:
            for stock in sector.get("buy_stocks", []):
                all_stocks.append(stock)

        if not all_stocks:
            return {"count": 0, "error": "No BUY signals found"}

        # Compute SQS for each stock
        sqs_scores = []
        for s in all_stocks:
            try:
                sqs = compute_sqs_for_signal(
                    s["code"],
                    signal_strategy="V4",
                    signal_maturity=s.get("maturity", "N/A"),
                )
                sqs_scores.append(sqs)
            except Exception as e:
                logger.debug(f"Optional operation failed: {e}")

        result = compute_sqs_distribution(sqs_scores)
        return make_serializable(result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# === Strategy Fitness ===


@router.get("/strategy-fitness")
def get_strategy_fitness(codes: str = ""):
    """Get strategy fitness labels (Gemini R38: Strategy Fitness Engine)

    Quick query of pre-computed V4/V5/Adaptive performance + Fitness Tag from SQLite.
    ?codes=2330,2317 to filter specific stocks. Empty = all.
    """
    from analysis.strategy_fitness import get_fitness_tags, get_fitness_summary
    from backend.dependencies import make_serializable
    try:
        code_list = [c.strip() for c in codes.split(",") if c.strip()] if codes else None
        tags = get_fitness_tags(code_list)
        summary = get_fitness_summary()
        return make_serializable({"stocks": tags, "summary": summary})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/strategy-fitness/scan")
def run_strategy_fitness_scan(period_days: int = 730, max_workers: int = 4):
    """Run strategy fitness scan (Gemini R38)

    Batch compute V4/V5/Adaptive performance for all SCAN_STOCKS.
    Note: Long-running operation (~10-30 min), recommend background execution.
    """
    from analysis.strategy_fitness import run_fitness_scan
    from backend.dependencies import make_serializable
    try:
        result = run_fitness_scan(period_days=period_days, max_workers=max_workers)
        return make_serializable(result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
