"""SSE (Server-Sent Events) 工具函數"""

import json


def sse_event(data: dict) -> str:
    """格式化 SSE 事件"""
    return f"data: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def sse_progress(current: int, total: int, message: str = "") -> str:
    """進度事件"""
    return sse_event({"type": "progress", "current": current, "total": total, "message": message})


def sse_done(result) -> str:
    """完成事件（含結果）"""
    return sse_event({"type": "done", "result": result})


def sse_error(message: str) -> str:
    """錯誤事件"""
    return sse_event({"type": "error", "message": message})
