"""技術指標計算測試"""

import pandas as pd
import numpy as np
import pytest
from analysis.indicators import (
    calculate_ma,
    calculate_rsi,
    calculate_macd,
    calculate_kd,
    calculate_bollinger_bands,
    calculate_volume_analysis,
    calculate_adx,
    calculate_atr,
    calculate_roc,
    calculate_all_indicators,
    compute_true_range,
)


class TestMA:
    def test_basic(self, sample_ohlcv):
        result = calculate_ma(sample_ohlcv)
        assert "ma5" in result.columns
        assert "ma20" in result.columns
        assert "ma60" in result.columns

    def test_ma_values_are_averages(self, sample_ohlcv):
        result = calculate_ma(sample_ohlcv)
        # MA5 最後一筆應等於最後 5 個收盤價的平均
        expected = sample_ohlcv["close"].tail(5).mean()
        assert abs(result["ma5"].iloc[-1] - expected) < 1e-6

    def test_ma_nan_at_start(self, sample_ohlcv):
        result = calculate_ma(sample_ohlcv)
        # MA60 前 59 筆應為 NaN
        assert result["ma60"].iloc[:59].isna().all()
        assert not np.isnan(result["ma60"].iloc[59])

    def test_custom_periods(self, sample_ohlcv):
        result = calculate_ma(sample_ohlcv, periods=[10, 30])
        assert "ma10" in result.columns
        assert "ma30" in result.columns

    def test_minimal_data(self, minimal_df):
        result = calculate_ma(minimal_df)
        assert "ma5" in result.columns
        assert not np.isnan(result["ma5"].iloc[-1])

    def test_flat_price(self, flat_price_df):
        result = calculate_ma(flat_price_df)
        # 所有 MA 都應等於 100
        assert abs(result["ma5"].iloc[-1] - 100.0) < 1e-6
        assert abs(result["ma20"].iloc[-1] - 100.0) < 1e-6


class TestRSI:
    def test_basic(self, sample_ohlcv):
        result = calculate_rsi(sample_ohlcv)
        assert "rsi" in result.columns

    def test_range(self, sample_ohlcv):
        result = calculate_rsi(sample_ohlcv)
        valid = result["rsi"].dropna()
        assert (valid >= 0).all()
        assert (valid <= 100).all()

    def test_flat_price_no_crash(self, flat_price_df):
        """價格不變時 avg_loss=0，不應除零錯誤"""
        result = calculate_rsi(flat_price_df)
        valid = result["rsi"].dropna()
        assert not valid.empty
        # 沒有價格變動時，RSI 應為 100（所有 gain=0, loss=0 → rs = 0/eps → 接近 0 → RSI 接近 50 或 100）
        assert not valid.isna().any()
        assert not np.isinf(valid).any()

    def test_monotonic_up(self):
        """持續上漲時 RSI 應接近 100"""
        n = 30
        dates = pd.bdate_range("2025-01-01", periods=n)
        df = pd.DataFrame({
            "close": np.arange(100, 100 + n, dtype=float),
        }, index=dates)
        result = calculate_rsi(df, period=14)
        valid = result["rsi"].dropna()
        assert valid.iloc[-1] > 95  # 持續上漲應接近 100

    def test_monotonic_down(self):
        """持續下跌時 RSI 應接近 0"""
        n = 30
        dates = pd.bdate_range("2025-01-01", periods=n)
        df = pd.DataFrame({
            "close": np.arange(200, 200 - n, -1, dtype=float),
        }, index=dates)
        result = calculate_rsi(df, period=14)
        valid = result["rsi"].dropna()
        assert valid.iloc[-1] < 5  # 持續下跌應接近 0


class TestMACD:
    def test_basic(self, sample_ohlcv):
        result = calculate_macd(sample_ohlcv)
        assert "macd" in result.columns
        assert "macd_signal" in result.columns
        assert "macd_hist" in result.columns

    def test_hist_equals_diff(self, sample_ohlcv):
        result = calculate_macd(sample_ohlcv)
        diff = result["macd"] - result["macd_signal"]
        assert np.allclose(result["macd_hist"].dropna(), diff.dropna(), atol=1e-10)

    def test_flat_price(self, flat_price_df):
        result = calculate_macd(flat_price_df)
        valid = result["macd"].dropna()
        # 平坦價格時 MACD 應接近 0
        assert abs(valid.iloc[-1]) < 0.01


class TestKD:
    def test_basic(self, sample_ohlcv):
        result = calculate_kd(sample_ohlcv)
        assert "k" in result.columns
        assert "d" in result.columns

    def test_range(self, sample_ohlcv):
        result = calculate_kd(sample_ohlcv)
        k_valid = result["k"].dropna()
        d_valid = result["d"].dropna()
        assert (k_valid >= 0).all() and (k_valid <= 100).all()
        assert (d_valid >= 0).all() and (d_valid <= 100).all()

    def test_flat_price_no_crash(self, flat_price_df):
        """價格不變時 high_max - low_min = 0，不應除零錯誤"""
        result = calculate_kd(flat_price_df)
        k_valid = result["k"].dropna()
        assert not k_valid.empty
        assert not np.isinf(k_valid).any()


class TestBollinger:
    def test_basic(self, sample_ohlcv):
        result = calculate_bollinger_bands(sample_ohlcv)
        assert "bb_upper" in result.columns
        assert "bb_middle" in result.columns
        assert "bb_lower" in result.columns

    def test_upper_above_lower(self, sample_ohlcv):
        result = calculate_bollinger_bands(sample_ohlcv)
        valid_mask = result["bb_upper"].notna()
        assert (result.loc[valid_mask, "bb_upper"] >= result.loc[valid_mask, "bb_lower"]).all()

    def test_flat_price_bands_equal(self, flat_price_df):
        result = calculate_bollinger_bands(flat_price_df)
        valid = result["bb_upper"].dropna()
        # 平坦價格時 std=0，上下軌應相同或極接近
        assert abs(valid.iloc[-1] - result["bb_lower"].dropna().iloc[-1]) < 1e-6


class TestVolumeAnalysis:
    def test_basic(self, sample_ohlcv):
        result = calculate_volume_analysis(sample_ohlcv)
        assert "volume_ma5" in result.columns
        assert "volume_ma20" in result.columns
        assert "volume_ratio" in result.columns

    def test_zero_volume_no_crash(self, zero_volume_df):
        """成交量全零時不應除零錯誤"""
        result = calculate_volume_analysis(zero_volume_df)
        # volume_ratio = 0 / 0 → 應為 NaN 而非 inf
        assert not np.isinf(result["volume_ratio"].dropna()).any()


class TestADX:
    def test_basic(self, sample_ohlcv):
        result = calculate_adx(sample_ohlcv)
        assert "adx" in result.columns
        assert "plus_di" in result.columns
        assert "minus_di" in result.columns

    def test_range(self, sample_ohlcv):
        result = calculate_adx(sample_ohlcv)
        valid = result["adx"].dropna()
        assert (valid >= 0).all()

    def test_flat_price_no_crash(self, flat_price_df):
        """價格不變時 DI 均為 0，不應除零錯誤（結果可為 NaN 但不可為 inf）"""
        result = calculate_adx(flat_price_df)
        # 平坦價格 ADX 可能全為 NaN（無波動無法計算），但不應有 inf
        adx_vals = result["adx"].replace([np.inf, -np.inf], np.nan)
        assert (adx_vals.isna() | (adx_vals >= 0)).all()

    def test_uptrend_plus_di_higher(self, uptrend_df):
        result = calculate_adx(uptrend_df)
        # 上升趨勢中 +DI 通常 > -DI
        assert result["plus_di"].iloc[-1] > result["minus_di"].iloc[-1]


class TestComputeTrueRange:
    def test_returns_series(self, sample_ohlcv):
        tr = compute_true_range(sample_ohlcv)
        assert isinstance(tr, pd.Series)
        assert len(tr) == len(sample_ohlcv)

    def test_positive_values(self, sample_ohlcv):
        tr = compute_true_range(sample_ohlcv)
        valid = tr.dropna()
        assert (valid >= 0).all()

    def test_flat_price_near_zero(self, flat_price_df):
        tr = compute_true_range(flat_price_df)
        valid = tr.dropna()
        assert valid.iloc[-1] < 0.01

    def test_first_row_uses_high_minus_low(self, sample_ohlcv):
        """First row has no prev_close, so TR = H - L (others are NaN)."""
        tr = compute_true_range(sample_ohlcv)
        expected_first = sample_ohlcv["high"].iloc[0] - sample_ohlcv["low"].iloc[0]
        # First row: H-L is valid, but |H-prevC| and |L-prevC| are NaN
        # max(H-L, NaN, NaN) = H-L via pandas
        assert abs(tr.iloc[0] - expected_first) < 1e-6


class TestATR:
    def test_basic(self, sample_ohlcv):
        result = calculate_atr(sample_ohlcv)
        assert "atr" in result.columns
        assert "atr_pct" in result.columns

    def test_positive(self, sample_ohlcv):
        result = calculate_atr(sample_ohlcv)
        valid = result["atr"].dropna()
        assert (valid >= 0).all()

    def test_flat_price(self, flat_price_df):
        result = calculate_atr(flat_price_df)
        valid = result["atr"].dropna()
        # 平坦價格時 ATR 應接近 0（但第一筆有 NaN diff）
        assert valid.iloc[-1] < 0.01

    def test_sma_method(self, sample_ohlcv):
        """SMA method should use simple rolling mean, not EMA."""
        result_sma = calculate_atr(sample_ohlcv, method="sma")
        result_ema = calculate_atr(sample_ohlcv, method="ema")
        # Both produce ATR columns but values differ
        assert "atr" in result_sma.columns
        sma_val = result_sma["atr"].dropna().iloc[-1]
        ema_val = result_ema["atr"].dropna().iloc[-1]
        # They should be different (unless data is flat/trivial)
        # Both should be positive
        assert sma_val > 0
        assert ema_val > 0

    def test_sma_matches_manual_rolling(self, sample_ohlcv):
        """SMA ATR should match manual TR.rolling(14).mean()."""
        tr = compute_true_range(sample_ohlcv)
        expected = tr.rolling(14).mean()
        result = calculate_atr(sample_ohlcv, period=14, method="sma")
        actual = result["atr"]
        # Compare non-NaN values
        mask = expected.notna() & actual.notna()
        np.testing.assert_allclose(actual[mask].values, expected[mask].values, rtol=1e-10)

    def test_custom_period(self, sample_ohlcv):
        result_7 = calculate_atr(sample_ohlcv, period=7, method="sma")
        result_14 = calculate_atr(sample_ohlcv, period=14, method="sma")
        # Period 7 should have fewer NaN at the start
        assert result_7["atr"].notna().sum() > result_14["atr"].notna().sum()

    def test_min_periods(self, sample_ohlcv):
        result = calculate_atr(sample_ohlcv, period=14, method="sma", min_periods=7)
        # Should have ATR values earlier than default min_periods=14
        result_default = calculate_atr(sample_ohlcv, period=14, method="sma")
        assert result["atr"].notna().sum() >= result_default["atr"].notna().sum()

    def test_atr_pct_ratio(self, sample_ohlcv):
        """atr_pct should equal atr / close."""
        result = calculate_atr(sample_ohlcv)
        valid = result.dropna(subset=["atr", "atr_pct"])
        expected_pct = valid["atr"] / valid["close"]
        np.testing.assert_allclose(valid["atr_pct"].values, expected_pct.values, rtol=1e-10)


class TestROC:
    def test_basic(self, sample_ohlcv):
        result = calculate_roc(sample_ohlcv)
        assert "roc" in result.columns

    def test_value(self, sample_ohlcv):
        result = calculate_roc(sample_ohlcv, period=1)
        # 1-period ROC 應等於百分比變化 * 100
        expected = sample_ohlcv["close"].pct_change() * 100
        np.testing.assert_allclose(
            result["roc"].dropna().values,
            expected.dropna().values,
            rtol=1e-10,
        )


class TestCalculateAllIndicators:
    def test_all_columns_present(self, sample_ohlcv):
        result = calculate_all_indicators(sample_ohlcv)
        expected_cols = [
            "ma5", "ma20", "ma60", "rsi", "macd", "macd_signal", "macd_hist",
            "k", "d", "bb_upper", "bb_middle", "bb_lower",
            "volume_ma5", "volume_ma20", "volume_ratio",
            "atr", "atr_pct", "adx", "plus_di", "minus_di", "roc",
        ]
        for col in expected_cols:
            assert col in result.columns, f"Missing column: {col}"

    def test_no_inf_values(self, sample_ohlcv):
        result = calculate_all_indicators(sample_ohlcv)
        for col in result.select_dtypes(include=[np.number]).columns:
            valid = result[col].dropna()
            assert not np.isinf(valid).any(), f"Inf found in column: {col}"

    def test_flat_price_no_crash(self, flat_price_df):
        """綜合邊界測試：平坦價格不應有任何 inf"""
        result = calculate_all_indicators(flat_price_df)
        for col in result.select_dtypes(include=[np.number]).columns:
            valid = result[col].dropna()
            assert not np.isinf(valid).any(), f"Inf found in column: {col}"

    def test_zero_volume_no_crash(self, zero_volume_df):
        """綜合邊界測試：零成交量不應有任何 inf"""
        result = calculate_all_indicators(zero_volume_df)
        for col in result.select_dtypes(include=[np.number]).columns:
            valid = result[col].dropna()
            assert not np.isinf(valid).any(), f"Inf found in column: {col}"

    def test_preserves_original_columns(self, sample_ohlcv):
        result = calculate_all_indicators(sample_ohlcv)
        for col in ["open", "high", "low", "close", "volume"]:
            assert col in result.columns
