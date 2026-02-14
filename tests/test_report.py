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
    _get_sector_profile,
    _SECTOR_PROFILES,
    _assess_news,
    _analyze_news_sentiment,
    _generate_summary,
    _resolve_technical_conflicts,
    _assess_industry_risks,
    _extract_news_insights,
    _generate_actionable_recommendation,
    _get_peer_context,
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
        analyst = {"target_mean": 115.0, "target_high": 130.0, "target_low": 85.0, "upside": 0.15, "num_analysts": 5}
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

    def test_biotech_skips_pe_roe_margin(self):
        """生技股：PE/ROE/淨利率負值不扣分"""
        data = {
            "trailing_pe": 50.0,   # 高 PE → default 會扣 1.0
            "return_on_equity": -0.10,  # 負 ROE → default 會扣 0.5
            "profit_margins": -2.0,     # 負淨利率 → default 會扣 0.5
        }
        result_default = _assess_fundamentals(data, 100.0)
        result_biotech = _assess_fundamentals(data, 100.0, sector="Healthcare", industry="Biotechnology")
        # 生技版分數應該更高（因為不扣分）
        assert result_biotech["fundamental_score"] > result_default["fundamental_score"]
        assert "生技新藥業" in result_biotech["fundamental_interpretation"]

    def test_biotech_still_rewards_high_roe(self):
        """生技股：ROE 高仍加分"""
        data = {"return_on_equity": 0.30}
        result = _assess_fundamentals(data, 100.0, sector="Healthcare", industry="Biotechnology")
        assert result["fundamental_score"] > 0

    def test_financial_skips_debt(self):
        """金融業：高負債不扣分"""
        data = {"debt_to_equity": 200}
        result_default = _assess_fundamentals(data, 100.0)
        result_financial = _assess_fundamentals(data, 100.0, sector="Financial Services")
        assert result_financial["fundamental_score"] > result_default["fundamental_score"]
        assert "金融/營建業" in result_financial["fundamental_interpretation"]

    def test_real_estate_skips_debt(self):
        """營建業：也走 financial profile"""
        data = {"debt_to_equity": 150}
        result = _assess_fundamentals(data, 100.0, sector="Real Estate")
        # 不應扣負債分
        assert result["fundamental_score"] >= 0

    def test_traditional_dividend_boost(self):
        """傳產/公用事業：殖利率加權提高"""
        data = {"dividend_yield": 0.04}
        result_default = _assess_fundamentals(data, 100.0)
        result_trad = _assess_fundamentals(data, 100.0, sector="Utilities")
        assert result_trad["fundamental_score"] > result_default["fundamental_score"]

    def test_technology_uses_default(self):
        """科技業走 default，分數與不帶 sector 時相同"""
        data = {
            "trailing_pe": 15.0,
            "return_on_equity": 0.20,
            "profit_margins": 0.10,
            "debt_to_equity": 50,
        }
        result_no_sector = _assess_fundamentals(data, 100.0)
        result_tech = _assess_fundamentals(data, 100.0, sector="Technology")
        assert result_tech["fundamental_score"] == result_no_sector["fundamental_score"]

    def test_healthcare_non_biotech_uses_default(self):
        """Healthcare 但非 biotech industry → default"""
        data = {"trailing_pe": 50.0, "return_on_equity": 0.05}
        result = _assess_fundamentals(data, 100.0, sector="Healthcare", industry="Medical Devices")
        # Should still penalize high PE (default profile)
        assert result["fundamental_score"] < 0


class TestGetSectorProfile:
    def test_biotech(self):
        profile = _get_sector_profile("Healthcare", "Biotechnology")
        assert profile["skip_pe"] is True
        assert profile["skip_roe"] is True

    def test_healthcare_non_biotech(self):
        profile = _get_sector_profile("Healthcare", "Medical Devices")
        assert profile["skip_pe"] is False  # falls to default

    def test_financial(self):
        profile = _get_sector_profile("Financial Services", "Banks")
        assert profile["skip_de"] is True

    def test_real_estate(self):
        profile = _get_sector_profile("Real Estate", "REIT")
        assert profile["skip_de"] is True

    def test_utilities(self):
        profile = _get_sector_profile("Utilities", "Electric Utilities")
        assert profile == _SECTOR_PROFILES["traditional"]

    def test_technology_default(self):
        profile = _get_sector_profile("Technology", "Semiconductors")
        assert profile == _SECTOR_PROFILES["default"]

    def test_empty_strings(self):
        profile = _get_sector_profile("", "")
        assert profile == _SECTOR_PROFILES["default"]


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


# ============================================================
# 新增測試：技術面矛盾解決
# ============================================================

class TestResolveTechnicalConflicts:
    """測試 _resolve_technical_conflicts"""

    def _make_momentum(self, macd_val=1.0, macd_sig=0.5, macd_hist=0.5,
                       k=60, d=55, rsi=55, adx=25):
        return {
            "adx_value": adx, "rsi_value": rsi,
            "macd_value": macd_val, "macd_signal_value": macd_sig,
            "macd_histogram": macd_hist,
            "macd_interpretation": "多頭格局" if macd_val > macd_sig else "空頭格局",
            "kd_interpretation": "黃金交叉" if k > d else "死亡交叉",
            "k_value": k, "d_value": d,
            "momentum_status": "偏多",
        }

    def _make_trend(self, direction="盤整", alignment="糾結"):
        return {"trend_direction": direction, "ma_alignment": alignment, "trend_strength": "中"}

    def _make_risk(self, rr=1.0):
        return {"risk_reward_ratio": rr, "max_drawdown_1y": -0.1, "current_drawdown": -0.05,
                "key_risk_level": 90.0, "risk_interpretation": ""}

    def _make_df(self, n=60):
        np.random.seed(42)
        dates = pd.bdate_range("2025-01-01", periods=n)
        close = 100.0 + np.random.normal(0, 1, n).cumsum()
        close = np.maximum(close, 50)
        df = pd.DataFrame({
            "open": close, "high": close + 1, "low": close - 1,
            "close": close, "volume": np.random.randint(5000, 50000, n).astype(float),
            "macd_hist": np.random.normal(0.1, 0.05, n),
        }, index=dates)
        return df

    def test_macd_vs_kd_conflict(self):
        """MACD 多頭 + KD 死叉 → 有衝突"""
        mom = self._make_momentum(macd_val=2.0, macd_sig=1.0, k=40, d=55)
        result = _resolve_technical_conflicts(mom, self._make_trend(), self._make_risk(), self._make_df())
        assert len(result["conflicts"]) > 0
        assert any("MACD" in c and "KD" in c for c in result["conflicts"])

    def test_no_conflict_all_bullish(self):
        """全部指標偏多 → 無衝突"""
        mom = self._make_momentum(macd_val=2.0, macd_sig=1.0, k=70, d=55, rsi=60, adx=30)
        result = _resolve_technical_conflicts(
            mom, self._make_trend("溫和上漲", "多頭排列"), self._make_risk(2.0), self._make_df())
        # 不保證零衝突（量價可能有），但 MACD/KD 不應衝突
        macd_kd_conflicts = [c for c in result["conflicts"] if "MACD" in c and "KD" in c]
        assert len(macd_kd_conflicts) == 0

    def test_low_rr_conflict(self):
        """RR < 0.5 → 標記風險報酬比衝突"""
        mom = self._make_momentum()
        result = _resolve_technical_conflicts(mom, self._make_trend(), self._make_risk(0.3), self._make_df())
        assert any("風險報酬比" in c for c in result["conflicts"])

    def test_bias_with_conflicts(self):
        """有衝突時偏向應包含「謹慎」"""
        mom = self._make_momentum(macd_val=2.0, macd_sig=1.0, k=40, d=55)
        result = _resolve_technical_conflicts(mom, self._make_trend(), self._make_risk(0.4), self._make_df())
        assert "謹慎" in result["technical_bias"] or "觀望" in result["technical_bias"]

    def test_rsi_overbought_with_bullish_ma(self):
        """均線多頭 + RSI 超買 → 有衝突"""
        mom = self._make_momentum(rsi=75, k=70, d=65)
        result = _resolve_technical_conflicts(
            mom, self._make_trend("溫和上漲", "多頭排列"), self._make_risk(), self._make_df())
        assert any("RSI" in c and "超買" in c for c in result["conflicts"])

    def test_returns_dict(self):
        """回傳格式正確"""
        mom = self._make_momentum()
        result = _resolve_technical_conflicts(mom, self._make_trend(), self._make_risk(), self._make_df())
        assert "conflicts" in result
        assert "technical_bias" in result
        assert isinstance(result["conflicts"], list)
        assert isinstance(result["technical_bias"], str)


# ============================================================
# 新增測試：產業特定風險
# ============================================================

class TestIndustryRisks:
    """測試 _assess_industry_risks"""

    def _vol(self, atr_pct=0.02):
        return {"atr_pct": atr_pct, "atr_value": 2.0, "volatility_level": "中"}

    def _volume(self, ratio=1.0):
        return {"volume_ratio": ratio, "volume_trend": "平穩", "accumulation_distribution": "中性"}

    def test_biotech_has_clinical_risk(self):
        """生技股應有臨床試驗風險"""
        risks = _assess_industry_risks(
            "Healthcare", "Biotechnology",
            {"operating_margins": -3.0, "revenue_growth": -0.30},
            self._vol(0.05), self._volume(), 50.0,
            {"market_cap": 3e9},
        )
        risk_names = [r["risk"] for r in risks]
        assert "臨床試驗與法規審批風險" in risk_names

    def test_biotech_cash_burn(self):
        """生技股營業利益率 < -100% → 高現金燃燒率"""
        risks = _assess_industry_risks(
            "Healthcare", "Biotechnology",
            {"operating_margins": -3.0},
            self._vol(), self._volume(), 50.0,
            {"market_cap": 3e9},
        )
        risk_names = [r["risk"] for r in risks]
        assert "高現金燃燒率" in risk_names

    def test_biotech_revenue_decline(self):
        """生技股營收衰退 > 20% → 營收大幅衰退風險"""
        risks = _assess_industry_risks(
            "Healthcare", "Biotechnology",
            {"revenue_growth": -0.35},
            self._vol(), self._volume(), 50.0,
            {"market_cap": 5e9},
        )
        risk_names = [r["risk"] for r in risks]
        assert "營收大幅衰退" in risk_names

    def test_financial_has_rate_risk(self):
        """金融業應有利率敏感度風險"""
        risks = _assess_industry_risks(
            "Financial Services", "Banks", {},
            self._vol(0.01), self._volume(), 100.0,
            {"market_cap": 100e9},
        )
        risk_names = [r["risk"] for r in risks]
        assert "利率敏感度風險" in risk_names

    def test_small_cap_risk(self):
        """市值 < 50 億 → 小型股風險"""
        risks = _assess_industry_risks(
            "Technology", "Software", {},
            self._vol(), self._volume(), 30.0,
            {"market_cap": 2e9},
        )
        risk_names = [r["risk"] for r in risks]
        assert "小型股風險" in risk_names

    def test_high_volatility_risk(self):
        """ATR > 5% → 極高波動"""
        risks = _assess_industry_risks(
            "Technology", "Software", {},
            self._vol(0.06), self._volume(), 100.0,
            {"market_cap": 50e9},
        )
        risk_names = [r["risk"] for r in risks]
        assert "極高波動度" in risk_names

    def test_low_liquidity_risk(self):
        """量能比 < 0.5 → 流動性不足"""
        risks = _assess_industry_risks(
            "Technology", "Software", {},
            self._vol(), self._volume(0.3), 100.0,
            {"market_cap": 50e9},
        )
        risk_names = [r["risk"] for r in risks]
        assert "流動性不足" in risk_names

    def test_empty_fundamentals(self):
        """空基本面不 crash"""
        risks = _assess_industry_risks(
            "", "", {}, self._vol(), self._volume(), 100.0, {"market_cap": 0},
        )
        assert isinstance(risks, list)

    def test_sorted_by_severity(self):
        """回傳應依 severity 排序（high 在前）"""
        risks = _assess_industry_risks(
            "Healthcare", "Biotechnology",
            {"operating_margins": -3.0, "revenue_growth": -0.35},
            self._vol(0.06), self._volume(0.3), 50.0,
            {"market_cap": 2e9},
        )
        severities = [r["severity"] for r in risks]
        order = {"high": 0, "medium": 1, "low": 2}
        assert severities == sorted(severities, key=lambda s: order.get(s, 2))


# ============================================================
# 新增測試：消息面洞察
# ============================================================

class TestExtractNewsInsights:
    """測試 _extract_news_insights"""

    def test_contradiction_detection(self):
        """新聞說營收雙增但實際營收衰退 → 偵測矛盾"""
        news = [
            {"title": "亞果生醫拚營收、獲利雙增", "summary": "", "source": "工商時報",
             "credibility_score": 2, "credibility": "可信"},
        ]
        result = _extract_news_insights(news, {"revenue_growth": -0.37}, "亞果生醫")
        assert len(result["contradictions"]) > 0
        assert "營收" in result["contradictions"][0]

    def test_no_contradiction_when_data_matches(self):
        """營收正成長 + 正面新聞 → 無矛盾"""
        news = [
            {"title": "公司營收成長創新高", "summary": "", "source": "經濟日報",
             "credibility_score": 2, "credibility": "可信"},
        ]
        result = _extract_news_insights(news, {"revenue_growth": 0.25}, "測試公司")
        assert len(result["contradictions"]) == 0

    def test_theme_classification(self):
        """新聞應被分到正確主題"""
        news = [
            {"title": "獲日本專利認證", "summary": "", "source": "經濟日報",
             "credibility_score": 2, "credibility": "可信"},
            {"title": "公司營收成長 30%", "summary": "", "source": "工商時報",
             "credibility_score": 2, "credibility": "可信"},
        ]
        result = _extract_news_insights(news, {}, "測試公司")
        assert "專利技術" in result["themes"]
        assert "營收財報" in result["themes"]

    def test_low_quality_filtered(self):
        """低品質新聞（credibility_score <= 0）不納入分析"""
        news = [
            {"title": "同學會討論", "summary": "", "source": "CMoney",
             "credibility_score": 0, "credibility": "存疑"},
            {"title": "正規新聞", "summary": "", "source": "經濟日報",
             "credibility_score": 2, "credibility": "可信"},
        ]
        result = _extract_news_insights(news, {}, "測試公司")
        assert result["credible_count"] == 1
        assert result["low_quality_count"] == 1

    def test_empty_news(self):
        """空新聞不 crash"""
        result = _extract_news_insights([], {}, "測試")
        assert result["credible_count"] == 0
        assert result["contradictions"] == []
        assert result["themes"] == {}

    def test_forum_note(self):
        """有低品質新聞時應產生 forum_note"""
        news = [
            {"title": "討論文", "summary": "", "source": "CMoney", "credibility_score": -1, "credibility": "存疑"},
        ]
        result = _extract_news_insights(news, {}, "測試")
        assert "低品質" in result["forum_note"]


# ============================================================
# 新增測試：行動建議
# ============================================================

class TestActionableRecommendation:
    """測試 _generate_actionable_recommendation"""

    def _make_args(self, rating="中性", rr=1.0, trend="盤整", rsi=50, atr_pct=0.03,
                   tech_bias="中性", high_risk_count=0):
        risk = {"risk_reward_ratio": rr, "max_drawdown_1y": -0.1}
        momentum = {"rsi_value": rsi, "adx_value": 22}
        trend_data = {"trend_direction": trend, "ma_alignment": "糾結"}
        vol = {"atr_pct": atr_pct, "atr_value": 3.0}
        supports = [SupportResistanceLevel(90.0, "support", "test", 2),
                    SupportResistanceLevel(85.0, "support", "test", 1)]
        resistances = [SupportResistanceLevel(110.0, "resistance", "test", 2),
                       SupportResistanceLevel(120.0, "resistance", "test", 1)]
        industry_risks = [{"risk": "test", "severity": "high", "detail": "test"}] * high_risk_count
        return (rating, risk, momentum, trend_data, vol,
                supports, resistances, 100.0, industry_risks, tech_bias, {})

    def test_buy_scenario(self):
        """買進評等 → BUY action"""
        args = self._make_args(rating="買進", rr=2.0, trend="溫和上漲")
        result = _generate_actionable_recommendation(*args)
        assert result["action"] == "BUY"
        assert result["entry_low"] is not None
        assert result["stop_loss"] is not None
        assert result["take_profit_t1"] is not None

    def test_sell_scenario(self):
        """賣出 + 低 RR → AVOID"""
        args = self._make_args(rating="賣出", rr=0.3)
        result = _generate_actionable_recommendation(*args)
        assert result["action"] == "AVOID"

    def test_sell_with_ok_rr(self):
        """賣出 + 正常 RR → SELL"""
        args = self._make_args(rating="賣出", rr=1.5)
        result = _generate_actionable_recommendation(*args)
        assert result["action"] == "SELL"

    def test_neutral_low_rr_avoid(self):
        """中性 + 低 RR → AVOID"""
        args = self._make_args(rating="中性", rr=0.4)
        result = _generate_actionable_recommendation(*args)
        assert result["action"] == "AVOID"

    def test_hold_scenario(self):
        """中性 + 正常 RR → HOLD"""
        args = self._make_args(rating="中性", rr=1.2, tech_bias="中性")
        result = _generate_actionable_recommendation(*args)
        assert result["action"] == "HOLD"

    def test_position_scales_with_volatility(self):
        """部位隨波動度縮放"""
        args_high = self._make_args(rating="買進", rr=2.0, atr_pct=0.06, trend="溫和上漲")
        args_low = self._make_args(rating="買進", rr=2.0, atr_pct=0.015, trend="溫和上漲")
        result_high = _generate_actionable_recommendation(*args_high)
        result_low = _generate_actionable_recommendation(*args_low)
        assert "3-5%" in result_high["position_pct"]
        assert "8-12%" in result_low["position_pct"]

    def test_thesis_not_empty(self):
        """所有場景都有投資論點"""
        for rating in ["強力買進", "買進", "中性", "賣出", "強力賣出"]:
            args = self._make_args(rating=rating)
            result = _generate_actionable_recommendation(*args)
            assert len(result["thesis"]) > 0

    def test_triggers_not_empty(self):
        """觸發條件不應為空"""
        for action_type in [("買進", 2.0, "溫和上漲"), ("中性", 1.0, "盤整"), ("賣出", 0.3, "溫和下跌")]:
            args = self._make_args(rating=action_type[0], rr=action_type[1], trend=action_type[2])
            result = _generate_actionable_recommendation(*args)
            assert len(result["trigger_conditions"]) > 0

    def test_hold_avoid_no_entry(self):
        """HOLD/AVOID 不應有進場價"""
        args = self._make_args(rating="中性", rr=1.2)
        result = _generate_actionable_recommendation(*args)
        if result["action"] in ("HOLD", "AVOID"):
            assert result["entry_low"] is None


# ============================================================
# 新增測試：產業基準對照
# ============================================================

class TestPeerContext:
    """測試 _get_peer_context"""

    def test_biotech_context(self):
        """生技股應回傳生技產業基準"""
        result = _get_peer_context("Healthcare", "Biotechnology",
                                   {"price_to_book": 7.0}, 50.0, {})
        assert result["industry_label"] == "台灣生技業"
        assert "毛利率" in result["key_metrics"]

    def test_financial_context(self):
        """金融業基準"""
        result = _get_peer_context("Financial Services", "Banks",
                                   {"trailing_pe": 10.0, "return_on_equity": 0.12}, 30.0, {})
        assert result["industry_label"] == "台灣金融業"

    def test_semiconductor_context(self):
        """半導體業基準"""
        result = _get_peer_context("Technology", "Semiconductors",
                                   {"trailing_pe": 25.0}, 500.0, {})
        assert result["industry_label"] == "台灣半導體業"

    def test_positioning_with_high_pb(self):
        """高 P/B 生技股 → 估值偏貴"""
        result = _get_peer_context("Healthcare", "Biotechnology",
                                   {"price_to_book": 8.0}, 50.0, {})
        assert any("偏貴" in p or "溢價" in p for p in result["positioning"])

    def test_empty_fundamentals(self):
        """空基本面 → positioning 為空但不 crash"""
        result = _get_peer_context("Technology", "Software", {}, 100.0, {})
        assert isinstance(result["positioning"], list)

    def test_default_for_unknown_sector(self):
        """未知產業 → 一般企業基準"""
        result = _get_peer_context("Unknown", "Unknown", {}, 100.0, {})
        assert result["industry_label"] == "台股一般企業"


# ============================================================
# 新增測試：評等邏輯修正
# ============================================================

class TestOverallRatingRRFix:
    """測試 _calculate_overall_rating 的 RR 矛盾修正"""

    def test_low_rr_not_neutral(self):
        """RR < 0.5 不應輕易給「中性」，應降級"""
        # 使用偏弱的場景 + 低 RR
        rating = _calculate_overall_rating(
            "盤整", "偏多", "HOLD", 0.0, 55, 0.3,
            base_3m_upside=0.05, fundamental_score=0.0,
        )
        # 低 RR 應讓評等至少不是「買進」
        assert rating != "強力買進"
        assert rating != "買進"

    def test_very_low_rr_penalized_harder(self):
        """RR < 0.3 應比 RR 0.5 懲罰更重"""
        rating_03 = _calculate_overall_rating(
            "盤整", "中性", "HOLD", 0.0, 50, 0.3,
        )
        rating_08 = _calculate_overall_rating(
            "盤整", "中性", "HOLD", 0.0, 50, 0.8,
        )
        # 低 RR 的評等應 <= 高 RR 的評等
        order = {"強力買進": 4, "買進": 3, "中性": 2, "賣出": 1, "強力賣出": 0}
        assert order[rating_03] <= order[rating_08]
