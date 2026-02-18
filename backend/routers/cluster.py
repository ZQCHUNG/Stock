"""多維度相似股分群路由 — 雙軌引擎 (Facts vs Opinion)

Endpoints:
  POST /api/cluster/similar-dual  — 雙區塊查詢（主 API）
  POST /api/cluster/similar       — Legacy 查詢（向後相容）
  GET  /api/cluster/dimensions    — 取得可用維度清單
  GET  /api/cluster/feature-status — 特徵資料狀態
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()


# --- Request / Response schemas ---

class DualSimilarRequest(BaseModel):
    stock_code: str = Field(..., min_length=4, max_length=6, description="目標股票代碼")
    query_date: str | None = Field(default=None, description="查詢日期 (YYYY-MM-DD)，預設最新")
    top_k: int = Field(default=30, ge=5, le=100, description="回傳前 K 個相似案例")
    exclude_self: bool = Field(default=True, description="排除自身股票")


class SimilarRequest(BaseModel):
    stock_code: str = Field(..., min_length=4, max_length=6, description="目標股票代碼")
    dimensions: list[str] = Field(
        default=["technical", "institutional"],
        description="要使用的維度",
    )
    window: int = Field(default=20, ge=5, le=120, description="Window 天數")
    top_k: int = Field(default=30, ge=5, le=100, description="回傳前 K 個相似案例")
    exclude_self: bool = Field(default=True, description="排除自身股票")
    min_date: str | None = Field(default=None, description="最小日期 (YYYY-MM-DD)")
    regime_match: bool = Field(default=True, description="同 regime 限定模式")


# --- Endpoints ---

@router.post("/similar-dual")
def query_similar_dual(req: DualSimilarRequest):
    """雙區塊查詢：Block 1 (Raw Facts) + Block 2 (System Opinion)。"""
    from analysis.cluster_search import find_similar_dual

    try:
        result = find_similar_dual(
            stock_code=req.stock_code,
            query_date=req.query_date,
            top_k=req.top_k,
            exclude_self=req.exclude_self,
        )
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/similar")
def query_similar(req: SimilarRequest):
    """Legacy 查詢：根據選定維度找出歷史相似案例。"""
    from analysis.cluster_search import find_similar

    try:
        result = find_similar(
            stock_code=req.stock_code,
            dimensions=req.dimensions,
            window=req.window,
            top_k=req.top_k,
            exclude_self=req.exclude_self,
            min_date=req.min_date,
            regime_match=req.regime_match,
        )
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dimensions")
def list_dimensions():
    """取得可用維度清單（含特徵數量和描述）。"""
    from analysis.cluster_search import get_dimensions

    try:
        return {"dimensions": get_dimensions()}
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/feature-status")
def feature_status():
    """取得特徵資料狀態（是否存在、大小、載入情形）。"""
    from analysis.cluster_search import get_feature_status

    return get_feature_status()
