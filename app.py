"""台股技術分析系統 - Streamlit Web 介面"""

import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np

from config import DEFAULT_STOCKS, SCAN_STOCKS, BACKTEST_PARAMS, STRATEGY_PARAMS, RISK_PARAMS, INDICATOR_PARAMS, STRATEGY_V4_PARAMS
from data.fetcher import get_stock_data
from data.stock_list import get_all_stocks, get_stock_name
from data.cache import get_cached_scan_results, set_cached_scan_results, get_cache_stats, flush_cache
from analysis.indicators import calculate_all_indicators
from analysis.strategy import generate_signals, get_latest_analysis
from analysis.strategy_v4 import generate_v4_signals, get_v4_analysis
from analysis.report import generate_report
from backtest.engine import run_backtest, run_backtest_v4, BacktestResult
from simulation.simulator import run_simulation, run_simulation_v4, simulation_to_dataframe, SimulationResult

# ===== 頁面設定 =====
st.set_page_config(
    page_title="台股技術分析系統",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("台股技術分析系統")

# ===== 載入完整股票清單 =====
@st.cache_data(ttl=3600)
def load_stock_list():
    return get_all_stocks()

all_stocks = load_stock_list()

# 建立 selectbox 選項：code name (market)
stock_select_options = sorted(
    [f"{code} {info['name']}" for code, info in all_stocks.items()],
    key=lambda x: x.split()[0],
)

# ===== 側邊欄 =====
with st.sidebar:
    st.header("設定")

    st.caption(f"股票清單：共 {len(all_stocks)} 隻（上市+上櫃）")

    # 搜尋式股票選擇
    selected_display = st.selectbox(
        "搜尋/選擇股票（輸入代碼或名稱）",
        options=stock_select_options,
        index=stock_select_options.index("2330 台積電") if "2330 台積電" in stock_select_options else 0,
    )
    default_code = selected_display.split()[0] if selected_display else "2330"

    # 最近搜尋紀錄（初始化）
    if "recent_stocks" not in st.session_state:
        st.session_state.recent_stocks = []

    def _add_recent(code):
        recents = st.session_state.recent_stocks
        if code in recents:
            recents.remove(code)
        recents.insert(0, code)
        st.session_state.recent_stocks = recents[:5]

    # 處理快捷按鈕跳轉（必須在 text_input 渲染之前設定）
    if st.session_state.get("_pending_stock"):
        st.session_state.custom_code_input = st.session_state.pop("_pending_stock")

    custom_code = st.text_input(
        "或直接輸入股票代碼",
        placeholder="例如: 2330、6748",
        key="custom_code_input",
    )
    stock_code = custom_code.strip() if custom_code.strip() else default_code

    if st.session_state.recent_stocks:
        st.caption("最近查詢")
        cols_count = min(len(st.session_state.recent_stocks), 5)
        recent_cols = st.columns(cols_count)
        for i, code in enumerate(st.session_state.recent_stocks):
            name = get_stock_name(code, all_stocks)
            short_name = name[:4] if len(name) > 4 else name
            with recent_cols[i]:
                if st.button(f"{code}\n{short_name}", key=f"recent_{code}", use_container_width=True):
                    st.session_state["_pending_stock"] = code
                    st.rerun()

    st.divider()

    # 頁面選擇
    page = st.radio(
        "功能",
        options=["技術分析", "回測報告", "模擬交易", "推薦股票", "分析報告"],
        index=0,
    )

    st.divider()

    # 策略版本選擇
    strategy_version = st.radio(
        "策略版本",
        options=["v4（趨勢動量）", "v2（評分系統）"],
        index=0,
        help="v4：趨勢動量+支撐進場+移動停利，回測 WR 54%、平均報酬 +59%\nv2：綜合評分系統+ATR 停損停利",
    )
    use_v4 = strategy_version.startswith("v4")

    st.divider()

    # 參數設定
    with st.expander("進階參數", expanded=False):
        initial_capital = st.number_input(
            "初始資金 (TWD)",
            min_value=100_000,
            max_value=100_000_000,
            value=BACKTEST_PARAMS["initial_capital"],
            step=100_000,
        )
        backtest_days = st.slider("回測天數", 90, 730, 365)
        sim_days = st.slider("模擬交易天數", 10, 60, 30)

        st.caption("策略閾值")
        buy_threshold = st.slider("買入閾值", 0.0, 1.0, STRATEGY_PARAMS["buy_threshold"], 0.05)
        sell_threshold = st.slider("賣出閾值", -1.0, 0.0, STRATEGY_PARAMS["sell_threshold"], 0.05)

        st.caption("風控參數")
        use_atr_stops = st.checkbox("ATR 動態停損停利（v3）", value=RISK_PARAMS.get("use_atr_stops", True))
        if use_atr_stops:
            atr_sl_mult = st.slider("停損倍數 (xATR)", 1.0, 5.0, RISK_PARAMS.get("atr_stop_loss_mult", 3.0), 0.5)
            atr_ts_mult = st.slider("停利倍數 (xATR)", 1.0, 5.0, RISK_PARAMS.get("atr_trailing_mult", 2.5), 0.5)
        else:
            stop_loss = st.slider("停損 (%)", 1, 20, int(RISK_PARAMS["stop_loss"] * 100), 1)
            trailing_stop = st.slider("移動停利 (%)", 1, 20, int(RISK_PARAMS["trailing_stop"] * 100), 1)
        max_position_pct = st.slider("單筆最大部位 (%)", 10, 100, int(RISK_PARAMS["max_position_pct"] * 100), 10)
        min_hold_days = st.number_input("最短持有天數（v3）", min_value=0, max_value=10, value=RISK_PARAMS.get("min_hold_days", 3))

        if use_v4:
            st.caption("v4 策略參數")
            v4_tp = st.slider("停利 (%)", 3, 30, int(STRATEGY_V4_PARAMS["take_profit_pct"] * 100), 1)
            v4_sl = st.slider("停損 (%)", 2, 15, int(STRATEGY_V4_PARAMS["stop_loss_pct"] * 100), 1)
            v4_trail = st.slider("移動停利 (%)", 1, 10, int(STRATEGY_V4_PARAMS["trailing_stop_pct"] * 100), 1)
            v4_hold = st.number_input("最短持有天數", min_value=0, max_value=15, value=STRATEGY_V4_PARAMS["min_hold_days"])
            v4_adx = st.slider("ADX 最低要求", 10, 35, STRATEGY_V4_PARAMS["adx_min"], 1)
        else:
            st.caption("訊號過濾")
            trend_filter = st.checkbox("趨勢過濾（MA20>MA60 才做多）", value=STRATEGY_PARAMS.get("trend_filter", True))
            volume_confirm = st.checkbox("量能確認（買入量>5日均量）", value=STRATEGY_PARAMS.get("volume_confirm", True))
            score_rising = st.checkbox("評分上升確認（v3）", value=STRATEGY_PARAMS.get("score_rising", True))
            confirm_days = st.number_input("訊號確認天數", min_value=1, max_value=5, value=STRATEGY_PARAMS.get("confirm_days", 2))

    # Redis 快取狀態
    with st.expander("快取狀態 (Redis)", expanded=False):
        stats = get_cache_stats()
        if stats["status"] == "connected":
            st.success(f"Redis 已連線")
            st.caption(f"快取鍵數：{stats['keys']} | 記憶體：{stats['memory_used']}")
            if st.button("清空快取"):
                flush_cache()
                st.cache_data.clear()
                st.rerun()
        else:
            st.warning("Redis 未連線（系統仍可正常運作，但速度較慢）")

    # 顏色圖例
    with st.expander("顏色說明", expanded=False):
        st.markdown("""
        **訊號顏色**
        - 🟢 **綠色 / 買入 (BUY)** — 技術面偏多，建議買進
        - 🔴 **紅色 / 賣出 (SELL)** — 技術面偏空，建議賣出
        - 🟡 **黃色 / 持有 (HOLD)** — 訊號不明確，建議觀望

        **指標評分**
        - 🟢 正分 (+) — 該指標偏多頭
        - 🔴 負分 (-) — 該指標偏空頭
        - ⚪ 零分 (0) — 中性

        **K 線圖**
        - 🔴 紅色 K 棒 — 收盤 > 開盤（上漲）
        - 🟢 綠色 K 棒 — 收盤 < 開盤（下跌）
        """)


# ===== 資料載入 =====
@st.cache_data(ttl=300)  # 快取 5 分鐘
def load_data(code: str, days: int):
    return get_stock_data(code, period_days=days)


# 推薦股票/分析報告頁面不需要預先載入單一股票
if page not in ("推薦股票", "分析報告"):
    try:
        fetch_days = max(backtest_days, 365) + 120
        raw_df = load_data(stock_code, fetch_days)
        stock_name = get_stock_name(stock_code, all_stocks)
        _add_recent(stock_code)
        st.sidebar.success(f"已載入 {stock_code} {stock_name}")
    except Exception as e:
        st.error(f"無法載入股票 {stock_code} 的資料：{e}")
        st.stop()

# ===== 覆寫策略閾值 & 風控參數 =====
if use_v4:
    STRATEGY_V4_PARAMS["take_profit_pct"] = v4_tp / 100
    STRATEGY_V4_PARAMS["stop_loss_pct"] = v4_sl / 100
    STRATEGY_V4_PARAMS["trailing_stop_pct"] = v4_trail / 100
    STRATEGY_V4_PARAMS["min_hold_days"] = v4_hold
    STRATEGY_V4_PARAMS["adx_min"] = v4_adx
else:
    STRATEGY_PARAMS["buy_threshold"] = buy_threshold
    STRATEGY_PARAMS["sell_threshold"] = sell_threshold
    STRATEGY_PARAMS["trend_filter"] = trend_filter
    STRATEGY_PARAMS["volume_confirm"] = volume_confirm
    STRATEGY_PARAMS["confirm_days"] = confirm_days
    STRATEGY_PARAMS["score_rising"] = score_rising
    RISK_PARAMS["use_atr_stops"] = use_atr_stops
    if use_atr_stops:
        RISK_PARAMS["atr_stop_loss_mult"] = atr_sl_mult
        RISK_PARAMS["atr_trailing_mult"] = atr_ts_mult
    else:
        RISK_PARAMS["stop_loss"] = stop_loss / 100
        RISK_PARAMS["trailing_stop"] = trailing_stop / 100
    RISK_PARAMS["max_position_pct"] = max_position_pct / 100
    RISK_PARAMS["min_hold_days"] = min_hold_days


# ===== 輔助函式：產生訊號原因說明 =====
def explain_signal(analysis: dict) -> str:
    """根據各指標評分產生訊號原因的中文說明"""
    scores = analysis["scores"]
    indicators = analysis["indicators"]
    signal = analysis["signal"]
    composite = analysis["composite_score"]

    bullish = []  # 偏多的指標
    bearish = []  # 偏空的指標
    neutral = []  # 中性的指標

    # MA
    ma_score = scores["MA"]
    if ma_score > 0:
        bullish.append(f"MA 均線多頭排列（MA5 > MA20），短期趨勢向上")
    elif ma_score < 0:
        bearish.append(f"MA 均線空頭排列（MA5 < MA20），短期趨勢向下")
    else:
        neutral.append("MA 均線方向不明")

    # RSI
    rsi_score = scores["RSI"]
    rsi_val = indicators.get("RSI", 0)
    if rsi_val and not pd.isna(rsi_val):
        if rsi_score > 0.5:
            bullish.append(f"RSI = {rsi_val:.1f}，處於超賣區（< 30），有反彈空間")
        elif rsi_score > 0:
            bullish.append(f"RSI = {rsi_val:.1f}，偏低但未超賣，仍有上漲動能")
        elif rsi_score < -0.5:
            bearish.append(f"RSI = {rsi_val:.1f}，處於超買區（> 70），注意回檔風險")
        elif rsi_score < 0:
            bearish.append(f"RSI = {rsi_val:.1f}，偏高，上漲動能趨緩")
        else:
            neutral.append(f"RSI = {rsi_val:.1f}，處於中性區間")

    # MACD
    macd_score = scores["MACD"]
    if macd_score > 0:
        bullish.append("MACD 多頭訊號，DIF 在 MACD 之上且柱狀體為正")
    elif macd_score < 0:
        bearish.append("MACD 空頭訊號，DIF 在 MACD 之下且柱狀體為負")
    else:
        neutral.append("MACD 訊號不明確")

    # KD
    kd_score = scores["KD"]
    k_val = indicators.get("K", 0)
    d_val = indicators.get("D", 0)
    if k_val and d_val and not pd.isna(k_val):
        if kd_score > 0:
            bullish.append(f"KD 指標 K={k_val:.1f} D={d_val:.1f}，K > D 黃金交叉偏多")
        elif kd_score < 0:
            bearish.append(f"KD 指標 K={k_val:.1f} D={d_val:.1f}，K < D 死亡交叉偏空")

    # 布林通道
    bb_score = scores["布林通道"]
    if bb_score > 0.3:
        bullish.append("股價靠近布林通道下軌，有反彈機會")
    elif bb_score < -0.3:
        bearish.append("股價靠近布林通道上軌，注意壓力")

    # 成交量
    vol_score = scores["成交量"]
    if vol_score > 0:
        bullish.append("成交量配合（量增價漲或量縮整理）")
    elif vol_score < 0:
        bearish.append("量增價跌，可能為出貨訊號")

    # 組合說明
    lines = []

    if signal == "BUY":
        lines.append(f"**建議買入** — 綜合評分 {composite:+.3f}（超過買入閾值 {buy_threshold}）")
    elif signal == "SELL":
        lines.append(f"**建議賣出** — 綜合評分 {composite:+.3f}（低於賣出閾值 {sell_threshold}）")
    else:
        lines.append(f"**建議持有/觀望** — 綜合評分 {composite:+.3f}（介於賣出閾值 {sell_threshold} 與買入閾值 {buy_threshold} 之間，訊號不夠強烈）")

    if bullish:
        lines.append("\n**偏多因素：**")
        for b in bullish:
            lines.append(f"- {b}")

    if bearish:
        lines.append("\n**偏空因素：**")
        for b in bearish:
            lines.append(f"- {b}")

    if neutral:
        lines.append("\n**中性因素：**")
        for n in neutral:
            lines.append(f"- {n}")

    return "\n".join(lines)


# ===== 頁面 1：技術分析 =====
if page == "技術分析":
    st.header(f"{stock_code} {stock_name} - 技術分析")

    if use_v4:
        # v4 分析
        analysis = get_v4_analysis(raw_df)
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("收盤價", f"${analysis['close']:.2f}")
        with col2:
            signal_map = {"BUY": "🟢 買入", "HOLD": "🟡 持有"}
            st.metric("v4 訊號", signal_map.get(analysis["signal"], analysis["signal"]))
        with col3:
            entry_type = analysis["entry_type"] or "—"
            st.metric("進場類型", entry_type)
        with col4:
            ut = analysis["uptrend_days"]
            st.metric("上升趨勢天數", f"{ut} 天")

        # v4 指標明細
        st.subheader("v4 策略指標")
        ind = analysis["indicators"]
        ind_cols = st.columns(4)
        with ind_cols[0]:
            adx_val = ind.get("ADX")
            st.metric("ADX", f"{adx_val:.1f}" if adx_val and not pd.isna(adx_val) else "N/A",
                      help=f"要求 ≥ {STRATEGY_V4_PARAMS['adx_min']}")
        with ind_cols[1]:
            rsi_val = ind.get("RSI")
            st.metric("RSI", f"{rsi_val:.1f}" if rsi_val and not pd.isna(rsi_val) else "N/A")
        with ind_cols[2]:
            di_p = ind.get("+DI")
            di_m = ind.get("-DI")
            if di_p and di_m and not pd.isna(di_p):
                st.metric("+DI / -DI", f"{di_p:.1f} / {di_m:.1f}")
            else:
                st.metric("+DI / -DI", "N/A")
        with ind_cols[3]:
            dist = analysis["dist_ma20"]
            st.metric("距離 MA20", f"{dist:+.1%}" if not pd.isna(dist) else "N/A")

        # v4 訊號說明
        st.subheader("v4 訊號分析")
        if analysis["signal"] == "BUY":
            st.success(f"**建議買入**（{analysis['entry_type']}模式）— 趨勢確認 {ut} 天，ADX={ind.get('ADX', 0):.1f}，RSI={ind.get('RSI', 0):.1f}")
        else:
            reasons = []
            if ut < STRATEGY_V4_PARAMS["min_uptrend_days"]:
                reasons.append(f"上升趨勢天數不足（{ut} < {STRATEGY_V4_PARAMS['min_uptrend_days']}）")
            if adx_val and not pd.isna(adx_val) and adx_val < STRATEGY_V4_PARAMS["adx_min"]:
                reasons.append(f"ADX 趨勢強度不足（{adx_val:.1f} < {STRATEGY_V4_PARAMS['adx_min']}）")
            if di_p and di_m and not pd.isna(di_p) and di_p <= di_m:
                reasons.append(f"+DI ≤ -DI，方向偏空")
            if not reasons:
                reasons.append("進場條件未滿足（支撐/動量模式均未觸發）")
            st.warning("**建議觀望** — " + "；".join(reasons))
    else:
        # v2 分析
        analysis = get_latest_analysis(raw_df)
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("收盤價", f"${analysis['close']:.2f}")
        with col2:
            signal_map = {"BUY": "🟢 買入", "SELL": "🔴 賣出", "HOLD": "🟡 持有"}
            st.metric("訊號", signal_map.get(analysis["signal"], analysis["signal"]))
        with col3:
            st.metric("綜合評分", f"{analysis['composite_score']:.3f}")
        with col4:
            rsi_val = analysis["indicators"].get("RSI", 0)
            st.metric("RSI", f"{rsi_val:.1f}" if rsi_val else "N/A")

        # 各指標評分
        st.subheader("指標評分明細")
        score_cols = st.columns(6)
        for i, (name, score) in enumerate(analysis["scores"].items()):
            with score_cols[i]:
                color = "🟢" if score > 0 else "🔴" if score < 0 else "⚪"
                st.metric(name, f"{color} {score:+.2f}")

        # 訊號原因說明
        st.subheader("訊號分析原因")
        explanation = explain_signal(analysis)
        st.markdown(explanation)

    # K線圖 + 技術指標
    if use_v4:
        signals_df = generate_v4_signals(raw_df).tail(120)
    else:
        signals_df = generate_signals(raw_df).tail(120)

    fig = make_subplots(
        rows=4, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.45, 0.18, 0.18, 0.19],
        subplot_titles=("K線圖 / MA / 布林通道", "MACD", "KD 隨機指標", "成交量"),
    )

    # K線
    fig.add_trace(go.Candlestick(
        x=signals_df.index,
        open=signals_df["open"],
        high=signals_df["high"],
        low=signals_df["low"],
        close=signals_df["close"],
        name="K線",
        increasing_line_color="#EF5350",  # 台股漲紅
        decreasing_line_color="#26A69A",  # 台股跌綠
    ), row=1, col=1)

    # MA
    for ma_col, color, name in [
        ("ma5", "#FF9800", "MA5"),
        ("ma20", "#2196F3", "MA20"),
        ("ma60", "#9C27B0", "MA60"),
    ]:
        if ma_col in signals_df.columns:
            fig.add_trace(go.Scatter(
                x=signals_df.index, y=signals_df[ma_col],
                mode="lines", name=name, line=dict(color=color, width=1),
            ), row=1, col=1)

    # 布林通道
    if "bb_upper" in signals_df.columns:
        fig.add_trace(go.Scatter(
            x=signals_df.index, y=signals_df["bb_upper"],
            mode="lines", name="布林上軌",
            line=dict(color="rgba(128,128,128,0.3)", width=1, dash="dot"),
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=signals_df.index, y=signals_df["bb_lower"],
            mode="lines", name="布林下軌",
            line=dict(color="rgba(128,128,128,0.3)", width=1, dash="dot"),
            fill="tonexty", fillcolor="rgba(128,128,128,0.05)",
        ), row=1, col=1)

    # 買賣訊號標記
    signal_col = "v4_signal" if use_v4 else "signal"
    buy_signals = signals_df[signals_df[signal_col] == "BUY"]
    sell_signals = signals_df[signals_df[signal_col] == "SELL"] if not use_v4 else signals_df.iloc[0:0]

    if not buy_signals.empty:
        fig.add_trace(go.Scatter(
            x=buy_signals.index, y=buy_signals["low"] * 0.98,
            mode="markers", name="買入訊號",
            marker=dict(symbol="triangle-up", size=12, color="#EF5350"),
        ), row=1, col=1)
    if not sell_signals.empty:
        fig.add_trace(go.Scatter(
            x=sell_signals.index, y=sell_signals["high"] * 1.02,
            mode="markers", name="賣出訊號",
            marker=dict(symbol="triangle-down", size=12, color="#26A69A"),
        ), row=1, col=1)

    # MACD
    colors = ["#EF5350" if v >= 0 else "#26A69A" for v in signals_df["macd_hist"]]
    fig.add_trace(go.Bar(
        x=signals_df.index, y=signals_df["macd_hist"],
        name="MACD 柱", marker_color=colors,
    ), row=2, col=1)
    fig.add_trace(go.Scatter(
        x=signals_df.index, y=signals_df["macd"],
        mode="lines", name="MACD", line=dict(color="#2196F3", width=1),
    ), row=2, col=1)
    fig.add_trace(go.Scatter(
        x=signals_df.index, y=signals_df["macd_signal"],
        mode="lines", name="Signal", line=dict(color="#FF9800", width=1),
    ), row=2, col=1)

    # KD
    fig.add_trace(go.Scatter(
        x=signals_df.index, y=signals_df["k"],
        mode="lines", name="K", line=dict(color="#2196F3", width=1),
    ), row=3, col=1)
    fig.add_trace(go.Scatter(
        x=signals_df.index, y=signals_df["d"],
        mode="lines", name="D", line=dict(color="#FF9800", width=1),
    ), row=3, col=1)
    fig.add_hline(y=80, line_dash="dash", line_color="red", opacity=0.5, row=3, col=1)
    fig.add_hline(y=20, line_dash="dash", line_color="green", opacity=0.5, row=3, col=1)

    # 成交量
    vol_colors = [
        "#EF5350" if signals_df["close"].iloc[i] >= signals_df["open"].iloc[i] else "#26A69A"
        for i in range(len(signals_df))
    ]
    fig.add_trace(go.Bar(
        x=signals_df.index, y=signals_df["volume"],
        name="成交量", marker_color=vol_colors,
    ), row=4, col=1)
    if "volume_ma5" in signals_df.columns:
        fig.add_trace(go.Scatter(
            x=signals_df.index, y=signals_df["volume_ma5"],
            mode="lines", name="5日均量",
            line=dict(color="#FF9800", width=1),
        ), row=4, col=1)

    fig.update_layout(
        height=900,
        xaxis_rangeslider_visible=False,
        template="plotly_dark",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_xaxes(type="category", row=4, col=1)

    st.plotly_chart(fig, use_container_width=True)


# ===== 頁面 2：回測報告 =====
elif page == "回測報告":
    st.header(f"{stock_code} {stock_name} - 回測報告")

    with st.spinner("正在執行回測..."):
        backtest_df = raw_df.tail(backtest_days + 60)
        if use_v4:
            result = run_backtest_v4(backtest_df, initial_capital=initial_capital)
        else:
            result = run_backtest(backtest_df, initial_capital=initial_capital)

    # 績效指標
    st.subheader("績效摘要")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("總報酬率", f"{result.total_return:.2%}")
    with col2:
        st.metric("年化報酬率", f"{result.annual_return:.2%}")
    with col3:
        st.metric("最大回撤", f"{result.max_drawdown:.2%}")
    with col4:
        st.metric("Sharpe Ratio", f"{result.sharpe_ratio:.2f}")

    col5, col6, col7, col8 = st.columns(4)
    with col5:
        st.metric("總交易次數", f"{result.total_trades}")
    with col6:
        st.metric("勝率", f"{result.win_rate:.2%}")
    with col7:
        st.metric("盈虧比", f"{result.profit_factor:.2f}")
    with col8:
        st.metric("平均持有天數", f"{result.avg_holding_days:.1f}")

    # 權益曲線
    st.subheader("權益曲線")
    if not result.equity_curve.empty:
        fig_equity = go.Figure()
        fig_equity.add_trace(go.Scatter(
            x=result.equity_curve.index,
            y=result.equity_curve.values,
            mode="lines",
            name="權益",
            fill="tozeroy",
            line=dict(color="#2196F3"),
        ))
        fig_equity.add_hline(
            y=initial_capital,
            line_dash="dash",
            line_color="white",
            opacity=0.5,
            annotation_text="初始資金",
        )
        fig_equity.update_layout(
            height=400,
            template="plotly_dark",
            yaxis_title="權益 (TWD)",
            xaxis_title="日期",
        )
        st.plotly_chart(fig_equity, use_container_width=True)

    # 每日報酬分布
    st.subheader("每日報酬分布")
    if not result.daily_returns.empty:
        fig_dist = go.Figure()
        fig_dist.add_trace(go.Histogram(
            x=result.daily_returns * 100,
            nbinsx=50,
            name="每日報酬 (%)",
            marker_color="#2196F3",
        ))
        fig_dist.update_layout(
            height=300,
            template="plotly_dark",
            xaxis_title="每日報酬 (%)",
            yaxis_title="次數",
        )
        st.plotly_chart(fig_dist, use_container_width=True)

    # 交易紀錄
    st.subheader("交易紀錄")
    if result.trades:
        exit_reason_map = {
            "signal": "訊號賣出",
            "stop_loss": "停損",
            "trailing_stop": "移動停利",
            "take_profit": "停利",
            "end_of_period": "期末平倉",
        }
        trade_data = []
        for t in result.trades:
            trade_data.append({
                "買入日期": t.date_open.strftime("%Y-%m-%d") if t.date_open else "",
                "賣出日期": t.date_close.strftime("%Y-%m-%d") if t.date_close else "",
                "股數": t.shares,
                "買入價": f"${t.price_open:.2f}",
                "賣出價": f"${t.price_close:.2f}",
                "出場原因": exit_reason_map.get(t.exit_reason, t.exit_reason),
                "手續費": f"${t.commission:,.0f}",
                "交易稅": f"${t.tax:,.0f}",
                "損益": f"${t.pnl:,.0f}",
                "報酬率": f"{t.return_pct:.2%}",
            })
        st.dataframe(pd.DataFrame(trade_data), use_container_width=True)
    else:
        st.info("回測期間沒有產生交易")


# ===== 頁面 3：模擬交易 =====
elif page == "模擬交易":
    st.header(f"{stock_code} {stock_name} - 模擬交易（最近 {sim_days} 個交易日）")

    with st.spinner("正在執行模擬..."):
        if use_v4:
            sim_result = run_simulation_v4(raw_df, initial_capital=initial_capital, days=sim_days)
        else:
            sim_result = run_simulation(raw_df, initial_capital=initial_capital, days=sim_days)

    # 績效摘要
    st.subheader("模擬績效")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric(
            "最終權益",
            f"${sim_result.final_equity:,.0f}",
            delta=f"{sim_result.total_return:+.2%}",
        )
    with col2:
        st.metric("最大回撤", f"{sim_result.max_drawdown:.2%}")
    with col3:
        st.metric("交易次數", f"{sim_result.total_trades}")
    with col4:
        win_rate = (
            sim_result.winning_trades / sim_result.total_trades
            if sim_result.total_trades > 0
            else 0
        )
        st.metric("勝率", f"{win_rate:.0%}")

    col5, col6, col7, col8 = st.columns(4)
    with col5:
        st.metric("初始資金", f"${sim_result.initial_capital:,.0f}")
    with col6:
        pnl = sim_result.final_equity - sim_result.initial_capital
        st.metric("總損益", f"${pnl:,.0f}")
    with col7:
        st.metric("總手續費", f"${sim_result.total_commission:,.0f}")
    with col8:
        st.metric("總交易稅", f"${sim_result.total_tax:,.0f}")

    # 權益曲線
    st.subheader("每日權益變化")
    if sim_result.daily_records:
        dates = [r.date for r in sim_result.daily_records]
        equities = [r.total_equity for r in sim_result.daily_records]

        fig_sim = go.Figure()
        fig_sim.add_trace(go.Scatter(
            x=dates, y=equities,
            mode="lines+markers",
            name="總權益",
            line=dict(color="#2196F3", width=2),
            marker=dict(size=4),
        ))
        fig_sim.add_hline(
            y=initial_capital,
            line_dash="dash",
            line_color="white",
            opacity=0.5,
            annotation_text="初始資金",
        )
        fig_sim.update_layout(
            height=400,
            template="plotly_dark",
            yaxis_title="權益 (TWD)",
        )
        st.plotly_chart(fig_sim, use_container_width=True)

    # 每日損益柱狀圖
    st.subheader("每日損益")
    if sim_result.daily_records:
        dates = [r.date for r in sim_result.daily_records]
        pnls = [r.daily_pnl for r in sim_result.daily_records]
        colors = ["#EF5350" if p >= 0 else "#26A69A" for p in pnls]

        fig_pnl = go.Figure()
        fig_pnl.add_trace(go.Bar(
            x=dates, y=pnls,
            name="每日損益",
            marker_color=colors,
        ))
        fig_pnl.update_layout(
            height=300,
            template="plotly_dark",
            yaxis_title="損益 (TWD)",
        )
        st.plotly_chart(fig_pnl, use_container_width=True)

    # 交易明細
    st.subheader("交易明細")
    if sim_result.trade_log:
        trade_df = pd.DataFrame(sim_result.trade_log)
        trade_df["日期"] = trade_df["日期"].dt.strftime("%Y-%m-%d")
        st.dataframe(trade_df, use_container_width=True)
    else:
        st.info("模擬期間沒有產生交易")

    # 每日紀錄
    st.subheader("每日模擬紀錄")
    sim_df = simulation_to_dataframe(sim_result)
    sim_df["日期"] = pd.to_datetime(sim_df["日期"]).dt.strftime("%Y-%m-%d")
    st.dataframe(sim_df, use_container_width=True, height=400)


# ===== 頁面 4：推薦股票 =====
elif page == "推薦股票":
    if use_v4:
        st.header("推薦股票 — v4 趨勢動量掃描")
        st.caption("掃描股票池，篩選 v4 策略發出「買入」訊號的股票。只推薦真正值得進場的標的。")
    else:
        st.header("推薦股票 — v2 技術面綜合評分")
        st.caption("掃描股票池，篩選綜合評分達到買入閾值的股票。")

    # 掃描範圍選擇
    scan_scope = st.radio(
        "掃描範圍",
        ["全部股票（較慢，首次約 5-15 分鐘）", "精選 25 檔（快速）"],
        horizontal=True,
    )
    use_full_scan = scan_scope.startswith("全部")
    scan_pool = all_stocks if use_full_scan else SCAN_STOCKS

    def _resolve_name(name):
        return name.get("name", "") if isinstance(name, dict) else name

    def scan_stocks_v4(stock_dict: dict):
        """用 v4 策略掃描，只回傳 BUY 訊號"""
        cached = get_cached_scan_results()
        if cached and isinstance(cached, list) and len(cached) > 0 and "entry_type" in cached[0]:
            return cached

        results = []
        progress_bar = st.progress(0, text="掃描中...")
        total = len(stock_dict)
        for i, (code, name) in enumerate(stock_dict.items()):
            display_name = _resolve_name(name)
            progress_bar.progress((i + 1) / total, text=f"掃描 {code} {display_name}... ({i+1}/{total})")
            try:
                df = get_stock_data(code, period_days=200)
                if df is None or len(df) < 60:
                    continue
                analysis = get_v4_analysis(df)
                analysis["code"] = code
                analysis["name"] = display_name
                if analysis["signal"] == "BUY":
                    results.append(analysis)
            except Exception:
                continue
        progress_bar.empty()

        if results:
            set_cached_scan_results(results, ttl=600)
        return results

    def scan_stocks_v2(stock_dict: dict):
        """用 v2 評分掃描全部股票"""
        cached = get_cached_scan_results()
        if cached and isinstance(cached, list) and len(cached) > 0 and "composite_score" in cached[0]:
            return cached

        results = []
        progress_bar = st.progress(0, text="掃描中...")
        total = len(stock_dict)
        for i, (code, name) in enumerate(stock_dict.items()):
            display_name = _resolve_name(name)
            progress_bar.progress((i + 1) / total, text=f"掃描 {code} {display_name}... ({i+1}/{total})")
            try:
                df = get_stock_data(code, period_days=200)
                if df is None or len(df) < 60:
                    continue
                analysis = get_latest_analysis(df)
                analysis["code"] = code
                analysis["name"] = display_name
                results.append(analysis)
            except Exception:
                continue
        progress_bar.empty()

        if results:
            set_cached_scan_results(results, ttl=600)
        return results

    if st.button("開始掃描", type="primary"):
        if use_v4:
            # ===== v4 掃描 =====
            buy_results = scan_stocks_v4(scan_pool)

            if not buy_results:
                st.warning(
                    f"掃描完成（共 {len(scan_pool)} 檔），目前沒有任何股票符合 v4 買入條件。\n\n"
                    "v4 進場條件較嚴格（ADX≥18 + MA20>MA60 連續10天 + 支撐反彈或動量突破），"
                    "代表目前市場可能缺乏明確趨勢機會，建議耐心等待。"
                )
            else:
                st.success(f"掃描完成（共 {len(scan_pool)} 檔），找到 **{len(buy_results)}** 檔符合 v4 買入條件！")

                buy_results.sort(key=lambda x: x.get("uptrend_days", 0), reverse=True)
                entry_type_map = {"support": "支撐反彈", "momentum": "動量突破"}

                for rank, stock in enumerate(buy_results[:10], 1):
                    st.subheader(f"第 {rank} 名：{stock['code']} {stock['name']}")

                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.metric("收盤價", f"${stock['close']:.2f}")
                    with col2:
                        st.metric("進場類型", entry_type_map.get(stock.get("entry_type", ""), "—"))
                    with col3:
                        st.metric("上升趨勢天數", f"{stock.get('uptrend_days', 0)} 天")
                    with col4:
                        st.metric("距離 MA20", f"{stock.get('dist_ma20', 0):.1%}")

                    ind = stock.get("indicators", {})
                    ind_cols = st.columns(5)
                    for j, label in enumerate(["ADX", "RSI", "+DI", "-DI", "ROC"]):
                        with ind_cols[j]:
                            val = ind.get(label)
                            st.metric(label, f"{val:.1f}" if val is not None and not pd.isna(val) else "—")
                    st.divider()

                # 全部列表
                st.subheader("全部買入訊號股票")
                table_data = []
                for i, s in enumerate(buy_results, 1):
                    ind = s.get("indicators", {})
                    table_data.append({
                        "排名": i,
                        "代碼": s["code"],
                        "名稱": s["name"],
                        "收盤價": f"${s['close']:.2f}",
                        "進場類型": entry_type_map.get(s.get("entry_type", ""), "—"),
                        "趨勢天數": s.get("uptrend_days", 0),
                        "距離MA20": f"{s.get('dist_ma20', 0):.1%}",
                        "ADX": f"{ind.get('ADX', 0):.1f}" if ind.get("ADX") else "—",
                        "RSI": f"{ind.get('RSI', 0):.1f}" if ind.get("RSI") else "—",
                    })
                st.dataframe(pd.DataFrame(table_data), use_container_width=True, hide_index=True)

        else:
            # ===== v2 掃描 =====
            all_scan = scan_stocks_v2(scan_pool)

            if not all_scan:
                st.error("無法取得任何股票資料")
            else:
                buy_only = [s for s in all_scan if s["signal"] == "BUY"]

                if not buy_only:
                    st.warning(
                        f"掃描完成（共 {len(scan_pool)} 檔），目前沒有股票綜合評分達到買入閾值（≥ {STRATEGY_PARAMS['buy_threshold']}）。\n\n"
                        "建議耐心等待更好的進場時機。以下為全部股票評分排行僅供參考。"
                    )
                    sorted_results = sorted(all_scan, key=lambda x: x["composite_score"], reverse=True)
                else:
                    st.success(f"掃描完成（共 {len(scan_pool)} 檔），找到 **{len(buy_only)}** 檔發出買入訊號！")
                    sorted_results = sorted(buy_only, key=lambda x: x["composite_score"], reverse=True)

                    for rank, stock in enumerate(sorted_results[:10], 1):
                        st.subheader(f"第 {rank} 名：{stock['code']} {stock['name']}")
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.metric("收盤價", f"${stock['close']:.2f}")
                        with col2:
                            st.metric("訊號", "🟢 買入")
                        with col3:
                            st.metric("綜合評分", f"{stock['composite_score']:+.3f}")
                        explanation = explain_signal(stock)
                        st.markdown(explanation)
                        score_cols = st.columns(6)
                        for j, (sname, score) in enumerate(stock["scores"].items()):
                            with score_cols[j]:
                                icon = "🟢" if score > 0 else "🔴" if score < 0 else "⚪"
                                st.metric(sname, f"{icon} {score:+.2f}")
                        st.divider()

                # 全部排行表
                if not buy_only:
                    sorted_results = sorted(all_scan, key=lambda x: x["composite_score"], reverse=True)
                st.subheader("全部股票評分排行")
                ranking_data = []
                for i, s in enumerate(sorted_results, 1):
                    signal_map = {"BUY": "🟢 買入", "SELL": "🔴 賣出", "HOLD": "🟡 持有"}
                    ranking_data.append({
                        "排名": i,
                        "代碼": s["code"],
                        "名稱": s["name"],
                        "收盤價": f"${s['close']:.2f}",
                        "訊號": signal_map.get(s["signal"], s["signal"]),
                        "綜合評分": f"{s['composite_score']:+.3f}",
                    })
                st.dataframe(pd.DataFrame(ranking_data), use_container_width=True, hide_index=True)


# ===== 頁面 5：分析報告 =====
elif page == "分析報告":
    st.header(f"分析報告 — {stock_code}")

    def _esc(text: str) -> str:
        """Escape $ signs to prevent Streamlit LaTeX rendering"""
        return text.replace("$", "\\$") if text else text

    if st.button("產生分析報告", type="primary"):
        with st.spinner("正在產生專業分析報告，請稍候（約 10-30 秒）..."):
            try:
                report = generate_report(stock_code, period_days=730)
                _add_recent(stock_code)
            except Exception as e:
                st.error(f"報告產生失敗：{e}")
                st.stop()

        # ---- 綜合評等 Banner ----
        rating_colors = {
            "強力買進": ("#1B5E20", "#C8E6C9"),
            "買進": ("#2E7D32", "#E8F5E9"),
            "中性": ("#F57F17", "#FFF9C4"),
            "賣出": ("#C62828", "#FFCDD2"),
            "強力賣出": ("#B71C1C", "#FFCDD2"),
        }
        bg, fg = rating_colors.get(report.overall_rating, ("#424242", "#EEEEEE"))
        st.markdown(
            f'<div style="background-color:{bg};color:{fg};padding:20px;border-radius:12px;'
            f'text-align:center;margin-bottom:20px">'
            f'<h1 style="margin:0;color:{fg}">{report.stock_name}（{report.stock_code}）</h1>'
            f'<h2 style="margin:8px 0;color:{fg}">綜合評等：{report.overall_rating}</h2>'
            f'<p style="margin:0;font-size:1.1em;color:{fg}">收盤價 ${report.current_price:.2f} '
            f'| 趨勢 {report.trend_direction} | 動能 {report.momentum_status}</p>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # ---- 一、公司概況 ----
        st.subheader("一、公司概況")
        info = report.company_info
        info_cols = st.columns(4)
        with info_cols[0]:
            st.metric("股票代碼", report.stock_code)
        with info_cols[1]:
            st.metric("公司名稱", report.stock_name)
        with info_cols[2]:
            sector = info.get("sector") or info.get("industry") or "N/A"
            st.metric("產業", sector)
        with info_cols[3]:
            mc = info.get("market_cap", 0)
            if mc and mc > 0:
                if mc >= 1e12:
                    st.metric("市值", f"${mc/1e12:.1f} 兆")
                elif mc >= 1e8:
                    st.metric("市值", f"${mc/1e8:.1f} 億")
                else:
                    st.metric("市值", f"${mc:,.0f}")
            else:
                st.metric("市值", "N/A")

        # ---- 二、價格表現 ----
        st.subheader("二、價格表現")
        perf_cols = st.columns(5)
        for i, (label, val) in enumerate([
            ("1 週", report.price_change_1w),
            ("1 個月", report.price_change_1m),
            ("3 個月", report.price_change_3m),
            ("6 個月", report.price_change_6m),
            ("1 年", report.price_change_1y),
        ]):
            with perf_cols[i]:
                st.metric(label, f"{val:+.2%}")

        hw_cols = st.columns(4)
        with hw_cols[0]:
            st.metric("52 週最高", f"${report.high_52w:.2f}")
        with hw_cols[1]:
            st.metric("最高日期", report.high_52w_date)
        with hw_cols[2]:
            st.metric("52 週最低", f"${report.low_52w:.2f}")
        with hw_cols[3]:
            st.metric("最低日期", report.low_52w_date)

        dist_cols = st.columns(2)
        with dist_cols[0]:
            st.metric("距 52 週高點", f"{report.pct_from_52w_high:+.2%}")
        with dist_cols[1]:
            st.metric("距 52 週低點", f"{report.pct_from_52w_low:+.2%}")

        # ---- 三、基本面分析 ----
        st.subheader("三、基本面分析")
        if report.fundamentals and any(v != "N/A" for v in report.fundamentals.values()):
            fm = report.fundamentals
            # Row 1: 估值與 EPS
            fund_r1 = st.columns(5)
            with fund_r1[0]:
                st.metric("本益比 (TTM)", fm.get("trailing_pe", "N/A"))
            with fund_r1[1]:
                st.metric("預估本益比", fm.get("forward_pe", "N/A"))
            with fund_r1[2]:
                st.metric("股價淨值比", fm.get("price_to_book", "N/A"))
            with fund_r1[3]:
                st.metric("EPS (TTM)", fm.get("trailing_eps", "N/A"))
            with fund_r1[4]:
                st.metric("預估 EPS", fm.get("forward_eps", "N/A"))

            # Row 2: 成長 & 報酬率
            fund_r2 = st.columns(4)
            with fund_r2[0]:
                st.metric("獲利成長率", fm.get("earnings_growth", "N/A"))
            with fund_r2[1]:
                st.metric("營收成長率", fm.get("revenue_growth", "N/A"))
            with fund_r2[2]:
                st.metric("ROE", fm.get("roe", "N/A"))
            with fund_r2[3]:
                st.metric("ROA", fm.get("roa", "N/A"))

            # Row 3: 利潤率 & 財務健全
            fund_r3 = st.columns(5)
            with fund_r3[0]:
                st.metric("毛利率", fm.get("gross_margins", "N/A"))
            with fund_r3[1]:
                st.metric("營業利益率", fm.get("operating_margins", "N/A"))
            with fund_r3[2]:
                st.metric("淨利率", fm.get("profit_margins", "N/A"))
            with fund_r3[3]:
                st.metric("負債權益比", fm.get("debt_to_equity", "N/A"))
            with fund_r3[4]:
                st.metric("流動比率", fm.get("current_ratio", "N/A"))

            # Row 4: 股利 & 風險 & 評分
            fund_r4 = st.columns(4)
            with fund_r4[0]:
                st.metric("殖利率", fm.get("dividend_yield", "N/A"))
            with fund_r4[1]:
                st.metric("年配息", fm.get("dividend_rate", "N/A"))
            with fund_r4[2]:
                st.metric("Beta", fm.get("beta", "N/A"))
            with fund_r4[3]:
                score_color = "🟢" if report.fundamental_score >= 2 else "🔴" if report.fundamental_score <= -2 else "🟡"
                st.metric("基本面評分", f"{score_color} {report.fundamental_score:+.1f}")

            # 法人共識
            ad = report.analyst_data
            if ad and ad.get("target_mean"):
                st.markdown("**法人共識**")
                an_cols = st.columns(5)
                with an_cols[0]:
                    n = ad.get("num_analysts")
                    st.metric("分析師人數", f"{int(n)}" if n else "N/A")
                with an_cols[1]:
                    st.metric("目標均價", f"\\${ad['target_mean']:.0f}")
                with an_cols[2]:
                    med = ad.get("target_median")
                    st.metric("中位數", f"\\${med:.0f}" if med else "N/A")
                with an_cols[3]:
                    hi = ad.get("target_high")
                    st.metric("最高", f"\\${hi:.0f}" if hi else "N/A")
                with an_cols[4]:
                    lo = ad.get("target_low")
                    st.metric("最低", f"\\${lo:.0f}" if lo else "N/A")
                upside = ad.get("upside", 0)
                if upside > 0:
                    st.success(f"法人目標均價較現價上檔空間 {upside:.0%}")
                elif upside < -0.05:
                    st.warning(f"法人目標均價較現價下檔 {abs(upside):.0%}")

            # 基本面解讀
            if report.fundamental_interpretation:
                st.markdown(_esc(report.fundamental_interpretation))
        else:
            st.info("此股票基本面數據不足，可能為小型股或上櫃股，yfinance 尚未提供完整基本面資料。")

        # ---- 四、技術面總覽 ----
        st.subheader("四、技術面總覽")
        trend_cols = st.columns(4)
        with trend_cols[0]:
            st.metric("趨勢方向", report.trend_direction)
        with trend_cols[1]:
            st.metric("趨勢強度", report.trend_strength)
        with trend_cols[2]:
            st.metric("均線排列", report.ma_alignment)
        with trend_cols[3]:
            st.metric("動能狀態", report.momentum_status)

        # ---- 五、支撐壓力分析 ----
        st.subheader("五、支撐壓力分析")
        sr_col1, sr_col2 = st.columns(2)
        with sr_col1:
            st.markdown("**壓力位**")
            if report.resistance_levels:
                r_data = []
                for r in report.resistance_levels:
                    stars = "★" * r.strength + "☆" * (3 - r.strength)
                    r_data.append({
                        "價位": f"${r.price:.2f}",
                        "來源": r.source,
                        "強度": stars,
                        "距離": f"{(r.price / report.current_price - 1):+.2%}",
                    })
                st.dataframe(pd.DataFrame(r_data), hide_index=True, width=400)
            else:
                st.info("無明顯壓力位")
        with sr_col2:
            st.markdown("**支撐位**")
            if report.support_levels:
                s_data = []
                for s in report.support_levels:
                    stars = "★" * s.strength + "☆" * (3 - s.strength)
                    s_data.append({
                        "價位": f"${s.price:.2f}",
                        "來源": s.source,
                        "強度": stars,
                        "距離": f"{(s.price / report.current_price - 1):+.2%}",
                    })
                st.dataframe(pd.DataFrame(s_data), hide_index=True, width=400)
            else:
                st.info("無明顯支撐位")

        # ---- 六、費氏回檔分析 ----
        st.subheader("六、費氏回檔分析")
        fib = report.fibonacci
        fib_info_cols = st.columns(3)
        with fib_info_cols[0]:
            st.metric("波段高點", f"${fib.swing_high:.2f}")
        with fib_info_cols[1]:
            st.metric("波段低點", f"${fib.swing_low:.2f}")
        with fib_info_cols[2]:
            st.metric("方向", "上升趨勢" if fib.direction == "uptrend" else "下降趨勢")

        fib_col1, fib_col2 = st.columns(2)
        with fib_col1:
            st.markdown("**回檔水位**")
            ret_data = [{"比率": f"{k:.1%}", "價位": f"${v:.2f}", "距離": f"{(v / report.current_price - 1):+.2%}"}
                        for k, v in fib.retracement.items()]
            st.dataframe(pd.DataFrame(ret_data), hide_index=True, width=350)
        with fib_col2:
            st.markdown("**延伸水位**")
            ext_data = [{"比率": f"{k:.1%}", "價位": f"${v:.2f}", "距離": f"{(v / report.current_price - 1):+.2%}"}
                        for k, v in fib.extension.items()]
            st.dataframe(pd.DataFrame(ext_data), hide_index=True, width=350)

        # 費氏 K 線圖
        st.markdown("**費氏回檔 K 線圖**")
        fib_df = report.indicators_df.tail(120) if report.indicators_df is not None else None
        if fib_df is not None:
            fig_fib = go.Figure()
            fig_fib.add_trace(go.Candlestick(
                x=list(range(len(fib_df))),
                open=fib_df["open"], high=fib_df["high"],
                low=fib_df["low"], close=fib_df["close"],
                name="K線",
                increasing_line_color="#EF5350",
                decreasing_line_color="#26A69A",
            ))
            # Fibonacci 水平線
            colors_fib = ["#FFD54F", "#FFB74D", "#FF8A65", "#E57373", "#EF5350"]
            for i_f, (ratio, price) in enumerate(fib.retracement.items()):
                fig_fib.add_hline(
                    y=price, line_dash="dash",
                    line_color=colors_fib[i_f % len(colors_fib)],
                    opacity=0.7,
                    annotation_text=f"Fib {ratio:.1%} (${price:.2f})",
                    annotation_position="right",
                )
            for ratio, price in fib.extension.items():
                fig_fib.add_hline(
                    y=price, line_dash="dot",
                    line_color="#81C784", opacity=0.6,
                    annotation_text=f"Ext {ratio:.1%} (${price:.2f})",
                    annotation_position="left",
                )
            fig_fib.update_layout(
                height=500, template="plotly_dark",
                xaxis_rangeslider_visible=False,
                title=f"{report.stock_name} 費氏回檔分析",
            )
            st.plotly_chart(fig_fib, use_container_width=True)

        # ---- 七、目標價估算 ----
        st.subheader("七、目標價估算")
        for tf_label in ["3M", "6M", "1Y"]:
            tf_map = {"3M": "三個月", "6M": "六個月", "1Y": "一年"}
            st.markdown(f"**{tf_map[tf_label]}目標價**")
            tf_targets = [t for t in report.price_targets if t.timeframe == tf_label]
            tgt_cols = st.columns(3)
            scenario_map = {"bull": ("樂觀", "🟢"), "base": ("基本", "🟡"), "bear": ("保守", "🔴")}
            for t in tf_targets:
                s_label, s_icon = scenario_map.get(t.scenario, (t.scenario, ""))
                col_idx = 0 if t.scenario == "bull" else 1 if t.scenario == "base" else 2
                with tgt_cols[col_idx]:
                    st.metric(
                        f"{s_icon} {s_label}情境",
                        f"${t.target_price:.2f}",
                        delta=f"{t.upside_pct:+.2%}",
                    )
                    st.caption(f"信心度：{t.confidence} | {t.rationale[:30]}...")

        # ---- 八、動能分析 ----
        st.subheader("八、動能分析")
        mom_cols = st.columns(4)
        with mom_cols[0]:
            st.metric("ADX", f"{report.adx_value:.1f}")
            st.caption(report.adx_interpretation)
        with mom_cols[1]:
            st.metric("RSI", f"{report.rsi_value:.1f}")
            st.caption(report.rsi_interpretation)
        with mom_cols[2]:
            st.metric("MACD", f"{report.macd_value:.4f}")
            st.caption(report.macd_interpretation)
        with mom_cols[3]:
            st.metric("KD", f"K={report.k_value:.1f} / D={report.d_value:.1f}")
            st.caption(report.kd_interpretation)

        # ---- 九、成交量分析 ----
        st.subheader("九、成交量分析")
        vol_cols = st.columns(3)
        with vol_cols[0]:
            st.metric("量能趨勢", report.volume_trend)
        with vol_cols[1]:
            st.metric("量能比", f"{report.volume_ratio:.1f}x")
        with vol_cols[2]:
            st.metric("籌碼判斷", report.accumulation_distribution)
        st.markdown(_esc(report.volume_interpretation))

        # ---- 十、波動度分析 ----
        st.subheader("十、波動度分析")
        vola_cols = st.columns(5)
        with vola_cols[0]:
            st.metric("ATR", f"${report.atr_value:.2f}")
        with vola_cols[1]:
            st.metric("ATR %", f"{report.atr_pct:.2%}")
        with vola_cols[2]:
            st.metric("20日波動率", f"{report.historical_volatility_20d:.1%}")
        with vola_cols[3]:
            st.metric("布林寬度", f"{report.bollinger_width:.3f}")
        with vola_cols[4]:
            st.metric("布林位置", f"{report.bollinger_position:.1%}")
        st.markdown(_esc(report.volatility_interpretation))

        # ---- 十一、風險評估 ----
        st.subheader("十一、風險評估")
        risk_cols = st.columns(4)
        with risk_cols[0]:
            st.metric("近1年最大回撤", f"{report.max_drawdown_1y:.2%}")
        with risk_cols[1]:
            st.metric("目前回撤", f"{report.current_drawdown:.2%}")
        with risk_cols[2]:
            st.metric("關鍵風險價位", f"${report.key_risk_level:.2f}")
        with risk_cols[3]:
            st.metric("風險報酬比", f"{report.risk_reward_ratio:.1f}:1")
        st.markdown(_esc(report.risk_interpretation))

        # ---- 十二、展望 ----
        st.subheader("十二、未來展望")
        for outlook in [report.outlook_3m, report.outlook_6m, report.outlook_1y]:
            st.markdown(f"**{outlook.timeframe}展望**")
            o_cols = st.columns(3)
            with o_cols[0]:
                st.markdown(f"🟢 **樂觀**（機率 {outlook.bull_probability}%）")
                st.markdown(f"目標：\\${outlook.bull_target:.2f}")
                st.markdown(_esc(outlook.bull_case))
            with o_cols[1]:
                st.markdown(f"🟡 **基本**（機率 {outlook.base_probability}%）")
                st.markdown(f"目標：\\${outlook.base_target:.2f}")
                st.markdown(_esc(outlook.base_case))
            with o_cols[2]:
                st.markdown(f"🔴 **保守**（機率 {outlook.bear_probability}%）")
                st.markdown(f"目標：\\${outlook.bear_target:.2f}")
                st.markdown(_esc(outlook.bear_case))
            st.divider()

        # ---- 十三、近期新聞 ----
        st.subheader("十三、近期新聞")
        if report.news_items:
            st.caption("可信度圖例：🟢 可信 ｜ 🟡 待確認 ｜ 🔴 存疑")
            for news in report.news_items:
                icon = news.get("credibility_icon", "🟡")
                cred = news.get("credibility", "待確認")
                title = news.get("title", "")
                with st.expander(f"{icon} {cred} | {title}"):
                    news_meta_cols = st.columns(2)
                    with news_meta_cols[0]:
                        st.markdown(f"**來源：** {news.get('source', 'Unknown')}")
                    with news_meta_cols[1]:
                        date_str = news.get("date", "")
                        if date_str:
                            st.markdown(f"**日期：** {str(date_str)[:19]}")
                    summary = news.get("summary", "")
                    if summary:
                        st.markdown(_esc(summary[:300]))
                    url = news.get("url", "")
                    if url:
                        st.markdown(f"[原文連結]({url})")
        else:
            st.info("目前無法取得此股票的相關新聞。")

        # ---- 十四、策略訊號交叉比對 ----
        st.subheader("十四、策略訊號交叉比對")
        sig_cols = st.columns(2)
        v4 = report.v4_analysis
        v2 = report.v2_analysis
        with sig_cols[0]:
            st.markdown("**v4 趨勢動量策略**")
            v4_sig = v4.get("signal", "HOLD")
            v4_icon = "🟢 買入" if v4_sig == "BUY" else "🟡 觀望"
            st.metric("訊號", v4_icon)
            if v4.get("entry_type"):
                st.metric("進場類型", v4["entry_type"])
            st.metric("上升趨勢天數", f"{v4.get('uptrend_days', 0)} 天")
        with sig_cols[1]:
            st.markdown("**v2 綜合評分策略**")
            v2_sig = v2.get("signal", "HOLD")
            v2_map = {"BUY": "🟢 買入", "SELL": "🔴 賣出", "HOLD": "🟡 持有"}
            st.metric("訊號", v2_map.get(v2_sig, v2_sig))
            st.metric("綜合評分", f"{v2.get('composite_score', 0):+.3f}")

        # ---- 摘要 ----
        st.subheader("分析摘要（約 500 字）")
        st.markdown(_esc(report.summary_text))

        # ---- 下載 ----
        report_text = f"=== {report.stock_name}（{report.stock_code}）技術分析報告 ===\n"
        report_text += f"報告日期：{report.report_date.strftime('%Y-%m-%d %H:%M')}\n"
        report_text += f"綜合評等：{report.overall_rating}\n"
        report_text += f"收盤價：${report.current_price:.2f}\n\n"
        report_text += report.summary_text
        st.download_button(
            label="下載報告文字檔",
            data=report_text.encode("utf-8"),
            file_name=f"report_{report.stock_code}_{report.report_date.strftime('%Y%m%d')}.txt",
            mime="text/plain",
        )


# ===== Footer =====
st.divider()
st.caption(
    "⚠️ 本系統僅供技術分析參考，不構成投資建議。投資有風險，請自行判斷。"
    " | 資料來源：Yahoo Finance"
)
