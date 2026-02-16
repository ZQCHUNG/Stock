"""分析報告資料模型

ReportResult 和相關 dataclasses，從 report.py 提取以提升可維護性。
"""

import math
import pandas as pd
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


# ============================================================
# Data Structures
# ============================================================

# ============================================================
# Override Traceability System (Protocol v3 — Phase 2)
# 評等覆寫溯源系統：將 Gatekeeper 的靜默降級轉為結構化可審計路徑
# ============================================================

class OverrideCode(str, Enum):
    """評等覆寫代碼 — 每個 Gatekeeper 對應一個"""
    GHOST_TOWN = "GHOST_TOWN"            # G1: 零法人 + 流動性差
    INST_EXTREME_NEG = "INST_NEG"        # G2: 籌碼面 < -2
    CASH_RUNWAY_CRITICAL = "CASH_CRIT"   # G3: 現金跑道 < 4 季
    CASH_RUNWAY_WARNING = "CASH_WARN"    # G3b: 現金跑道 < 8 季
    BEAR_MARKET_CAP = "BEAR_CAP"         # G5: 空頭市場上限
    CONFLICT_CAP = "CONFLICT_CAP"        # G6: 技術矛盾上限
    RSI_OVERBOUGHT_CAP = "RSI_OB_CAP"   # G7: RSI 超買上限 [PLACEHOLDER_NEEDS_DATA]
    ACTION_CONSISTENCY = "ACT_CONSIST"   # G8: 行動建議一致性（deprecated, 待 G9 上線後移除）


class OverrideSeverity(str, Enum):
    """覆寫嚴重程度"""
    HARD_CAP = "hard_cap"    # 強制上限（不可被其他分數覆蓋）
    SOFT_CAP = "soft_cap"    # 軟性限制（降一級）
    OVERRIDE = "override"    # 事後改寫


@dataclass
class RatingOverride:
    """單次覆寫記錄"""
    code: OverrideCode
    severity: OverrideSeverity
    rating_before: str          # 覆寫前評等
    rating_after: str           # 覆寫後評等
    cap_limit: str              # 此 Gatekeeper 的上限等級
    threshold_value: float      # 觸發門檻值（如 -2, 4, 70）
    actual_value: float         # 實際觀測值
    data_source: str            # [VERIFIED: xxx] 或 [PLACEHOLDER: xxx]
    data_confidence: str = "high"  # high / medium / low


# Gatekeeper 中文描述（面向使用者的 UI）
# UI 不使用 [PLACEHOLDER] 等內部標籤，改用「保守型限制」(Conservative Guardrail)
OVERRIDE_DISPLAY_NAMES = {
    OverrideCode.GHOST_TOWN: "流動性風險（法人未交易且成交量偏低）",
    OverrideCode.INST_EXTREME_NEG: "法人籌碼面極度偏空",
    OverrideCode.CASH_RUNWAY_CRITICAL: "現金跑道不足（高財務風險）",
    OverrideCode.CASH_RUNWAY_WARNING: "現金跑道偏低（注意財務狀況）",
    OverrideCode.BEAR_MARKET_CAP: "空頭市場保守型限制",
    OverrideCode.CONFLICT_CAP: "技術面訊號矛盾保守型限制",
    OverrideCode.RSI_OVERBOUGHT_CAP: "RSI 超買保守型限制",
    OverrideCode.ACTION_CONSISTENCY: "行動建議一致性修正",
}


@dataclass
class RatingDecision:
    """完整評等決策記錄 — Override Traceability System 核心"""
    raw_score: float              # 加權前原始分數
    raw_rating: str               # Gatekeeper 介入前的評等
    final_rating: str             # 最終評等
    dimension_scores: dict        # {"tech": 5.2, "fund": 1.3, "inst": -3.0}
    dimension_weights: dict       # {"tech": 0.35, "fund": 0.25, ...}
    overrides: list = field(default_factory=list)   # list[RatingOverride]
    was_overridden: bool = False

    def __str__(self) -> str:
        """向下相容：str(rating_decision) == final_rating"""
        return self.final_rating

    def __eq__(self, other):
        """向下相容：rating_decision == "買進" """
        if isinstance(other, str):
            return self.final_rating == other
        return NotImplemented

    def __hash__(self):
        return hash(self.final_rating)

    @property
    def override_count(self) -> int:
        return len(self.overrides)

    @property
    def active_risk_factors(self) -> list[str]:
        """面向 UI 的風險因子描述列表（使用「保守型限制」用語）"""
        return [OVERRIDE_DISPLAY_NAMES.get(o.code, str(o.code))
                for o in self.overrides]

    def to_dict(self) -> dict:
        """序列化為 JSON-safe dict（供 API 回傳）"""
        return {
            "raw_score": round(self.raw_score, 2),
            "raw_rating": self.raw_rating,
            "final_rating": self.final_rating,
            "was_overridden": self.was_overridden,
            "override_count": self.override_count,
            "dimension_scores": {k: round(v, 2) for k, v in self.dimension_scores.items()},
            "dimension_weights": self.dimension_weights,
            "overrides": [
                {
                    "code": o.code.value,
                    "severity": o.severity.value,
                    "display_name": OVERRIDE_DISPLAY_NAMES.get(o.code, str(o.code)),
                    "rating_before": o.rating_before,
                    "rating_after": o.rating_after,
                    "cap_limit": o.cap_limit,
                    "data_confidence": o.data_confidence,
                }
                for o in self.overrides
            ],
            "active_risk_factors": self.active_risk_factors,
        }


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
    # 估值模型結果
    valuation: dict = field(default_factory=dict)
    # 籌碼面評分（Gemini R19）
    institutional_score: dict = field(default_factory=dict)
    # 是否為生技股（自動偵測）
    is_biotech: bool = False
    # 評分權重（用於前端顯示）
    rating_weights: dict = field(default_factory=dict)
    # Cash Runway（Gemini R20: 生技股財務風險）
    cash_runway: dict | None = None
    # 評等決策溯源（Protocol v3 Phase 2: Override Traceability）
    rating_decision: RatingDecision | None = None


# ============================================================
# Utility
# ============================================================

def _safe(val, default=0.0):
    """安全取值，處理 NaN"""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return default
    return float(val)
