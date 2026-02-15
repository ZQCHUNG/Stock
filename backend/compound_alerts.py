"""複合條件警報規則引擎

R55-3: 進階警報規則
- 支援 AND/OR 條件組合
- 多指標組合觸發（價格、成交量、技術指標）
- 規則持久化（JSON）
- 與現有 SQS 警報整合
"""

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"
RULES_FILE = DATA_DIR / "compound_alert_rules.json"


class ConditionType(str, Enum):
    PRICE_ABOVE = "price_above"
    PRICE_BELOW = "price_below"
    PRICE_CHANGE_PCT = "price_change_pct"
    VOLUME_ABOVE = "volume_above"
    VOLUME_RATIO = "volume_ratio"         # volume vs 20d avg
    RSI_ABOVE = "rsi_above"
    RSI_BELOW = "rsi_below"
    MACD_CROSS_UP = "macd_cross_up"       # MACD golden cross
    MACD_CROSS_DOWN = "macd_cross_down"   # MACD death cross
    KD_CROSS_UP = "kd_cross_up"           # K crosses above D
    KD_CROSS_DOWN = "kd_cross_down"
    MA_CROSS_UP = "ma_cross_up"           # short MA > long MA
    MA_CROSS_DOWN = "ma_cross_down"
    ADX_ABOVE = "adx_above"
    BOLLINGER_UPPER = "bb_upper_break"    # price > upper band
    BOLLINGER_LOWER = "bb_lower_break"    # price < lower band
    SQS_ABOVE = "sqs_above"
    V4_BUY = "v4_buy_signal"
    V4_SELL = "v4_sell_signal"


class CombineMode(str, Enum):
    AND = "AND"
    OR = "OR"


@dataclass
class Condition:
    type: str        # ConditionType value
    value: float = 0.0
    params: dict = field(default_factory=dict)  # e.g. {"short_period": 5, "long_period": 20} for MA cross

    def to_dict(self) -> dict:
        return {"type": self.type, "value": self.value, "params": self.params}

    @staticmethod
    def from_dict(d: dict) -> "Condition":
        return Condition(type=d["type"], value=d.get("value", 0), params=d.get("params", {}))


@dataclass
class CompoundRule:
    id: str
    name: str
    codes: list[str]              # stocks to watch (empty = all scan stocks)
    conditions: list[Condition]
    combine_mode: str = "AND"     # AND or OR
    enabled: bool = True
    notify_line: bool = False
    notify_browser: bool = True
    cooldown_hours: float = 4.0
    created_at: float = field(default_factory=time.time)
    last_triggered: float = 0.0
    trigger_count: int = 0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["conditions"] = [c.to_dict() for c in self.conditions]
        return d

    @staticmethod
    def from_dict(d: dict) -> "CompoundRule":
        conditions = [Condition.from_dict(c) for c in d.get("conditions", [])]
        return CompoundRule(
            id=d["id"],
            name=d["name"],
            codes=d.get("codes", []),
            conditions=conditions,
            combine_mode=d.get("combine_mode", "AND"),
            enabled=d.get("enabled", True),
            notify_line=d.get("notify_line", False),
            notify_browser=d.get("notify_browser", True),
            cooldown_hours=d.get("cooldown_hours", 4.0),
            created_at=d.get("created_at", time.time()),
            last_triggered=d.get("last_triggered", 0.0),
            trigger_count=d.get("trigger_count", 0),
        )


# --- Rule persistence ---

def load_rules() -> list[CompoundRule]:
    """Load rules from JSON file."""
    if not RULES_FILE.exists():
        return []
    try:
        data = json.loads(RULES_FILE.read_text(encoding="utf-8"))
        return [CompoundRule.from_dict(r) for r in data]
    except Exception as e:
        logger.error(f"Failed to load compound rules: {e}")
        return []


def save_rules(rules: list[CompoundRule]):
    """Persist rules to JSON file."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data = [r.to_dict() for r in rules]
    RULES_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_rule(rule_id: str) -> CompoundRule | None:
    rules = load_rules()
    return next((r for r in rules if r.id == rule_id), None)


def add_rule(rule: CompoundRule) -> CompoundRule:
    rules = load_rules()
    rules.append(rule)
    save_rules(rules)
    return rule


def update_rule(rule_id: str, updates: dict) -> CompoundRule | None:
    rules = load_rules()
    for r in rules:
        if r.id == rule_id:
            for k, v in updates.items():
                if k == "conditions":
                    r.conditions = [Condition.from_dict(c) for c in v]
                elif hasattr(r, k):
                    setattr(r, k, v)
            save_rules(rules)
            return r
    return None


def delete_rule(rule_id: str) -> bool:
    rules = load_rules()
    new_rules = [r for r in rules if r.id != rule_id]
    if len(new_rules) < len(rules):
        save_rules(new_rules)
        return True
    return False


# --- Condition evaluation ---

def evaluate_condition(cond: Condition, stock_data: dict) -> bool:
    """Evaluate a single condition against stock data.

    stock_data should contain:
    - price: current price
    - prev_close: previous close
    - volume: current volume
    - avg_volume_20d: 20-day average volume
    - rsi: current RSI
    - macd: current MACD value
    - macd_signal: MACD signal line
    - macd_prev: previous MACD value
    - macd_signal_prev: previous signal line
    - k: stochastic K
    - d: stochastic D
    - k_prev: previous K
    - d_prev: previous D
    - adx: current ADX
    - bb_upper: Bollinger upper band
    - bb_lower: Bollinger lower band
    - sqs: Signal Quality Score
    - v4_signal: "BUY" / "SELL" / "HOLD"
    - ma_short: short-period MA (default MA5)
    - ma_long: long-period MA (default MA20)
    - ma_short_prev: previous short MA
    - ma_long_prev: previous long MA
    """
    ct = cond.type
    val = cond.value
    price = stock_data.get("price")

    if price is None:
        return False

    try:
        if ct == ConditionType.PRICE_ABOVE:
            return price > val

        elif ct == ConditionType.PRICE_BELOW:
            return price < val

        elif ct == ConditionType.PRICE_CHANGE_PCT:
            prev = stock_data.get("prev_close")
            if prev and prev > 0:
                pct = (price - prev) / prev * 100
                return pct >= val if val >= 0 else pct <= val
            return False

        elif ct == ConditionType.VOLUME_ABOVE:
            vol = stock_data.get("volume", 0)
            return vol > val

        elif ct == ConditionType.VOLUME_RATIO:
            vol = stock_data.get("volume", 0)
            avg = stock_data.get("avg_volume_20d", 0)
            return avg > 0 and vol / avg >= val

        elif ct == ConditionType.RSI_ABOVE:
            return (stock_data.get("rsi") or 0) > val

        elif ct == ConditionType.RSI_BELOW:
            return (stock_data.get("rsi") or 0) < val

        elif ct == ConditionType.MACD_CROSS_UP:
            macd = stock_data.get("macd")
            sig = stock_data.get("macd_signal")
            mp = stock_data.get("macd_prev")
            sp = stock_data.get("macd_signal_prev")
            if None in (macd, sig, mp, sp):
                return False
            return mp <= sp and macd > sig

        elif ct == ConditionType.MACD_CROSS_DOWN:
            macd = stock_data.get("macd")
            sig = stock_data.get("macd_signal")
            mp = stock_data.get("macd_prev")
            sp = stock_data.get("macd_signal_prev")
            if None in (macd, sig, mp, sp):
                return False
            return mp >= sp and macd < sig

        elif ct == ConditionType.KD_CROSS_UP:
            k = stock_data.get("k")
            d = stock_data.get("d")
            kp = stock_data.get("k_prev")
            dp = stock_data.get("d_prev")
            if None in (k, d, kp, dp):
                return False
            return kp <= dp and k > d

        elif ct == ConditionType.KD_CROSS_DOWN:
            k = stock_data.get("k")
            d = stock_data.get("d")
            kp = stock_data.get("k_prev")
            dp = stock_data.get("d_prev")
            if None in (k, d, kp, dp):
                return False
            return kp >= dp and k < d

        elif ct == ConditionType.MA_CROSS_UP:
            ms = stock_data.get("ma_short")
            ml = stock_data.get("ma_long")
            msp = stock_data.get("ma_short_prev")
            mlp = stock_data.get("ma_long_prev")
            if None in (ms, ml, msp, mlp):
                return False
            return msp <= mlp and ms > ml

        elif ct == ConditionType.MA_CROSS_DOWN:
            ms = stock_data.get("ma_short")
            ml = stock_data.get("ma_long")
            msp = stock_data.get("ma_short_prev")
            mlp = stock_data.get("ma_long_prev")
            if None in (ms, ml, msp, mlp):
                return False
            return msp >= mlp and ms < ml

        elif ct == ConditionType.ADX_ABOVE:
            return (stock_data.get("adx") or 0) > val

        elif ct == ConditionType.BOLLINGER_UPPER:
            bb = stock_data.get("bb_upper")
            return bb is not None and price > bb

        elif ct == ConditionType.BOLLINGER_LOWER:
            bb = stock_data.get("bb_lower")
            return bb is not None and price < bb

        elif ct == ConditionType.SQS_ABOVE:
            return (stock_data.get("sqs") or 0) >= val

        elif ct == ConditionType.V4_BUY:
            return stock_data.get("v4_signal") == "BUY"

        elif ct == ConditionType.V4_SELL:
            return stock_data.get("v4_signal") == "SELL"

        else:
            logger.warning(f"Unknown condition type: {ct}")
            return False

    except Exception as e:
        logger.debug(f"Condition eval error for {ct}: {e}")
        return False


def evaluate_rule(rule: CompoundRule, stock_data: dict) -> bool:
    """Evaluate a compound rule against stock data."""
    if not rule.conditions:
        return False

    results = [evaluate_condition(c, stock_data) for c in rule.conditions]

    if rule.combine_mode == CombineMode.OR:
        return any(results)
    else:  # AND
        return all(results)


def check_cooldown(rule: CompoundRule) -> bool:
    """Check if enough time has passed since last trigger."""
    if rule.last_triggered == 0:
        return True
    elapsed_hours = (time.time() - rule.last_triggered) / 3600
    return elapsed_hours >= rule.cooldown_hours


def get_stock_indicator_data(code: str) -> dict:
    """Fetch current indicator data for a stock for condition evaluation.

    Returns a flat dict with all fields needed by evaluate_condition().
    """
    try:
        from data.fetcher import get_stock_data
        from analysis.indicators import calculate_all_indicators

        df = get_stock_data(code, period_days=60)
        if df is None or df.empty or len(df) < 20:
            return {}

        indicators = calculate_all_indicators(df)
        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else last

        # Volume average
        avg_vol_20 = float(df["volume"].tail(20).mean()) if "volume" in df.columns else 0

        result = {
            "code": code,
            "price": float(last.get("close", 0)),
            "prev_close": float(prev.get("close", 0)),
            "volume": float(last.get("volume", 0)),
            "avg_volume_20d": avg_vol_20,
        }

        # Extract indicator values
        if indicators:
            cols = indicators.get("columns", {})
            # RSI
            rsi = cols.get("rsi_14", [])
            if rsi:
                result["rsi"] = rsi[-1]

            # MACD
            macd = cols.get("macd", [])
            macd_sig = cols.get("macd_signal", [])
            if macd and macd_sig:
                result["macd"] = macd[-1]
                result["macd_signal"] = macd_sig[-1]
                if len(macd) > 1 and len(macd_sig) > 1:
                    result["macd_prev"] = macd[-2]
                    result["macd_signal_prev"] = macd_sig[-2]

            # KD
            k_vals = cols.get("k", [])
            d_vals = cols.get("d", [])
            if k_vals and d_vals:
                result["k"] = k_vals[-1]
                result["d"] = d_vals[-1]
                if len(k_vals) > 1 and len(d_vals) > 1:
                    result["k_prev"] = k_vals[-2]
                    result["d_prev"] = d_vals[-2]

            # ADX
            adx = cols.get("adx", [])
            if adx:
                result["adx"] = adx[-1]

            # Bollinger Bands
            bb_upper = cols.get("bb_upper", [])
            bb_lower = cols.get("bb_lower", [])
            if bb_upper:
                result["bb_upper"] = bb_upper[-1]
            if bb_lower:
                result["bb_lower"] = bb_lower[-1]

            # MA
            ma5 = cols.get("ma_5", cols.get("sma_5", []))
            ma20 = cols.get("ma_20", cols.get("sma_20", []))
            if ma5 and ma20:
                result["ma_short"] = ma5[-1]
                result["ma_long"] = ma20[-1]
                if len(ma5) > 1 and len(ma20) > 1:
                    result["ma_short_prev"] = ma5[-2]
                    result["ma_long_prev"] = ma20[-2]

        # V4 signal
        try:
            from analysis.strategy_v4 import get_v4_analysis
            v4 = get_v4_analysis(df)
            if v4:
                result["v4_signal"] = v4.get("signal", "HOLD")
        except Exception:
            pass

        return result

    except Exception as e:
        logger.error(f"Failed to get indicator data for {code}: {e}")
        return {}
