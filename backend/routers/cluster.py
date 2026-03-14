"""多維度相似股分群路由 — 雙軌引擎 (Facts vs Opinion)

Endpoints:
  POST /api/cluster/similar-dual      — 雙區塊查詢（主 API）
  POST /api/cluster/similar           — Legacy 查詢（向後相容）
  POST /api/cluster/pattern-simulate  — Pattern 模擬：多 Horizon 勝率
  GET  /api/cluster/dimensions        — 取得可用維度清單
  GET  /api/cluster/feature-status    — 特徵資料狀態
  GET  /api/cluster/mutations         — 基因突變掃描 (R88.7)
  GET  /api/cluster/daily-summary     — 每日自動摘要 (R88.7 Phase 10)
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


# --- Request / Response schemas ---

class DualSimilarRequest(BaseModel):
    stock_code: str = Field(..., min_length=4, max_length=6, description="目標股票代碼")
    query_date: str | None = Field(default=None, description="查詢日期 (YYYY-MM-DD)，預設最新")
    top_k: int = Field(default=30, ge=5, le=100, description="回傳前 K 個相似案例")
    exclude_self: bool = Field(default=True, description="排除自身股票")
    dimensions: list[str] | None = Field(
        default=None,
        description="Block 1 使用的維度（None=全部）。可選: technical, institutional, industry, fundamental, attention",
    )


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
            dimensions=req.dimensions,
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


@router.get("/winner-registry")
def get_winner_registry():
    """取得 Winner Branch Registry 資訊。"""
    from analysis.winner_registry import load_registry, WINNER_OUTPUT_PATH

    registry_data = load_registry(WINNER_OUTPUT_PATH)
    if not registry_data:
        return {"winners": {}, "count": 0, "status": "not_built"}

    return {
        "winners": registry_data,
        "count": len(registry_data),
        "status": "ready",
    }


@router.get("/mutations")
def scan_mutations(
    threshold: float = 1.5,
    top_n: int = 10,
    use_weights: bool = False,
):
    """基因突變掃描：找出 Brokerage vs Technical 顯著背離的個股。

    [R88.7 Phase 7 — Wall Street Trader APPROVED]
    Δ_div > threshold_sigma → 匿蹤吸貨 (stealth accumulation)
    Δ_div < -threshold_sigma → 誘多派發 (deceptive distribution)
    """
    from analysis.cluster_search import scan_gene_mutations

    try:
        result = scan_gene_mutations(
            threshold_sigma=threshold,
            top_n=top_n,
            use_weights=use_weights,
        )
        if "error" in result:
            raise HTTPException(status_code=503, detail=result["error"])
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Pattern Simulation (Phase 1: multi-horizon win rates) ───────

class PatternSimulateRequest(BaseModel):
    stock_code: str = Field(..., min_length=4, max_length=6, description="目標股票代碼")
    query_date: str | None = Field(default=None, description="查詢日期 (YYYY-MM-DD)")
    dimensions: list[str] | None = Field(default=None, description="維度 (None=全部6維)")
    top_k: int = Field(default=30, ge=5, le=100, description="相似案例數")


@router.post("/pattern-simulate")
def pattern_simulate(req: PatternSimulateRequest):
    """Pattern 模擬 — 找相似歷史案例，計算 d3/d5/d7/d14/d21/d30/d90/d180 勝率。

    回傳：
      - cases: 相似案例清單（含各 horizon forward return）
      - statistics: 每個 horizon 的 win_rate, mean, expectancy
      - spaghetti: 90 天前瞻價格線（用於圖表）
      - sniper_assessment: Sniper 信心分級
    """
    from analysis.pattern_simulator import simulate_pattern
    from backend.dependencies import make_serializable

    try:
        result = simulate_pattern(
            stock_code=req.stock_code,
            query_date=req.query_date,
            dimensions=req.dimensions,
            top_k=req.top_k,
        )
        return make_serializable(result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/daily-summary")
def get_daily_summary(regenerate: bool = False):
    """取得每日自動摘要 — pipeline 健康 + 突變掃描 + 市場脈搏。

    [R88.7 Phase 10 — Auto-Summary]
    Args:
        regenerate: If True, force regenerate (default: read cached JSON).
    """
    import json as json_mod
    from pathlib import Path

    summary_path = Path(__file__).parent.parent.parent / "data" / "daily_summary.json"

    if not regenerate and summary_path.exists():
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                return json_mod.load(f)
        except Exception as e:
            logger.debug(f"Optional data load failed: {e}")
            pass  # Fall through to regenerate

    # Generate fresh summary
    from analysis.cluster_search import generate_daily_summary

    try:
        result = generate_daily_summary()
        if "error" in result.get("market_pulse", {}):
            raise HTTPException(status_code=503, detail=result["market_pulse"]["error"])
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
