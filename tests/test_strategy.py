"""策略訊號產生測試"""

import pandas as pd
import numpy as np
import pytest
from analysis.strategy import (
    _score_ma,
    _score_rsi,
    _score_macd,
    _score_kd,
    _score_bb,
    _score_volume,
    generate_signals,
    get_latest_analysis,
)


class TestScoreMA:
    def test_bullish(self):
        row = pd.Series({"ma5": 110, "ma20": 105, "ma60": 100})
        assert _score_ma(row) == 1.0

    def test_bearish(self):
        row = pd.Series({"ma5": 90, "ma20": 95, "ma60": 100})
        assert _score_ma(row) == -1.0

    def test_mixed(self):
        row = pd.Series({"ma5": 105, "ma20": 100, "ma60": 103})
        assert _score_ma(row) == 0.0  # ma5>ma20 (+0.5), ma20<ma60 (-0.5)

    def test_nan_returns_zero(self):
        row = pd.Series({"ma5": 100, "ma20": np.nan, "ma60": 90})
        assert _score_ma(row) == 0.0


class TestScoreRSI:
    def test_oversold(self):
        row = pd.Series({"rsi": 20})
        assert _score_rsi(row) == 1.0

    def test_overbought(self):
        row = pd.Series({"rsi": 80})
        assert _score_rsi(row) == -1.0

    def test_neutral(self):
        row = pd.Series({"rsi": 50})
        assert _score_rsi(row) == 0.0

    def test_nan_returns_zero(self):
        row = pd.Series({"rsi": np.nan})
        assert _score_rsi(row) == 0.0

    def test_interpolation(self):
        # rsi=40 is between 30 and 50: (50-40)/20 = 0.5
        row = pd.Series({"rsi": 40})
        assert abs(_score_rsi(row) - 0.5) < 1e-6

    def test_boundary_30(self):
        row = pd.Series({"rsi": 30})
        assert abs(_score_rsi(row) - 1.0) < 1e-6

    def test_boundary_70(self):
        row = pd.Series({"rsi": 70})
        assert abs(_score_rsi(row) - (-1.0)) < 1e-6


class TestScoreMACD:
    def test_bullish(self):
        row = pd.Series({"macd": 1.0, "macd_signal": 0.5, "macd_hist": 0.5})
        assert _score_macd(row) == 1.0

    def test_bearish(self):
        row = pd.Series({"macd": -1.0, "macd_signal": -0.5, "macd_hist": -0.5})
        assert _score_macd(row) == -1.0

    def test_nan_returns_zero(self):
        row = pd.Series({"macd": np.nan, "macd_signal": 0, "macd_hist": 0})
        assert _score_macd(row) == 0.0


class TestScoreKD:
    def test_golden_cross_oversold(self):
        row = pd.Series({"k": 15, "d": 10})
        assert _score_kd(row) == 1.0  # k>d (+0.5) + k<20 (+0.5)

    def test_death_cross_overbought(self):
        row = pd.Series({"k": 85, "d": 90})
        assert _score_kd(row) == -1.0  # k<d (-0.5) + k>80 (-0.5)


class TestScoreBB:
    def test_at_lower_band(self):
        row = pd.Series({"close": 90, "bb_upper": 110, "bb_lower": 90, "bb_middle": 100})
        assert _score_bb(row) == 1.0  # position=0 → score=1

    def test_at_upper_band(self):
        row = pd.Series({"close": 110, "bb_upper": 110, "bb_lower": 90, "bb_middle": 100})
        assert _score_bb(row) == -1.0  # position=1 → score=-1

    def test_zero_width(self):
        """布林通道寬度為 0 時不應除零"""
        row = pd.Series({"close": 100, "bb_upper": 100, "bb_lower": 100, "bb_middle": 100})
        assert _score_bb(row) == 0.0

    def test_nearly_zero_width(self):
        """布林通道寬度接近 0 時不應除零"""
        row = pd.Series({"close": 100, "bb_upper": 100 + 1e-15, "bb_lower": 100, "bb_middle": 100})
        assert _score_bb(row) == 0.0


class TestScoreVolume:
    def test_volume_up_price_up(self):
        row = pd.Series({"volume_ratio": 1.5, "close": 105, "ma5": 100})
        assert _score_volume(row) == 0.5

    def test_volume_up_price_down(self):
        row = pd.Series({"volume_ratio": 1.5, "close": 95, "ma5": 100})
        assert _score_volume(row) == -1.0

    def test_nan_returns_zero(self):
        row = pd.Series({"volume_ratio": np.nan, "close": 100, "ma5": 100})
        assert _score_volume(row) == 0.0


class TestGenerateSignals:
    def test_output_columns(self, sample_ohlcv):
        result = generate_signals(sample_ohlcv)
        assert "composite_score" in result.columns
        assert "raw_signal" in result.columns
        assert "signal" in result.columns

    def test_signal_values(self, sample_ohlcv):
        result = generate_signals(sample_ohlcv)
        valid_signals = {"BUY", "SELL", "HOLD"}
        assert set(result["signal"].unique()).issubset(valid_signals)

    def test_flat_price_no_crash(self, flat_price_df):
        result = generate_signals(flat_price_df)
        assert not result.empty

    def test_trend_filter_blocks_downtrend_buy(self, downtrend_df):
        """下降趨勢中，趨勢過濾應阻止 BUY 訊號"""
        result = generate_signals(downtrend_df)
        # MA20 < MA60 的列，signal 不應有 BUY
        valid = result.dropna(subset=["ma20", "ma60"])
        downtrend_rows = valid[valid["ma20"] < valid["ma60"]]
        if not downtrend_rows.empty:
            assert (downtrend_rows["signal"] != "BUY").all()


class TestGetLatestAnalysis:
    def test_returns_dict(self, sample_ohlcv):
        result = get_latest_analysis(sample_ohlcv)
        assert isinstance(result, dict)
        assert "signal" in result
        assert "composite_score" in result
        assert "scores" in result
        assert "indicators" in result

    def test_scores_are_numbers(self, sample_ohlcv):
        result = get_latest_analysis(sample_ohlcv)
        for name, val in result["scores"].items():
            assert isinstance(val, (int, float, np.floating)), f"Score {name} is not numeric"
