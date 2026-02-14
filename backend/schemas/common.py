"""共用 Pydantic 模型"""

from pydantic import BaseModel


class TimeSeriesResponse(BaseModel):
    """時間序列資料（DataFrame 序列化格式）"""
    dates: list[str]
    columns: dict[str, list]


class SeriesResponse(BaseModel):
    """單一 Series 資料"""
    dates: list[str]
    values: list[float | None]


class MessageResponse(BaseModel):
    ok: bool = True
    message: str = ""
