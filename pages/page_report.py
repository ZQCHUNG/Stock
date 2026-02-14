"""分析報告頁面"""

import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import numpy as np

from analysis.report import generate_report


def _esc(text: str) -> str:
    """Escape $ signs to prevent Streamlit LaTeX rendering"""
    return text.replace("$", "\\$") if text else text


def render(stock_code, add_recent_fn):
    st.header(f"分析報告 — {stock_code}")

    # 產生報告
    auto_report = st.session_state.pop("_auto_report", False)
    cached = st.session_state.get("_cached_report")
    need_generate = auto_report or cached is None or (cached is not None and cached.stock_code != stock_code)

    col_btn, col_hint = st.columns([1, 3])
    with col_btn:
        manual_click = st.button("重新產生報告", type="primary")
    with col_hint:
        if cached and cached.stock_code == stock_code:
            st.caption(f"已載入 {stock_code} 報告，可直接查看。點左方按鈕可重新產生。")

    if need_generate or manual_click:
        with st.spinner("正在產生專業分析報告，請稍候（約 10-30 秒）..."):
            try:
                _regime_info = st.session_state.get("_market_regime")
                _mkt_regime = _regime_info["regime"] if _regime_info else None
                report = generate_report(stock_code, period_days=730,
                                          market_regime=_mkt_regime)
                add_recent_fn(stock_code)
                st.session_state["_cached_report"] = report
            except Exception as e:
                st.error(f"報告產生失敗：{e}")
                st.session_state.pop("_cached_report", None)
                st.stop()

    cached = st.session_state.get("_cached_report")
    if cached is None:
        st.info("報告產生中...")
        return

    report = cached

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

    # ---- 一、摘要（always visible）----
    st.subheader("分析摘要")
    st.markdown(_esc(report.summary_text))

    # ---- 行動建議（提到最上方，最重要的資訊先看）----
    rec = report.actionable_recommendation
    if rec:
        action = rec.get("action", "HOLD")
        action_display = {
            "BUY": ("🟢 買入", "success"), "SELL": ("🔴 賣出", "error"),
            "HOLD": ("🟡 觀望", "info"), "AVOID": ("⛔ 避開", "warning"),
        }
        label, msg_type = action_display.get(action, ("🟡 觀望", "info"))
        getattr(st, msg_type)(f"**{label}** — {rec.get('thesis', '')}")

        if action in ("BUY", "SELL"):
            price_cols = st.columns(5)
            with price_cols[0]:
                if rec.get("entry_low") and rec.get("entry_high"):
                    st.metric("進場區間", f"\\${rec['entry_low']:.2f}～\\${rec['entry_high']:.2f}")
            with price_cols[1]:
                if rec.get("stop_loss"):
                    st.metric("停損", f"\\${rec['stop_loss']:.2f}")
            with price_cols[2]:
                if rec.get("take_profit_t1"):
                    st.metric("目標 T1", f"\\${rec['take_profit_t1']:.2f}")
            with price_cols[3]:
                if rec.get("take_profit_t2"):
                    st.metric("目標 T2", f"\\${rec['take_profit_t2']:.2f}")
            with price_cols[4]:
                st.metric("建議部位", rec.get("position_pct", "N/A"))

        triggers = rec.get("trigger_conditions", [])
        if triggers:
            st.markdown("**觸發條件**")
            for trigger in triggers:
                st.markdown(f"- {_esc(trigger)}")

    # ---- 分頁式詳細分析 ----
    tab_fund, tab_tech, tab_inst, tab_news, tab_price, tab_risk, tab_strategy = st.tabs(
        ["基本面", "技術面", "籌碼面", "消息面", "關鍵價位", "風險評估", "展望策略"]
    )

    # ========== Tab: 基本面 ==========
    with tab_fund:
        _render_tab_fundamentals(report, _esc)

    # ========== Tab: 技術面 ==========
    with tab_tech:
        _render_tab_technical(report, _esc)

    # ========== Tab: 籌碼面 ==========
    with tab_inst:
        _render_tab_institutional(stock_code)

    # ========== Tab: 消息面 ==========
    with tab_news:
        _render_tab_news(report, _esc)

    # ========== Tab: 關鍵價位 ==========
    with tab_price:
        _render_tab_price(report)

    # ========== Tab: 風險評估 ==========
    with tab_risk:
        _render_tab_risk(report, _esc)

    # ========== Tab: 展望策略 ==========
    with tab_strategy:
        _render_tab_strategy(report, _esc)

    # ---- 下載 ----
    _render_download(report, rec)


def _render_tab_fundamentals(report, _esc):
    """基本面分頁"""
    info = report.company_info
    ov_col1, ov_col2 = st.columns(2)
    with ov_col1:
        info_cols = st.columns(2)
        with info_cols[0]:
            st.metric("股票代碼", report.stock_code)
            sector = info.get("sector") or info.get("industry") or "N/A"
            st.metric("產業", sector)
        with info_cols[1]:
            st.metric("公司名稱", report.stock_name)
            mc = info.get("market_cap", 0)
            if mc and mc > 0:
                if mc >= 1e12:
                    mc_str = f"${mc/1e12:.1f} 兆"
                elif mc >= 1e8:
                    mc_str = f"${mc/1e8:.1f} 億"
                else:
                    mc_str = f"${mc:,.0f}"
            else:
                mc_str = "N/A"
            st.metric("市值", mc_str)
            shares = info.get("shares_outstanding", 0)
            if shares and shares > 0:
                capital = shares * 10
                if capital >= 1e8:
                    cap_str = f"${capital/1e8:.1f} 億"
                else:
                    cap_str = f"${capital:,.0f}"
            else:
                cap_str = "N/A"
            st.metric("股本", cap_str)
    with ov_col2:
        perf_data = pd.DataFrame({
            "期間": ["1 週", "1 個月", "3 個月", "6 個月", "1 年", "距 52W 高", "距 52W 低"],
            "漲跌幅": [
                f"{report.price_change_1w:+.2%}",
                f"{report.price_change_1m:+.2%}",
                f"{report.price_change_3m:+.2%}",
                f"{report.price_change_6m:+.2%}",
                f"{report.price_change_1y:+.2%}",
                f"{report.pct_from_52w_high:+.2%}",
                f"{report.pct_from_52w_low:+.2%}",
            ],
            "備註": [
                "", "", "", "",
                "",
                f"高點 ${report.high_52w:.2f}（{report.high_52w_date}）",
                f"低點 ${report.low_52w:.2f}（{report.low_52w_date}）",
            ],
        })
        st.dataframe(perf_data, hide_index=True, width="stretch")

    # 基本面
    if report.fundamentals and any(v != "N/A" for v in report.fundamentals.values()):
        fm = report.fundamentals
        fund_col1, fund_col2 = st.columns(2)
        with fund_col1:
            st.markdown("**估值與獲利**")
            val_data = pd.DataFrame({
                "指標": ["本益比 (TTM)", "預估本益比", "股價淨值比", "EPS (TTM)", "預估 EPS", "獲利成長率", "營收成長率"],
                "數值": [
                    fm.get("trailing_pe", "N/A"), fm.get("forward_pe", "N/A"),
                    fm.get("price_to_book", "N/A"), fm.get("trailing_eps", "N/A"),
                    fm.get("forward_eps", "N/A"), fm.get("earnings_growth", "N/A"),
                    fm.get("revenue_growth", "N/A"),
                ],
            })
            st.dataframe(val_data, hide_index=True, width="stretch")
        with fund_col2:
            st.markdown("**財務與股利**")
            fin_data = pd.DataFrame({
                "指標": ["ROE", "ROA", "淨利率", "負債權益比", "殖利率", "Beta", "基本面評分"],
                "數值": [
                    fm.get("roe", "N/A"), fm.get("roa", "N/A"),
                    fm.get("profit_margins", "N/A"), fm.get("debt_to_equity", "N/A"),
                    fm.get("dividend_yield", "N/A"), fm.get("beta", "N/A"),
                    f"{'🟢' if report.fundamental_score >= 2 else '🔴' if report.fundamental_score <= -2 else '🟡'} {report.fundamental_score:+.1f}",
                ],
            })
            st.dataframe(fin_data, hide_index=True, width="stretch")

        ad = report.analyst_data
        if ad and ad.get("target_mean"):
            n = ad.get("num_analysts")
            n_str = f"{int(n)} 位分析師" if n else "分析師"
            upside = ad.get("upside", 0)
            target_msg = f"{n_str}目標均價 \\${ad['target_mean']:.0f}（{upside:+.0%}）"
            if upside > 0:
                st.success(target_msg)
            elif upside < -0.05:
                st.warning(target_msg)
            else:
                st.info(target_msg)

        if report.fundamental_interpretation:
            st.markdown(_esc(report.fundamental_interpretation))
    else:
        st.info("此股票基本面數據不足，可能為小型股或上櫃股，yfinance 尚未提供完整基本面資料。")


def _render_tab_technical(report, _esc):
    """技術面分頁"""
    trend_cols = st.columns(4)
    with trend_cols[0]:
        st.metric("趨勢方向", report.trend_direction)
    with trend_cols[1]:
        st.metric("趨勢強度", report.trend_strength)
    with trend_cols[2]:
        st.metric("均線排列", report.ma_alignment)
    with trend_cols[3]:
        st.metric("動能狀態", report.momentum_status)

    with st.expander("指標明細"):
        tech_col1, tech_col2 = st.columns(2)
        with tech_col1:
            tech_data = pd.DataFrame({
                "指標": ["ADX", "RSI", "MACD", "KD"],
                "數值": [
                    f"{report.adx_value:.1f}",
                    f"{report.rsi_value:.1f}",
                    f"{report.macd_value:.4f}",
                    f"K={report.k_value:.1f} / D={report.d_value:.1f}",
                ],
                "解讀": [
                    report.adx_interpretation.split("（")[0],
                    report.rsi_interpretation,
                    report.macd_interpretation.split("，")[0],
                    report.kd_interpretation,
                ],
            })
            st.dataframe(tech_data, hide_index=True, width="stretch")
        with tech_col2:
            vol_data = pd.DataFrame({
                "指標": ["量能趨勢", "量能比", "籌碼判斷"],
                "數值": [
                    report.volume_trend,
                    f"{report.volume_ratio:.1f}x",
                    report.accumulation_distribution,
                ],
            })
            st.dataframe(vol_data, hide_index=True, width="stretch")
        st.markdown(_esc(report.volume_interpretation))

    if report.technical_bias:
        st.markdown(f"**綜合技術偏向：{report.technical_bias}**")
    if report.technical_conflicts:
        for conflict in report.technical_conflicts:
            st.warning(f"{conflict}")


def _render_tab_institutional(stock_code):
    """籌碼面分頁 — 三大法人買賣超"""
    _cache_key = f"_rpt_inst_{stock_code}"
    if _cache_key not in st.session_state:
        if st.button("載入法人資料", key=f"rpt_inst_load_{stock_code}",
                     help="從 TWSE / Redis 取得近 20 日三大法人買賣超"):
            with st.spinner("載入法人籌碼資料..."):
                try:
                    from data.fetcher import get_institutional_data
                    inst_df = get_institutional_data(stock_code, days=20)
                    st.session_state[_cache_key] = inst_df
                except Exception as e:
                    st.error(f"載入失敗：{e}")
                    return
        else:
            st.info("點擊「載入法人資料」查看三大法人近期動態。")
            return

    inst_df = st.session_state.get(_cache_key)
    if inst_df is None or inst_df.empty:
        st.info("無法取得法人資料，可能此股票非上市股票或資料暫未更新。")
        return

    # 確認訊號
    from analysis.strategy_v4 import get_v4_analysis_with_institutional
    from data.fetcher import get_stock_data
    try:
        _df = get_stock_data(stock_code, period_days=200)
        _analysis = get_v4_analysis_with_institutional(_df, inst_df)
        _conf = _analysis.get("institutional_confirmation", "N/A")
        _conf_map = {
            "strong": ("強力確認", "三大法人齊買", "success"),
            "moderate": ("中度確認", "外資或投信買超", "success"),
            "weak": ("弱確認", "合計買超但法人分歧", "info"),
            "neutral": ("中性", "法人無明顯動向", "info"),
            "negative": ("反向訊號", "法人淨賣超", "warning"),
        }
        _label, _desc, _msg_type = _conf_map.get(_conf, ("N/A", "", "info"))
        getattr(st, _msg_type)(f"**法人確認度：{_label}** — {_desc}")
    except Exception:
        pass

    # 5 日摘要
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

    # 趨勢圖
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
        height=400, template="plotly_dark",
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


def _render_tab_news(report, _esc):
    """消息面分頁"""
    if report.news_items:
        sent_cols = st.columns(3)
        with sent_cols[0]:
            sent_icon = {"偏多": "📈", "偏空": "📉", "中性": "➖"}.get(report.news_sentiment_label, "❓")
            st.metric("新聞情緒", f"{sent_icon} {report.news_sentiment_label}")
        with sent_cols[1]:
            st.metric("相關新聞數", f"{len(report.news_items)} 則")
        with sent_cols[2]:
            st.metric("情緒分數", f"{report.news_sentiment_score:+.1f}")

        if report.news_contradictions:
            for contradiction in report.news_contradictions:
                st.error(f"**消息 vs 數據矛盾：**{_esc(contradiction)}")
        if report.news_insights:
            with st.expander("消息面洞察（可信來源摘要）"):
                for insight in report.news_insights:
                    s_label = insight.get("sentiment", "中性")
                    s_map = {"利多": "🟢", "利空": "🔴", "中性": "🟡"}
                    st.markdown(f"{s_map.get(s_label, '🟡')} **{_esc(insight['title'][:60])}** — {insight.get('source', '')}")
        if report.news_themes:
            with st.expander("新聞主題分類"):
                for theme, titles in report.news_themes.items():
                    st.markdown(f"**{theme}**（{len(titles)} 則）")
                    for t in titles[:3]:
                        st.markdown(f"- {_esc(t[:60])}")

        with st.expander(f"近期新聞列表（{len(report.news_items)} 則）"):
            for n in report.news_items:
                cred_icon = n.get("credibility_icon", "")
                s_icon = n.get("sentiment_icon", "")
                title = n.get("title", "")
                source = n.get("source", "")
                raw_date = n.get("date", "") or ""
                try:
                    from email.utils import parsedate_to_datetime
                    dt = parsedate_to_datetime(raw_date)
                    date_str = dt.strftime("%Y-%m-%d")
                except Exception:
                    date_str = raw_date[:10] if len(raw_date) >= 10 else raw_date
                url = n.get("url", "")
                st.markdown(
                    f"{s_icon}{cred_icon} **{_esc(title)}**\n\n"
                    f"來源：{source} | {date_str} | "
                    f"可信度：{n.get('credibility', 'N/A')} | "
                    f"情緒：{n.get('sentiment', 'N/A')}"
                )
                if url:
                    st.markdown(f"[閱讀全文]({url})")
                st.divider()
    else:
        st.info("此股票近期無相關新聞。")


def _render_tab_price(report):
    """關鍵價位分頁"""
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
            st.dataframe(pd.DataFrame(r_data), hide_index=True, width="stretch")
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
            st.dataframe(pd.DataFrame(s_data), hide_index=True, width="stretch")
        else:
            st.info("無明顯支撐位")

    # 六個月目標價
    st.markdown("**六個月目標價**")
    tf_targets_6m = [t for t in report.price_targets if t.timeframe == "6M"]
    tgt_cols = st.columns(3)
    scenario_map = {"bull": ("樂觀", "🟢"), "base": ("基本", "🟡"), "bear": ("保守", "🔴")}
    for t in tf_targets_6m:
        s_label, s_icon = scenario_map.get(t.scenario, (t.scenario, ""))
        col_idx = 0 if t.scenario == "bull" else 1 if t.scenario == "base" else 2
        with tgt_cols[col_idx]:
            st.metric(
                f"{s_icon} {s_label}情境",
                f"${t.target_price:.2f}",
                delta=f"{t.upside_pct:+.2%}",
            )

    with st.expander("3M/1Y 目標價及費氏分析"):
        for tf_label in ["3M", "1Y"]:
            tf_map = {"3M": "三個月", "1Y": "一年"}
            st.markdown(f"**{tf_map[tf_label]}目標價**")
            tf_targets = [t for t in report.price_targets if t.timeframe == tf_label]
            ex_tgt_cols = st.columns(3)
            for t in tf_targets:
                s_label, s_icon = scenario_map.get(t.scenario, (t.scenario, ""))
                col_idx = 0 if t.scenario == "bull" else 1 if t.scenario == "base" else 2
                with ex_tgt_cols[col_idx]:
                    st.metric(
                        f"{s_icon} {s_label}情境",
                        f"${t.target_price:.2f}",
                        delta=f"{t.upside_pct:+.2%}",
                    )
                    st.caption(f"信心度：{t.confidence}")

        fib = report.fibonacci
        st.markdown("**費氏回檔分析**")
        fib_info_cols = st.columns(3)
        with fib_info_cols[0]:
            st.metric("波段高點", f"${fib.swing_high:.2f}")
        with fib_info_cols[1]:
            st.metric("波段低點", f"${fib.swing_low:.2f}")
        with fib_info_cols[2]:
            st.metric("方向", "上升趨勢" if fib.direction == "uptrend" else "下降趨勢")

        fib_col1, fib_col2 = st.columns(2)
        with fib_col1:
            ret_data = [{"比率": f"{k:.1%}", "價位": f"${v:.2f}", "距離": f"{(v / report.current_price - 1):+.2%}"}
                        for k, v in fib.retracement.items()]
            st.dataframe(pd.DataFrame(ret_data), hide_index=True, width="stretch")
        with fib_col2:
            ext_data = [{"比率": f"{k:.1%}", "價位": f"${v:.2f}", "距離": f"{(v / report.current_price - 1):+.2%}"}
                        for k, v in fib.extension.items()]
            st.dataframe(pd.DataFrame(ext_data), hide_index=True, width="stretch")

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
            st.plotly_chart(fig_fib, width="stretch")


def _render_tab_risk(report, _esc):
    """風險評估分頁"""
    risk_cols = st.columns(5)
    with risk_cols[0]:
        st.metric("最大回撤", f"{report.max_drawdown_1y:.2%}")
    with risk_cols[1]:
        st.metric("目前回撤", f"{report.current_drawdown:.2%}")
    with risk_cols[2]:
        st.metric("風險報酬比", f"{report.risk_reward_ratio:.1f}:1")
    with risk_cols[3]:
        st.metric("ATR %", f"{report.atr_pct:.2%}")
    with risk_cols[4]:
        st.metric("20日波動率", f"{report.historical_volatility_20d:.1%}")
    st.markdown(_esc(report.risk_interpretation))

    if report.industry_risks:
        st.markdown("**產業特定風險**")
        for ir in report.industry_risks:
            sev = ir["severity"]
            sev_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(sev, "🟡")
            st.markdown(f"{sev_icon} **{ir['risk']}**：{_esc(ir['detail'])}")

    if report.peer_context and report.peer_context.get("positioning"):
        with st.expander(f"產業對照（{report.peer_context.get('industry_label', '')}）"):
            for pos in report.peer_context["positioning"]:
                st.markdown(f"- {_esc(pos)}")
            notes = report.peer_context.get("industry_notes", "")
            if notes:
                st.caption(notes)
            key_metrics = report.peer_context.get("key_metrics", [])
            if key_metrics:
                st.markdown(f"**此產業關鍵觀察指標：**{'、'.join(key_metrics)}")


def _render_tab_strategy(report, _esc):
    """展望策略分頁"""
    outlook_3m = report.outlook_3m
    st.markdown(f"**{outlook_3m.timeframe}展望**")
    o_cols = st.columns(3)
    with o_cols[0]:
        st.markdown(f"🟢 **樂觀**（機率 {outlook_3m.bull_probability}%）")
        st.markdown(f"目標：\\${outlook_3m.bull_target:.2f}")
        st.markdown(_esc(outlook_3m.bull_case))
    with o_cols[1]:
        st.markdown(f"🟡 **基本**（機率 {outlook_3m.base_probability}%）")
        st.markdown(f"目標：\\${outlook_3m.base_target:.2f}")
        st.markdown(_esc(outlook_3m.base_case))
    with o_cols[2]:
        st.markdown(f"🔴 **保守**（機率 {outlook_3m.bear_probability}%）")
        st.markdown(f"目標：\\${outlook_3m.bear_target:.2f}")
        st.markdown(_esc(outlook_3m.bear_case))

    with st.expander("6 個月 / 1 年展望"):
        for outlook in [report.outlook_6m, report.outlook_1y]:
            st.markdown(f"**{outlook.timeframe}展望**")
            ex_o_cols = st.columns(3)
            with ex_o_cols[0]:
                st.markdown(f"🟢 **樂觀**（機率 {outlook.bull_probability}%）")
                st.markdown(f"目標：\\${outlook.bull_target:.2f}")
                st.markdown(_esc(outlook.bull_case))
            with ex_o_cols[1]:
                st.markdown(f"🟡 **基本**（機率 {outlook.base_probability}%）")
                st.markdown(f"目標：\\${outlook.base_target:.2f}")
                st.markdown(_esc(outlook.base_case))
            with ex_o_cols[2]:
                st.markdown(f"🔴 **保守**（機率 {outlook.bear_probability}%）")
                st.markdown(f"目標：\\${outlook.bear_target:.2f}")
                st.markdown(_esc(outlook.bear_case))
            st.divider()

    st.markdown("**策略訊號**")
    sig_cols = st.columns(2)
    v4 = report.v4_analysis
    v2 = report.v2_analysis
    with sig_cols[0]:
        st.markdown("**v4 趨勢動量策略**")
        v4_sig = v4.get("signal", "HOLD")
        v4_map = {"BUY": "🟢 買入", "SELL": "🔴 賣出", "HOLD": "🟡 觀望"}
        v4_icon = v4_map.get(v4_sig, "🟡 觀望")
        st.metric("訊號", v4_icon)
        if v4.get("entry_type"):
            _et_map = {"support": "支撐", "momentum": "動量"}
            st.metric("進場類型", _et_map.get(v4["entry_type"], v4["entry_type"]))
        st.metric("趨勢天數", f"{v4.get('uptrend_days', 0)} 天")
    with sig_cols[1]:
        st.markdown("**v2 綜合評分策略**")
        v2_sig = v2.get("signal", "HOLD")
        v2_map = {"BUY": "🟢 買入", "SELL": "🔴 賣出", "HOLD": "🟡 持有"}
        st.metric("訊號", v2_map.get(v2_sig, v2_sig))
        st.metric("綜合評分", f"{v2.get('composite_score', 0):+.3f}")

    # (行動建議已移至頁面頂部)


def _render_download(report, rec):
    st.divider()
    st.subheader("下載報告")

    _rating_html_colors = {
        "強力買進": "#1B5E20", "買進": "#2E7D32", "中性": "#F57F17",
        "賣出": "#C62828", "強力賣出": "#B71C1C",
    }
    _r_color = _rating_html_colors.get(report.overall_rating, "#424242")

    _fund = report.fundamentals
    _fund_rows = ""
    for _fk, _fl in [("trailing_pe", "本益比"), ("price_to_book", "淨值比"),
                     ("return_on_equity", "ROE"), ("dividend_yield", "殖利率"),
                     ("revenue_growth", "營收成長"), ("profit_margins", "淨利率")]:
        _fv = _fund.get(_fk)
        if _fv is not None and isinstance(_fv, (int, float)) and not np.isnan(_fv):
            if _fk in ("return_on_equity", "dividend_yield", "revenue_growth", "profit_margins"):
                _fund_rows += f"<tr><td>{_fl}</td><td>{_fv*100:.1f}%</td></tr>"
            else:
                _fund_rows += f"<tr><td>{_fl}</td><td>{_fv:.2f}</td></tr>"

    _news_rows = ""
    for _ni in report.news_items[:5]:
        _nt = _ni.get("title", "")
        _ns = _ni.get("source", "")
        _news_rows += f"<li>{_nt}（{_ns}）</li>"

    report_html = f"""<!DOCTYPE html>
<html lang="zh-TW"><head><meta charset="UTF-8">
<title>{report.stock_name}({report.stock_code}) 分析報告</title>
<style>
body{{font-family:-apple-system,sans-serif;max-width:800px;margin:0 auto;padding:20px;background:#1a1a2e;color:#e0e0e0}}
h1,h2,h3{{color:#e0e0e0}} table{{border-collapse:collapse;width:100%;margin:10px 0}}
td,th{{border:1px solid #444;padding:8px;text-align:left}} th{{background:#2a2a4a}}
.banner{{background:{_r_color};color:white;padding:20px;border-radius:12px;text-align:center;margin:20px 0}}
.section{{background:#16213e;padding:15px;border-radius:8px;margin:15px 0}}
.metric{{display:inline-block;background:#1a1a2e;padding:10px 15px;border-radius:8px;margin:5px;text-align:center}}
.metric .label{{font-size:0.85em;color:#888}} .metric .value{{font-size:1.3em;font-weight:bold}}
</style></head><body>
<div class="banner"><h1>{report.stock_name}（{report.stock_code}）</h1>
<h2>綜合評等：{report.overall_rating}</h2>
<p>收盤價 ${report.current_price:.2f} | 趨勢 {report.trend_direction} | 動能 {report.momentum_status}</p>
<p style="font-size:0.85em">報告日期：{report.report_date.strftime('%Y-%m-%d %H:%M')}</p></div>

<div class="section"><h2>分析摘要</h2><p>{report.summary_text}</p></div>

<div class="section"><h2>價格績效</h2>
<div class="metric"><div class="label">1 週</div><div class="value">{report.price_change_1w:+.2f}%</div></div>
<div class="metric"><div class="label">1 月</div><div class="value">{report.price_change_1m:+.2f}%</div></div>
<div class="metric"><div class="label">3 月</div><div class="value">{report.price_change_3m:+.2f}%</div></div>
<div class="metric"><div class="label">6 月</div><div class="value">{report.price_change_6m:+.2f}%</div></div>
<div class="metric"><div class="label">1 年</div><div class="value">{report.price_change_1y:+.2f}%</div></div>
<div class="metric"><div class="label">52 週高</div><div class="value">${report.high_52w:.2f}</div></div>
<div class="metric"><div class="label">52 週低</div><div class="value">${report.low_52w:.2f}</div></div>
</div>

<div class="section"><h2>技術指標</h2><table>
<tr><th>指標</th><th>數值</th><th>解讀</th></tr>
<tr><td>RSI(14)</td><td>{report.rsi_value:.1f}</td><td>{report.rsi_interpretation}</td></tr>
<tr><td>ADX(14)</td><td>{report.adx_value:.1f}</td><td>{report.adx_interpretation}</td></tr>
<tr><td>MACD</td><td>{report.macd_value:.2f}</td><td>{report.macd_interpretation}</td></tr>
<tr><td>KD</td><td>K={report.k_value:.1f} D={report.d_value:.1f}</td><td>{report.kd_interpretation}</td></tr>
</table></div>

<div class="section"><h2>基本面</h2>
<p>{report.fundamental_interpretation}</p>
<table><tr><th>指標</th><th>數值</th></tr>{_fund_rows}</table></div>

<div class="section"><h2>消息面</h2>
<p>情緒：{report.news_sentiment_label}（分數 {report.news_sentiment_score:+.1f}）</p>
<ul>{_news_rows if _news_rows else '<li>暫無新聞</li>'}</ul></div>

<div class="section"><h2>3 個月展望</h2><table>
<tr><th>情境</th><th>機率</th><th>目標價</th><th>說明</th></tr>
<tr><td>樂觀</td><td>{report.outlook_3m.bull_probability}%</td><td>${report.outlook_3m.bull_target:.2f}</td><td>{report.outlook_3m.bull_case}</td></tr>
<tr><td>基本</td><td>{report.outlook_3m.base_probability}%</td><td>${report.outlook_3m.base_target:.2f}</td><td>{report.outlook_3m.base_case}</td></tr>
<tr><td>保守</td><td>{report.outlook_3m.bear_probability}%</td><td>${report.outlook_3m.bear_target:.2f}</td><td>{report.outlook_3m.bear_case}</td></tr>
</table></div>

<div class="section"><h2>風險評估</h2>
<p>{report.risk_interpretation}</p>
<div class="metric"><div class="label">最大回撤(1Y)</div><div class="value">{report.max_drawdown_1y:.1f}%</div></div>
<div class="metric"><div class="label">波動率(20D)</div><div class="value">{report.historical_volatility_20d:.1f}%</div></div>
<div class="metric"><div class="label">ATR</div><div class="value">{report.atr_value:.2f}({report.atr_pct:.1f}%)</div></div>
</div>"""

    # HTML: 技術面矛盾
    _tech_conflict_html = ""
    if report.technical_conflicts:
        rows = "".join(f"<li>{c}</li>" for c in report.technical_conflicts)
        _tech_conflict_html = f"""
<div class="section"><h2>技術面矛盾</h2>
<p>綜合偏向：<strong>{report.technical_bias}</strong></p>
<ul>{rows}</ul></div>"""

    # HTML: 產業風險
    _risk_html = ""
    if report.industry_risks:
        sev_map = {"high": "🔴", "medium": "🟡", "low": "🟢"}
        rows = "".join(
            f"<tr><td>{sev_map.get(r['severity'], '🟡')}</td><td>{r['risk']}</td><td>{r['detail']}</td></tr>"
            for r in report.industry_risks
        )
        _risk_html = f"""
<div class="section"><h2>產業特定風險</h2><table>
<tr><th>嚴重度</th><th>風險</th><th>說明</th></tr>{rows}</table></div>"""

    # HTML: 行動建議
    _rec_html = ""
    if rec:
        action_color = {"BUY": "#1B5E20", "SELL": "#C62828", "HOLD": "#F57F17", "AVOID": "#B71C1C"}
        _ac = rec.get("action", "HOLD")
        _ac_label = {"BUY": "買入", "SELL": "賣出", "HOLD": "觀望", "AVOID": "避開"}.get(_ac, "觀望")
        _rec_html = f"""
<div class="section" style="border:2px solid {action_color.get(_ac, '#424242')}">
<h2>行動建議：{_ac_label}</h2>
<p><strong>{rec.get('thesis', '')}</strong></p>"""
        if _ac in ("BUY", "SELL"):
            _rec_html += '<div style="display:flex;flex-wrap:wrap;gap:10px">'
            if rec.get("entry_low") and rec.get("entry_high"):
                _rec_html += f'<div class="metric"><div class="label">進場區間</div><div class="value">${rec["entry_low"]:.2f}～${rec["entry_high"]:.2f}</div></div>'
            if rec.get("stop_loss"):
                _rec_html += f'<div class="metric"><div class="label">停損</div><div class="value">${rec["stop_loss"]:.2f}</div></div>'
            if rec.get("take_profit_t1"):
                _rec_html += f'<div class="metric"><div class="label">目標 T1</div><div class="value">${rec["take_profit_t1"]:.2f}</div></div>'
            if rec.get("take_profit_t2"):
                _rec_html += f'<div class="metric"><div class="label">目標 T2</div><div class="value">${rec["take_profit_t2"]:.2f}</div></div>'
            _rec_html += f'<div class="metric"><div class="label">建議部位</div><div class="value">{rec.get("position_pct", "N/A")}</div></div>'
            _rec_html += '</div>'
        triggers = rec.get("trigger_conditions", [])
        if triggers:
            _rec_html += "<h3>觸發條件</h3><ul>" + "".join(f"<li>{t}</li>" for t in triggers) + "</ul>"
        _rec_html += "</div>"

    report_html += f"""
{_tech_conflict_html}
{_risk_html}
{_rec_html}

<p style="text-align:center;color:#666;margin-top:30px">本報告由台股技術分析系統自動產生，僅供參考，不構成投資建議。</p>
</body></html>"""

    dl_cols = st.columns(2)
    with dl_cols[0]:
        st.download_button(
            label="下載 HTML 報告",
            data=report_html.encode("utf-8"),
            file_name=f"report_{report.stock_code}_{report.report_date.strftime('%Y%m%d')}.html",
            mime="text/html",
        )
    with dl_cols[1]:
        report_text = f"=== {report.stock_name}（{report.stock_code}）技術分析報告 ===\n"
        report_text += f"報告日期：{report.report_date.strftime('%Y-%m-%d %H:%M')}\n"
        report_text += f"綜合評等：{report.overall_rating}\n"
        report_text += f"收盤價：${report.current_price:.2f}\n\n"
        report_text += report.summary_text
        st.download_button(
            label="下載文字檔",
            data=report_text.encode("utf-8"),
            file_name=f"report_{report.stock_code}_{report.report_date.strftime('%Y%m%d')}.txt",
            mime="text/plain",
        )
