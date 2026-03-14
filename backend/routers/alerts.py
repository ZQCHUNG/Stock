"""SQS 警報系統路由（Gemini R44 → R45 升級）

R44: 基礎 CRUD + 前端輪詢
R45: 後端 APScheduler + 去重推播 + 排程狀態 API
"""

import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()
logger = logging.getLogger(__name__)

ALERT_CONFIG_PATH = Path(__file__).parent.parent.parent / "data" / "alert_config.json"
ALERT_HISTORY_PATH = Path(__file__).parent.parent.parent / "data" / "alert_history.json"


class AlertConfig(BaseModel):
    sqs_threshold: float = 70
    notify_browser: bool = True
    notify_line: bool = False
    line_token: str = ""
    notify_telegram: bool = False  # R56: Telegram Bot notification
    telegram_bot_token: str = ""   # R56: @BotFather token
    telegram_chat_id: str = ""     # R56: target chat/group ID
    watch_codes: list[str] = []  # Empty = watch all BUY signals
    scheduler_interval: int = 5  # R45: minutes between checks


def _load_config() -> AlertConfig:
    if ALERT_CONFIG_PATH.exists():
        try:
            data = json.loads(ALERT_CONFIG_PATH.read_text(encoding="utf-8"))
            return AlertConfig(**data)
        except Exception as e:
            logger.debug(f"Optional data load failed: {e}")
    return AlertConfig()


def _save_config(config: AlertConfig):
    ALERT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    ALERT_CONFIG_PATH.write_text(
        json.dumps(config.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _load_history() -> list[dict]:
    if ALERT_HISTORY_PATH.exists():
        try:
            return json.loads(ALERT_HISTORY_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            logger.debug(f"Optional data load failed: {e}")
    return []


@router.get("/config")
def get_alert_config():
    """取得當前警報設定"""
    config = _load_config()
    masked = config.model_dump()
    if masked["line_token"]:
        masked["line_token"] = masked["line_token"][:8] + "***"
    if masked["telegram_bot_token"]:
        masked["telegram_bot_token"] = masked["telegram_bot_token"][:8] + "***"
    return masked


@router.post("/config")
def save_alert_config(config: AlertConfig):
    """儲存警報設定"""
    original = _load_config()
    if config.line_token.endswith("***"):
        config.line_token = original.line_token
    if config.telegram_bot_token.endswith("***"):
        config.telegram_bot_token = original.telegram_bot_token
    _save_config(config)
    return {"status": "ok"}


@router.get("/check")
def check_alerts():
    """取得最新的警報觸發結果（R45: 由後端排程產生，前端僅讀取）

    如果排程器未啟動，fallback 為即時計算。
    """
    from backend.scheduler import get_last_check, get_scheduler_status

    status = get_scheduler_status()
    config = _load_config()

    if status["running"] and status["last_check"]["timestamp"]:
        # Return cached result from scheduler
        last = status["last_check"]
        return {
            "triggered": last["triggered"],
            "threshold": config.sqs_threshold,
            "notify_browser": config.notify_browser,
            "notify_line": config.notify_line,
            "source": "scheduler",
            "last_check_time": last["timestamp"],
        }

    # Fallback: compute on-demand (scheduler not running)
    return _check_alerts_fallback(config)


def _check_alerts_fallback(config: AlertConfig) -> dict:
    """Fallback alert check when scheduler is not running."""
    from datetime import datetime

    triggered = []
    try:
        from data.cache import get_cached_sector_heat
        alpha = get_cached_sector_heat()
        if not alpha or not alpha.get("sectors"):
            return {"triggered": [], "threshold": config.sqs_threshold}

        all_stocks = []
        for sector in alpha["sectors"]:
            for stock in sector.get("buy_stocks", []):
                all_stocks.append(stock)

        if config.watch_codes:
            watch_set = set(config.watch_codes)
            all_stocks = [s for s in all_stocks if s["code"] in watch_set]

        from analysis.scoring import compute_sqs_for_signal
        for stock in all_stocks:
            try:
                sqs = compute_sqs_for_signal(
                    stock["code"],
                    signal_strategy="V4",
                    signal_maturity=stock.get("maturity", "N/A"),
                )
                if sqs["sqs"] >= config.sqs_threshold:
                    triggered.append({
                        "code": stock["code"],
                        "name": stock.get("name", ""),
                        "sqs": sqs["sqs"],
                        "grade": sqs["grade"],
                        "grade_label": sqs["grade_label"],
                        "maturity": stock.get("maturity", ""),
                        "confidence": stock.get("confidence", 0),
                    })
            except Exception as e:
                logger.debug(f"Optional operation failed: {e}")

        triggered.sort(key=lambda x: x["sqs"], reverse=True)
    except Exception as e:
        logger.warning(f"Alert check fallback failed: {e}")

    return {
        "triggered": triggered,
        "threshold": config.sqs_threshold,
        "notify_browser": config.notify_browser,
        "notify_line": config.notify_line,
        "source": "fallback",
        "last_check_time": datetime.now().isoformat(),
    }


@router.post("/trigger-check")
def trigger_manual_check():
    """手動觸發一次警報檢查（R45: 調用排程器的 check 函數）"""
    from backend.scheduler import run_alert_check, get_last_check
    run_alert_check()
    return get_last_check()


@router.get("/scheduler-status")
def scheduler_status():
    """取得排程器運行狀態"""
    from backend.scheduler import get_scheduler_status
    return get_scheduler_status()


@router.post("/send-line")
def send_line_notification(payload: dict):
    """手動觸發 LINE Notify 推播"""
    config = _load_config()
    if not config.line_token:
        raise HTTPException(status_code=400, detail="LINE token not configured")

    message = payload.get("message", "")
    if not message:
        raise HTTPException(status_code=400, detail="Message is required")

    try:
        from backend.scheduler import _send_line_notify
        _send_line_notify(config.line_token, message)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/send-test")
def send_test_notification(payload: dict):
    """R56: 發送測試通知到所有啟用的管道（LINE + Telegram）"""
    message = payload.get("message", "🧪 測試通知 — 如收到此訊息，通知管道設定正確！")
    try:
        from backend.scheduler import _send_notification
        _send_notification(message)
        return {"status": "ok", "message": message}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/notify-triggered")
def notify_triggered_alerts():
    """R56: 檢查 + 推播觸發的警報（LINE + Telegram 統一推播）"""
    from datetime import datetime
    from backend.scheduler import _send_notification

    config = _load_config()
    result = check_alerts()
    triggered = result.get("triggered", [])

    if not triggered:
        return {"status": "no alerts", "count": 0}

    lines = [f"\n📊 SQS Alert (≥{config.sqs_threshold})"]
    lines.append(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"共 {len(triggered)} 檔觸發:\n")
    for t in triggered[:10]:
        icon = "💎" if t["grade"] == "diamond" else "🥇" if t["grade"] == "gold" else "🥈"
        lines.append(f"{icon} {t['code']} {t['name']} — SQS {t['sqs']} ({t['maturity']})")

    message = "\n".join(lines)
    _send_notification(message)

    return {"status": "ok", "count": len(triggered), "message": message}


@router.get("/health")
def scheduler_health():
    """R46-3: 排程器健康檢查 — 包含 uptime、錯誤率、心跳狀態"""
    from backend.scheduler import get_health
    return get_health()


@router.get("/history")
def get_alert_history():
    """取得警報歷史紀錄"""
    return _load_history()


# ---------------------------------------------------------------------------
# R55-3: Compound Alert Rules
# ---------------------------------------------------------------------------

class CompoundRuleRequest(BaseModel):
    name: str
    codes: list[str] = []
    conditions: list[dict] = []
    combine_mode: str = "AND"
    notify_line: bool = False
    notify_browser: bool = True
    cooldown_hours: float = 4.0


@router.get("/rules")
def list_compound_rules():
    """列出所有複合條件警報規則"""
    from backend.compound_alerts import load_rules
    return [r.to_dict() for r in load_rules()]


@router.post("/rules")
def create_compound_rule(req: CompoundRuleRequest):
    """建立複合條件警報規則"""
    import time
    from uuid import uuid4
    from backend.compound_alerts import CompoundRule, Condition, add_rule

    rule = CompoundRule(
        id=str(uuid4())[:8],
        name=req.name,
        codes=req.codes,
        conditions=[Condition.from_dict(c) for c in req.conditions],
        combine_mode=req.combine_mode,
        notify_line=req.notify_line,
        notify_browser=req.notify_browser,
        cooldown_hours=req.cooldown_hours,
        created_at=time.time(),
    )
    add_rule(rule)
    return rule.to_dict()


@router.patch("/rules/{rule_id}")
def update_compound_rule(rule_id: str, updates: dict):
    """更新複合條件警報規則"""
    from backend.compound_alerts import update_rule
    rule = update_rule(rule_id, updates)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    return rule.to_dict()


@router.delete("/rules/{rule_id}")
def delete_compound_rule(rule_id: str):
    """刪除複合條件警報規則"""
    from backend.compound_alerts import delete_rule
    if not delete_rule(rule_id):
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"ok": True}


@router.post("/rules/check")
def check_compound_rules(codes: list[str] | None = None):
    """檢查所有啟用的複合條件警報規則

    可選傳入 codes 只檢查特定股票，否則依每條規則設定的 codes。
    """
    from backend.compound_alerts import (
        load_rules, evaluate_rule, check_cooldown,
        get_stock_indicator_data, save_rules,
    )
    import time

    rules = load_rules()
    triggered = []
    updated = False

    for rule in rules:
        if not rule.enabled:
            continue
        if not check_cooldown(rule):
            continue

        check_codes = codes or rule.codes
        if not check_codes:
            # Default: use scan stocks from config
            try:
                from config import SCAN_STOCKS
                check_codes = SCAN_STOCKS[:20]  # Limit for performance
            except Exception as e:
                logger.debug(f"Optional operation failed: {e}")
                check_codes = []

        for code in check_codes:
            try:
                stock_data = get_stock_indicator_data(code)
                if not stock_data:
                    continue
                if evaluate_rule(rule, stock_data):
                    triggered.append({
                        "rule_id": rule.id,
                        "rule_name": rule.name,
                        "code": code,
                        "combine_mode": rule.combine_mode,
                        "conditions_met": len(rule.conditions),
                        "notify_browser": rule.notify_browser,
                        "notify_line": rule.notify_line,
                    })
                    rule.last_triggered = time.time()
                    rule.trigger_count += 1
                    updated = True
            except Exception as e:
                logger.debug(f"Rule check error for {code}: {e}")

    if updated:
        save_rules(rules)

    return {"triggered": triggered, "rules_checked": len([r for r in rules if r.enabled])}


@router.get("/condition-types")
def list_condition_types():
    """列出所有可用的條件類型（供前端下拉選單用）"""
    from backend.compound_alerts import ConditionType
    return [
        {"value": ct.value, "label": _condition_label(ct)}
        for ct in ConditionType
    ]


def _condition_label(ct) -> str:
    """Human-readable label for condition type."""
    labels = {
        "price_above": "價格 > 指定值",
        "price_below": "價格 < 指定值",
        "price_change_pct": "漲跌幅 (%) ≥",
        "volume_above": "成交量 > 指定值",
        "volume_ratio": "量能比（vs 20日均量）≥",
        "rsi_above": "RSI >",
        "rsi_below": "RSI <",
        "macd_cross_up": "MACD 黃金交叉",
        "macd_cross_down": "MACD 死亡交叉",
        "kd_cross_up": "KD 黃金交叉",
        "kd_cross_down": "KD 死亡交叉",
        "ma_cross_up": "均線黃金交叉",
        "ma_cross_down": "均線死亡交叉",
        "adx_above": "ADX >",
        "bb_upper_break": "突破布林上軌",
        "bb_lower_break": "跌破布林下軌",
        "sqs_above": "SQS ≥",
        "v4_buy_signal": "V4 買入信號",
        "v4_sell_signal": "V4 賣出信號",
    }
    return labels.get(ct.value, ct.value)
