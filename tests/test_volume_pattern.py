"""量能型態偵測測試"""

import pandas as pd
import numpy as np
import pytest

from analysis.volume_pattern import (
    detect_volume_patterns,
    get_volume_pattern_summary,
)


@pytest.fixture
def breakout_df():
    """含爆量突破的 DataFrame：第 30 天爆量上漲"""
    np.random.seed(42)
    n = 60
    dates = pd.bdate_range("2024-01-01", periods=n)
    close = np.full(n, 100.0)
    volume = np.full(n, 10000.0)

    # 前 29 天：穩定盤整
    for i in range(1, n):
        close[i] = close[i - 1] + np.random.normal(0, 0.3)
    close = np.maximum(close, 80)

    # 第 30 天：爆量突破（+3%, 量 3x）
    close[30] = close[29] * 1.03
    volume[30] = 30000.0

    # 第 31-35 天：縮量回調（量 0.4x，價格微跌但仍在支撐上）
    for i in range(31, min(36, n)):
        close[i] = close[30] * (1 - 0.005 * (i - 30))
        volume[i] = 4000.0

    # 後續回升
    for i in range(36, n):
        close[i] = close[35] + (i - 35) * 0.2

    df = pd.DataFrame({
        "open": close - np.random.uniform(0, 0.5, n),
        "high": close + np.random.uniform(0.5, 1.5, n),
        "low": close - np.random.uniform(0.5, 1.5, n),
        "close": close,
        "volume": volume,
    }, index=dates)
    df.index.name = "date"
    return df


@pytest.fixture
def no_pattern_df():
    """沒有明顯量能型態的 DataFrame"""
    np.random.seed(99)
    n = 60
    dates = pd.bdate_range("2024-01-01", periods=n)
    close = 100 + np.random.normal(0, 0.5, n).cumsum()
    close = np.maximum(close, 80)
    volume = np.random.uniform(9000, 11000, n)

    df = pd.DataFrame({
        "open": close - 0.3,
        "high": close + 0.5,
        "low": close - 0.5,
        "close": close,
        "volume": volume,
    }, index=dates)
    df.index.name = "date"
    return df


class TestDetectVolumePatterns:
    def test_returns_dataframe(self, breakout_df):
        result = detect_volume_patterns(breakout_df)
        assert isinstance(result, pd.DataFrame)

    def test_has_required_columns(self, breakout_df):
        result = detect_volume_patterns(breakout_df)
        for col in ["vol_ratio", "is_breakout", "is_pullback",
                     "breakout_pullback", "volume_pattern"]:
            assert col in result.columns

    def test_detects_breakout(self, breakout_df):
        result = detect_volume_patterns(breakout_df)
        assert result["is_breakout"].any(), "Should detect at least one breakout"

    def test_detects_pullback(self, breakout_df):
        result = detect_volume_patterns(breakout_df)
        assert result["is_pullback"].any(), "Should detect at least one pullback"

    def test_detects_breakout_pullback_sequence(self, breakout_df):
        result = detect_volume_patterns(breakout_df)
        assert result["breakout_pullback"].any(), \
            "Should detect breakout→pullback sequence"

    def test_sequence_after_breakout(self, breakout_df):
        """序列偵測應在爆量之後"""
        result = detect_volume_patterns(breakout_df)
        breakout_dates = result.index[result["is_breakout"]]
        bp_dates = result.index[result["breakout_pullback"]]
        if len(breakout_dates) > 0 and len(bp_dates) > 0:
            assert bp_dates[0] >= breakout_dates[0]

    def test_vol_ratio_calculated(self, breakout_df):
        result = detect_volume_patterns(breakout_df)
        # 爆量日的 vol_ratio 應 > 2
        breakout_rows = result[result["is_breakout"]]
        if not breakout_rows.empty:
            assert breakout_rows["vol_ratio"].max() >= 2.0

    def test_volume_pattern_labels(self, breakout_df):
        result = detect_volume_patterns(breakout_df)
        patterns = result["volume_pattern"].unique()
        # 至少應有空字串（無型態）
        assert "" in patterns

    def test_no_pattern_stable_data(self, no_pattern_df):
        """穩定量能不應產生爆量突破"""
        result = detect_volume_patterns(no_pattern_df)
        # 穩定量能下爆量突破應該很少
        breakout_count = result["is_breakout"].sum()
        assert breakout_count <= 3, f"Too many breakouts ({breakout_count}) in stable data"

    def test_short_data_no_crash(self):
        """短資料不應崩潰"""
        dates = pd.bdate_range("2024-01-01", periods=5)
        df = pd.DataFrame({
            "open": [100] * 5,
            "high": [101] * 5,
            "low": [99] * 5,
            "close": [100] * 5,
            "volume": [10000] * 5,
        }, index=dates, dtype=float)
        df.index.name = "date"
        result = detect_volume_patterns(df)
        assert isinstance(result, pd.DataFrame)

    def test_none_data(self):
        result = detect_volume_patterns(None)
        assert isinstance(result, pd.DataFrame)

    def test_custom_thresholds(self, breakout_df):
        """自訂門檻"""
        result = detect_volume_patterns(
            breakout_df,
            breakout_vol_ratio=1.5,  # 更低的爆量門檻
            pullback_vol_ratio=0.8,  # 更高的縮量門檻
        )
        assert isinstance(result, pd.DataFrame)
        # 門檻較寬鬆時應偵測到更多型態
        breakout_count = result["is_breakout"].sum()
        assert breakout_count >= 1

    def test_lookback_window(self, breakout_df):
        """短 lookback 應減少序列偵測"""
        result_long = detect_volume_patterns(breakout_df, sequence_lookback=10)
        result_short = detect_volume_patterns(breakout_df, sequence_lookback=2)
        # 短 lookback 的序列數 <= 長 lookback
        assert result_short["breakout_pullback"].sum() <= result_long["breakout_pullback"].sum()

    def test_preserves_original_columns(self, breakout_df):
        """不應改變原始 OHLCV 欄位"""
        original_cols = set(breakout_df.columns)
        result = detect_volume_patterns(breakout_df)
        for col in original_cols:
            assert col in result.columns
            np.testing.assert_array_equal(
                result[col].values, breakout_df[col].values
            )


class TestGetVolumePatternSummary:
    def test_returns_dict(self, breakout_df):
        summary = get_volume_pattern_summary(breakout_df)
        assert isinstance(summary, dict)

    def test_has_required_keys(self, breakout_df):
        summary = get_volume_pattern_summary(breakout_df)
        for key in ["current_pattern", "current_vol_ratio",
                     "recent_breakouts", "recent_pullbacks",
                     "has_active_sequence", "days_since_breakout",
                     "volume_trend"]:
            assert key in summary

    def test_volume_trend_values(self, breakout_df):
        summary = get_volume_pattern_summary(breakout_df)
        assert summary["volume_trend"] in ("increasing", "decreasing", "stable", "unknown")

    def test_recent_counts_non_negative(self, breakout_df):
        summary = get_volume_pattern_summary(breakout_df)
        assert summary["recent_breakouts"] >= 0
        assert summary["recent_pullbacks"] >= 0

    def test_none_data(self):
        summary = get_volume_pattern_summary(None)
        assert summary["current_pattern"] == ""
        assert summary["volume_trend"] == "unknown"

    def test_empty_data(self):
        summary = get_volume_pattern_summary(pd.DataFrame())
        assert summary["current_pattern"] == ""
