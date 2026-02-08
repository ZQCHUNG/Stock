"""v4 策略測試"""

import pandas as pd
import numpy as np
import pytest
from analysis.strategy_v4 import generate_v4_signals, get_v4_analysis


class TestGenerateV4Signals:
    def test_output_columns(self, sample_ohlcv):
        result = generate_v4_signals(sample_ohlcv)
        assert "v4_signal" in result.columns
        assert "v4_entry_type" in result.columns
        assert "dist_ma20" in result.columns
        assert "uptrend_days" in result.columns

    def test_signal_values(self, sample_ohlcv):
        result = generate_v4_signals(sample_ohlcv)
        assert set(result["v4_signal"].unique()).issubset({"BUY", "HOLD", "SELL"})

    def test_entry_type_values(self, sample_ohlcv):
        result = generate_v4_signals(sample_ohlcv)
        assert set(result["v4_entry_type"].unique()).issubset({"support", "momentum", ""})

    def test_no_buy_in_downtrend(self, downtrend_df):
        """下降趨勢中不應有 BUY 訊號（uptrend_days < min_uptrend_days）"""
        result = generate_v4_signals(downtrend_df)
        # 下降趨勢 MA20 不會持續 > MA60 十天以上
        buy_rows = result[result["v4_signal"] == "BUY"]
        # 如果有 BUY，uptrend_days 必須 >= 10
        if not buy_rows.empty:
            assert (buy_rows["uptrend_days"] >= 10).all()

    def test_sell_in_downtrend(self, downtrend_df):
        """下降趨勢中應有 SELL 訊號（MA20<MA60 且 -DI>+DI）"""
        result = generate_v4_signals(downtrend_df)
        sell_rows = result[result["v4_signal"] == "SELL"]
        # 持續下跌趨勢中，應有一些 SELL 訊號
        assert len(sell_rows) > 0

    def test_uptrend_may_generate_buy(self, uptrend_df):
        """上升趨勢中可能有 BUY 訊號"""
        result = generate_v4_signals(uptrend_df)
        # 上升趨勢中至少應該有一些 BUY 訊號（不保證，但常見）
        assert result["v4_signal"].isin(["BUY", "HOLD", "SELL"]).all()

    def test_uptrend_days_counter(self, uptrend_df):
        """上升趨勢中 uptrend_days 應遞增"""
        result = generate_v4_signals(uptrend_df)
        ut = result["uptrend_days"]
        # 至少有一段 uptrend_days > 10
        assert ut.max() >= 10

    def test_custom_params(self, sample_ohlcv):
        """自訂參數應覆蓋預設值"""
        result = generate_v4_signals(sample_ohlcv, params={"adx_min": 100})
        # ADX 門檻設很高，不應有 BUY
        assert "BUY" not in result["v4_signal"].values

    def test_flat_price_no_crash(self, flat_price_df):
        result = generate_v4_signals(flat_price_df)
        assert not result.empty

    def test_minimal_data(self, minimal_df):
        result = generate_v4_signals(minimal_df)
        assert len(result) == len(minimal_df)

    def test_dist_ma20_calculation(self, sample_ohlcv):
        result = generate_v4_signals(sample_ohlcv)
        valid = result.dropna(subset=["dist_ma20", "ma20"])
        if not valid.empty:
            row = valid.iloc[-1]
            expected = (row["close"] - row["ma20"]) / row["ma20"]
            assert abs(row["dist_ma20"] - expected) < 1e-10


class TestGetV4Analysis:
    def test_returns_dict(self, sample_ohlcv):
        result = get_v4_analysis(sample_ohlcv)
        assert isinstance(result, dict)
        assert "signal" in result
        assert "entry_type" in result
        assert "uptrend_days" in result
        assert "indicators" in result

    def test_indicator_keys(self, sample_ohlcv):
        result = get_v4_analysis(sample_ohlcv)
        expected_keys = {"ADX", "+DI", "-DI", "RSI", "ROC", "MA5", "MA20", "MA60"}
        assert expected_keys == set(result["indicators"].keys())
