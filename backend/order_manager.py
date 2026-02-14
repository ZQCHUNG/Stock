"""Simulated Order Management System (Gemini R50-2)

Auto-executes stop-loss, take-profit, and trailing-stop exits for open positions.
Runs as a scheduled job during market hours. All executions are logged to
the `order_events` table for audit trail.

Order lifecycle: Signal → Position Open → Monitor → Auto-Exit (SL/TP/TS) or Manual Close
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from backend import db

logger = logging.getLogger(__name__)

# V4 strategy exit parameters (mirrored from config.py)
TAKE_PROFIT_PCT = 0.10     # +10%
STOP_LOSS_PCT = -0.07      # -7%
TRAILING_STOP_PCT = 0.02   # 2% trailing from high
MIN_HOLD_DAYS = 5          # Minimum hold before trailing stop activates


def check_positions_and_execute() -> dict:
    """Main OMS loop: check all open positions and auto-execute exits.

    Returns summary of actions taken.
    """
    positions = db.get_open_positions()
    if not positions:
        return {"checked": 0, "actions": []}

    # Fetch current prices in parallel
    codes = list({p["code"] for p in positions})
    price_map = _fetch_current_prices(codes)

    actions = []
    for pos in positions:
        code = pos["code"]
        current_price = price_map.get(code)
        if current_price is None:
            continue

        entry_price = pos["entry_price"]
        stop_loss = pos.get("stop_loss", 0)
        trailing_stop = pos.get("trailing_stop")
        entry_date = pos.get("entry_date", "")
        days_held = (datetime.now() - datetime.fromisoformat(entry_date)).days if entry_date else 0
        pnl_pct = (current_price / entry_price - 1) if entry_price > 0 else 0

        # 1. Check stop-loss
        if stop_loss > 0 and current_price <= stop_loss:
            result = _execute_exit(pos, current_price, "stop_loss",
                                   f"觸發停損 ${stop_loss:.2f}，現價 ${current_price:.2f}")
            if result:
                actions.append(result)
            continue

        # 2. Check trailing stop (only after min hold days)
        if trailing_stop and trailing_stop > 0 and days_held >= MIN_HOLD_DAYS:
            if current_price <= trailing_stop:
                result = _execute_exit(pos, current_price, "trailing_stop",
                                       f"觸發移動停利 ${trailing_stop:.2f}，現價 ${current_price:.2f}")
                if result:
                    actions.append(result)
                continue

        # 3. Check take-profit (+10%)
        if pnl_pct >= TAKE_PROFIT_PCT:
            result = _execute_exit(pos, current_price, "take_profit",
                                   f"達停利 +{pnl_pct:.1%}，現價 ${current_price:.2f}")
            if result:
                actions.append(result)
            continue

        # 4. Update trailing stop if price moved higher
        _update_trailing_stop(pos, current_price, days_held)

    summary = {
        "checked": len(positions),
        "priced": len(price_map),
        "actions": actions,
        "timestamp": datetime.now().isoformat(),
    }

    if actions:
        logger.info(f"OMS executed {len(actions)} exits: "
                     f"{[a['exit_reason'] for a in actions]}")

    return summary


def _fetch_current_prices(codes: list[str]) -> dict[str, float]:
    """Fetch current prices for multiple stocks in parallel."""
    from data.fetcher import get_stock_data

    def _get_price(code):
        try:
            df = get_stock_data(code, period_days=5)
            if len(df) >= 1:
                return code, float(df["close"].iloc[-1])
        except Exception:
            pass
        return code, None

    with ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(_get_price, codes))

    return {code: price for code, price in results if price is not None}


def _execute_exit(pos: dict, exit_price: float, reason: str, detail: str) -> dict | None:
    """Close a position and log the order event."""
    try:
        result = db.close_position(pos["id"], exit_price, reason)
        if result:
            # Log the order event
            _log_order_event(
                position_id=pos["id"],
                code=pos["code"],
                event_type="auto_exit",
                exit_reason=reason,
                exit_price=exit_price,
                detail=detail,
                pnl=result.get("net_pnl", 0),
            )
            logger.info(f"OMS auto-exit: {pos['code']} {pos.get('name', '')} — {reason}: {detail}")
            return {
                "position_id": pos["id"],
                "code": pos["code"],
                "name": pos.get("name", ""),
                "exit_reason": reason,
                "exit_price": exit_price,
                "detail": detail,
                "net_pnl": result.get("net_pnl", 0),
            }
    except Exception as e:
        logger.error(f"OMS exit failed for {pos['code']}: {e}")
    return None


def _update_trailing_stop(pos: dict, current_price: float, days_held: int):
    """Update trailing stop based on highest price movement.

    Trailing stop = highest_close × (1 - TRAILING_STOP_PCT)
    Only activates after MIN_HOLD_DAYS.
    """
    if days_held < MIN_HOLD_DAYS:
        return

    entry_price = pos["entry_price"]
    current_trailing = pos.get("trailing_stop") or 0

    # Calculate new trailing stop: 2% below current price
    new_trailing = round(current_price * (1 - TRAILING_STOP_PCT), 2)

    # Only ratchet UP (never lower the trailing stop)
    if new_trailing > current_trailing and new_trailing > entry_price:
        try:
            db.update_position(pos["id"], {"trailing_stop": new_trailing})
            _log_order_event(
                position_id=pos["id"],
                code=pos["code"],
                event_type="trailing_update",
                detail=f"移動停利更新: ${current_trailing:.2f} → ${new_trailing:.2f} (現價 ${current_price:.2f})",
            )
            logger.debug(f"OMS trailing update: {pos['code']} "
                         f"${current_trailing:.2f} → ${new_trailing:.2f}")
        except Exception as e:
            logger.error(f"Trailing stop update failed for {pos['code']}: {e}")


def _log_order_event(
    position_id: str,
    code: str,
    event_type: str,
    exit_reason: str = "",
    exit_price: float = 0,
    detail: str = "",
    pnl: float = 0,
):
    """Persist an order event to the database for audit trail."""
    try:
        db.insert_order_event({
            "position_id": position_id,
            "code": code,
            "event_type": event_type,
            "exit_reason": exit_reason,
            "exit_price": exit_price,
            "detail": detail,
            "pnl": pnl,
        })
    except Exception as e:
        logger.warning(f"Failed to log order event: {e}")


def get_order_events(limit: int = 50) -> list[dict]:
    """Get recent order events for the frontend."""
    return db.get_order_events(limit=limit)


def get_oms_stats() -> dict:
    """Get OMS execution statistics."""
    events = db.get_order_events(limit=500)
    if not events:
        return {"total_events": 0, "auto_exits": 0, "trailing_updates": 0}

    auto_exits = [e for e in events if e["event_type"] == "auto_exit"]
    trailing_updates = [e for e in events if e["event_type"] == "trailing_update"]

    # Breakdown by exit reason
    reason_counts: dict[str, int] = {}
    total_pnl = 0
    for e in auto_exits:
        reason = e.get("exit_reason", "unknown")
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
        total_pnl += e.get("pnl", 0)

    return {
        "total_events": len(events),
        "auto_exits": len(auto_exits),
        "trailing_updates": len(trailing_updates),
        "exit_reasons": reason_counts,
        "total_auto_pnl": round(total_pnl, 0),
        "last_event": events[0]["timestamp"] if events else None,
    }
