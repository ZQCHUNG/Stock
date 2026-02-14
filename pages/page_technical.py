"""技術分析頁面"""

import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np

from analysis.strategy import generate_signals, get_latest_analysis
from analysis.strategy_v4 import generate_v4_signals, get_v4_analysis
from backtest.engine import run_backtest, run_backtest_v4
from data.stock_list import get_stock_name
from pages.common import explain_signal


def render(stock_code, stock_name, raw_df, use_v4, all_stocks,
           v4_params, buy_threshold, sell_threshold,
           initial_capital, backtest_days,
           save_watchlist_fn, load_data_fn):
    st.header(f"{stock_code} {stock_name} - 技術分析")

    # 自選股快捷按鈕
    _wl = st.session_state.get("watchlist", [])
    _in_wl = stock_code in _wl
    _wl_col1, _wl_col2 = st.columns([1, 5])
    with _wl_col1:
        if _in_wl:
            if st.button("從自選股移除", key="tech_wl_remove", type="secondary"):
                st.session_state.watchlist.remove(stock_code)
                save_watchlist_fn(st.session_state.watchlist)
                st.rerun()
        else:
            if st.button("加入自選股", key="tech_wl_add", type="primary"):
                st.session_state.watchlist.append(stock_code)
                save_watchlist_fn(st.session_state.watchlist)
                st.rerun()
    with _wl_col2:
        if _in_wl:
            st.caption("已在自選股清單中")

    if use_v4:
        # v4 分析
        analysis = get_v4_analysis(raw_df)
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("收盤價", f"${analysis['close']:.2f}")
        with col2:
            signal_map = {"BUY": "🟢 買入", "SELL": "🔴 賣出", "HOLD": "🟡 觀望"}
            st.metric("v4 訊號", signal_map.get(analysis["signal"], analysis["signal"]))
        with col3:
            _entry_map = {"support": "支撐", "momentum": "動量"}
            entry_label = _entry_map.get(analysis["entry_type"], "—")
            st.metric("進場類型", entry_label)
        with col4:
            ut = analysis["uptrend_days"]
            st.metric("趨勢天數", f"{ut} 天")

        # v4 指標明細
        st.subheader("v4 策略指標")
        ind = analysis["indicators"]
        ind_cols = st.columns(5)
        with ind_cols[0]:
            adx_val = ind.get("ADX")
            st.metric("ADX", f"{adx_val:.1f}" if adx_val and not pd.isna(adx_val) else "N/A",
                      help=f"要求 ≥ {v4_params['adx_min']}")
        with ind_cols[1]:
            rsi_val = ind.get("RSI")
            st.metric("RSI", f"{rsi_val:.1f}" if rsi_val and not pd.isna(rsi_val) else "N/A")
        with ind_cols[2]:
            di_p = ind.get("+DI")
            st.metric("+DI", f"{di_p:.1f}" if di_p and not pd.isna(di_p) else "N/A")
        with ind_cols[3]:
            di_m = ind.get("-DI")
            st.metric("-DI", f"{di_m:.1f}" if di_m and not pd.isna(di_m) else "N/A")
        with ind_cols[4]:
            dist = analysis["dist_ma20"]
            st.metric("MA20距離", f"{dist:+.1%}" if not pd.isna(dist) else "N/A")

        # v4 訊號說明
        st.subheader("v4 訊號分析")
        _entry_label_map = {"support": "支撐反彈", "momentum": "動量突破"}
        if analysis["signal"] == "BUY":
            _et_label = _entry_label_map.get(analysis["entry_type"], analysis["entry_type"])
            st.success(f"**建議買入**（{_et_label}）— 趨勢確認 {ut} 天，ADX={ind.get('ADX', 0):.1f}，RSI={ind.get('RSI', 0):.1f}")
        elif analysis["signal"] == "SELL":
            reasons = ["MA20 < MA60（下降趨勢）", "-DI > +DI（空方主導）"]
            if rsi_val and not pd.isna(rsi_val) and rsi_val > 70:
                reasons.append(f"RSI 過熱（{rsi_val:.1f}）")
            st.error("**建議賣出** — " + "；".join(reasons))
        else:
            reasons = []
            if ut < v4_params["min_uptrend_days"]:
                reasons.append(f"上升趨勢天數不足（{ut} < {v4_params['min_uptrend_days']}）")
            if adx_val and not pd.isna(adx_val) and adx_val < v4_params["adx_min"]:
                reasons.append(f"ADX 趨勢強度不足（{adx_val:.1f} < {v4_params['adx_min']}）")
            if di_p and di_m and not pd.isna(di_p) and di_p <= di_m:
                reasons.append("+DI ≤ -DI，方向偏空")
            if not reasons:
                reasons.append("進場條件未滿足（支撐/動量模式均未觸發）")
            st.warning("**建議觀望** — " + "；".join(reasons))

        # --- 下單計算機 ---
        with st.expander("下單計算機", expanded=False):
            # 市場環境自動調整
            _regime = st.session_state.get("_market_regime")
            _regime_mult = 1.0
            if _regime:
                _regime_mult = _regime.get("position_multiplier", 1.0)
                _r_label = _regime.get("regime_label", "未知")
                if _regime.get("regime") == "bear":
                    st.warning(f"大盤環境：{_r_label}（部位自動降至 {_regime_mult:.0%}）")
                elif _regime.get("regime") == "sideways":
                    st.info(f"大盤環境：{_r_label}（部位建議降至 {_regime_mult:.0%}）")

            _calc_cols = st.columns(3)
            with _calc_cols[0]:
                _total_capital = st.number_input(
                    "總資金 (TWD)", min_value=100_000, max_value=100_000_000,
                    value=initial_capital, step=100_000, key="calc_capital",
                )
            with _calc_cols[1]:
                _risk_pct = st.slider(
                    "單筆風險上限 (%)", 1, 10, 2, key="calc_risk_pct",
                    help="單筆交易最多虧損總資金的百分比",
                )
            with _calc_cols[2]:
                # 空頭市場時信心分數上限鎖定
                _conf_options = [1.0, 1.5, 1.7, 2.0]
                if _regime and _regime.get("regime") == "bear":
                    _conf_options = [0.5, 1.0]
                    st.caption("空頭市場：信心分數上限鎖定")
                _confidence = st.selectbox(
                    "信心分數", _conf_options, index=0, key="calc_confidence",
                    help="1.0=純技術, 1.5=法人買入, 1.7=投信連買, 2.0=全法人連3買",
                )

            _price = analysis["close"]
            _sl_pct = v4_params["stop_loss_pct"]
            _sl_price = _price * (1 - _sl_pct)
            _loss_per_share = _price - _sl_price

            # 風險金額 = 總資金 * 風險比例 * 信心倍數 * 市場環境倍率
            _effective_risk = _total_capital * (_risk_pct / 100) * _confidence * _regime_mult
            # 可買股數（向下取整到 1000 股 = 1 張）
            _shares = int(_effective_risk / _loss_per_share) if _loss_per_share > 0 else 0
            _lots = _shares // 1000
            _shares_rounded = _lots * 1000
            _cost = _shares_rounded * _price
            _max_loss = _shares_rounded * _loss_per_share

            _r_cols = st.columns(4)
            with _r_cols[0]:
                st.metric("建議張數", f"{_lots} 張" if _lots > 0 else "不建議")
            with _r_cols[1]:
                st.metric("買入成本", f"${_cost:,.0f}")
            with _r_cols[2]:
                st.metric("停損價", f"${_sl_price:.2f}")
            with _r_cols[3]:
                st.metric("最大虧損", f"${_max_loss:,.0f}")

            # 購買力檢查
            if _cost > _total_capital:
                st.error(f"買入成本 (${_cost:,.0f}) 超過總資金 (${_total_capital:,.0f})，無法執行。")
            elif _cost > _total_capital * 0.9:
                st.warning(f"買入成本佔總資金 {_cost/_total_capital*100:.0f}%，集中度過高。")
            elif _lots > 0:
                _cost_pct = _cost / _total_capital * 100
                _loss_pct = _max_loss / _total_capital * 100
                st.caption(
                    f"佔總資金 {_cost_pct:.1f}% | "
                    f"停損 -{_sl_pct:.0%} = ${_sl_price:.2f} | "
                    f"最大虧損佔總資金 {_loss_pct:.1f}%"
                )
                if _regime_mult < 1.0:
                    st.caption(f"市場環境倍率 {_regime_mult:.0%} 已自動調整部位大小")

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
        explanation = explain_signal(analysis, buy_threshold, sell_threshold)
        st.markdown(explanation)

    # K線圖 + 技術指標（快取訊號結果避免重複計算）
    _sig_cache_key = f"_signals_{stock_code}_{len(raw_df)}_{use_v4}"
    if _sig_cache_key in st.session_state:
        _full_signals_df = st.session_state[_sig_cache_key]
    else:
        _full_signals_df = generate_v4_signals(raw_df) if use_v4 else generate_signals(raw_df)
        st.session_state[_sig_cache_key] = _full_signals_df
    signals_df = _full_signals_df.tail(120)

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
        increasing_line_color="#EF5350",
        decreasing_line_color="#26A69A",
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

    # 支撐/壓力線
    _sr_highs = signals_df["high"].values
    _sr_lows = signals_df["low"].values
    _sr_window = 5
    _sr_levels = []
    for i in range(_sr_window, len(_sr_highs) - _sr_window):
        if _sr_highs[i] == max(_sr_highs[i - _sr_window:i + _sr_window + 1]):
            _sr_levels.append(("resistance", _sr_highs[i]))
        if _sr_lows[i] == min(_sr_lows[i - _sr_window:i + _sr_window + 1]):
            _sr_levels.append(("support", _sr_lows[i]))
    _sr_clustered = []
    _sr_used = set()
    for idx, (kind, level) in enumerate(sorted(_sr_levels, key=lambda x: x[1])):
        if idx in _sr_used:
            continue
        cluster = [level]
        for jdx, (_, other) in enumerate(sorted(_sr_levels, key=lambda x: x[1])):
            if jdx != idx and jdx not in _sr_used and abs(other - level) / level < 0.015:
                cluster.append(other)
                _sr_used.add(jdx)
        _sr_used.add(idx)
        avg_level = np.mean(cluster)
        _sr_clustered.append((kind, avg_level, len(cluster)))
    _cur_price = signals_df["close"].iloc[-1]
    _sr_filtered = [(k, lvl, cnt) for k, lvl, cnt in _sr_clustered
                     if abs(lvl - _cur_price) / _cur_price < 0.15]
    _sr_filtered.sort(key=lambda x: x[2], reverse=True)
    for _sr_kind, _sr_lvl, _sr_cnt in _sr_filtered[:6]:
        _sr_color = "rgba(255,23,68,0.4)" if _sr_kind == "resistance" else "rgba(0,200,83,0.4)"
        _sr_label = f"{'壓力' if _sr_kind == 'resistance' else '支撐'} ${_sr_lvl:.1f}"
        fig.add_hline(
            y=_sr_lvl, line_dash="dot", line_color=_sr_color, opacity=0.6,
            annotation_text=_sr_label, annotation_position="right",
            annotation_font_size=10, annotation_font_color=_sr_color,
            row=1, col=1,
        )

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

    st.plotly_chart(fig, width="stretch")

    # 支撐壓力摘要
    if _sr_filtered:
        _supports = sorted([lvl for k, lvl, _ in _sr_filtered if k == "support"], reverse=True)
        _resistances = sorted([lvl for k, lvl, _ in _sr_filtered if k == "resistance"])
        _sr_parts = []
        if _supports:
            _sr_parts.append("支撐：" + " / ".join([f"\\${s:.1f}" for s in _supports[:3]]))
        if _resistances:
            _sr_parts.append("壓力：" + " / ".join([f"\\${r:.1f}" for r in _resistances[:3]]))
        if _sr_parts:
            st.caption("關鍵價位 — " + "　|　".join(_sr_parts))

    # --- 股價比較 ---
    st.divider()
    st.subheader("股價比較")
    _benchmarks = ["0050"]
    _wl_codes = [c for c in st.session_state.get("watchlist", []) if c != stock_code]
    _compare_pool = _benchmarks + _wl_codes
    _compare_options = [f"{c} {get_stock_name(c, all_stocks)}" for c in _compare_pool if c != stock_code]
    _comp_selected = st.multiselect(
        "選擇比較標的（可多選）",
        _compare_options,
        key="tech_compare",
        help="選擇後會疊加正規化報酬率折線圖",
    )

    if _comp_selected:
        _comp_days_tech = st.slider("比較天數", 30, 365, 90, key="tech_comp_days")
        fig_cmp = go.Figure()

        _cur_close = raw_df["close"].tail(_comp_days_tech)
        if len(_cur_close) >= 2:
            _cur_base = _cur_close.iloc[0]
            _cur_norm = (_cur_close / _cur_base - 1) * 100
            fig_cmp.add_trace(go.Scatter(
                x=_cur_close.index, y=_cur_norm,
                mode="lines", name=f"{stock_code} {stock_name}",
                line=dict(width=2.5),
            ))

        for _cmp_item in _comp_selected:
            _cmp_code = _cmp_item.split()[0]
            try:
                _cmp_df = load_data_fn(_cmp_code, _comp_days_tech + 30)
                if _cmp_df is None or _cmp_df.empty:
                    continue
                _cmp_close = _cmp_df["close"].tail(_comp_days_tech)
                if len(_cmp_close) < 2:
                    continue
                _cmp_base = _cmp_close.iloc[0]
                _cmp_norm = (_cmp_close / _cmp_base - 1) * 100
                _cmp_name = get_stock_name(_cmp_code, all_stocks)
                fig_cmp.add_trace(go.Scatter(
                    x=_cmp_close.index, y=_cmp_norm,
                    mode="lines", name=f"{_cmp_code} {_cmp_name}",
                ))
            except Exception:
                continue

        fig_cmp.add_hline(y=0, line_dash="dash", line_color="white", opacity=0.3)
        fig_cmp.update_layout(
            yaxis_title="報酬率 (%)",
            xaxis_title="日期",
            hovermode="x unified",
            template="plotly_dark",
            height=400,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        st.plotly_chart(fig_cmp, width="stretch")

    # --- 快速回測摘要 ---
    st.divider()
    with st.expander("快速回測摘要（730 天）", expanded=False):
        _qbt_df = raw_df.tail(730 + 60)
        if use_v4:
            _qbt = run_backtest_v4(_qbt_df, initial_capital=initial_capital)
        else:
            _qbt = run_backtest(_qbt_df, initial_capital=initial_capital)
        _qbt_cols = st.columns(6)
        with _qbt_cols[0]:
            st.metric("總報酬", f"{_qbt.total_return:.2%}")
        with _qbt_cols[1]:
            st.metric("年化報酬", f"{_qbt.annual_return:.2%}")
        with _qbt_cols[2]:
            st.metric("最大回撤", f"{_qbt.max_drawdown:.2%}")
        with _qbt_cols[3]:
            st.metric("勝率", f"{_qbt.win_rate:.0%}")
        with _qbt_cols[4]:
            st.metric("交易次數", f"{_qbt.total_trades}")
        with _qbt_cols[5]:
            st.metric("Sharpe", f"{_qbt.sharpe_ratio:.2f}")
        st.caption("展開「回測報告」頁面查看完整分析")

    # --- 法人籌碼 ---
    with st.expander("法人籌碼（三大法人買賣超）", expanded=False):
        _render_institutional(stock_code)


def _render_institutional(stock_code):
    """顯示法人籌碼資料"""
    # 使用 session_state 快取避免重複 API 呼叫
    _cache_key = f"_inst_{stock_code}"
    if _cache_key not in st.session_state:
        if st.button("載入法人資料", key=f"inst_load_{stock_code}",
                     help="從 TWSE 取得近 20 個交易日的三大法人買賣超"):
            with st.spinner("載入法人籌碼資料（約 10 秒）..."):
                try:
                    from data.fetcher import get_institutional_data
                    inst_df = get_institutional_data(stock_code, days=20)
                    st.session_state[_cache_key] = inst_df
                except Exception as e:
                    st.error(f"載入失敗：{e}")
                    return
        else:
            st.caption("點擊「載入法人資料」查看三大法人近期動態。")
            return

    inst_df = st.session_state.get(_cache_key)
    if inst_df is None or inst_df.empty:
        st.info("無法取得法人資料，可能此股票非上市股票或資料暫未更新。")
        return

    # 摘要指標
    _recent_5 = inst_df.tail(5)
    _foreign_5 = _recent_5["foreign_net"].sum()
    _trust_5 = _recent_5["trust_net"].sum()
    _dealer_5 = _recent_5["dealer_net"].sum()
    _total_5 = _recent_5["total_net"].sum()

    _cols = st.columns(4)
    with _cols[0]:
        _f_color = "normal" if _foreign_5 > 0 else "inverse"
        st.metric("外資 (5日)", f"{_foreign_5:+,.0f} 股",
                   delta=f"{'買超' if _foreign_5 > 0 else '賣超'}", delta_color=_f_color)
    with _cols[1]:
        _t_color = "normal" if _trust_5 > 0 else "inverse"
        st.metric("投信 (5日)", f"{_trust_5:+,.0f} 股",
                   delta=f"{'買超' if _trust_5 > 0 else '賣超'}", delta_color=_t_color)
    with _cols[2]:
        _d_color = "normal" if _dealer_5 > 0 else "inverse"
        st.metric("自營商 (5日)", f"{_dealer_5:+,.0f} 股",
                   delta=f"{'買超' if _dealer_5 > 0 else '賣超'}", delta_color=_d_color)
    with _cols[3]:
        _tt_color = "normal" if _total_5 > 0 else "inverse"
        st.metric("三大法人 (5日)", f"{_total_5:+,.0f} 股",
                   delta=f"{'買超' if _total_5 > 0 else '賣超'}", delta_color=_tt_color)

    # 買賣超趨勢圖
    fig_inst = go.Figure()
    fig_inst.add_trace(go.Bar(
        x=inst_df.index, y=inst_df["foreign_net"],
        name="外資", marker_color="#2196F3",
    ))
    fig_inst.add_trace(go.Bar(
        x=inst_df.index, y=inst_df["trust_net"],
        name="投信", marker_color="#FF9800",
    ))
    fig_inst.add_trace(go.Bar(
        x=inst_df.index, y=inst_df["dealer_net"],
        name="自營商", marker_color="#9C27B0",
    ))
    fig_inst.add_trace(go.Scatter(
        x=inst_df.index, y=inst_df["total_net"],
        mode="lines+markers", name="三大法人合計",
        line=dict(color="white", width=2),
    ))
    fig_inst.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
    fig_inst.update_layout(
        height=350, template="plotly_dark",
        barmode="group",
        yaxis_title="買賣超 (股)", xaxis_title="日期",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(t=40, b=30),
    )
    st.plotly_chart(fig_inst, width="stretch")

    # 明細表
    _display_df = inst_df.copy()
    _display_df.index = _display_df.index.strftime("%Y-%m-%d")
    for col in ["foreign_net", "trust_net", "dealer_net", "total_net"]:
        _display_df[col] = _display_df[col].apply(lambda x: f"{x:+,.0f}")
    _display_df.columns = ["外資", "投信", "自營商", "三大法人"]
    st.dataframe(_display_df, width="stretch")
