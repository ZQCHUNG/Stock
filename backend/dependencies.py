"""共用工具 — DataFrame 序列化、股票清單 loader"""

import math
import numpy as np
import pandas as pd


def df_to_response(df: pd.DataFrame, tail: int | None = None) -> dict:
    """DataFrame → JSON-safe dict

    格式: {dates: str[], columns: {col_name: (float|None)[]}}
    前端直接用 dates 作 x 軸，columns 各自取值。

    Args:
        df: 時間序列 DataFrame（index 為日期）
        tail: 只回傳最後 N 筆（可選）
    """
    if df is None or df.empty:
        return {"dates": [], "columns": {}}

    data = df.tail(tail) if tail else df

    dates = data.index.strftime("%Y-%m-%d").tolist()
    columns = {}
    for col in data.columns:
        vals = data[col].tolist()
        columns[col] = [_safe_float(v) for v in vals]

    return {"dates": dates, "columns": columns}


def series_to_response(s: pd.Series) -> dict:
    """Series → JSON-safe dict {dates: str[], values: float[]}"""
    if s is None or s.empty:
        return {"dates": [], "values": []}
    return {
        "dates": s.index.strftime("%Y-%m-%d").tolist(),
        "values": [_safe_float(v) for v in s.tolist()],
    }


def _safe_float(v) -> float | None:
    """將 numpy/pandas 值轉為 JSON-safe float"""
    if v is None:
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        if math.isnan(v) or math.isinf(v):
            return None
        return float(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, (pd.Timestamp,)):
        return v.isoformat()
    return v


def make_serializable(obj):
    """遞迴清理 dict/list 中的 numpy/pandas 類型"""
    if isinstance(obj, dict):
        return {k: make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [make_serializable(v) for v in obj]
    if isinstance(obj, pd.Series):
        return series_to_response(obj)
    if isinstance(obj, pd.DataFrame):
        return df_to_response(obj)
    return _safe_float(obj)
