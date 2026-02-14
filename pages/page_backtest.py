"""回測報告頁面（含模擬交易）"""

import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np

from backtest.engine import run_backtest, run_backtest_v4, run_portfolio_backtest_v4
from backtest.rolling import run_rolling_backtest, run_parameter_sensitivity
from simulation.simulator import run_simulation, run_simulation_v4, simulation_to_dataframe
from data.stock_list import get_stock_name
from data.fetcher import get_taiex_data


def _show_backtest_disclaimers():
    """回測免責聲明：生還者偏差 + 即時執行假設 + 撮合風險"""
    st.caption(
        "**免責聲明**：本系統使用現存上市櫃股票回測，未校正生還者偏差（Survivorship Bias），"
        "結果可能偏樂觀。訊號使用當日收盤價計算並假設 13:25 前下 MOC（收盤委託）單成交，"
        "未考慮最後一盤撮合之價格跳動風險，實際成交價可能有差異。"
    )


def render(stock_code, stock_name, raw_df, use_v4, initial_capital, backtest_days,
           all_stocks=None, load_data_fn=None, sim_days=30):
    # 模式選擇
    _bt_mode = st.radio(
        "回測模式", ["單一股票", "組合回測（等權重）", "模擬交易", "一致性測試"],
        horizontal=True, key="bt_mode_radio",
    )

    if _bt_mode == "組合回測（等權重）" and load_data_fn and all_stocks:
        _render_portfolio(use_v4, initial_capital, backtest_days,
                          all_stocks, load_data_fn)
        return

    if _bt_mode == "模擬交易":
        _render_simulation(stock_code, stock_name, raw_df, use_v4,
                           initial_capital, sim_days)
        return

    if _bt_mode == "一致性測試":
        _render_rolling_backtest(stock_code, stock_name, raw_df, use_v4,
                                 initial_capital)
        return

    st.header(f"{stock_code} {stock_name} - 回測報告")

    _include_div = st.checkbox("顯示估計股利收入", value=True, key="bt_include_div",
                               help="報酬率已透過調整後股價包含除權息。勾選後額外顯示持倉期間的估計股利收入金額")

    with st.spinner("正在執行回測..."):
        backtest_df = raw_df.tail(backtest_days + 60)
        dividends = None
        if _include_div and use_v4:
            try:
                from data.fetcher import get_dividend_data
                dividends = get_dividend_data(stock_code)
            except Exception:
                dividends = None
        if use_v4:
            result = run_backtest_v4(backtest_df, initial_capital=initial_capital,
                                    dividends=dividends)
        else:
            result = run_backtest(backtest_df, initial_capital=initial_capital)

    # 策略參數快照
    if result.params_description:
        st.caption(f"策略參數：{result.params_description}")

    _show_backtest_disclaimers()

    # 績效指標
    st.subheader("績效摘要")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("總報酬率", f"{result.total_return:.2%}",
                   delta=f"{result.total_return:.2%}", delta_color="normal")
    with col2:
        st.metric("年化報酬率", f"{result.annual_return:.2%}",
                   delta=f"{result.annual_return:.2%}", delta_color="normal")
    with col3:
        st.metric("最大回撤", f"{result.max_drawdown:.2%}",
                   delta=f"{result.max_drawdown:.2%}", delta_color="inverse")
    with col4:
        _sharpe_label = "佳" if result.sharpe_ratio > 1 else ("普通" if result.sharpe_ratio > 0 else "差")
        st.metric("Sharpe Ratio", f"{result.sharpe_ratio:.2f}",
                   delta=_sharpe_label, delta_color="normal" if result.sharpe_ratio > 0 else "inverse")

    col5, col6, col7, col8 = st.columns(4)
    with col5:
        st.metric("總交易次數", f"{result.total_trades}")
    with col6:
        _wr_delta = "佳" if result.win_rate > 0.5 else "偏低"
        st.metric("勝率", f"{result.win_rate:.2%}",
                   delta=_wr_delta, delta_color="normal" if result.win_rate > 0.5 else "inverse")
    with col7:
        _pf_delta = "佳" if result.profit_factor > 1.5 else ("中" if result.profit_factor > 1 else "差")
        st.metric("盈虧比", f"{result.profit_factor:.2f}",
                   delta=_pf_delta, delta_color="normal" if result.profit_factor > 1 else "inverse")
    with col8:
        st.metric("平均持有天數", f"{result.avg_holding_days:.1f}")

    # 第三行指標
    col9, col10, col11, col12 = st.columns(4)
    with col9:
        _sortino_label = "佳" if result.sortino_ratio > 1.5 else ("普通" if result.sortino_ratio > 0 else "差")
        st.metric("Sortino Ratio", f"{result.sortino_ratio:.2f}",
                   delta=_sortino_label, delta_color="normal" if result.sortino_ratio > 0 else "inverse")
    with col10:
        _calmar_label = "佳" if result.calmar_ratio > 1 else ("普通" if result.calmar_ratio > 0 else "差")
        st.metric("Calmar Ratio", f"{result.calmar_ratio:.2f}",
                   delta=_calmar_label, delta_color="normal" if result.calmar_ratio > 0 else "inverse")
    with col11:
        st.metric("平均獲利", f"{result.avg_win:.2%}" if result.avg_win else "—",
                   delta=f"連勝 {result.max_consecutive_wins}" if result.max_consecutive_wins else None)
    with col12:
        st.metric("平均虧損", f"{result.avg_loss:.2%}" if result.avg_loss else "—",
                   delta=f"連敗 {result.max_consecutive_losses}" if result.max_consecutive_losses else None,
                   delta_color="inverse")

    # 生還者偏差啟發式修正
    _bt_years = backtest_days / 365
    _survivorship_adj = _bt_years * 0.01  # 每年扣 1%
    _adjusted_return = result.total_return - _survivorship_adj
    st.caption(
        f"生還者偏差修正後報酬：**{_adjusted_return:.2%}**"
        f"（原始 {result.total_return:.2%} − 修正 {_survivorship_adj:.2%}，"
        f"以每年 1% 估算 {_bt_years:.1f} 年偏差）"
    )

    # 股利收入顯示
    st.caption("報酬率已透過調整後股價包含除權息（yfinance auto_adjust）")
    if result.dividend_income > 0:
        _div_pct = result.dividend_income / initial_capital * 100
        st.caption(f"估計股利收入：**${result.dividend_income:,.0f}** "
                   f"（佔初始資金 {_div_pct:.2f}%），僅供參考")

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
        # 買入持有基準線
        _bt_close = backtest_df.tail(backtest_days)["close"]
        if len(_bt_close) > 1:
            _bh_equity = initial_capital * (_bt_close / _bt_close.iloc[0])
            _bh_aligned = _bh_equity.reindex(result.equity_curve.index, method="ffill")
            if not _bh_aligned.empty:
                fig_equity.add_trace(go.Scatter(
                    x=_bh_aligned.index, y=_bh_aligned.values,
                    mode="lines", name="買入持有",
                    line=dict(color="#FF9100", width=1, dash="dot"),
                    opacity=0.7,
                ))
                _bh_return = (_bt_close.iloc[-1] / _bt_close.iloc[0]) - 1
                _strategy_beats = result.total_return > _bh_return
                _diff = result.total_return - _bh_return
                if _strategy_beats:
                    st.caption(f"策略 vs 買入持有：策略勝出 **{_diff:+.2%}**（策略 {result.total_return:+.2%} vs 持有 {_bh_return:+.2%}）")
                else:
                    st.caption(f"策略 vs 買入持有：持有勝出 **{-_diff:+.2%}**（策略 {result.total_return:+.2%} vs 持有 {_bh_return:+.2%}）")

        # 大盤基準（TAIEX）
        _taiex_return = _add_taiex_benchmark(fig_equity, result.equity_curve, initial_capital)
        if _taiex_return is not None:
            _alpha = result.total_return - _taiex_return
            st.caption(f"策略 vs 大盤：超額報酬 (alpha) **{_alpha:+.2%}**"
                       f"（策略 {result.total_return:+.2%} vs 大盤 {_taiex_return:+.2%}）")

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
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        st.plotly_chart(fig_equity, width="stretch")

        # 回撤圖
        _peak = result.equity_curve.cummax()
        _drawdown = (result.equity_curve - _peak) / _peak * 100
        if _drawdown.min() < 0:
            fig_dd = go.Figure()
            fig_dd.add_trace(go.Scatter(
                x=_drawdown.index, y=_drawdown.values,
                mode="lines", fill="tozeroy",
                name="回撤 (%)",
                line=dict(color="#FF1744", width=1),
                fillcolor="rgba(255,23,68,0.2)",
            ))
            fig_dd.update_layout(
                height=200, template="plotly_dark",
                yaxis_title="回撤 (%)", margin=dict(t=10, b=30),
            )
            st.plotly_chart(fig_dd, width="stretch")

    # K 線圖 + 交易標記
    if result.trades:
        st.subheader("交易標記圖")
        bt_df = backtest_df.tail(backtest_days).copy()
        fig_trades = make_subplots(
            rows=2, cols=1, shared_xaxes=True,
            row_heights=[0.75, 0.25],
            vertical_spacing=0.03,
        )
        fig_trades.add_trace(go.Candlestick(
            x=bt_df.index, open=bt_df["open"], high=bt_df["high"],
            low=bt_df["low"], close=bt_df["close"],
            name="K線",
            increasing_line_color="#EF5350", decreasing_line_color="#26A69A",
        ), row=1, col=1)
        vol_colors = ["#EF5350" if c >= o else "#26A69A"
                      for c, o in zip(bt_df["close"], bt_df["open"])]
        fig_trades.add_trace(go.Bar(
            x=bt_df.index, y=bt_df["volume"], name="成交量",
            marker_color=vol_colors, opacity=0.5,
        ), row=2, col=1)
        # 買入標記
        buy_dates = [t.date_open for t in result.trades if t.date_open is not None]
        buy_prices = [t.price_open for t in result.trades if t.date_open is not None]
        if buy_dates:
            fig_trades.add_trace(go.Scatter(
                x=buy_dates, y=buy_prices, mode="markers",
                marker=dict(symbol="triangle-up", size=14, color="#00E676",
                            line=dict(width=1, color="white")),
                name="買入", text=[f"買入 ${p:.2f}" for p in buy_prices],
                hoverinfo="text+x",
            ), row=1, col=1)
        # 賣出標記
        exit_reason_map_chart = {
            "signal": "訊號", "stop_loss": "停損", "trailing_stop": "移動停利",
            "take_profit": "停利", "end_of_period": "期末",
        }
        sell_dates = [t.date_close for t in result.trades if t.date_close is not None]
        sell_prices = [t.price_close for t in result.trades if t.date_close is not None]
        sell_reasons = [exit_reason_map_chart.get(t.exit_reason, t.exit_reason)
                        for t in result.trades if t.date_close is not None]
        sell_colors = []
        for t in result.trades:
            if t.date_close is None:
                continue
            if t.exit_reason == "take_profit":
                sell_colors.append("#FFD600")
            elif t.exit_reason == "stop_loss":
                sell_colors.append("#FF1744")
            elif t.exit_reason == "trailing_stop":
                sell_colors.append("#FF9100")
            else:
                sell_colors.append("#E040FB")
        if sell_dates:
            fig_trades.add_trace(go.Scatter(
                x=sell_dates, y=sell_prices, mode="markers",
                marker=dict(symbol="triangle-down", size=14, color=sell_colors,
                            line=dict(width=1, color="white")),
                name="賣出",
                text=[f"{r} ${p:.2f}" for p, r in zip(sell_prices, sell_reasons)],
                hoverinfo="text+x",
            ), row=1, col=1)
        # 持倉區間
        for t in result.trades:
            if t.date_open and t.date_close:
                color = "rgba(0,230,118,0.08)" if t.pnl >= 0 else "rgba(255,23,68,0.08)"
                fig_trades.add_vrect(
                    x0=t.date_open, x1=t.date_close,
                    fillcolor=color, layer="below", line_width=0,
                    row=1, col=1,
                )
        fig_trades.update_layout(
            height=550, template="plotly_dark",
            xaxis_rangeslider_visible=False,
            xaxis2_title="日期",
            yaxis_title="股價",
            yaxis2_title="成交量",
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            margin=dict(t=40),
        )
        st.plotly_chart(fig_trades, width="stretch")

    # 出場原因分布 + 單筆交易報酬
    if result.trades and len(result.trades) > 1:
        _exit_cols = st.columns(2)
        exit_reason_map_pie = {
            "signal": "訊號賣出", "stop_loss": "停損", "trailing_stop": "移動停利",
            "take_profit": "停利", "end_of_period": "期末平倉",
        }
        exit_color_map = {
            "訊號賣出": "#E040FB", "停損": "#FF1744", "移動停利": "#FF9100",
            "停利": "#FFD600", "期末平倉": "#78909C",
        }
        with _exit_cols[0]:
            st.subheader("出場原因分布")
            _exit_counts = {}
            for t in result.trades:
                _reason = exit_reason_map_pie.get(t.exit_reason, t.exit_reason)
                _exit_counts[_reason] = _exit_counts.get(_reason, 0) + 1
            fig_pie = go.Figure(data=go.Pie(
                labels=list(_exit_counts.keys()),
                values=list(_exit_counts.values()),
                marker=dict(colors=[exit_color_map.get(k, "#888") for k in _exit_counts.keys()]),
                hole=0.4,
                textinfo="label+percent+value",
            ))
            fig_pie.update_layout(height=350, template="plotly_dark", margin=dict(t=20, b=20))
            st.plotly_chart(fig_pie, width="stretch")

        with _exit_cols[1]:
            st.subheader("單筆交易報酬")
            _trade_returns = [t.return_pct * 100 for t in result.trades]
            _trade_colors = ["#00C853" if r >= 0 else "#FF1744" for r in _trade_returns]
            _trade_labels = [f"#{i+1}" for i in range(len(result.trades))]
            fig_bar = go.Figure(data=go.Bar(
                x=_trade_labels, y=_trade_returns,
                marker_color=_trade_colors,
                hovertemplate="交易 %{x}<br>報酬: %{y:.2f}%<extra></extra>",
            ))
            fig_bar.add_hline(y=0, line_dash="dash", line_color="white", opacity=0.3)
            fig_bar.update_layout(
                height=350, template="plotly_dark",
                xaxis_title="交易序號", yaxis_title="報酬率 (%)",
                margin=dict(t=20, b=20),
            )
            st.plotly_chart(fig_bar, width="stretch")

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
        st.plotly_chart(fig_dist, width="stretch")

    # 月度報酬熱力圖
    if not result.daily_returns.empty and len(result.daily_returns) > 30:
        st.subheader("月度報酬熱力圖")
        _monthly = result.daily_returns.resample("ME").apply(lambda x: (1 + x).prod() - 1) * 100
        if len(_monthly) > 1:
            _monthly_df = pd.DataFrame({
                "年": _monthly.index.year,
                "月": _monthly.index.month,
                "報酬%": _monthly.values,
            })
            _pivot = _monthly_df.pivot_table(index="年", columns="月", values="報酬%", aggfunc="sum")
            _pivot.columns = [f"{m}月" for m in _pivot.columns]

            fig_heatmap = go.Figure(data=go.Heatmap(
                z=_pivot.values,
                x=_pivot.columns,
                y=[str(y) for y in _pivot.index],
                colorscale=[[0, "#FF1744"], [0.5, "#212121"], [1, "#00C853"]],
                zmid=0,
                text=[[f"{v:.1f}%" if not np.isnan(v) else "" for v in row] for row in _pivot.values],
                texttemplate="%{text}",
                textfont=dict(size=12),
                hovertemplate="年: %{y}<br>月: %{x}<br>報酬: %{z:.2f}%<extra></extra>",
            ))
            fig_heatmap.update_layout(
                height=max(200, len(_pivot) * 50 + 80),
                template="plotly_dark",
                yaxis=dict(dtick=1),
                margin=dict(t=20, b=20),
            )
            st.plotly_chart(fig_heatmap, width="stretch")

            # 年度彙總
            _yearly = result.daily_returns.resample("YE").apply(lambda x: (1 + x).prod() - 1) * 100
            if len(_yearly) > 0:
                _yr_data = [{"年度": str(d.year), "報酬率": f"{v:+.2f}%"} for d, v in _yearly.items()]
                st.caption("年度報酬：" + " | ".join([f"{r['年度']}: {r['報酬率']}" for r in _yr_data]))

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
        _liquidity_warnings = 0
        for t in result.trades:
            _row = {
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
            }
            if t.liquidity_warning:
                _row["流動性"] = t.liquidity_warning
                _liquidity_warnings += 1
            trade_data.append(_row)
        _trade_df = pd.DataFrame(trade_data)
        st.dataframe(_trade_df, width="stretch")
        if _liquidity_warnings > 0:
            st.warning(
                f"⚠️ {_liquidity_warnings} 筆交易有流動性風險（交易金額佔當日成交額 > 5%），"
                "現實中可能面臨滑價擴大或無法成交的問題。"
            )

        _csv_lines = [
            f"# 股票：{stock_code} {stock_name}",
            f"# 策略：v4 趨勢動量" if use_v4 else "# 策略：v2 技術面",
            f"# 參數：{result.params_description}" if result.params_description else "# 參數：預設",
            f"# 回測區間：{backtest_days} 天",
            f"# 總報酬率：{result.total_return:.2%} | Sharpe：{result.sharpe_ratio:.2f} | 最大回撤：{result.max_drawdown:.2%}",
            f"# 勝率：{result.win_rate:.2%} | 交易次數：{result.total_trades} | 盈虧比：{result.profit_factor:.2f}",
            "",
        ]
        _csv_header = "\n".join(_csv_lines) + "\n"
        _csv_data = (_csv_header + _trade_df.to_csv(index=False)).encode("utf-8-sig")
        st.download_button(
            label="下載交易紀錄 (CSV)",
            data=_csv_data,
            file_name=f"backtest_{stock_code}_{backtest_days}d.csv",
            mime="text/csv",
        )
    else:
        st.warning("回測期間沒有產生交易")
        if use_v4:
            st.info(
                "💡 **v4 策略進場條件較嚴格**（需 ADX≥18 + 上升趨勢 ≥10 天 + 支撐/動量觸發），"
                "部分股票在短期回測中可能不會觸發交易。\n\n"
                "**建議**：將左側「回測天數」調高至 **730～1095 天**，讓策略有更多進出場機會。"
            )


def _add_taiex_benchmark(fig, equity_curve, initial_capital):
    """將 TAIEX 大盤基準加入權益曲線圖

    Args:
        fig: plotly Figure
        equity_curve: 策略權益曲線
        initial_capital: 初始資金

    Returns:
        TAIEX 期間報酬率，若取得失敗則 None
    """
    try:
        _start = equity_curve.index[0]
        _end = equity_curve.index[-1]
        _days = (_end - _start).days + 60
        taiex_df = get_taiex_data(period_days=_days)
        if taiex_df is None or taiex_df.empty:
            return None

        # 裁剪到回測期間
        taiex_close = taiex_df["close"]
        taiex_close = taiex_close[taiex_close.index >= _start]
        taiex_close = taiex_close[taiex_close.index <= _end]
        if len(taiex_close) < 2:
            return None

        # 正規化為等值權益曲線
        taiex_equity = initial_capital * (taiex_close / taiex_close.iloc[0])
        taiex_aligned = taiex_equity.reindex(equity_curve.index, method="ffill")

        fig.add_trace(go.Scatter(
            x=taiex_aligned.index, y=taiex_aligned.values,
            mode="lines", name="大盤 (TAIEX)",
            line=dict(color="#FFD600", width=1, dash="dash"),
            opacity=0.7,
        ))

        taiex_return = (taiex_close.iloc[-1] / taiex_close.iloc[0]) - 1
        return taiex_return
    except Exception:
        return None


def _render_portfolio(use_v4, initial_capital, backtest_days, all_stocks, load_data_fn):
    """組合回測頁面"""
    st.header("組合回測（等權重）")
    st.caption("將資金等分配置於多檔股票，獨立執行 v4 策略回測，評估分散投資的效果。")
    _show_backtest_disclaimers()

    if not use_v4:
        st.warning("組合回測目前僅支援 v4 策略。請在側邊欄切換至 v4。")
        return

    # 股票選擇
    wl = st.session_state.get("watchlist", [])
    _source = st.radio("股票來源", ["自選股", "手動輸入"], horizontal=True, key="pf_source")

    if _source == "自選股":
        if not wl:
            st.info("自選股為空，請先加入股票或改用「手動輸入」。")
            return
        _wl_opts = [f"{c} {get_stock_name(c, all_stocks)}" for c in wl]
        _selected = st.multiselect("選擇股票（至少 2 檔）", _wl_opts,
                                   default=_wl_opts, key="pf_stocks_ms")
        selected_codes = [s.split()[0] for s in _selected]
    else:
        _input = st.text_input("輸入股票代碼（逗號分隔）", value="2330,2317,2454,2881,0050",
                               key="pf_stocks_input")
        selected_codes = [c.strip() for c in _input.split(",") if c.strip()]

    if len(selected_codes) < 2:
        st.warning("請至少選擇 2 檔股票進行組合回測。")
        return

    st.caption(f"已選 {len(selected_codes)} 檔，每檔分配 ${initial_capital / len(selected_codes):,.0f}")

    if not st.button("開始組合回測", type="primary", key="pf_run_bt"):
        # 顯示之前的結果
        _prev = st.session_state.get("_pf_bt_result")
        if _prev:
            _display_portfolio_result(_prev, initial_capital)
        return

    # 載入資料並回測
    stock_data = {}
    stock_names = {}
    _prog = st.progress(0, text="載入股票資料...")
    for i, code in enumerate(selected_codes):
        _prog.progress((i + 1) / len(selected_codes), text=f"回測 {code} ({i+1}/{len(selected_codes)})...")
        try:
            df = load_data_fn(code, backtest_days + 120)
            if df is not None and len(df) > 60:
                stock_data[code] = df.tail(backtest_days + 60)
                stock_names[code] = get_stock_name(code, all_stocks)
        except Exception:
            continue
    _prog.empty()

    if len(stock_data) < 2:
        st.error(f"僅載入 {len(stock_data)} 檔有效資料，至少需要 2 檔。")
        return

    with st.spinner("執行組合回測..."):
        pf_result = run_portfolio_backtest_v4(
            stock_data, stock_names=stock_names,
            initial_capital=initial_capital,
        )

    st.session_state["_pf_bt_result"] = pf_result
    _display_portfolio_result(pf_result, initial_capital)


def _display_portfolio_result(pf_result, initial_capital):
    """顯示組合回測結果"""
    if pf_result.equity_curve.empty:
        st.warning("組合回測未產生有效結果。")
        return

    st.success(f"組合回測完成：{len(pf_result.stock_results)} 檔股票，"
               f"共 {pf_result.total_trades} 筆交易")

    # 組合績效摘要
    st.subheader("組合績效摘要")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("總報酬率", f"{pf_result.total_return:.2%}",
                   delta=f"{pf_result.total_return:.2%}", delta_color="normal")
    with c2:
        st.metric("年化報酬率", f"{pf_result.annual_return:.2%}",
                   delta=f"{pf_result.annual_return:.2%}", delta_color="normal")
    with c3:
        st.metric("最大回撤", f"{pf_result.max_drawdown:.2%}",
                   delta=f"{pf_result.max_drawdown:.2%}", delta_color="inverse")
    with c4:
        st.metric("Sharpe Ratio", f"{pf_result.sharpe_ratio:.2f}")

    c5, c6, c7, c8 = st.columns(4)
    with c5:
        st.metric("Sortino Ratio", f"{pf_result.sortino_ratio:.2f}")
    with c6:
        st.metric("Calmar Ratio", f"{pf_result.calmar_ratio:.2f}")
    with c7:
        st.metric("獲利股數", f"{pf_result.winning_stocks}/{len(pf_result.stock_results)}")
    with c8:
        st.metric("每股資金", f"${pf_result.per_stock_capital:,.0f}")

    # 組合權益曲線
    st.subheader("組合權益曲線")
    fig_eq = go.Figure()
    fig_eq.add_trace(go.Scatter(
        x=pf_result.equity_curve.index, y=pf_result.equity_curve.values,
        mode="lines", name="組合權益", fill="tozeroy",
        line=dict(color="#2196F3", width=2),
    ))
    # 大盤基準
    _pf_taiex_ret = _add_taiex_benchmark(fig_eq, pf_result.equity_curve, initial_capital)
    if _pf_taiex_ret is not None:
        _pf_alpha = pf_result.total_return - _pf_taiex_ret
        st.caption(f"組合 vs 大盤：超額報酬 (alpha) **{_pf_alpha:+.2%}**"
                   f"（組合 {pf_result.total_return:+.2%} vs 大盤 {_pf_taiex_ret:+.2%}）")

    fig_eq.add_hline(y=initial_capital, line_dash="dash", line_color="white",
                     opacity=0.5, annotation_text="初始資金")
    fig_eq.update_layout(
        height=400, template="plotly_dark",
        yaxis_title="權益 (TWD)", xaxis_title="日期",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(fig_eq, width="stretch")

    # 組合回撤
    _peak = pf_result.equity_curve.cummax()
    _dd = (pf_result.equity_curve - _peak) / _peak * 100
    if _dd.min() < 0:
        fig_dd = go.Figure()
        fig_dd.add_trace(go.Scatter(
            x=_dd.index, y=_dd.values, mode="lines", fill="tozeroy",
            name="回撤 (%)", line=dict(color="#FF1744", width=1),
            fillcolor="rgba(255,23,68,0.2)",
        ))
        fig_dd.update_layout(height=200, template="plotly_dark",
                             yaxis_title="回撤 (%)", margin=dict(t=10, b=30))
        st.plotly_chart(fig_dd, width="stretch")

    # 個股權益曲線比較
    if pf_result.stock_equity_curves:
        st.subheader("個股報酬率比較")
        fig_comp = go.Figure()
        for code, eq in pf_result.stock_equity_curves.items():
            if len(eq) < 2:
                continue
            _norm = (eq / eq.iloc[0] - 1) * 100
            _name = pf_result.stock_names.get(code, code)
            fig_comp.add_trace(go.Scatter(
                x=_norm.index, y=_norm.values, mode="lines",
                name=f"{code} {_name}",
            ))
        fig_comp.add_hline(y=0, line_dash="dash", line_color="white", opacity=0.3)
        fig_comp.update_layout(
            height=450, template="plotly_dark",
            yaxis_title="報酬率 (%)", xaxis_title="日期",
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        st.plotly_chart(fig_comp, width="stretch")

    # 個股績效表格
    st.subheader("個股績效明細")
    _rows = []
    for code in pf_result.stock_codes:
        bt = pf_result.stock_results.get(code)
        if bt is None:
            continue
        _rows.append({
            "代碼": code,
            "名稱": pf_result.stock_names.get(code, ""),
            "總報酬率%": round(bt.total_return * 100, 2),
            "年化報酬%": round(bt.annual_return * 100, 2),
            "最大回撤%": round(bt.max_drawdown * 100, 2),
            "Sharpe": round(bt.sharpe_ratio, 2),
            "勝率%": round(bt.win_rate * 100, 1),
            "交易次數": bt.total_trades,
            "盈虧比": round(bt.profit_factor, 2),
            "平均持有天數": round(bt.avg_holding_days, 1),
        })

    if _rows:
        df_pf = pd.DataFrame(_rows).sort_values("總報酬率%", ascending=False)

        def _color_ret(val):
            if isinstance(val, (int, float)) and not np.isnan(val):
                return "color: #00C853" if val > 0 else "color: #FF1744" if val < 0 else ""
            return ""

        styled = df_pf.style.map(_color_ret, subset=["總報酬率%", "年化報酬%"])
        st.dataframe(styled, width="stretch", hide_index=True)

        _avg_ret = np.mean([r["總報酬率%"] for r in _rows])
        _pos_n = sum(1 for r in _rows if r["總報酬率%"] > 0)
        st.caption(f"平均個股報酬率：{_avg_ret:+.2f}% | 獲利：{_pos_n}/{len(_rows)} 檔")

    # 相關性矩陣
    if not pf_result.correlation_matrix.empty:
        st.subheader("報酬率相關性矩陣")
        _corr = pf_result.correlation_matrix
        # 替換 code 為 name
        _labels = [f"{c} {pf_result.stock_names.get(c, '')}" for c in _corr.columns]
        fig_corr = go.Figure(data=go.Heatmap(
            z=_corr.values, x=_labels, y=_labels,
            colorscale=[[0, "#2196F3"], [0.5, "#212121"], [1, "#FF1744"]],
            zmid=0, zmin=-1, zmax=1,
            text=[[f"{v:.2f}" for v in row] for row in _corr.values],
            texttemplate="%{text}",
            textfont=dict(size=11),
        ))
        fig_corr.update_layout(
            height=max(300, len(_corr) * 50 + 100),
            template="plotly_dark", margin=dict(t=20, b=20),
        )
        st.plotly_chart(fig_corr, width="stretch")
        _avg_corr = _corr.values[np.triu_indices_from(_corr.values, k=1)].mean()
        st.caption(f"平均相關係數：{_avg_corr:.3f}（越低代表分散效果越好）")


def _render_simulation(stock_code, stock_name, raw_df, use_v4, initial_capital, sim_days):
    """模擬交易模式（原獨立頁面，現合併至回測）"""
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
        st.metric("最大回撤", f"{sim_result.max_drawdown:.2%}",
                   delta=f"{sim_result.max_drawdown:.2%}", delta_color="inverse")
    with col3:
        st.metric("交易次數", f"{sim_result.total_trades}")
    with col4:
        win_rate = (
            sim_result.winning_trades / sim_result.total_trades
            if sim_result.total_trades > 0
            else 0
        )
        _sim_wr_delta = "佳" if win_rate > 0.5 else "偏低"
        st.metric("勝率", f"{win_rate:.0%}",
                   delta=_sim_wr_delta, delta_color="normal" if win_rate > 0.5 else "inverse")

    col5, col6, col7, col8 = st.columns(4)
    with col5:
        st.metric("初始資金", f"${sim_result.initial_capital:,.0f}")
    with col6:
        pnl = sim_result.final_equity - sim_result.initial_capital
        st.metric("總損益", f"${pnl:,.0f}",
                   delta=f"{pnl:+,.0f}", delta_color="normal")
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
        st.plotly_chart(fig_sim, width="stretch")

    # K 線圖 + 交易標記
    if sim_result.trade_log:
        st.subheader("交易標記圖")
        sim_ohlc = raw_df.tail(sim_days + 10).copy()
        fig_sim_trades = make_subplots(
            rows=2, cols=1, shared_xaxes=True,
            row_heights=[0.75, 0.25], vertical_spacing=0.03,
        )
        fig_sim_trades.add_trace(go.Candlestick(
            x=sim_ohlc.index, open=sim_ohlc["open"], high=sim_ohlc["high"],
            low=sim_ohlc["low"], close=sim_ohlc["close"], name="K線",
            increasing_line_color="#EF5350", decreasing_line_color="#26A69A",
        ), row=1, col=1)
        sim_vol_colors = ["#EF5350" if c >= o else "#26A69A"
                          for c, o in zip(sim_ohlc["close"], sim_ohlc["open"])]
        fig_sim_trades.add_trace(go.Bar(
            x=sim_ohlc.index, y=sim_ohlc["volume"], name="成交量",
            marker_color=sim_vol_colors, opacity=0.5,
        ), row=2, col=1)
        # 買入
        sim_buys = [t for t in sim_result.trade_log if "買入" in t.get("動作", "")]
        sim_sells = [t for t in sim_result.trade_log if "賣出" in t.get("動作", "")]
        if sim_buys:
            fig_sim_trades.add_trace(go.Scatter(
                x=[t["日期"] for t in sim_buys],
                y=[t["價格"] for t in sim_buys],
                mode="markers",
                marker=dict(symbol="triangle-up", size=14, color="#00E676",
                            line=dict(width=1, color="white")),
                name="買入",
                text=[f"買入 ${t['價格']:.2f}" for t in sim_buys],
                hoverinfo="text+x",
            ), row=1, col=1)
        if sim_sells:
            fig_sim_trades.add_trace(go.Scatter(
                x=[t["日期"] for t in sim_sells],
                y=[t["價格"] for t in sim_sells],
                mode="markers",
                marker=dict(symbol="triangle-down", size=14, color="#FF1744",
                            line=dict(width=1, color="white")),
                name="賣出",
                text=[f"{t['動作']} ${t['價格']:.2f}" for t in sim_sells],
                hoverinfo="text+x",
            ), row=1, col=1)
        fig_sim_trades.update_layout(
            height=500, template="plotly_dark",
            xaxis_rangeslider_visible=False,
            xaxis2_title="日期", yaxis_title="股價", yaxis2_title="成交量",
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            margin=dict(t=40),
        )
        st.plotly_chart(fig_sim_trades, width="stretch")

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
        st.plotly_chart(fig_pnl, width="stretch")

    # 交易明細
    st.subheader("交易明細")
    if sim_result.trade_log:
        trade_df = pd.DataFrame(sim_result.trade_log)
        trade_df["日期"] = trade_df["日期"].dt.strftime("%Y-%m-%d")
        st.dataframe(trade_df, width="stretch")

        _sim_csv = trade_df.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            label="下載交易明細 (CSV)",
            data=_sim_csv,
            file_name=f"simulation_{stock_code}_{sim_days}d.csv",
            mime="text/csv",
        )
    else:
        st.warning("模擬期間沒有產生交易")
        if use_v4:
            st.info(
                "v4 策略在短期模擬中不一定會觸發進場。"
                "模擬僅回放最近 {0} 個交易日，若期間沒有支撐反彈或動量進場訊號就不會交易。"
                "這是正常現象，代表策略在等待更好的時機。".format(sim_days)
            )

    # 每日紀錄
    st.subheader("每日模擬紀錄")
    sim_df = simulation_to_dataframe(sim_result)
    sim_df["日期"] = pd.to_datetime(sim_df["日期"]).dt.strftime("%Y-%m-%d")
    st.dataframe(sim_df, width="stretch", height=400)


def _render_rolling_backtest(stock_code, stock_name, raw_df, use_v4, initial_capital):
    """一致性測試 — Rolling Backtest + Parameter Sensitivity"""
    st.header(f"{stock_code} {stock_name} - 一致性測試")

    if not use_v4:
        st.warning("一致性測試目前僅支援 v4 策略。請在側邊欄切換至 v4。")
        return

    _show_backtest_disclaimers()
    st.caption(
        "將歷史資料分割為多個半年視窗，用相同固定參數分別回測，"
        "驗證策略是否在不同市場環境下穩定獲利。"
        "若一致性分數高，代表策略較不容易過擬合。"
    )

    _tab_rolling, _tab_sensitivity = st.tabs(["前推一致性", "參數敏感度"])

    with _tab_rolling:
        _render_rolling_tab(stock_code, raw_df, initial_capital)

    with _tab_sensitivity:
        _render_sensitivity_tab(stock_code, raw_df, initial_capital)


def _render_rolling_tab(stock_code, raw_df, initial_capital):
    """前推一致性測試 Tab"""
    _window = st.selectbox("視窗大小", [3, 6, 12], index=1,
                           format_func=lambda x: f"{x} 個月", key="rolling_window")

    _cache_key = f"_rolling_{stock_code}_{_window}"
    if st.button("執行一致性測試", type="primary", key="btn_rolling"):
        if len(raw_df) < 200:
            st.warning("資料不足（建議 3 年以上）。請在側邊欄增加回測天數。")
            return
        with st.spinner("正在執行一致性測試..."):
            result = run_rolling_backtest(raw_df, initial_capital=initial_capital,
                                          window_months=_window)
        st.session_state[_cache_key] = result

    result = st.session_state.get(_cache_key)
    if result is None:
        st.info("點擊「執行一致性測試」開始分析。建議使用 3 年以上資料。")
        return

    if result.total_windows == 0:
        st.warning("資料不足，無法產生有效視窗。請增加回測天數。")
        return

    # 一致性分數
    st.subheader("一致性總評")
    _score = result.consistency_score
    if _score >= 70:
        _grade = "優良"
        _color = "#00C853"
    elif _score >= 50:
        _grade = "普通"
        _color = "#FFD600"
    else:
        _grade = "不穩定"
        _color = "#FF1744"

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("一致性分數", f"{_score:.0f}/100",
                   delta=_grade, delta_color="normal" if _score >= 50 else "inverse")
    with c2:
        st.metric("正報酬視窗", f"{result.positive_windows}/{result.total_windows}")
    with c3:
        st.metric("平均報酬率", f"{result.avg_return:.2%}")
    with c4:
        st.metric("報酬標準差", f"{result.return_std:.2%}")

    c5, c6, c7, c8 = st.columns(4)
    with c5:
        st.metric("最佳視窗", f"{result.max_return:.2%}")
    with c6:
        st.metric("最差視窗", f"{result.min_return:.2%}")
    with c7:
        st.metric("平均勝率", f"{result.avg_win_rate:.1%}")
    with c8:
        st.metric("平均最大回撤", f"{result.avg_max_drawdown:.2%}")

    # 各視窗報酬柱狀圖
    st.subheader("各視窗報酬率")
    _names = [w.window_name for w in result.windows]
    _returns = [w.total_return * 100 for w in result.windows]
    _colors = ["#00C853" if r >= 0 else "#FF1744" for r in _returns]

    fig_bar = go.Figure(data=go.Bar(
        x=_names, y=_returns, marker_color=_colors,
        hovertemplate="%{x}<br>報酬: %{y:.2f}%<extra></extra>",
    ))
    fig_bar.add_hline(y=0, line_dash="dash", line_color="white", opacity=0.3)
    fig_bar.update_layout(
        height=350, template="plotly_dark",
        xaxis_title="視窗", yaxis_title="報酬率 (%)",
        margin=dict(t=20, b=30),
    )
    st.plotly_chart(fig_bar, width="stretch")

    # 詳細表格
    st.subheader("各視窗明細")
    _rows = []
    for w in result.windows:
        _rows.append({
            "視窗": w.window_name,
            "期間": f"{w.start_date} ~ {w.end_date}",
            "交易日": w.trading_days,
            "報酬率%": round(w.total_return * 100, 2),
            "年化報酬%": round(w.annual_return * 100, 2),
            "最大回撤%": round(w.max_drawdown * 100, 2),
            "勝率%": round(w.win_rate * 100, 1),
            "交易次數": w.total_trades,
            "盈虧比": round(w.profit_factor, 2),
            "Sharpe": round(w.sharpe_ratio, 2),
        })

    if _rows:
        _df = pd.DataFrame(_rows)

        def _color_ret(val):
            if isinstance(val, (int, float)) and not np.isnan(val):
                return "color: #00C853" if val > 0 else "color: #FF1744" if val < 0 else ""
            return ""

        styled = _df.style.map(_color_ret, subset=["報酬率%", "年化報酬%"])
        st.dataframe(styled, width="stretch", hide_index=True)

    # 解讀
    st.subheader("解讀")
    if _score >= 70:
        st.success(
            f"策略一致性良好（{_score:.0f}/100）。"
            f"在 {result.total_windows} 個視窗中有 {result.positive_windows} 個正報酬，"
            f"報酬標準差 {result.return_std:.2%}，表現穩定。"
        )
    elif _score >= 50:
        st.warning(
            f"策略一致性普通（{_score:.0f}/100）。"
            f"部分視窗表現不佳（最差 {result.min_return:.2%}），"
            f"建議搭配其他策略分散風險。"
        )
    else:
        st.error(
            f"策略一致性偏低（{_score:.0f}/100）。"
            f"不同時期表現差異大（最佳 {result.max_return:.2%} vs 最差 {result.min_return:.2%}），"
            f"可能存在過擬合風險。建議調整參數或重新審視進場條件。"
        )


def _render_sensitivity_tab(stock_code, raw_df, initial_capital):
    """參數敏感度分析 Tab"""
    st.caption(
        "測試不同策略參數對回測結果的影響。"
        "若微小參數變化導致結果劇烈變化，策略可能過擬合。"
    )

    _cache_key = f"_sensitivity_{stock_code}"
    if st.button("執行敏感度分析", type="primary", key="btn_sensitivity"):
        if len(raw_df) < 200:
            st.warning("資料不足（建議 3 年以上）。")
            return
        with st.spinner("正在測試不同參數組合..."):
            results = run_parameter_sensitivity(raw_df, initial_capital=initial_capital)
        st.session_state[_cache_key] = results

    results = st.session_state.get(_cache_key)
    if results is None:
        st.info("點擊「執行敏感度分析」開始分析。")
        return

    if not results:
        st.warning("無法產生有效結果。")
        return

    # 按參數分組顯示
    _params = {}
    for r in results:
        _params.setdefault(r["param"], []).append(r)

    for param_name, param_results in _params.items():
        st.subheader(f"{param_name} 敏感度")

        _values = [str(r["value"]) for r in param_results]
        _ret = [r["return"] * 100 for r in param_results]
        _wr = [r["win_rate"] * 100 for r in param_results]
        _trades = [r["trades"] for r in param_results]

        fig = make_subplots(
            rows=1, cols=2,
            subplot_titles=["報酬率 (%)", "勝率 (%)"],
        )

        fig.add_trace(go.Bar(
            x=_values, y=_ret,
            marker_color=["#00C853" if r >= 0 else "#FF1744" for r in _ret],
            name="報酬率",
            hovertemplate="%{x}<br>報酬: %{y:.2f}%<extra></extra>",
        ), row=1, col=1)

        fig.add_trace(go.Bar(
            x=_values, y=_wr,
            marker_color="#42A5F5",
            name="勝率",
            hovertemplate="%{x}<br>勝率: %{y:.1f}%<extra></extra>",
        ), row=1, col=2)

        fig.update_layout(
            height=300, template="plotly_dark",
            showlegend=False,
            margin=dict(t=40, b=30),
        )
        st.plotly_chart(fig, width="stretch")

        # 明細表
        _tbl = pd.DataFrame([{
            "參數值": str(r["value"]),
            "報酬率%": round(r["return"] * 100, 2),
            "勝率%": round(r["win_rate"] * 100, 1),
            "交易次數": r["trades"],
            "最大回撤%": round(r["max_dd"] * 100, 2),
            "Sharpe": round(r["sharpe"], 2),
        } for r in param_results])
        st.dataframe(_tbl, width="stretch", hide_index=True)

        # 穩定度判定
        _ret_range = max(_ret) - min(_ret)
        if _ret_range < 20:
            st.caption(f"報酬率變化範圍 {_ret_range:.1f}% — 參數對 {param_name} 不敏感 (穩健)")
        elif _ret_range < 50:
            st.caption(f"報酬率變化範圍 {_ret_range:.1f}% — 參數對 {param_name} 中度敏感")
        else:
            st.caption(f"報酬率變化範圍 {_ret_range:.1f}% — 參數對 {param_name} 高度敏感 (注意過擬合)")

        # 懸崖效應偵測：使用敏感度係數 = |報酬變化%| / |參數變化%|
        if len(param_results) >= 3:
            _best_idx = max(range(len(_ret)), key=lambda i: _ret[i])
            _best_ret = _ret[_best_idx]
            _raw_values = [r["value"] for r in param_results]
            if _best_ret > 0:
                _max_sensitivity = 0.0
                _cliff_detail = ""
                for _ni in [_best_idx - 1, _best_idx + 1]:
                    if 0 <= _ni < len(_ret):
                        _ret_change = abs(_best_ret - _ret[_ni])
                        _best_val = float(_raw_values[_best_idx])
                        _neighbor_val = float(_raw_values[_ni])
                        _param_change_pct = abs(_best_val - _neighbor_val) / abs(_best_val) * 100 if _best_val != 0 else 100
                        _sensitivity = _ret_change / _param_change_pct if _param_change_pct > 0 else 0
                        if _sensitivity > _max_sensitivity:
                            _max_sensitivity = _sensitivity
                            _cliff_detail = (
                                f"最佳值 {_values[_best_idx]} 報酬 {_best_ret:.1f}%，"
                                f"相鄰值 {_values[_ni]} 報酬 {_ret[_ni]:.1f}%"
                                f"（敏感度係數 {_sensitivity:.1f}）"
                            )
                # 敏感度係數 > 3：參數變動 1% 導致報酬變動 > 3%
                if _max_sensitivity > 3:
                    st.error(
                        f"懸崖效應：{_cliff_detail}。"
                        f"參數微調即造成報酬劇烈變動，過擬合風險極高。"
                    )
                elif _max_sensitivity > 1.5:
                    st.warning(
                        f"參數敏感：{_cliff_detail}。"
                        f"建議驗證相鄰參數值的一致性。"
                    )

    # 總結
    st.subheader("總結")
    _all_returns = [r["return"] * 100 for r in results]
    _overall_std = float(np.std(_all_returns))
    if _overall_std < 15:
        st.success(f"參數敏感度低（報酬率標準差 {_overall_std:.1f}%）。策略對參數變化穩健，過擬合風險低。")
    elif _overall_std < 30:
        st.warning(f"參數敏感度中等（報酬率標準差 {_overall_std:.1f}%）。部分參數調整會顯著影響結果。")
    else:
        st.error(f"參數敏感度高（報酬率標準差 {_overall_std:.1f}%）。策略高度依賴特定參數設定，過擬合風險高。")
