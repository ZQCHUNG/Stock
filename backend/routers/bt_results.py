"""回測結果歷史路由 — 保存/列出/刪除回測結果"""

import json
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

RESULTS_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "bt_results.json"


def _load_results() -> list:
    try:
        if RESULTS_FILE.exists():
            return json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []


def _save_results(data: list):
    RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class SaveResultRequest(BaseModel):
    name: str
    stockCode: str
    stockName: str
    config: dict
    metrics: dict


@router.get("/")
def list_results():
    """列出所有回測結果歷史"""
    return _load_results()


@router.post("/")
def save_result(req: SaveResultRequest):
    """保存回測結果"""
    if not req.name.strip():
        raise HTTPException(400, "name is required")

    results = _load_results()

    results.insert(0, {
        "name": req.name,
        "stockCode": req.stockCode,
        "stockName": req.stockName,
        "config": req.config,
        "metrics": req.metrics,
        "savedAt": datetime.now().isoformat(),
    })

    # Keep max 50 results
    _save_results(results[:50])
    return {"ok": True}


@router.delete("/{index}")
def delete_result(index: int):
    """刪除回測結果（按索引）"""
    results = _load_results()
    if 0 <= index < len(results):
        results.pop(index)
        _save_results(results)
    return {"ok": True}
