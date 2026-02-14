"""市場環境偵測（Market Regime Filter）

判斷大盤目前處於什麼環境，幫助策略決定是否應該降低部位或暫停交易。
v4 是趨勢動量策略，在空頭和盤整市場容易被反覆打臉（Whipsaw）。

環境判定邏輯：
- 多頭 (Bull): 大盤 > MA50 且 MA20 > MA50
- 盤整 (Sideways): 大盤在 MA50 附近震盪
- 空頭 (Bear): 大盤 < MA50 且 MA20 < MA50

建議部位倍率：
- 多頭: 1.0x（正常部位）
- 盤整: 0.5x（降低 50%）
- 空頭: 0.25x（大幅降低）
"""

import pandas as pd
import numpy as np


def detect_market_regime(taiex_df: pd.DataFrame) -> dict:
    """偵測目前的市場環境

    Args:
        taiex_df: TAIEX 大盤 DataFrame（需至少 60 天收盤價）

    Returns:
        dict with keys:
        - regime: "bull" / "sideways" / "bear"
        - regime_label: 中文標籤
        - position_multiplier: 建議部位倍率 (0.25~1.0)
        - ma20: 大盤 MA20
        - ma50: 大盤 MA50
        - close: 最新收盤價
        - ma20_above_ma50: bool
        - dist_ma50_pct: 距離 MA50 百分比
        - trend_strength: "strong" / "moderate" / "weak"
        - detail: 描述文字
    """
    if taiex_df is None or len(taiex_df) < 60:
        return {
            "regime": "unknown",
            "regime_label": "資料不足",
            "position_multiplier": 0.5,
            "detail": "大盤資料不足，無法判斷市場環境。建議保守操作。",
        }

    close = taiex_df["close"]
    ma20 = close.rolling(20).mean()
    ma50 = close.rolling(50).mean()

    latest_close = float(close.iloc[-1])
    latest_ma20 = float(ma20.iloc[-1])
    latest_ma50 = float(ma50.iloc[-1])

    dist_ma50 = (latest_close - latest_ma50) / latest_ma50

    # MA20 > MA50 的連續天數
    ma20_above = ma20 > ma50
    ma20_above_days = 0
    for i in range(len(ma20_above) - 1, -1, -1):
        if ma20_above.iloc[i]:
            ma20_above_days += 1
        else:
            break

    # 近 20 日波動率
    returns_20d = close.pct_change().tail(20)
    volatility = float(returns_20d.std()) if len(returns_20d) > 5 else 0

    # 環境判定
    if latest_close > latest_ma50 and latest_ma20 > latest_ma50:
        if dist_ma50 > 0.05 and ma20_above_days >= 10:
            regime = "bull"
            strength = "strong"
            multiplier = 1.0
            detail = (f"大盤處於強勢多頭（收盤 {latest_close:,.0f}，"
                      f"高於 MA50 {dist_ma50:+.1%}，MA20>MA50 連續 {ma20_above_days} 天）。"
                      f"v4 動量策略環境良好。")
        else:
            regime = "bull"
            strength = "moderate"
            multiplier = 0.8
            detail = (f"大盤溫和上漲（收盤 {latest_close:,.0f}，"
                      f"高於 MA50 {dist_ma50:+.1%}）。可正常操作，但注意回檔風險。")
    elif latest_close < latest_ma50 and latest_ma20 < latest_ma50:
        if dist_ma50 < -0.05:
            regime = "bear"
            strength = "strong"
            multiplier = 0.25
            detail = (f"大盤處於空頭（收盤 {latest_close:,.0f}，"
                      f"低於 MA50 {dist_ma50:+.1%}）。"
                      f"v4 動量策略在空頭市場容易被反覆打臉，建議大幅降低部位。")
        else:
            regime = "bear"
            strength = "moderate"
            multiplier = 0.4
            detail = (f"大盤偏空（收盤 {latest_close:,.0f}，"
                      f"低於 MA50 {dist_ma50:+.1%}）。建議謹慎操作，降低部位。")
    else:
        regime = "sideways"
        strength = "moderate" if volatility < 0.015 else "weak"
        multiplier = 0.5
        detail = (f"大盤盤整震盪（收盤 {latest_close:,.0f}，"
                  f"MA50 附近 {dist_ma50:+.1%}）。"
                  f"趨勢不明確，動量策略效果打折，建議降低部位。")

    return {
        "regime": regime,
        "regime_label": {"bull": "多頭", "sideways": "盤整", "bear": "空頭"}.get(regime, "未知"),
        "position_multiplier": multiplier,
        "ma20": latest_ma20,
        "ma50": latest_ma50,
        "close": latest_close,
        "ma20_above_ma50": latest_ma20 > latest_ma50,
        "ma20_above_days": ma20_above_days,
        "dist_ma50_pct": dist_ma50,
        "trend_strength": strength,
        "volatility_20d": volatility,
        "detail": detail,
    }


def get_regime_color(regime: str) -> str:
    """取得環境對應的顏色"""
    return {
        "bull": "#00C853",
        "sideways": "#FFD600",
        "bear": "#FF1744",
    }.get(regime, "#888888")


def get_regime_emoji(regime: str) -> str:
    """取得環境對應的 emoji"""
    return {
        "bull": "📈",
        "sideways": "📊",
        "bear": "📉",
    }.get(regime, "❓")
