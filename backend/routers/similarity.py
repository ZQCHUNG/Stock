"""Multi-Window Similarity Engine API routes.

Endpoints:
  POST /api/similarity/{code}/search   — Multi-window similar case search
  GET  /api/similarity/status           — Engine status (loaded windows, memory)
"""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter()


# --- Request / Response schemas ---


class MultiWindowSimilarRequest(BaseModel):
    """Request body for multi-window similarity search."""

    window: int = Field(
        default=30,
        description="Window size in days. Supported: 7, 14, 30, 90, 180.",
    )
    dimensions: list[str] | None = Field(
        default=None,
        description=(
            "User-facing dimensions to include. "
            "Options: technical, institutional, fundamental, news, industry. "
            "Default: all 5."
        ),
    )
    query_date: str | None = Field(
        default=None,
        description="Query date (YYYY-MM-DD). Default: latest available.",
    )
    top_k: int = Field(
        default=30, ge=1, le=200, description="Number of similar cases to return."
    )
    exclude_self: bool = Field(
        default=True, description="Exclude the query stock+date from results."
    )


# --- Endpoints ---


@router.post("/{code}/search")
async def search_multi_window_similar(code: str, request: MultiWindowSimilarRequest):
    """Search for similar cases using multi-window cosine similarity.

    Returns top-k similar stock-date pairs with per-dimension similarity
    breakdown and forward return statistics.
    """
    try:
        from analysis.similarity_engine import search_similar

        result = search_similar(
            stock_code=code,
            window=request.window,
            dimensions=request.dimensions,
            query_date=request.query_date,
            top_k=request.top_k,
            exclude_self=request.exclude_self,
        )
        return result.to_dict()

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.exception("Similarity search failed for %s: %s", code, e)
        raise HTTPException(status_code=500, detail=f"Search failed: {e}")


@router.get("/status")
async def get_similarity_engine_status():
    """Return engine status: loaded windows, dimensions, memory usage."""
    try:
        from analysis.similarity_engine import get_engine_status

        return get_engine_status()
    except Exception as e:
        logger.exception("Engine status failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
