"""配置持久化路由 — 保存/載入回測與選股器配置"""

import json
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

CONFIGS_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "configs.json"


def _load_all() -> dict:
    try:
        if CONFIGS_FILE.exists():
            return json.loads(CONFIGS_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        logger.debug(f"Optional data load failed: {e}")
    return {"backtest": [], "screener": []}


def _save_all(data: dict):
    CONFIGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class SaveConfigRequest(BaseModel):
    name: str
    config: dict


@router.get("/{config_type}")
def list_configs(config_type: str):
    """列出某類型的所有配置"""
    if config_type not in ("backtest", "screener"):
        raise HTTPException(400, "config_type must be 'backtest' or 'screener'")
    data = _load_all()
    return data.get(config_type, [])


@router.post("/{config_type}")
def save_config(config_type: str, req: SaveConfigRequest):
    """保存配置（同名覆蓋）"""
    if config_type not in ("backtest", "screener"):
        raise HTTPException(400, "config_type must be 'backtest' or 'screener'")
    if not req.name.strip():
        raise HTTPException(400, "name is required")

    data = _load_all()
    configs = data.get(config_type, [])

    # Remove existing config with same name
    configs = [c for c in configs if c.get("name") != req.name]

    configs.insert(0, {
        "name": req.name,
        "config": req.config,
        "updatedAt": datetime.now().isoformat(),
    })

    # Keep max 20 configs per type
    data[config_type] = configs[:20]
    _save_all(data)
    return {"ok": True}


class RenameConfigRequest(BaseModel):
    new_name: str


@router.patch("/{config_type}/{name}")
def rename_config(config_type: str, name: str, req: RenameConfigRequest):
    """重新命名配置"""
    if config_type not in ("backtest", "screener"):
        raise HTTPException(400, "config_type must be 'backtest' or 'screener'")
    if not req.new_name.strip():
        raise HTTPException(400, "new_name is required")

    data = _load_all()
    configs = data.get(config_type, [])

    # Check new name doesn't already exist
    if any(c.get("name") == req.new_name for c in configs):
        raise HTTPException(409, f"配置名稱「{req.new_name}」已存在")

    found = False
    for c in configs:
        if c.get("name") == name:
            c["name"] = req.new_name
            c["updatedAt"] = datetime.now().isoformat()
            found = True
            break

    if not found:
        raise HTTPException(404, f"配置「{name}」不存在")

    data[config_type] = configs
    _save_all(data)
    return {"ok": True}


class BatchDeleteRequest(BaseModel):
    names: list[str]


@router.post("/{config_type}/batch-delete")
def batch_delete_configs(config_type: str, req: BatchDeleteRequest):
    """批量刪除配置"""
    if config_type not in ("backtest", "screener"):
        raise HTTPException(400, "config_type must be 'backtest' or 'screener'")

    names_set = set(req.names)
    data = _load_all()
    configs = data.get(config_type, [])
    data[config_type] = [c for c in configs if c.get("name") not in names_set]
    _save_all(data)
    return {"ok": True, "deleted": len(names_set)}


@router.delete("/{config_type}/{name}")
def delete_config(config_type: str, name: str):
    """刪除配置"""
    if config_type not in ("backtest", "screener"):
        raise HTTPException(400, "config_type must be 'backtest' or 'screener'")

    data = _load_all()
    configs = data.get(config_type, [])
    data[config_type] = [c for c in configs if c.get("name") != name]
    _save_all(data)
    return {"ok": True}
