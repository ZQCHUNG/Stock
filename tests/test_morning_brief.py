"""Tests for Morning Briefing Generator (V1.2 P1)."""

import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock
from pathlib import Path


class TestIsMarketOpen:
    """Test market calendar / trading day detection."""

    def test_weekday_is_open(self):
        from analysis.morning_brief import is_market_open
        # 2026-02-26 is Thursday
        assert is_market_open(datetime(2026, 2, 26)) is True

    def test_saturday_is_closed(self):
        from analysis.morning_brief import is_market_open
        assert is_market_open(datetime(2026, 2, 28)) is False  # Saturday

    def test_sunday_is_closed(self):
        from analysis.morning_brief import is_market_open
        assert is_market_open(datetime(2026, 3, 1)) is False  # Sunday

    def test_holiday_is_closed(self):
        from analysis.morning_brief import is_market_open
        # 2026-02-28 is 228 Peace Memorial Day (in calendar.yaml)
        # But 2026-02-28 is also Saturday, so test 2026-02-27 (Friday, 補假)
        assert is_market_open(datetime(2026, 2, 27)) is False

    def test_normal_friday_is_open(self):
        from analysis.morning_brief import is_market_open
        # 2026-03-06 is a normal Friday
        assert is_market_open(datetime(2026, 3, 6)) is True

    def test_missing_calendar_defaults_open(self):
        from analysis.morning_brief import is_market_open
        with patch("analysis.morning_brief.CALENDAR_PATH", Path("/nonexistent.yaml")):
            # Weekday with no calendar → should be open
            assert is_market_open(datetime(2026, 2, 26)) is True


class TestPriorityScore:
    """Test Priority Score calculation."""

    def test_all_max_scores_100(self):
        from analysis.morning_brief import _compute_priority_score
        sig = {
            "rs_rating": 100,
            "sim_score": 100,
            "aqs_phase": "BETA",
            "peer_alpha": 3.0,
            "liquidity_score": 100,
        }
        score = _compute_priority_score(sig)
        assert score == 100.0

    def test_all_zero_scores_0(self):
        from analysis.morning_brief import _compute_priority_score
        sig = {
            "rs_rating": 0,
            "sim_score": 0,
            "aqs_phase": "NONE",
            "peer_alpha": 0.5,
            "liquidity_score": 0,
        }
        score = _compute_priority_score(sig)
        assert score == 0.0

    def test_missing_data_uses_defaults(self):
        from analysis.morning_brief import _compute_priority_score
        sig = {}  # All missing → defaults to median
        score = _compute_priority_score(sig)
        # rs=50*0.3 + sqs=50*0.25 + aqs=0*0.2 + pa=20*0.15 + liq=50*0.1
        expected = 15.0 + 12.5 + 0 + 3.0 + 5.0
        assert abs(score - expected) < 0.01

    def test_rs_has_highest_weight(self):
        from analysis.morning_brief import _compute_priority_score
        high_rs = {"rs_rating": 100, "sim_score": 0, "aqs_phase": "NONE", "peer_alpha": 0.5, "liquidity_score": 0}
        high_sqs = {"rs_rating": 0, "sim_score": 100, "aqs_phase": "NONE", "peer_alpha": 0.5, "liquidity_score": 0}
        assert _compute_priority_score(high_rs) > _compute_priority_score(high_sqs)


class TestActionTags:
    """Test action tag generation."""

    def test_live_position_tag(self):
        from analysis.morning_brief import _get_action_tag
        sig = {"is_live": True, "trailing_phase": 0}
        tag = _get_action_tag(sig, "2026-02-26")
        assert "\u6301\u5009\u4e2d" in tag  # "持倉中"

    def test_live_atr_trail_tag(self):
        from analysis.morning_brief import _get_action_tag
        sig = {"is_live": True, "trailing_phase": 2}
        tag = _get_action_tag(sig, "2026-02-26")
        assert "ATR" in tag

    def test_new_signal_tag(self):
        from analysis.morning_brief import _get_action_tag
        sig = {"is_live": False, "signal_date": "2026-02-26", "aqs_phase": "NONE"}
        tag = _get_action_tag(sig, "2026-02-26")
        assert "\u65b0\u4fe1\u865f" in tag  # "新信號"

    def test_beta_aqs_tag(self):
        from analysis.morning_brief import _get_action_tag
        sig = {"is_live": False, "signal_date": "2026-02-20", "aqs_phase": "BETA"}
        tag = _get_action_tag(sig, "2026-02-26")
        assert "\u8a66\u55ae" in tag  # "試單"


class TestStopProximity:
    """Test stop loss proximity detection."""

    def test_near_stop(self):
        from analysis.morning_brief import _is_stop_near
        sig = {"entry_price": 100, "current_stop": 97}
        assert _is_stop_near(sig) is True  # 100/97 = 1.03 < 1.05

    def test_far_from_stop(self):
        from analysis.morning_brief import _is_stop_near
        sig = {"entry_price": 100, "current_stop": 80}
        assert _is_stop_near(sig) is False  # 100/80 = 1.25 > 1.05

    def test_no_stop_data(self):
        from analysis.morning_brief import _is_stop_near
        sig = {"entry_price": 100, "current_stop": None}
        assert _is_stop_near(sig) is False


class TestRiskAlerts:
    """Test risk alert generation."""

    def test_lockdown_alert(self):
        from analysis.morning_brief import _get_risk_alerts
        alerts = _get_risk_alerts([], {"level": 2, "label": "LOCKDOWN"}, 20)
        assert any("LOCKDOWN" in a for a in alerts)

    def test_caution_alert(self):
        from analysis.morning_brief import _get_risk_alerts
        alerts = _get_risk_alerts([], {"level": 1, "label": "CAUTION"}, 50)
        assert any("CAUTION" in a for a in alerts)

    def test_normal_no_alert(self):
        from analysis.morning_brief import _get_risk_alerts
        alerts = _get_risk_alerts([], {"level": 0, "label": "NORMAL"}, 60)
        assert len(alerts) == 0

    def test_stop_near_alert(self):
        from analysis.morning_brief import _get_risk_alerts
        signals = [{"code": "2330", "name": "台積電", "is_live": True, "entry_price": 100, "current_stop": 97}]
        alerts = _get_risk_alerts(signals, {"level": 0}, 60)
        assert any("2330" in a for a in alerts)


class TestUrgencySort:
    """Test BRIEF_URGENCY_SORT — risk alerts move to top when Aggressive Index < 40."""

    @patch("analysis.morning_brief._get_aggressive_index", return_value=(30, "Defensive", "\U0001f9ca"))
    @patch("analysis.morning_brief._get_market_guard", return_value={"level": 1, "label": "CAUTION", "taiex": 20000, "taiex_pct": -1.5, "ma20_dir": "\u2193"})
    @patch("analysis.morning_brief._get_active_signals_enriched", return_value=[])
    def test_urgency_mode_risk_first(self, mock_sigs, mock_guard, mock_agg):
        from analysis.morning_brief import generate_morning_brief
        result = generate_morning_brief(send_notification=False)
        msg = result["message"]
        # Risk alerts should appear before "Joe's Morning Brief" header
        alert_pos = msg.find("\u7dca\u6025\u8b66\u5831")  # "緊急警報"
        brief_pos = msg.find("Joe's Morning Brief")
        assert result["urgency_mode"] is True
        assert alert_pos < brief_pos

    @patch("analysis.morning_brief._get_aggressive_index", return_value=(75, "Aggressive", "\U0001f525"))
    @patch("analysis.morning_brief._get_market_guard", return_value={"level": 0, "label": "NORMAL", "taiex": 23000, "taiex_pct": 0.5, "ma20_dir": "\u2191"})
    @patch("analysis.morning_brief._get_active_signals_enriched", return_value=[])
    def test_normal_mode_no_urgency(self, mock_sigs, mock_guard, mock_agg):
        from analysis.morning_brief import generate_morning_brief
        result = generate_morning_brief(send_notification=False)
        assert result["urgency_mode"] is False


class TestGenerateMorningBrief:
    """Test full morning brief generation."""

    @patch("analysis.morning_brief._get_aggressive_index", return_value=(65, "Normal", "\u2618\ufe0f"))
    @patch("analysis.morning_brief._get_market_guard", return_value={"level": 0, "label": "NORMAL", "taiex": 23456, "taiex_pct": 0.8, "ma20_dir": "\u2191"})
    @patch("analysis.morning_brief._get_active_signals_enriched")
    def test_full_brief_with_signals(self, mock_sigs, mock_guard, mock_agg):
        from analysis.morning_brief import generate_morning_brief
        mock_sigs.return_value = [
            {"code": "2330", "name": "台積電", "entry_price": 980, "current_stop": 930,
             "trailing_phase": 2, "is_live": True, "signal_date": "2026-02-20",
             "rs_rating": 99, "sim_score": 85, "confidence_grade": "HIGH",
             "scale_out_triggered": False, "peer_alpha": 1.8, "sector": "半導體"},
            {"code": "6770", "name": "力積電", "entry_price": 76.8, "current_stop": 67.1,
             "trailing_phase": 0, "is_live": True, "signal_date": "2026-02-25",
             "rs_rating": 99.6, "sim_score": 70, "confidence_grade": "MEDIUM",
             "scale_out_triggered": False, "peer_alpha": 2.1, "sector": "半導體"},
        ]
        result = generate_morning_brief(send_notification=False)

        assert result["aggressive_index"]["score"] == 65
        assert result["market_guard"]["taiex"] == 23456
        assert len(result["focus_stocks"]) == 2
        assert "2330" in result["message"]
        assert "6770" in result["message"]
        assert "23,456" in result["message"]

    @patch("analysis.morning_brief._get_aggressive_index", return_value=(50, "Normal", "\u2618\ufe0f"))
    @patch("analysis.morning_brief._get_market_guard", return_value={"level": 0, "label": "NORMAL", "taiex": None, "taiex_pct": 0, "ma20_dir": "?"})
    @patch("analysis.morning_brief._get_active_signals_enriched", return_value=[])
    def test_empty_signals(self, mock_sigs, mock_guard, mock_agg):
        from analysis.morning_brief import generate_morning_brief
        result = generate_morning_brief(send_notification=False)
        assert "\u7121\u6d3b\u8e8d\u4fe1\u865f" in result["message"]  # "無活躍信號"

    @patch("analysis.morning_brief._get_aggressive_index", return_value=(65, "Normal", "\u2618\ufe0f"))
    @patch("analysis.morning_brief._get_market_guard", return_value={"level": 0, "label": "NORMAL", "taiex": 23000, "taiex_pct": 0.3, "ma20_dir": "\u2191"})
    @patch("analysis.morning_brief._get_active_signals_enriched")
    def test_top5_selection_with_20_signals(self, mock_sigs, mock_guard, mock_agg):
        """CTO question: 20 signals → only Top 5 shown."""
        from analysis.morning_brief import generate_morning_brief
        signals = []
        for i in range(20):
            signals.append({
                "code": f"{1000 + i}", "name": f"Stock{i}",
                "entry_price": 100, "current_stop": 80,
                "trailing_phase": 0, "is_live": False,
                "signal_date": "2026-02-20",
                "rs_rating": 50 + i * 2.5,
                "sim_score": 50 + i,
                "confidence_grade": "MEDIUM",
                "scale_out_triggered": False,
            })
        mock_sigs.return_value = signals
        result = generate_morning_brief(send_notification=False)
        # Should have at most MAX_FOCUS (5) stocks
        assert len(result["focus_stocks"]) <= 5

    @patch("analysis.morning_brief._get_aggressive_index", return_value=(65, "Normal", "\u2618\ufe0f"))
    @patch("analysis.morning_brief._get_market_guard", return_value={"level": 0, "label": "NORMAL", "taiex": 23000, "taiex_pct": 0.3, "ma20_dir": "\u2191"})
    @patch("analysis.morning_brief._get_active_signals_enriched")
    def test_live_positions_always_included(self, mock_sigs, mock_guard, mock_agg):
        """Live positions must always appear even if not in top 5 by score."""
        from analysis.morning_brief import generate_morning_brief
        signals = []
        # 6 high-score non-live signals
        for i in range(6):
            signals.append({
                "code": f"{2000 + i}", "name": f"HighScore{i}",
                "entry_price": 100, "current_stop": 80,
                "trailing_phase": 0, "is_live": False,
                "signal_date": "2026-02-20",
                "rs_rating": 90 + i, "sim_score": 90,
                "confidence_grade": "HIGH", "scale_out_triggered": False,
            })
        # 1 low-score live position
        signals.append({
            "code": "9999", "name": "LiveLowScore",
            "entry_price": 50, "current_stop": 40,
            "trailing_phase": 1, "is_live": True,
            "signal_date": "2026-02-15",
            "rs_rating": 20, "sim_score": 30,
            "confidence_grade": "LOW", "scale_out_triggered": False,
        })
        mock_sigs.return_value = signals
        result = generate_morning_brief(send_notification=False)
        focus_codes = [s["code"] for s in result["focus_stocks"]]
        # Live position MUST be included
        assert "9999" in focus_codes
