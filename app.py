"""台股技術分析系統 - Streamlit Web 介面"""

import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np

from config import DEFAULT_STOCKS, SCAN_STOCKS, BACKTEST_PARAMS, STRATEGY_PARAMS, RISK_PARAMS, INDICATOR_PARAMS
from data.fetcher import get_stock_data
from data.stock_list import get_all_stocks, get_stock_name
from data.cache import get_cached_scan_results, set_cached_scan_results, get_cache_stats, flush_cache
from analysis.indicators import calculate_all_indicators
from analysis.strategy import generate_signals, get_latest_analysis
from backtest.engine import run_backtest, BacktestResult
from simulation.simulator import run_simulation, simulation_to_dataframe, SimulationResult

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

    custom_code = st.text_input(
        "或直接輸入股票代碼",
        value="",
        placeholder="例如: 2330、6748",
    )
    stock_code = custom_code.strip() if custom_code.strip() else default_code

    st.divider()

    # 頁面選擇
    page = st.radio(
        "功能",
        options=["技術分析", "回測報告", "模擬交易", "推薦股票"],
        index=0,
    )

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

        st.caption("v2 風控參數")
        stop_loss = st.slider("停損 (%)", 1, 20, int(RISK_PARAMS["stop_loss"] * 100), 1)
        trailing_stop = st.slider("移動停利 (%)", 1, 20, int(RISK_PARAMS["trailing_stop"] * 100), 1)
        max_position_pct = st.slider("單筆最大部位 (%)", 10, 100, int(RISK_PARAMS["max_position_pct"] * 100), 10)

        st.caption("v2 訊號過濾")
        trend_filter = st.checkbox("趨勢過濾（MA20>MA60 才做多）", value=STRATEGY_PARAMS.get("trend_filter", True))
        volume_confirm = st.checkbox("量能確認（買入量>5日均量）", value=STRATEGY_PARAMS.get("volume_confirm", True))
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


# 推薦股票頁面不需要預先載入單一股票
if page != "推薦股票":
    try:
        fetch_days = max(backtest_days, 365) + 120
        raw_df = load_data(stock_code, fetch_days)
        stock_name = get_stock_name(stock_code, all_stocks)
        st.sidebar.success(f"已載入 {stock_code} {stock_name}")
    except Exception as e:
        st.error(f"無法載入股票 {stock_code} 的資料：{e}")
        st.stop()

# ===== 覆寫策略閾值 & v2 參數 =====
STRATEGY_PARAMS["buy_threshold"] = buy_threshold
STRATEGY_PARAMS["sell_threshold"] = sell_threshold
STRATEGY_PARAMS["trend_filter"] = trend_filter
STRATEGY_PARAMS["volume_confirm"] = volume_confirm
STRATEGY_PARAMS["confirm_days"] = confirm_days
RISK_PARAMS["stop_loss"] = stop_loss / 100
RISK_PARAMS["trailing_stop"] = trailing_stop / 100
RISK_PARAMS["max_position_pct"] = max_position_pct / 100


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

    # 最新分析摘要
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
    signals_df = generate_signals(raw_df).tail(120)  # 最近 120 個交易日

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
    buy_signals = signals_df[signals_df["signal"] == "BUY"]
    sell_signals = signals_df[signals_df["signal"] == "SELL"]

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
    st.header("推薦股票 — 技術面綜合評分 Top 3")
    st.caption("從股票池中掃描所有股票，依綜合評分排序，推薦前 3 名最具技術面買進訊號的股票。")

    def scan_all_stocks():
        """掃描所有股票池（優先用 Redis 快取）"""
        # 嘗試 Redis 快取
        cached = get_cached_scan_results()
        if cached:
            return cached

        results = []
        progress_bar = st.progress(0, text="掃描中...")
        total = len(SCAN_STOCKS)
        for i, (code, name) in enumerate(SCAN_STOCKS.items()):
            progress_bar.progress((i + 1) / total, text=f"掃描 {code} {name}... ({i+1}/{total})")
            try:
                df = get_stock_data(code, period_days=200)
                analysis = get_latest_analysis(df)
                analysis["code"] = code
                analysis["name"] = name
                results.append(analysis)
            except Exception:
                continue
        progress_bar.empty()

        # 寫入 Redis 快取（10 分鐘）
        if results:
            set_cached_scan_results(results, ttl=600)
        return results

    with st.spinner("正在掃描股票池..."):
        all_results = scan_all_stocks()

    if not all_results:
        st.error("無法取得任何股票資料")
        st.stop()

    # 依綜合評分排序，取前 3 名
    sorted_results = sorted(all_results, key=lambda x: x["composite_score"], reverse=True)
    top3 = sorted_results[:3]

    for rank, stock in enumerate(top3, 1):
        signal_map = {"BUY": "🟢 買入", "SELL": "🔴 賣出", "HOLD": "🟡 持有"}
        signal_text = signal_map.get(stock["signal"], stock["signal"])

        st.subheader(f"第 {rank} 名：{stock['code']} {stock['name']}")

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("收盤價", f"${stock['close']:.2f}")
        with col2:
            st.metric("訊號", signal_text)
        with col3:
            st.metric("綜合評分", f"{stock['composite_score']:+.3f}")

        # 推薦原因
        explanation = explain_signal(stock)
        st.markdown(explanation)

        # 各指標評分一覽
        score_cols = st.columns(6)
        for i, (name, score) in enumerate(stock["scores"].items()):
            with score_cols[i]:
                icon = "🟢" if score > 0 else "🔴" if score < 0 else "⚪"
                st.metric(name, f"{icon} {score:+.2f}")

        st.divider()

    # 完整排行表
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
            "MA": f"{s['scores']['MA']:+.2f}",
            "RSI": f"{s['scores']['RSI']:+.2f}",
            "MACD": f"{s['scores']['MACD']:+.2f}",
            "KD": f"{s['scores']['KD']:+.2f}",
            "布林": f"{s['scores']['布林通道']:+.2f}",
            "量能": f"{s['scores']['成交量']:+.2f}",
        })
    st.dataframe(pd.DataFrame(ranking_data), use_container_width=True, hide_index=True)


# ===== Footer =====
st.divider()
st.caption(
    "⚠️ 本系統僅供技術分析參考，不構成投資建議。投資有風險，請自行判斷。"
    " | 資料來源：Yahoo Finance"
)
