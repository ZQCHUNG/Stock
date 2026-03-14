"""Export routes — CSV and PDF export for positions, signals, backtest, portfolio, screener, report.

Split from system.py — all /export/* endpoints.
"""

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/export/positions/csv")
def export_positions_csv():
    """R47-3: Export positions as CSV"""
    from backend.backup import export_positions_csv as _export
    content = _export()
    if not content:
        return Response(content="No data", media_type="text/plain")
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=positions.csv"},
    )


@router.get("/export/positions/json")
def export_positions_json():
    """R47-3: Export positions as JSON"""
    from backend.backup import export_positions_json as _export
    from backend.dependencies import make_serializable
    return make_serializable(_export())


@router.get("/export/signals/csv")
def export_signals_csv(source: str | None = None):
    """R47-3: Export SQS signal records as CSV"""
    from backend.backup import export_signals_csv as _export
    content = _export(source=source)
    if not content:
        return Response(content="No data", media_type="text/plain")
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=signals.csv"},
    )


# ---------------------------------------------------------------------------
# R55-2: CSV Export for backtest results, portfolio, screener, report
# ---------------------------------------------------------------------------


@router.post("/export/backtest/csv")
def export_backtest_csv(result: dict):
    """R55-2: Export backtest results as CSV"""
    from backend.export_utils import backtest_to_csv
    content = backtest_to_csv(result)
    code = result.get("code", "unknown")
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=backtest_{code}.csv"},
    )


@router.get("/export/portfolio/csv")
def export_full_portfolio_csv():
    """R55-2: Export full portfolio report as CSV"""
    from backend import db
    from backend.export_utils import portfolio_to_csv
    positions = db.get_open_positions()
    closed = db.get_closed_positions(limit=200)
    summary = {}
    if positions:
        total_value = sum(p.get("entry_price", 0) * p.get("lots", 0) * 1000 for p in positions)
        summary = {
            "total_positions": len(positions),
            "total_market_value": total_value,
        }
    content = portfolio_to_csv(positions, closed, summary)
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=portfolio.csv"},
    )


@router.post("/export/screener/csv")
def export_screener_csv(payload: dict):
    """R55-2: Export screener results as CSV"""
    from backend.export_utils import screener_to_csv
    results = payload.get("results", [])
    filters = payload.get("filters")
    content = screener_to_csv(results, filters)
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=screener_results.csv"},
    )


@router.post("/export/report/csv")
def export_report_csv(report: dict):
    """R55-2: Export analysis report as CSV"""
    from backend.export_utils import report_to_csv
    code = report.get("code", "unknown")
    content = report_to_csv(report)
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=report_{code}.csv"},
    )


# ---------------------------------------------------------------------------
# R57: PDF Export via Playwright
# ---------------------------------------------------------------------------


@router.get("/export/report/pdf/{code}")
async def export_report_pdf(code: str):
    """R57: Export analysis report as PDF (Playwright renders Vue page)"""
    try:
        from backend.pdf_export import export_report_pdf as _export
        pdf_bytes = await _export(code)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=report_{code}.pdf"},
        )
    except ImportError:
        raise HTTPException(status_code=500, detail="Playwright not installed. Run: pip install playwright && python -m playwright install chromium")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {e}")


@router.get("/export/portfolio/pdf")
async def export_portfolio_pdf():
    """R57: Export portfolio as PDF"""
    try:
        from backend.pdf_export import export_portfolio_pdf as _export
        pdf_bytes = await _export()
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=portfolio.pdf"},
        )
    except ImportError:
        raise HTTPException(status_code=500, detail="Playwright not installed")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {e}")


@router.get("/export/backtest/pdf/{code}")
async def export_backtest_pdf(code: str, period: int = 1095):
    """R57: Export backtest report as PDF"""
    try:
        from backend.pdf_export import export_backtest_pdf as _export
        pdf_bytes = await _export(code, period)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=backtest_{code}.pdf"},
        )
    except ImportError:
        raise HTTPException(status_code=500, detail="Playwright not installed")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {e}")
