"""分析報告測試（不需網路的單元測試）"""

import pandas as pd
import numpy as np
import pytest
from analysis.report import (
    _safe,
    _calculate_price_performance,
    _detect_swing_points,
    _get_round_numbers,
    _assess_trend,
    _assess_momentum,
    _assess_volume,
    _assess_volatility,
    _assess_risk,
    _calculate_price_targets,
    _calculate_overall_rating,
    _generate_outlook,
    _assess_fundamentals,
    _assess_news,
    _analyze_news_sentiment,
    _generate_summary,
    FibonacciLevels,
    SupportResistanceLevel,
    OutlookScenario,
)
from analysis.indicators import calculate_all_indicators


class TestSafe:
    def test_normal_value(self):
        assert _safe(42.0) == 42.0

    def test_nan(self):
        assert _safe(float("nan")) == 0.0

    def test_none(self):
        assert _safe(None) == 0.0

    def test_custom_default(self):
        assert _safe(None, default=99.0) == 99.0

    def test_numpy_nan(self):
        assert _safe(np.nan) == 0.0


class TestPricePerformance:
    def test_basic(self, sample_ohlcv):
        result = _calculate_price_performance(sample_ohlcv)
        assert "price_change_1w" in result
        assert "high_52w" in result
        assert "low_52w" in result
        assert result["high_52w"] >= result["low_52w"]

    def test_pct_from_52w(self, sample_ohlcv):
        result = _calculate_price_performance(sample_ohlcv)
        assert result["pct_from_52w_high"] <= 0  # 當前價 ≤ 最高價
        assert result["pct_from_52w_low"] >= 0   # 當前價 ≥ 最低價


class TestSwingPoints:
    def test_basic(self, sample_ohlcv):
        result = _detect_swing_points(sample_ohlcv, window=5)
        assert "swing_highs" in result
        assert "swing_lows" in result
        assert "recent_swing_high" in result
        assert "recent_swing_low" in result

    def test_high_above_low(self, sample_ohlcv):
        result = _detect_swing_points(sample_ohlcv)
        assert result["recent_swing_high"] >= result["recent_swing_low"]


class TestRoundNumbers:
    def test_low_price(self):
        nums = _get_round_numbers(35)
        assert all(n > 0 for n in nums)
        assert any(n == 35 for n in nums)

    def test_high_price(self):
        nums = _get_round_numbers(550)
        assert all(n > 0 for n in nums)
        assert 500 in nums or 550 in nums or 525 in nums

    def test_very_high_price(self):
        nums = _get_round_numbers(2500)
        assert all(n > 0 for n in nums)


class TestAssessTrend:
    def test_uptrend(self, uptrend_df):
        df = calculate_all_indicators(uptrend_df)
        result = _assess_trend(df)
        assert result["trend_direction"] in ("強勢上漲", "溫和上漲", "盤整")
        assert result["ma_alignment"] in ("多頭排列", "空頭排列", "糾結")

    def test_downtrend(self, downtrend_df):
        df = calculate_all_indicators(downtrend_df)
        result = _assess_trend(df)
        assert result["trend_direction"] in ("強勢下跌", "溫和下跌", "盤整")


class TestAssessMomentum:
    def test_basic(self, sample_ohlcv):
        df = calculate_all_indicators(sample_ohlcv)
        result = _assess_momentum(df)
        assert "momentum_status" in result
        assert "adx_value" in result
        assert "rsi_value" in result
        assert result["momentum_status"] in ("強勁多頭", "偏多", "中性", "偏空", "強勁空頭")


class TestAssessVolume:
    def test_basic(self, sample_ohlcv):
        df = calculate_all_indicators(sample_ohlcv)
        result = _assess_volume(df)
        assert "volume_trend" in result
        assert result["volume_trend"] in ("放量", "縮量", "平穩")
        assert "accumulation_distribution" in result
        assert result["accumulation_distribution"] in ("吸籌", "出貨", "中性")


class TestAssessVolatility:
    def test_basic(self, sample_ohlcv):
        df = calculate_all_indicators(sample_ohlcv)
        result = _assess_volatility(df)
        assert "atr_value" in result
        assert "volatility_level" in result
        assert result["volatility_level"] in ("高", "中", "低")
        assert result["atr_value"] >= 0


class TestAssessRisk:
    def test_basic(self, sample_ohlcv):
        df = calculate_all_indicators(sample_ohlcv)
        supports = [SupportResistanceLevel(price=95.0, level_type="support", source="test", strength=2)]
        result = _assess_risk(df, supports)
        assert "max_drawdown_1y" in result
        assert "risk_reward_ratio" in result
        assert result["max_drawdown_1y"] <= 0

    def test_no_supports(self, sample_ohlcv):
        df = calculate_all_indicators(sample_ohlcv)
        result = _assess_risk(df, [])
        assert result["risk_reward_ratio"] >= 0


class TestPriceTargets:
    def _make_fib(self):
        return FibonacciLevels(
            swing_high=120.0, swing_low=80.0,
            direction="uptrend",
            retracement={0.236: 110.56, 0.382: 104.72, 0.5: 100.0, 0.618: 95.28, 0.786: 88.56},
            extension={1.0: 120.0, 1.272: 130.88, 1.618: 144.72, 2.0: 160.0},
        )

    def test_nine_targets(self):
        fib = self._make_fib()
        targets = _calculate_price_targets(
            100.0, fib, 0.02,
            [SupportResistanceLevel(110.0, "resistance", "test", 2)],
            [SupportResistanceLevel(90.0, "support", "test", 2)],
            "溫和上漲", 25.0,
        )
        assert len(targets) == 9  # 3 timeframes * 3 scenarios

    def test_bull_above_bear(self):
        fib = self._make_fib()
        targets = _calculate_price_targets(
            100.0, fib, 0.02,
            [SupportResistanceLevel(110.0, "resistance", "test", 2)],
            [SupportResistanceLevel(90.0, "support", "test", 2)],
            "溫和上漲", 25.0,
        )
        for tf in ["3M", "6M", "1Y"]:
            bull = next(t for t in targets if t.timeframe == tf and t.scenario == "bull")
            bear = next(t for t in targets if t.timeframe == tf and t.scenario == "bear")
            assert bull.target_price > bear.target_price

    def test_analyst_data_blending(self):
        fib = self._make_fib()
        analyst = {"target_mean": 115.0, "target_high": 130.0, "target_low": 85.0, "upside": 0.15}
        targets = _calculate_price_targets(
            100.0, fib, 0.02,
            [SupportResistanceLevel(110.0, "resistance", "test", 2)],
            [SupportResistanceLevel(90.0, "support", "test", 2)],
            "溫和上漲", 25.0,
            analyst_data=analyst,
        )
        # 有法人資料，6M/1Y 的目標價應與無法人資料的不同
        targets_no_analyst = _calculate_price_targets(
            100.0, fib, 0.02,
            [SupportResistanceLevel(110.0, "resistance", "test", 2)],
            [SupportResistanceLevel(90.0, "support", "test", 2)],
            "溫和上漲", 25.0,
        )
        base_6m = next(t for t in targets if t.timeframe == "6M" and t.scenario == "base")
        base_6m_no = next(t for t in targets_no_analyst if t.timeframe == "6M" and t.scenario == "base")
        assert base_6m.target_price != base_6m_no.target_price

    def test_no_nan_targets(self):
        fib = self._make_fib()
        targets = _calculate_price_targets(
            100.0, fib, 0.02, [], [], "盤整", 15.0,
        )
        for t in targets:
            assert not np.isnan(t.target_price)
            assert not np.isinf(t.target_price)
            assert not np.isnan(t.upside_pct)


class TestOverallRating:
    def test_strong_buy(self):
        rating = _calculate_overall_rating(
            "強勢上漲", "強勁多頭", "BUY", 0.5, 45, 3.0,
            base_3m_upside=0.15, fundamental_score=3.0,
        )
        assert rating in ("強力買進", "買進")

    def test_strong_sell(self):
        rating = _calculate_overall_rating(
            "強勢下跌", "強勁空頭", "HOLD", -0.5, 80, 0.3,
            base_3m_upside=-0.10, fundamental_score=-3.0,
        )
        assert rating in ("賣出", "強力賣出")

    def test_neutral(self):
        rating = _calculate_overall_rating(
            "盤整", "中性", "HOLD", 0.0, 50, 1.0,
        )
        assert rating in ("中性", "買進", "賣出")

    def test_valid_ratings(self):
        valid = {"強力買進", "買進", "中性", "賣出", "強力賣出"}
        rating = _calculate_overall_rating(
            "盤整", "中性", "HOLD", 0, 50, 1.0,
        )
        assert rating in valid


class TestGenerateOutlook:
    def _make_targets(self, current=100):
        from analysis.report import PriceTarget
        targets = []
        for tf in ["3M", "6M", "1Y"]:
            targets.append(PriceTarget("bull", current * 1.15, 0.15, "", tf, "中"))
            targets.append(PriceTarget("base", current * 1.05, 0.05, "", tf, "中"))
            targets.append(PriceTarget("bear", current * 0.90, -0.10, "", tf, "中"))
        return targets

    def test_returns_three_outlooks(self):
        targets = self._make_targets()
        o3, o6, o1 = _generate_outlook(
            "溫和上漲", "偏多", targets, "中", 100, 25, 55,
        )
        assert isinstance(o3, OutlookScenario)
        assert isinstance(o6, OutlookScenario)
        assert isinstance(o1, OutlookScenario)

    def test_probabilities_sum_to_100(self):
        targets = self._make_targets()
        o3, o6, o1 = _generate_outlook(
            "溫和上漲", "偏多", targets, "中", 100, 25, 55,
        )
        for o in [o3, o6, o1]:
            total = o.bull_probability + o.base_probability + o.bear_probability
            assert total == 100, f"Probabilities sum to {total}, not 100"

    def test_probabilities_non_negative(self):
        targets = self._make_targets()
        o3, o6, o1 = _generate_outlook(
            "強勢下跌", "強勁空頭", targets, "高", 100, 35, 25,
            fundamental_score=-4.0,
        )
        for o in [o3, o6, o1]:
            assert o.bull_probability >= 5
            assert o.base_probability >= 5
            assert o.bear_probability >= 5

    def test_fundamental_adjusts_probability(self):
        targets = self._make_targets()
        # 高基本面分數
        o3_good, _, _ = _generate_outlook(
            "盤整", "中性", targets, "中", 100, 20, 50,
            fundamental_score=3.0,
        )
        # 低基本面分數
        o3_bad, _, _ = _generate_outlook(
            "盤整", "中性", targets, "中", 100, 20, 50,
            fundamental_score=-3.0,
        )
        # 基本面好的 bull probability 應更高
        assert o3_good.bull_probability >= o3_bad.bull_probability


class TestAssessFundamentals:
    def test_good_fundamentals(self):
        data = {
            "trailing_pe": 10.0,
            "forward_pe": 8.0,
            "earnings_growth": 0.35,
            "revenue_growth": 0.25,
            "return_on_equity": 0.30,
            "profit_margins": 0.35,
            "debt_to_equity": 20,
            "dividend_yield": 0.06,
        }
        result = _assess_fundamentals(data, 100.0)
        assert result["fundamental_score"] > 2.0
        assert "優異" in result["fundamental_interpretation"] or "穩健" in result["fundamental_interpretation"]

    def test_bad_fundamentals(self):
        data = {
            "trailing_pe": 50.0,
            "earnings_growth": -0.20,
            "return_on_equity": 0.05,
            "profit_margins": 0.02,
            "debt_to_equity": 150,
        }
        result = _assess_fundamentals(data, 100.0)
        assert result["fundamental_score"] < 0

    def test_empty_fundamentals(self):
        result = _assess_fundamentals({}, 100.0)
        assert result["fundamental_score"] == 0.0
        assert result["available_count"] == 0

    def test_score_clamped(self):
        data = {
            "trailing_pe": 5.0,
            "forward_pe": 3.0,
            "earnings_growth": 0.80,
            "revenue_growth": 0.50,
            "return_on_equity": 0.50,
            "profit_margins": 0.50,
            "debt_to_equity": 5,
            "dividend_yield": 0.10,
            "target_mean_price": 200.0,
        }
        result = _assess_fundamentals(data, 100.0)
        assert result["fundamental_score"] <= 5.0
        assert result["fundamental_score"] >= -5.0

    def test_dividend_yield_normalization(self):
        """殖利率 > 1 的應被正規化為百分比"""
        data = {"dividend_yield": 3.5}  # 3.5% 以百分比形式
        result = _assess_fundamentals(data, 100.0)
        assert result["metrics"]["dividend_yield"] == "3.50%"  # 正規化後為 0.035

    def test_analyst_data(self):
        data = {"target_mean_price": 120.0, "target_high_price": 150.0, "target_low_price": 90.0}
        result = _assess_fundamentals(data, 100.0)
        assert "analyst_data" in result
        assert result["analyst_data"]["target_mean"] == 120.0
        assert result["analyst_data"]["upside"] == pytest.approx(0.20)


class TestAssessNews:
    def test_trusted_source(self):
        news = [{"title": "Test news", "summary": "content", "source": "Reuters"}]
        result = _assess_news(news)
        assert result[0]["credibility"] == "可信"

    def test_questionable_source(self):
        news = [{"title": "Test news", "summary": "content", "source": "Seeking Alpha"}]
        result = _assess_news(news)
        assert result[0]["credibility"] in ("待確認", "存疑")

    def test_clickbait_penalty(self):
        news = [{"title": "Stock will SKYROCKET 100%!", "summary": "", "source": "Reuters"}]
        result = _assess_news(news)
        # 即使是可信來源，聳動標題也會扣分
        assert result[0]["credibility_score"] < 2

    def test_forum_detection(self):
        news = [{"title": "台積電同學會 | CMoney 股市", "summary": "", "source": "CMoney"}]
        result = _assess_news(news)
        assert result[0]["credibility"] == "存疑"

    def test_empty_news(self):
        result = _assess_news([])
        assert result == []

    def test_google_news_source_matching(self):
        """Google News 台灣來源的 substring matching"""
        news = [{"title": "test", "summary": "", "source": "聯合新聞網"}]
        result = _assess_news(news)
        assert result[0]["credibility"] == "可信"


class TestAnalyzeNewsSentiment:
    def test_positive_sentiment(self):
        news = [
            {"title": "公司營收成長突破新高", "summary": "獲利表現強勁", "credibility_score": 2},
            {"title": "新專利通過認證", "summary": "", "credibility_score": 2},
        ]
        result = _analyze_news_sentiment(news)
        assert result["score"] > 0
        assert result["positive_count"] > 0

    def test_negative_sentiment(self):
        news = [
            {"title": "公司虧損擴大", "summary": "營收衰退", "credibility_score": 2},
            {"title": "裁員風險升高", "summary": "利空消息", "credibility_score": 2},
        ]
        result = _analyze_news_sentiment(news)
        assert result["score"] < 0
        assert result["negative_count"] > 0

    def test_empty_news(self):
        result = _analyze_news_sentiment([])
        assert result["score"] == 0.0
        assert result["label"] == "無資料"

    def test_credibility_weighting(self):
        """可信來源權重較高"""
        # 正面新聞，高可信度
        high_cred = [{"title": "revenue growth", "summary": "profit surge", "credibility_score": 2}]
        # 正面新聞，低可信度
        low_cred = [{"title": "revenue growth", "summary": "profit surge", "credibility_score": 0}]

        result_high = _analyze_news_sentiment(high_cred)
        result_low = _analyze_news_sentiment(low_cred)
        assert result_high["score"] > result_low["score"]

    def test_sentiment_labels_added(self):
        news = [{"title": "growth profit revenue", "summary": "", "credibility_score": 1}]
        _analyze_news_sentiment(news)
        assert "sentiment" in news[0]
        assert news[0]["sentiment"] in ("正面", "負面", "中性")
