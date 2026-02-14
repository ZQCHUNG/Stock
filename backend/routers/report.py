"""分析報告路由"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class ReportRequest(BaseModel):
    period_days: int = 730
    market_regime: str | None = None


@router.post("/{code}/generate")
def generate_report_api(code: str, req: ReportRequest):
    """產生完整分析報告"""
    from analysis.report import generate_report
    from backend.dependencies import make_serializable
    try:
        report = generate_report(
            code,
            period_days=req.period_days,
            market_regime=req.market_regime,
        )

        # 序列化 ReportResult dataclass
        result = {
            "stock_code": report.stock_code,
            "stock_name": report.stock_name,
            "report_date": report.report_date.isoformat(),
            "current_price": report.current_price,
            # 價格表現
            "price_change_1w": report.price_change_1w,
            "price_change_1m": report.price_change_1m,
            "price_change_3m": report.price_change_3m,
            "price_change_6m": report.price_change_6m,
            "price_change_1y": report.price_change_1y,
            "high_52w": report.high_52w,
            "low_52w": report.low_52w,
            "pct_from_52w_high": report.pct_from_52w_high,
            "pct_from_52w_low": report.pct_from_52w_low,
            # 趨勢
            "trend_direction": report.trend_direction,
            "trend_strength": report.trend_strength,
            "momentum_status": report.momentum_status,
            "volatility_level": report.volatility_level,
            "overall_rating": report.overall_rating,
            "ma_alignment": report.ma_alignment,
            # 支撐壓力
            "support_levels": [
                {"price": s.price, "source": s.source, "strength": s.strength}
                for s in (report.support_levels or [])
            ],
            "resistance_levels": [
                {"price": r.price, "source": r.source, "strength": r.strength}
                for r in (report.resistance_levels or [])
            ],
            # 費氏
            "fibonacci": {
                "swing_high": report.fibonacci.swing_high,
                "swing_low": report.fibonacci.swing_low,
                "direction": report.fibonacci.direction,
                "retracement": report.fibonacci.retracement,
                "extension": report.fibonacci.extension,
            } if report.fibonacci else None,
            # 目標價
            "price_targets": [
                {
                    "scenario": t.scenario,
                    "target_price": t.target_price,
                    "upside_pct": t.upside_pct,
                    "rationale": t.rationale,
                    "timeframe": t.timeframe,
                    "confidence": t.confidence,
                }
                for t in (report.price_targets or [])
            ],
            # 動能指標
            "adx_value": report.adx_value,
            "adx_interpretation": report.adx_interpretation,
            "rsi_value": report.rsi_value,
            "rsi_interpretation": report.rsi_interpretation,
            "macd_value": report.macd_value,
            "macd_signal_value": report.macd_signal_value,
            "macd_histogram": report.macd_histogram,
            "macd_interpretation": report.macd_interpretation,
            "k_value": report.k_value,
            "d_value": report.d_value,
            "kd_interpretation": report.kd_interpretation,
            # 量能
            "volume_trend": report.volume_trend,
            "volume_ratio": report.volume_ratio,
            "volume_interpretation": report.volume_interpretation,
            # 波動
            "atr_value": report.atr_value,
            "atr_pct": report.atr_pct,
            "bollinger_width": report.bollinger_width,
            "bollinger_position": report.bollinger_position,
            "volatility_interpretation": report.volatility_interpretation,
            # 風險
            "max_drawdown_1y": report.max_drawdown_1y,
            "current_drawdown": report.current_drawdown,
            "risk_reward_ratio": report.risk_reward_ratio,
            "risk_interpretation": report.risk_interpretation,
            # 展望
            "outlook_3m": _serialize_outlook(report.outlook_3m),
            "outlook_6m": _serialize_outlook(report.outlook_6m),
            "outlook_1y": _serialize_outlook(report.outlook_1y),
            # 摘要
            "summary_text": report.summary_text,
            # 策略
            "v4_analysis": report.v4_analysis,
            "v2_analysis": report.v2_analysis,
            # 基本面
            "fundamentals": report.fundamentals,
            "fundamental_interpretation": report.fundamental_interpretation,
            "fundamental_score": report.fundamental_score,
            "analyst_data": report.analyst_data,
            # 消息面
            "news_items": report.news_items,
            "news_sentiment_score": report.news_sentiment_score,
            "news_sentiment_label": report.news_sentiment_label,
            "news_insights": report.news_insights,
            "news_themes": report.news_themes,
            # 行動建議
            "actionable_recommendation": report.actionable_recommendation,
            "industry_risks": report.industry_risks,
            "technical_conflicts": report.technical_conflicts,
            "technical_bias": report.technical_bias,
            "peer_context": report.peer_context,
            "valuation": report.valuation,
            # 籌碼面（Gemini R19）
            "institutional_score": report.institutional_score,
            "is_biotech": report.is_biotech,
            "rating_weights": report.rating_weights,
            # Cash Runway（Gemini R20）
            "cash_runway": report.cash_runway,
        }

        return make_serializable(result)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


def _serialize_outlook(outlook) -> dict | None:
    if outlook is None:
        return None
    return {
        "timeframe": outlook.timeframe,
        "bull_case": outlook.bull_case,
        "bull_target": outlook.bull_target,
        "bull_probability": outlook.bull_probability,
        "base_case": outlook.base_case,
        "base_target": outlook.base_target,
        "base_probability": outlook.base_probability,
        "bear_case": outlook.bear_case,
        "bear_target": outlook.bear_target,
        "bear_probability": outlook.bear_probability,
    }
