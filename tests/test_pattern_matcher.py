"""Tests for analysis/pattern_matcher.py — DTW-based pattern matching."""

import numpy as np
import pytest

from analysis.pattern_matcher import (
    dtw_distance,
    normalize_series,
    return_series,
    _quick_similarity,
)


class TestDTW:
    def test_identical_series(self):
        s = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        assert dtw_distance(s, s) == 0.0

    def test_similar_series(self):
        s1 = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        s2 = np.array([1.1, 2.1, 3.1, 4.1, 5.1])
        dist = dtw_distance(s1, s2)
        assert dist < 0.2  # Very similar

    def test_opposite_series(self):
        s1 = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        s2 = np.array([5.0, 4.0, 3.0, 2.0, 1.0])
        dist = dtw_distance(s1, s2)
        assert dist > 0.5  # Clearly different

    def test_empty_series(self):
        assert dtw_distance(np.array([]), np.array([1.0])) == float("inf")
        assert dtw_distance(np.array([1.0]), np.array([])) == float("inf")

    def test_different_lengths(self):
        s1 = np.array([1.0, 2.0, 3.0])
        s2 = np.array([1.0, 1.5, 2.0, 2.5, 3.0])
        dist = dtw_distance(s1, s2)
        assert dist < 1.0  # Same trend, different speed

    def test_time_warped(self):
        """DTW should handle time-shifted versions well."""
        s1 = np.array([0, 0, 1, 2, 3, 3, 3], dtype=float)
        s2 = np.array([0, 1, 2, 3, 3, 3, 3], dtype=float)
        dist = dtw_distance(s1, s2)
        assert dist < 0.5  # Same shape, slightly shifted


class TestNormalize:
    def test_basic(self):
        s = np.array([10, 20, 30, 40, 50], dtype=float)
        norm = normalize_series(s)
        assert abs(np.mean(norm)) < 1e-6
        assert abs(np.std(norm) - 1.0) < 1e-6

    def test_constant_series(self):
        s = np.array([5.0, 5.0, 5.0])
        norm = normalize_series(s)
        assert all(v == 0 for v in norm)

    def test_scale_invariant(self):
        """Different price levels, same pattern → same normalized shape."""
        s1 = np.array([100, 110, 105, 115, 120], dtype=float)
        s2 = np.array([1000, 1100, 1050, 1150, 1200], dtype=float)
        n1 = normalize_series(s1)
        n2 = normalize_series(s2)
        np.testing.assert_allclose(n1, n2, atol=1e-6)


class TestReturnSeries:
    def test_basic(self):
        prices = np.array([100, 110, 105], dtype=float)
        ret = return_series(prices)
        np.testing.assert_allclose(ret, [0.1, -0.0454545], atol=1e-4)

    def test_single_price(self):
        ret = return_series(np.array([100.0]))
        assert len(ret) == 0


class TestQuickSimilarity:
    def test_identical(self):
        r = np.array([0.01, -0.02, 0.03, 0.01, -0.01])
        corr = _quick_similarity(r, r)
        assert abs(corr - 1.0) < 1e-6

    def test_opposite(self):
        r1 = np.array([0.01, -0.02, 0.03, 0.01, -0.01])
        r2 = -r1
        corr = _quick_similarity(r1, r2)
        assert corr < -0.9

    def test_too_short(self):
        r = np.array([0.01, 0.02])
        assert _quick_similarity(r, r) == -1.0

    def test_different_lengths(self):
        """When lengths differ, uses last N elements of the longer series."""
        r1 = np.array([0.05, 0.01, -0.02, 0.03, 0.01, -0.01])
        r2 = np.array([0.01, -0.02, 0.03, 0.01, -0.01])
        corr = _quick_similarity(r1, r2)
        # Last 5 of r1 match r2 exactly → correlation should be 1.0
        assert corr > 0.99


class TestIntegration:
    def test_dtw_with_normalization(self):
        """End-to-end: normalize then DTW should find similar shapes."""
        # Stock A: gradual rise
        a = np.array([100, 102, 105, 108, 112, 115, 118, 120], dtype=float)
        # Stock B: same pattern at different price level
        b = np.array([50, 51, 52.5, 54, 56, 57.5, 59, 60], dtype=float)
        # Stock C: decline
        c = np.array([100, 98, 95, 92, 88, 85, 82, 80], dtype=float)

        na, nb, nc = normalize_series(a), normalize_series(b), normalize_series(c)

        dist_ab = dtw_distance(na, nb)
        dist_ac = dtw_distance(na, nc)

        # A and B have same shape → lower distance
        assert dist_ab < dist_ac
        assert dist_ab < 0.01  # Nearly identical after normalization
