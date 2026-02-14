"""Strategy Workbench API (Gemini R50-3)

CRUD for strategy configurations. Strategies are stored in a JSON file.
Each strategy is a named set of V4 parameters that can be used for
backtesting or live signal generation.
"""

import json
import uuid
import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()

STRATEGY_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "strategies.json"


class StrategyParams(BaseModel):
    """V4 strategy parameters."""
    adx_threshold: float = 18
    ma_short: int = 20
    ma_long: int = 60
    ma_trend_days: int = 10
    take_profit_pct: float = 0.10
    stop_loss_pct: float = -0.07
    trailing_stop_pct: float = 0.02
    min_hold_days: int = 5
    min_volume: int = 500
    confidence_weight: float = 1.0


class CreateStrategyRequest(BaseModel):
    name: str
    description: str = ""
    params: StrategyParams = StrategyParams()


class UpdateStrategyRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    params: StrategyParams | None = None


def _load_strategies() -> list[dict]:
    """Load strategies from JSON file."""
    if not STRATEGY_FILE.exists():
        return _default_strategies()
    try:
        data = json.loads(STRATEGY_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return _default_strategies()


def _save_strategies(strategies: list[dict]):
    """Save strategies to JSON file."""
    STRATEGY_FILE.parent.mkdir(parents=True, exist_ok=True)
    STRATEGY_FILE.write_text(
        json.dumps(strategies, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _default_strategies() -> list[dict]:
    """Create default strategy set."""
    defaults = [
        {
            "id": "v4-default",
            "name": "V4 Standard",
            "description": "V4 標準參數 — 適合多數市場環境",
            "params": StrategyParams().model_dump(),
            "is_default": True,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        },
        {
            "id": "v4-conservative",
            "name": "V4 Conservative",
            "description": "保守版 — 更高 ADX 門檻、更緊停損",
            "params": StrategyParams(
                adx_threshold=25, stop_loss_pct=-0.05,
                trailing_stop_pct=0.015, min_volume=800,
            ).model_dump(),
            "is_default": False,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        },
        {
            "id": "v4-aggressive",
            "name": "V4 Aggressive",
            "description": "積極版 — 較低門檻、更寬停損、更大獲利空間",
            "params": StrategyParams(
                adx_threshold=15, take_profit_pct=0.15,
                stop_loss_pct=-0.10, trailing_stop_pct=0.025,
                min_volume=300,
            ).model_dump(),
            "is_default": False,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        },
    ]
    _save_strategies(defaults)
    return defaults


@router.get("/")
def list_strategies():
    """列出所有策略"""
    return {"strategies": _load_strategies()}


@router.get("/{strategy_id}")
def get_strategy(strategy_id: str):
    """取得單一策略"""
    strategies = _load_strategies()
    for s in strategies:
        if s["id"] == strategy_id:
            return s
    raise HTTPException(404, f"Strategy {strategy_id} not found")


@router.post("/")
def create_strategy(req: CreateStrategyRequest):
    """建立新策略"""
    strategies = _load_strategies()

    if len(strategies) >= 20:
        raise HTTPException(400, "最多允許 20 個策略")

    new_strategy = {
        "id": str(uuid.uuid4())[:8],
        "name": req.name,
        "description": req.description,
        "params": req.params.model_dump(),
        "is_default": False,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }

    strategies.append(new_strategy)
    _save_strategies(strategies)

    return {"ok": True, "strategy": new_strategy}


@router.put("/{strategy_id}")
def update_strategy(strategy_id: str, req: UpdateStrategyRequest):
    """更新策略"""
    strategies = _load_strategies()

    for s in strategies:
        if s["id"] == strategy_id:
            if req.name is not None:
                s["name"] = req.name
            if req.description is not None:
                s["description"] = req.description
            if req.params is not None:
                s["params"] = req.params.model_dump()
            s["updated_at"] = datetime.now().isoformat()
            _save_strategies(strategies)
            return {"ok": True, "strategy": s}

    raise HTTPException(404, f"Strategy {strategy_id} not found")


@router.post("/{strategy_id}/clone")
def clone_strategy(strategy_id: str):
    """複製策略"""
    strategies = _load_strategies()

    if len(strategies) >= 20:
        raise HTTPException(400, "最多允許 20 個策略")

    for s in strategies:
        if s["id"] == strategy_id:
            cloned = {
                "id": str(uuid.uuid4())[:8],
                "name": f"{s['name']} (Copy)",
                "description": s.get("description", ""),
                "params": dict(s["params"]),
                "is_default": False,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
            }
            strategies.append(cloned)
            _save_strategies(strategies)
            return {"ok": True, "strategy": cloned}

    raise HTTPException(404, f"Strategy {strategy_id} not found")


@router.delete("/{strategy_id}")
def delete_strategy(strategy_id: str):
    """刪除策略（預設策略無法刪除）"""
    strategies = _load_strategies()

    for i, s in enumerate(strategies):
        if s["id"] == strategy_id:
            if s.get("is_default"):
                raise HTTPException(400, "無法刪除預設策略")
            strategies.pop(i)
            _save_strategies(strategies)
            return {"ok": True}

    raise HTTPException(404, f"Strategy {strategy_id} not found")


@router.post("/{strategy_id}/backtest/{code}")
def run_strategy_backtest(strategy_id: str, code: str):
    """使用指定策略參數執行回測（R51-3: 含月度報酬 + 情境分解）"""
    strategies = _load_strategies()

    strategy = None
    for s in strategies:
        if s["id"] == strategy_id:
            strategy = s
            break

    if not strategy:
        raise HTTPException(404, f"Strategy {strategy_id} not found")

    params = strategy["params"]

    try:
        from data.fetcher import get_stock_data
        from backtest.engine import run_backtest_v4
        from backend.dependencies import make_serializable

        df = get_stock_data(code, period_days=365 * 2)
        if df is None or len(df) < 60:
            raise HTTPException(400, f"{code} 數據不足")

        result = run_backtest_v4(
            df,
            initial_capital=1_000_000,
            params=params,
        )

        # R51-3: Monthly return distribution
        monthly_returns = _compute_monthly_returns(result)

        # R51-3: Regime-based performance breakdown
        regime_breakdown = _compute_regime_breakdown(result, df)

        return make_serializable({
            "strategy_name": strategy["name"],
            "code": code,
            "result": result,
            "monthly_returns": monthly_returns,
            "regime_breakdown": regime_breakdown,
        })
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


def _compute_monthly_returns(result) -> list[dict]:
    """R51-3: Compute monthly P&L from trades."""
    monthly: dict[str, float] = {}
    for t in result.trades:
        if t.date_close:
            month = t.date_close.strftime("%Y-%m")
            monthly[month] = monthly.get(month, 0) + t.pnl
    return [{"month": m, "pnl": round(v, 0)} for m, v in sorted(monthly.items())]


def _compute_regime_breakdown(result, df) -> list[dict]:
    """R51-3: Classify each trade's entry date into ML regime and aggregate."""
    import numpy as np

    if not result.trades:
        return []

    try:
        from backend.ml_regime import classify_market_regime
    except ImportError:
        return []

    regime_trades: dict[str, list] = {}

    for trade in result.trades:
        if trade.date_open is None:
            continue

        # Get 60-day window ending at entry date for regime classification
        entry_idx = df.index.get_indexer([trade.date_open], method="nearest")[0]
        start_idx = max(0, entry_idx - 59)
        window = df.iloc[start_idx:entry_idx + 1]

        if len(window) < 30:
            regime_label = "資料不足"
        else:
            try:
                regime_data = classify_market_regime(
                    close=window["close"].values,
                    high=window["high"].values,
                    low=window["low"].values,
                    volume=window["volume"].values.astype(float),
                )
                regime_label = regime_data.get("regime_label", "未知")
            except Exception:
                regime_label = "分類失敗"

        regime_trades.setdefault(regime_label, []).append(trade)

    breakdown = []
    for regime_label, trades in regime_trades.items():
        pnls = [t.pnl for t in trades]
        returns = [t.return_pct for t in trades]
        wins = sum(1 for p in pnls if p > 0)
        breakdown.append({
            "regime": regime_label,
            "count": len(trades),
            "win_rate": round(wins / len(trades), 3) if trades else 0,
            "avg_return": round(float(np.mean(returns)), 4) if returns else 0,
            "total_pnl": round(sum(pnls), 0),
        })

    breakdown.sort(key=lambda x: x["count"], reverse=True)
    return breakdown


@router.get("/adaptive-recommendation")
def get_adaptive_recommendation_endpoint():
    """R51-1: 自適應策略推薦

    根據當前 ML 市場情境，自動推薦最合適的策略與參數調整。
    """
    from data.fetcher import get_stock_data
    from backend.ml_regime import classify_market_regime
    from backend.strategy_adapter import get_adaptive_recommendation
    from backend.dependencies import make_serializable

    try:
        df = get_stock_data("0050", period_days=250)
        if df is None or len(df) < 60:
            return {"error": "數據不足"}

        regime_data = classify_market_regime(
            close=df["close"].values,
            high=df["high"].values,
            low=df["low"].values,
            volume=df["volume"].values,
        )

        strategies = _load_strategies()
        recommendation = get_adaptive_recommendation(regime_data, strategies)

        return make_serializable(recommendation)
    except Exception as e:
        return {"error": str(e)}
