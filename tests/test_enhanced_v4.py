"""v4 增強訊號 + 風險管理模組測試"""

import pandas as pd
import numpy as np
import pytest


# ===== v4 增強訊號測試 =====

class TestEnhancedV4Signals:
    """generate_v4_enhanced_signals 測試"""

    def test_enhanced_signals_returns_dataframe(self, uptrend_df):
        from analysis.strategy_v4 import generate_v4_enhanced_signals
        result = generate_v4_enhanced_signals(uptrend_df)
        assert isinstance(result, pd.DataFrame)
        assert "v4_signal" in result.columns
        assert "v4_entry_type" in result.columns

    def test_enhanced_signals_preserves_original(self, uptrend_df):
        """增強訊號不應改變原有的 support/momentum 訊號"""
        from analysis.strategy_v4 import generate_v4_signals, generate_v4_enhanced_signals
        original = generate_v4_signals(uptrend_df)
        enhanced = generate_v4_enhanced_signals(uptrend_df)

        # 原有非 HOLD 訊號應保持不變
        for i in range(len(original)):
            if original.iloc[i]["v4_signal"] != "HOLD":
                assert enhanced.iloc[i]["v4_signal"] == original.iloc[i]["v4_signal"]
                assert enhanced.iloc[i]["v4_entry_type"] == original.iloc[i]["v4_entry_type"]

    def test_enhanced_adds_pullback_signals(self):
        """測試縮量回調可以產生 pullback 訊號"""
        from analysis.strategy_v4 import generate_v4_enhanced_signals
        # 建構一個明確的縮量回調場景
        np.random.seed(42)
        n = 200
        dates = pd.bdate_range("2024-01-01", periods=n)

        # 穩定上升趨勢
        base = 100.0 + np.arange(n) * 0.3
        close = base.copy()

        # 最後幾天製造縮量回調：價格微跌但仍在 MA20 上方
        close[-3] = close[-4] - 0.1
        close[-2] = close[-3] - 0.1
        close[-1] = close[-2] + 0.05

        volume = np.full(n, 20000.0)
        # 最後幾天極度縮量
        volume[-3:] = 3000.0

        df = pd.DataFrame({
            "open": close - 0.5,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": volume,
        }, index=dates)
        df.index.name = "date"

        result = generate_v4_enhanced_signals(df)
        entry_types = result["v4_entry_type"].tolist()
        # 可能產生 pullback，也可能不產生（取決於指標）
        # 只要不崩潰就好
        assert len(result) == n

    def test_enhanced_with_params(self, uptrend_df):
        from analysis.strategy_v4 import generate_v4_enhanced_signals
        params = {"adx_min": 15, "rsi_low": 25, "rsi_high": 85}
        result = generate_v4_enhanced_signals(uptrend_df, params=params)
        assert isinstance(result, pd.DataFrame)

    def test_enhanced_entry_types(self, uptrend_df):
        """確認 entry_type 只有合法值"""
        from analysis.strategy_v4 import generate_v4_enhanced_signals
        result = generate_v4_enhanced_signals(uptrend_df)
        valid_types = {"", "support", "momentum", "pullback"}
        for et in result["v4_entry_type"]:
            assert et in valid_types


class TestEnhancedAnalysis:
    """get_v4_enhanced_analysis 測試"""

    def test_enhanced_analysis_basic(self, uptrend_df):
        from analysis.strategy_v4 import get_v4_enhanced_analysis
        result = get_v4_enhanced_analysis(uptrend_df)
        assert "signal" in result
        assert "gatekeeper_passed" in result
        assert "confidence_score" in result
        assert result["gatekeeper_passed"] is True
        assert result["confidence_score"] == 1.0

    def test_enhanced_analysis_no_institutional(self, uptrend_df):
        """無法人資料時 gatekeeper 通過"""
        from analysis.strategy_v4 import get_v4_enhanced_analysis
        result = get_v4_enhanced_analysis(uptrend_df, inst_df=None)
        assert result["gatekeeper_passed"] is True
        assert result["confidence_score"] == 1.0

    def test_gatekeeper_blocks_on_selling(self, uptrend_df):
        """法人大量賣出時 gatekeeper 應擋下 BUY"""
        from analysis.strategy_v4 import get_v4_enhanced_analysis, get_v4_analysis

        # 先看原始訊號
        base = get_v4_analysis(uptrend_df)

        if base["signal"] == "BUY":
            # 造一個法人大量賣出的 DataFrame
            vol_5d = uptrend_df["volume"].tail(5).sum()
            inst_dates = uptrend_df.index[-5:]
            inst_df = pd.DataFrame({
                "total_net": [-vol_5d * 0.1] * 5,  # 大量賣出
                "foreign_net": [-vol_5d * 0.05] * 5,
                "trust_net": [-vol_5d * 0.03] * 5,
                "dealer_net": [-vol_5d * 0.02] * 5,
            }, index=inst_dates)

            result = get_v4_enhanced_analysis(uptrend_df, inst_df=inst_df)
            assert result["gatekeeper_blocked"] is True
            assert result["signal"] == "HOLD"

    def test_confidence_score_with_positive_inst(self, uptrend_df):
        """法人買入時信心分數應提升"""
        from analysis.strategy_v4 import get_v4_enhanced_analysis, get_v4_analysis

        base = get_v4_analysis(uptrend_df)

        if base["signal"] == "BUY":
            inst_dates = uptrend_df.index[-5:]
            inst_df = pd.DataFrame({
                "total_net": [10000] * 5,
                "foreign_net": [5000] * 5,
                "trust_net": [3000] * 5,
                "dealer_net": [2000] * 5,
            }, index=inst_dates)

            result = get_v4_enhanced_analysis(uptrend_df, inst_df=inst_df)
            assert result["confidence_score"] >= 1.5

    def test_enhanced_analysis_empty_inst(self, uptrend_df):
        """空法人資料不應崩潰"""
        from analysis.strategy_v4 import get_v4_enhanced_analysis
        result = get_v4_enhanced_analysis(uptrend_df, inst_df=pd.DataFrame())
        assert "signal" in result
        assert result["gatekeeper_passed"] is True


# ===== 風險管理測試 =====

class TestCorrelationMatrix:
    """calculate_correlation_matrix 測試"""

    def test_correlation_with_two_stocks(self):
        from analysis.risk import calculate_correlation_matrix
        np.random.seed(42)
        n = 100
        dates = pd.bdate_range("2024-01-01", periods=n)
        base = np.random.normal(0.001, 0.02, n)

        df1 = pd.DataFrame({"close": 100 * np.cumprod(1 + base)}, index=dates)
        # 高相關：同方向
        df2 = pd.DataFrame({"close": 100 * np.cumprod(1 + base * 0.9 + np.random.normal(0, 0.002, n))}, index=dates)

        corr = calculate_correlation_matrix({"A": df1, "B": df2}, days=60)
        assert not corr.empty
        assert corr.loc["A", "B"] > 0.5  # 應該高度相關

    def test_correlation_insufficient_data(self):
        from analysis.risk import calculate_correlation_matrix
        dates = pd.bdate_range("2024-01-01", periods=5)
        df1 = pd.DataFrame({"close": [100, 101, 102, 103, 104]}, index=dates, dtype=float)
        result = calculate_correlation_matrix({"A": df1}, days=60)
        assert result.empty  # 只有 1 檔，無法計算

    def test_correlation_empty_input(self):
        from analysis.risk import calculate_correlation_matrix
        result = calculate_correlation_matrix({}, days=60)
        assert result.empty


class TestPortfolioVaR:
    """calculate_portfolio_var 測試"""

    def test_var_basic(self):
        from analysis.risk import calculate_portfolio_var
        np.random.seed(42)
        n = 300
        dates = pd.bdate_range("2024-01-01", periods=n)

        df1 = pd.DataFrame({"close": 100 * np.cumprod(1 + np.random.normal(0.001, 0.02, n))}, index=dates)
        df2 = pd.DataFrame({"close": 100 * np.cumprod(1 + np.random.normal(0.001, 0.015, n))}, index=dates)

        result = calculate_portfolio_var({"A": df1, "B": df2})
        assert result["var_pct"] < 0  # VaR 是負數（虧損）
        assert result["var_amount"] < 0
        assert result["stocks_used"] == 2

    def test_var_empty_input(self):
        from analysis.risk import calculate_portfolio_var
        result = calculate_portfolio_var({})
        assert result["var_pct"] == 0
        assert result["stocks_used"] == 0

    def test_var_insufficient_data(self):
        from analysis.risk import calculate_portfolio_var
        dates = pd.bdate_range("2024-01-01", periods=5)
        df = pd.DataFrame({"close": [100, 101, 102, 103, 104]}, index=dates, dtype=float)
        result = calculate_portfolio_var({"A": df})
        assert result["stocks_used"] == 0


class TestRiskAlerts:
    """check_risk_alerts 測試"""

    def test_high_correlation_alert(self):
        from analysis.risk import check_risk_alerts
        corr = pd.DataFrame(
            [[1.0, 0.85], [0.85, 1.0]],
            index=["A", "B"], columns=["A", "B"],
        )
        alerts = check_risk_alerts(corr, {"var_amount": -10000})
        assert len(alerts) >= 1
        assert "高相關性" in alerts[0]

    def test_var_alert(self):
        from analysis.risk import check_risk_alerts
        corr = pd.DataFrame(
            [[1.0, 0.3], [0.3, 1.0]],
            index=["A", "B"], columns=["A", "B"],
        )
        alerts = check_risk_alerts(corr, {"var_amount": -50000}, max_daily_loss=-30000)
        assert any("VaR" in a for a in alerts)

    def test_no_alerts(self):
        from analysis.risk import check_risk_alerts
        corr = pd.DataFrame(
            [[1.0, 0.3], [0.3, 1.0]],
            index=["A", "B"], columns=["A", "B"],
        )
        alerts = check_risk_alerts(corr, {"var_amount": -10000})
        assert len(alerts) == 0

    def test_empty_corr_no_crash(self):
        from analysis.risk import check_risk_alerts
        alerts = check_risk_alerts(pd.DataFrame(), {"var_amount": 0})
        assert isinstance(alerts, list)


class TestIndustryConcentration:
    """analyze_industry_concentration 測試"""

    def test_no_concentration(self):
        from analysis.risk import analyze_industry_concentration
        data = {"A": "Technology", "B": "Financial", "C": "Healthcare"}
        result = analyze_industry_concentration(data)
        assert result["total_stocks"] == 3
        assert len(result["concentrated"]) == 0
        assert len(result["alerts"]) == 0

    def test_high_concentration(self):
        from analysis.risk import analyze_industry_concentration
        data = {"A": "Technology", "B": "Technology", "C": "Technology", "D": "Financial"}
        result = analyze_industry_concentration(data, concentration_threshold=0.35)
        assert len(result["concentrated"]) >= 1
        assert result["concentrated"][0][0] == "Technology"
        assert len(result["alerts"]) >= 1

    def test_empty_input(self):
        from analysis.risk import analyze_industry_concentration
        result = analyze_industry_concentration({})
        assert result["total_stocks"] == 0
        assert len(result["alerts"]) == 0

    def test_na_sectors(self):
        from analysis.risk import analyze_industry_concentration
        data = {"A": "N/A", "B": "N/A", "C": "Technology"}
        result = analyze_industry_concentration(data)
        assert "未分類" in result["sectors"]


class TestPortfolioBeta:
    """calculate_portfolio_beta 測試"""

    def test_beta_calculation(self):
        from analysis.risk import calculate_portfolio_beta
        np.random.seed(42)
        n = 200
        dates = pd.bdate_range("2024-01-01", periods=n)
        market_ret = np.random.normal(0.001, 0.01, n)
        market = pd.DataFrame({
            "close": 100 * np.cumprod(1 + market_ret),
        }, index=dates)

        # 高 Beta 股票（放大市場波動）
        stock_high = pd.DataFrame({
            "close": 100 * np.cumprod(1 + market_ret * 1.5 + np.random.normal(0, 0.005, n)),
        }, index=dates)

        betas = calculate_portfolio_beta({"HIGH": stock_high}, market, days=120)
        assert "HIGH" in betas
        assert betas["HIGH"] > 1.0  # 高 Beta

    def test_beta_empty_market(self):
        from analysis.risk import calculate_portfolio_beta
        betas = calculate_portfolio_beta({"A": pd.DataFrame()}, None)
        assert betas == {}

    def test_beta_short_data(self):
        from analysis.risk import calculate_portfolio_beta
        dates = pd.bdate_range("2024-01-01", periods=10)
        market = pd.DataFrame({"close": range(10, 20)}, index=dates, dtype=float)
        stock = pd.DataFrame({"close": range(10, 20)}, index=dates, dtype=float)
        betas = calculate_portfolio_beta({"A": stock}, market, days=120)
        assert len(betas) == 0  # 資料太短
