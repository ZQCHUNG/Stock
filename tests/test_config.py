"""Config Dataclass 測試"""

import pytest
from config import StrategyV4Config, DEFAULT_V4_CONFIG


class TestStrategyV4Config:
    def test_default_values(self):
        cfg = StrategyV4Config()
        assert cfg.adx_min == 18
        assert cfg.take_profit_pct == 0.10
        assert cfg.stop_loss_pct == 0.07
        assert cfg.trailing_stop_pct == 0.02
        assert cfg.min_hold_days == 5

    def test_frozen(self):
        cfg = StrategyV4Config()
        with pytest.raises(AttributeError):
            cfg.adx_min = 20

    def test_to_dict(self):
        cfg = StrategyV4Config()
        d = cfg.to_dict()
        assert isinstance(d, dict)
        assert d["adx_min"] == 18
        assert d["take_profit_pct"] == 0.10

    def test_with_overrides(self):
        cfg = StrategyV4Config()
        cfg2 = cfg.with_overrides(adx_min=20, take_profit_pct=0.15)
        assert cfg2.adx_min == 20
        assert cfg2.take_profit_pct == 0.15
        # 原始不變
        assert cfg.adx_min == 18

    def test_from_dict(self):
        d = {"adx_min": 22, "rsi_low": 25, "unknown_key": 999}
        cfg = StrategyV4Config.from_dict(d)
        assert cfg.adx_min == 22
        assert cfg.rsi_low == 25
        # unknown_key should be ignored

    def test_describe(self):
        cfg = StrategyV4Config()
        desc = cfg.describe()
        assert "ADX" in desc
        assert "TP" in desc
        assert "SL" in desc

    def test_default_instance(self):
        assert DEFAULT_V4_CONFIG.adx_min == 18
        assert DEFAULT_V4_CONFIG.to_dict() == StrategyV4Config().to_dict()

    def test_equality(self):
        cfg1 = StrategyV4Config()
        cfg2 = StrategyV4Config()
        assert cfg1 == cfg2

    def test_inequality_after_override(self):
        cfg1 = StrategyV4Config()
        cfg2 = cfg1.with_overrides(adx_min=25)
        assert cfg1 != cfg2
