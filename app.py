"""台股技術分析系統 - Streamlit Web 介面"""

import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np

from config import DEFAULT_STOCKS, BACKTEST_PARAMS, STRATEGY_PARAMS, INDICATOR_PARAMS
from data.fetcher import get_stock_data
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

# ===== 側邊欄 =====
with st.sidebar:
    st.header("設定")

    # 股票選擇
    stock_options = {f"{code} {name}": code for code, name in DEFAULT_STOCKS.items()}
    selected_display = st.selectbox(
        "選擇股票",
        options=list(stock_options.keys()),
        index=0,
    )
    default_code = stock_options[selected_display]

    custom_code = st.text_input("或輸入股票代碼", value="", placeholder="例如: 2330")
    stock_code = custom_code.strip() if custom_code.strip() else default_code

    st.divider()

    # 頁面選擇
    page = st.radio(
        "功能",
        options=["技術分析", "回測報告", "模擬交易"],
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


# ===== 資料載入 =====
@st.cache_data(ttl=300)  # 快取 5 分鐘
def load_data(code: str, days: int):
    return get_stock_data(code, period_days=days)


try:
    # 多抓一些資料供指標計算使用（指標需要前面的資料暖機）
    fetch_days = max(backtest_days, 365) + 120
    raw_df = load_data(stock_code, fetch_days)
    stock_name = DEFAULT_STOCKS.get(stock_code, stock_code)
    st.sidebar.success(f"已載入 {stock_code} {stock_name}")
except Exception as e:
    st.error(f"無法載入股票 {stock_code} 的資料：{e}")
    st.stop()


# ===== 覆寫策略閾值 =====
STRATEGY_PARAMS["buy_threshold"] = buy_threshold
STRATEGY_PARAMS["sell_threshold"] = sell_threshold


# ===== 頁面 1：技術分析 =====
if page == "技術分析":
    st.header(f"{stock_code} {stock_name} - 技術分析")

    # 最新分析摘要
    analysis = get_latest_analysis(raw_df)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("收盤價", f"${analysis['close']:.2f}")
    with col2:
        signal_color = {"BUY": "🟢 買入", "SELL": "🔴 賣出", "HOLD": "🟡 持有"}
        st.metric("訊號", signal_color.get(analysis["signal"], analysis["signal"]))
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

    # K線圖 + 技術指標
    signals_df = generate_signals(raw_df).tail(120)  # 最近 120 個交易日

    # 主圖：K線 + MA + 布林通道 + 買賣訊號
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
    # 超買超賣線
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
        # 取回測期間的資料
        backtest_df = raw_df.tail(backtest_days + 60)  # 多取一些供指標暖機
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
        trade_data = []
        for t in result.trades:
            trade_data.append({
                "買入日期": t.date_open.strftime("%Y-%m-%d") if t.date_open else "",
                "賣出日期": t.date_close.strftime("%Y-%m-%d") if t.date_close else "",
                "股數": t.shares,
                "買入價": f"${t.price_open:.2f}",
                "賣出價": f"${t.price_close:.2f}",
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


# ===== Footer =====
st.divider()
st.caption(
    "⚠️ 本系統僅供技術分析參考，不構成投資建議。投資有風險，請自行判斷。"
    " | 資料來源：Yahoo Finance"
)
