"""分析報告資料模型

ReportResult 和相關 dataclasses，從 report.py 提取以提升可維護性。
"""

import math
import pandas as pd
from dataclasses import dataclass, field
from datetime import datetime


# ============================================================
# Data Structures
# ============================================================

@dataclass
class SupportResistanceLevel:
    price: float
    level_type: str   # "support" or "resistance"
    source: str       # "swing", "ma20", "ma60", "ma120", "ma240", "bb", "round"
    strength: int     # 1-3


@dataclass
class FibonacciLevels:
    swing_high: float
    swing_low: float
    direction: str           # "uptrend" or "downtrend"
    retracement: dict        # {0.236: price, ...}
    extension: dict          # {1.272: price, ...}


@dataclass
class PriceTarget:
    scenario: str            # "bull", "base", "bear"
    target_price: float
    upside_pct: float
    rationale: str
    timeframe: str           # "3M", "6M", "1Y"
    confidence: str          # "高", "中", "低"


@dataclass
class OutlookScenario:
    timeframe: str
    bull_case: str
    bull_target: float
    bull_probability: int
    base_case: str
    base_target: float
    base_probability: int
    bear_case: str
    bear_target: float
    bear_probability: int


@dataclass
class ReportResult:
    stock_code: str
    stock_name: str
    report_date: datetime
    data_period_days: int

    company_info: dict

    current_price: float
    price_change_1w: float
    price_change_1m: float
    price_change_3m: float
    price_change_6m: float
    price_change_1y: float
    high_52w: float
    low_52w: float
    high_52w_date: str
    low_52w_date: str
    pct_from_52w_high: float
    pct_from_52w_low: float

    trend_direction: str
    trend_strength: str
    momentum_status: str
    volatility_level: str
    overall_rating: str
    ma_alignment: str

    support_levels: list
    resistance_levels: list

    fibonacci: FibonacciLevels

    price_targets: list

    adx_value: float
    adx_interpretation: str
    rsi_value: float
    rsi_interpretation: str
    macd_value: float
    macd_signal_value: float
    macd_histogram: float
    macd_interpretation: str
    k_value: float
    d_value: float
    kd_interpretation: str

    volume_trend: str
    volume_ratio: float
    accumulation_distribution: str
    volume_interpretation: str

    atr_value: float
    atr_pct: float
    historical_volatility_20d: float
    historical_volatility_60d: float
    bollinger_width: float
    bollinger_position: float
    volatility_interpretation: str

    max_drawdown_1y: float
    current_drawdown: float
    key_risk_level: float
    risk_reward_ratio: float
    risk_interpretation: str

    outlook_3m: OutlookScenario
    outlook_6m: OutlookScenario
    outlook_1y: OutlookScenario

    summary_text: str

    v4_analysis: dict
    v2_analysis: dict

    # 基本面
    fundamentals: dict = field(default_factory=dict)
    fundamental_interpretation: str = ""
    fundamental_score: float = 0.0
    analyst_data: dict = field(default_factory=dict)

    # 消息面
    news_items: list = field(default_factory=list)
    news_sentiment_score: float = 0.0
    news_sentiment_label: str = "無資料"

    indicators_df: pd.DataFrame = field(default=None, repr=False)

    # 行動建議
    actionable_recommendation: dict = field(default_factory=dict)
    # 產業特定風險
    industry_risks: list = field(default_factory=list)
    # 消息面洞察
    news_insights: list = field(default_factory=list)
    # 新聞主題分類
    news_themes: dict = field(default_factory=dict)
    # 消息面矛盾
    news_contradictions: list = field(default_factory=list)
    # 技術面矛盾
    technical_conflicts: list = field(default_factory=list)
    # 綜合技術偏向
    technical_bias: str = ""
    # 產業基準對照
    peer_context: dict = field(default_factory=dict)


# ============================================================
# Utility
# ============================================================

def _safe(val, default=0.0):
    """安全取值，處理 NaN"""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return default
    return float(val)
