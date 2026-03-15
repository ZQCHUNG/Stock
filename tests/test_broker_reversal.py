"""Tests for analysis/broker_reversal.py — Phase 3 F6

Tests broker feature score computation, institutional accumulation
detection, and combined broker reversal score.

Uses REAL Parquet data (E2E) — no mocks.
"""

import numpy as np
import pandas as pd
import pytest
from pathlib import Path

from analysis.broker_reversal import (
    FEATURES_PARQUET,
    compute_broker_feature_score,
    compute_broker_reversal_score,
    detect_institutional_accumulation,
    clear_cache,
)


# ---------- Fixtures ----------

@pytest.fixture(autouse=True)
def _clear_parquet_cache():
    """Clear parquet cache before each test."""
    clear_cache()
    yield
    clear_cache()


def _parquet_available() -> bool:
    """Check if the features parquet exists."""
    return FEATURES_PARQUET.exists()


def _get_stock_with_broker_data() -> str | None:
    """Find a stock code that has broker data in the parquet."""
    if not _parquet_available():
        return None
    try:
        df = pd.read_parquet(FEATURES_PARQUET)
        # Find a stock with non-NaN broker_consistency_streak
        has_broker = df.dropna(subset=["broker_consistency_streak"])
        if has_broker.empty:
            return None
        return has_broker["stock_code"].iloc[-1]
    except Exception:
        return None


# ================================================================
# F6A: Broker Feature Score
# ================================================================

class TestBrokerFeatureScore:
    """Tests for compute_broker_feature_score()."""

    def test_score_with_available_parquet(self):
        """Score computation returns valid result when Parquet exists."""
        if not _parquet_available():
            pytest.skip("Features parquet not available")
        stock = _get_stock_with_broker_data()
        if stock is None:
            pytest.skip("No stock with broker data found")

        score, details = compute_broker_feature_score(stock)
        assert score is not None
        assert 0 <= score <= 100
        assert "streak_score" in details
        assert "purity_score" in details

    def test_missing_stock_returns_none(self):
        """Non-existent stock should return None."""
        if not _parquet_available():
            pytest.skip("Features parquet not available")

        score, details = compute_broker_feature_score("XXXX_NONEXISTENT")
        assert score is None
        assert details.get("reason") == "no_data"

    def test_missing_parquet_returns_none(self):
        """When parquet file doesn't exist, returns None gracefully."""
        # Use a fake DataFrame that's empty
        empty_df = pd.DataFrame(columns=["date", "stock_code", "broker_consistency_streak"])
        score, details = compute_broker_feature_score("2330", df=empty_df)
        assert score is None

    def test_score_range(self):
        """Score should be 0-100."""
        if not _parquet_available():
            pytest.skip("Features parquet not available")
        stock = _get_stock_with_broker_data()
        if stock is None:
            pytest.skip("No stock with broker data found")

        score, _ = compute_broker_feature_score(stock)
        if score is not None:
            assert 0 <= score <= 100


# ================================================================
# F6B: Institutional Accumulation Detection
# ================================================================

class TestInstitutionalAccumulation:
    """Tests for detect_institutional_accumulation()."""

    def test_accumulation_on_known_stock(self):
        """Accumulation detection on a stock that has broker data."""
        if not _parquet_available():
            pytest.skip("Features parquet not available")
        stock = _get_stock_with_broker_data()
        if stock is None:
            pytest.skip("No stock with broker data found")

        result = detect_institutional_accumulation(stock)
        assert isinstance(result, dict)
        assert "has_accumulation" in result
        assert "streak_length" in result
        assert "confidence" in result
        assert isinstance(result["has_accumulation"], bool)

    def test_missing_stock_no_accumulation(self):
        """Non-existent stock should return no accumulation."""
        if not _parquet_available():
            pytest.skip("Features parquet not available")

        result = detect_institutional_accumulation("XXXX_NONEXISTENT")
        assert result["has_accumulation"] is False
        assert result["streak_length"] == 0

    def test_confidence_range(self):
        """Confidence should be 0-100."""
        if not _parquet_available():
            pytest.skip("Features parquet not available")
        stock = _get_stock_with_broker_data()
        if stock is None:
            pytest.skip("No stock with broker data found")

        result = detect_institutional_accumulation(stock)
        assert 0 <= result["confidence"] <= 100

    def test_empty_dataframe_handling(self):
        """Empty DataFrame should return no accumulation gracefully."""
        empty_df = pd.DataFrame(columns=["date", "stock_code", "broker_purity_score", "broker_consistency_streak"])
        result = detect_institutional_accumulation("2330", df=empty_df)
        assert result["has_accumulation"] is False


# ================================================================
# Combined: compute_broker_reversal_score()
# ================================================================

class TestBrokerReversalScore:
    """Tests for the combined compute_broker_reversal_score()."""

    def test_e2e_score_on_real_stock(self):
        """E2E: compute combined score on a stock with broker data."""
        if not _parquet_available():
            pytest.skip("Features parquet not available")
        stock = _get_stock_with_broker_data()
        if stock is None:
            pytest.skip("No stock with broker data found")

        score, details = compute_broker_reversal_score(stock)
        assert score is not None
        assert 0 <= score <= 100
        assert "feature_score" in details
        assert "accumulation" in details

    def test_missing_stock_returns_none(self):
        """Non-existent stock should return None score."""
        if not _parquet_available():
            pytest.skip("Features parquet not available")

        score, details = compute_broker_reversal_score("XXXX_NONEXISTENT")
        assert score is None
