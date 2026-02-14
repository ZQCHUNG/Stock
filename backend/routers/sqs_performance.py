"""SQS 信號績效追蹤路由（Gemini R45-2）

提供:
1. 績效摘要 — 不同 SQS 等級的勝率/報酬
2. 信號列表 — 原始追蹤紀錄
3. 手動更新 — 觸發前向報酬計算
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
):
    """取得 SQS 信號績效摘要

    按 SQS 等級、分數區間分組，含勝率/平均報酬/累積曲線。
    """
    from backtest.sqs_performance import get_performance_summary
    return get_performance_summary(date_from=date_from, date_to=date_to, min_sqs=min_sqs)


@router.get("/signals")
def tracked_signals(limit: int = 100, offset: int = 0):
    """取得追蹤中的信號列表"""
    from backtest.sqs_performance import get_tracked_signals
    return get_tracked_signals(limit=limit, offset=offset)


@router.post("/update-returns")
def update_returns(max_records: int = 50):
    """手動觸發前向報酬更新

    檢查已記錄的信號，用最新價格數據補全 d1/d3/d5/d10/d20 報酬。
    """
    from backtest.sqs_performance import update_forward_returns
    count = update_forward_returns(max_records=max_records)
    return {"updated": count}


@router.post("/record")
def manual_record(signals: list[dict]):
    """手動記錄信號（通常由排程器自動調用）"""
    from backtest.sqs_performance import record_signals
    count = record_signals(signals)
    return {"recorded": count}
