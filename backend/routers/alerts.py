"""SQS 警報系統路由（Gemini R44）

提供:
1. 警報設定 CRUD (SQS 閾值, 通知方式)
2. 檢查當前觸發的警報
3. LINE Notify webhook 推播
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
    watch_codes: list[str] = []  # Empty = watch all BUY signals


def _load_config() -> AlertConfig:
    if ALERT_CONFIG_PATH.exists():
        try:
            data = json.loads(ALERT_CONFIG_PATH.read_text(encoding="utf-8"))
            return AlertConfig(**data)
        except Exception:
            pass
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
        except Exception:
            pass
    return []


def _save_history(history: list[dict]):
    ALERT_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Keep last 200 entries
    ALERT_HISTORY_PATH.write_text(
        json.dumps(history[-200:], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


@router.get("/config")
def get_alert_config():
    """取得當前警報設定"""
    config = _load_config()
    # Mask LINE token for security
    masked = config.model_dump()
    if masked["line_token"]:
        masked["line_token"] = masked["line_token"][:8] + "***"
    return masked


@router.post("/config")
def save_alert_config(config: AlertConfig):
    """儲存警報設定"""
    # If token is masked (unchanged), preserve original
    if config.line_token.endswith("***"):
        original = _load_config()
        config.line_token = original.line_token
    _save_config(config)
    return {"status": "ok"}


@router.get("/check")
def check_alerts():
    """檢查當前觸發的警報（前端定期輪詢）

    掃描 Alpha Hunter 數據，找出 SQS >= threshold 的信號。
    """
    from datetime import datetime

    config = _load_config()
    triggered = []

    try:
        from data.cache import get_cached_alpha_hunter
        alpha = get_cached_alpha_hunter()
        if not alpha or not alpha.get("sectors"):
            return {"triggered": [], "threshold": config.sqs_threshold}

        # Collect all BUY stocks
        all_stocks = []
        for sector in alpha["sectors"]:
            for stock in sector.get("stocks", []):
                all_stocks.append(stock)

        # Filter by watch list if specified
        if config.watch_codes:
            watch_set = set(config.watch_codes)
            all_stocks = [s for s in all_stocks if s["code"] in watch_set]

        # Compute SQS for each
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
            except Exception:
                pass

        # Sort by SQS descending
        triggered.sort(key=lambda x: x["sqs"], reverse=True)

        # Record in history
        if triggered:
            history = _load_history()
            history.append({
                "timestamp": datetime.now().isoformat(),
                "count": len(triggered),
                "top_stocks": [t["code"] for t in triggered[:5]],
                "threshold": config.sqs_threshold,
            })
            _save_history(history)

    except Exception as e:
        logger.warning(f"Alert check failed: {e}")

    return {
        "triggered": triggered,
        "threshold": config.sqs_threshold,
        "notify_browser": config.notify_browser,
        "notify_line": config.notify_line,
    }


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
        _send_line_notify(config.line_token, message)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/notify-triggered")
def notify_triggered_alerts():
    """檢查 + 推播觸發的警報到 LINE"""
    from datetime import datetime

    config = _load_config()
    result = check_alerts()
    triggered = result.get("triggered", [])

    if not triggered:
        return {"status": "no alerts", "count": 0}

    # Build message
    lines = [f"\n📊 SQS Alert (≥{config.sqs_threshold})"]
    lines.append(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"共 {len(triggered)} 檔觸發:\n")
    for t in triggered[:10]:
        icon = "💎" if t["grade"] == "diamond" else "🥇" if t["grade"] == "gold" else "🥈"
        lines.append(f"{icon} {t['code']} {t['name']} — SQS {t['sqs']} ({t['maturity']})")

    message = "\n".join(lines)

    # Send via LINE if configured
    if config.notify_line and config.line_token:
        try:
            _send_line_notify(config.line_token, message)
        except Exception as e:
            logger.warning(f"LINE notify failed: {e}")

    return {
        "status": "ok",
        "count": len(triggered),
        "message": message,
    }


@router.get("/history")
def get_alert_history():
    """取得警報歷史紀錄"""
    return _load_history()


def _send_line_notify(token: str, message: str):
    """Send LINE Notify message."""
    import urllib.request
    import urllib.parse

    url = "https://notify-api.line.me/api/notify"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = urllib.parse.urlencode({"message": message}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    urllib.request.urlopen(req, timeout=10)
