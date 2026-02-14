"""SQS 信號績效追蹤路由（Gemini R45-2 → R46 升級）

提供:
1. 績效摘要 — 不同 SQS 等級的勝率/報酬
2. 信號列表 — 原始追蹤紀錄（支援 source 篩選）
3. 手動更新 — 觸發前向報酬計算
4. 歷史回測預填 — 冷啟動數據填充
"""

import logging

from fastapi import APIRouter

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/summary")
def performance_summary(
    date_from: str | None = None,
    date_to: str | None = None,
    min_sqs: float | None = None,
    source: str | None = None,
):
    """取得 SQS 信號績效摘要

    source: "live" | "backtest" | None (all)
    """
    from backtest.sqs_performance import get_performance_summary
    return get_performance_summary(
        date_from=date_from, date_to=date_to,
        min_sqs=min_sqs, source=source,
    )


@router.get("/signals")
def tracked_signals(limit: int = 100, offset: int = 0, source: str | None = None):
    """取得追蹤中的信號列表"""
    from backtest.sqs_performance import get_tracked_signals
    return get_tracked_signals(limit=limit, offset=offset, source=source)


@router.post("/update-returns")
def update_returns(max_records: int = 50):
    """手動觸發前向報酬更新"""
    from backtest.sqs_performance import update_forward_returns
    count = update_forward_returns(max_records=max_records)
    return {"updated": count}


@router.post("/record")
def manual_record(signals: list[dict]):
    """手動記錄信號（通常由排程器自動調用）"""
    from backtest.sqs_performance import record_signals
    count = record_signals(signals)
    return {"recorded": count}


@router.post("/backfill")
def backfill_historical(period_days: int = 730):
    """用歷史回測數據預填績效追蹤器 (R46-1 冷啟動)

    注意: 這是耗時操作（可能數分鐘），建議只執行一次。
    """
    from backtest.sqs_performance import backfill_from_sqs_backtest
    count = backfill_from_sqs_backtest(period_days=period_days)
    return {"backfilled": count, "source": "backtest"}
