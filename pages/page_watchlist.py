"""自選股總覽頁面"""

import time as _time
import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed

from analysis.strategy_v4 import get_v4_analysis
from backtest.engine import run_backtest_v4
from data.fetcher import get_stock_data
from data.stock_list import get_stock_name


def _load_one_stock(code, all_stocks):
    """載入單檔股票資料並分析（thread-safe，直接用 get_stock_data 繞過 st.cache_data）"""
    _df = get_stock_data(code, period_days=180)
    if _df is None or _df.empty or len(_df) < 5:
        return None
    _name = get_stock_name(code, all_stocks)
    _ana = get_v4_analysis(_df)

    _close = _ana["close"]
    _prev = _df["close"].iloc[-2]
    _chg_pct = (_close - _prev) / _prev * 100
    _chg_amt = _close - _prev

    _ind = _ana["indicators"]
    _rsi = _ind.get("RSI")
    _adx = _ind.get("ADX")

    _vol = _df["volume"].iloc[-1]
    _vol_ma5 = _df["volume"].tail(5).mean()
    _vol_ratio = _vol / _vol_ma5 if _vol_ma5 > 0 else 0

    _entry_map = {"support": "支撐", "momentum": "動量"}
    row_data = {
        "代碼": code,
        "名稱": _name,
        "收盤價": f"${_close:,.2f}",
        "漲跌%": f"{_chg_pct:+.2f}%",
        "漲跌": f"{_chg_amt:+.2f}",
        "RSI": f"{_rsi:.1f}" if _rsi and not pd.isna(_rsi) else "—",
        "ADX": f"{_adx:.1f}" if _adx and not pd.isna(_adx) else "—",
        "訊號": _ana["signal"],
        "進場": _entry_map.get(_ana["entry_type"], "—"),
        "趨勢天數": _ana["uptrend_days"],
        "量比": f"{_vol_ratio:.2f}",
        "MA20距離": f"{_ana['dist_ma20'] * 100:+.1f}%" if not pd.isna(_ana["dist_ma20"]) else "—",
        "_chg_raw": _chg_pct,
        "_rsi_raw": _rsi if _rsi and not pd.isna(_rsi) else 50,
        "_adx_raw": _adx if _adx and not pd.isna(_adx) else 0,
        "_vol_raw": _vol_ratio,
    }
    return code, _df, row_data


def render(all_stocks, initial_capital, load_data_fn):
    st.header("自選股總覽")

    wl = st.session_state.get("watchlist", [])
    if not wl:
        st.info("尚未加入自選股。在任何頁面的側邊欄點擊「☆」即可加入股票。")
        st.caption("提示：前往「技術分析」或「條件選股」頁面，找到感興趣的股票後加入自選股。")
        return

    st.caption(f"共 {len(wl)} 檔自選股")

    # --- 快取 key：自選股清單內容 ---
    _wl_key = ",".join(wl)
    _cache_valid = (
        st.session_state.get("_wl_cache_key") == _wl_key
        and st.session_state.get("_wl_dashboard_rows") is not None
        and st.session_state.get("_wl_data") is not None
    )

    # 重新整理按鈕
    _btn_cols = st.columns([1, 1, 5])
    with _btn_cols[0]:
        _force_refresh = st.button("重新整理", key="wl_refresh", type="primary" if _cache_valid else "secondary")
    with _btn_cols[1]:
        if _cache_valid:
            st.caption("使用快取資料")

    if _cache_valid and not _force_refresh:
        dashboard_rows = st.session_state["_wl_dashboard_rows"]
        _wl_data = st.session_state["_wl_data"]
    else:
        # --- 載入所有自選股資料（平行） ---
        dashboard_rows = []
        _wl_data = {}
        _prog = st.progress(0, text="載入自選股資料...")
        _start = _time.time()

        _done = 0
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(_load_one_stock, code, all_stocks): code for code in wl}
            for future in as_completed(futures):
                _done += 1
                _prog.progress(_done / len(wl), text=f"載入自選股 ({_done}/{len(wl)})...")
                try:
                    result = future.result()
                    if result is not None:
                        code, _df, row_data = result
                        _wl_data[code] = _df
                        dashboard_rows.append(row_data)
                except Exception:
                    continue

        # 按原始自選股順序排列
        _order = {code: i for i, code in enumerate(wl)}
        dashboard_rows.sort(key=lambda r: _order.get(r["代碼"], 999))

        _elapsed = _time.time() - _start
        _prog.empty()
        st.caption(f"載入完成，耗時 {_elapsed:.1f} 秒")

        # 存入 session_state 快取
        st.session_state["_wl_cache_key"] = _wl_key
        st.session_state["_wl_dashboard_rows"] = dashboard_rows
        st.session_state["_wl_data"] = _wl_data

    if not dashboard_rows:
        st.warning("無法載入自選股資料，請稍後重試。")
        return

    # --- 風險管理 ---
    if len(dashboard_rows) >= 2 and _wl_data:
        with st.expander("風險管理", expanded=False):
            from analysis.risk import (
                calculate_correlation_matrix,
                calculate_portfolio_var,
                check_risk_alerts,
                analyze_industry_concentration,
                calculate_portfolio_beta,
            )
            import plotly.express as px

            _risk_tab1, _risk_tab2, _risk_tab3 = st.tabs(
                ["相關性 & VaR", "產業集中度", "Beta 曝險"])

            with _risk_tab1:
                # 相關性矩陣
                corr_matrix = calculate_correlation_matrix(_wl_data, days=60)
                var_info = calculate_portfolio_var(_wl_data, confidence=0.95)

                if not corr_matrix.empty:
                    st.subheader("相關性矩陣（60 日對數報酬率）")
                    fig_corr = px.imshow(
                        corr_matrix,
                        text_auto=".2f",
                        color_continuous_scale="RdBu_r",
                        zmin=-1, zmax=1,
                        aspect="auto",
                    )
                    fig_corr.update_layout(
                        height=max(300, len(corr_matrix) * 50),
                        template="plotly_dark",
                    )
                    st.plotly_chart(fig_corr, use_container_width=True)

                if var_info.get("stocks_used", 0) > 0:
                    st.subheader("Historical VaR（95% 信心水準）")
                    var_cols = st.columns(3)
                    with var_cols[0]:
                        st.metric("日 VaR%", f"{var_info['var_pct']:.2%}")
                    with var_cols[1]:
                        st.metric("日 VaR 金額", f"${abs(var_info['var_amount']):,.0f}")
                    with var_cols[2]:
                        st.metric("使用股票數", var_info["stocks_used"])
                    st.caption("假設等權重 100 萬組合，95% 信心水準下單日最大虧損。")

                # 風險警報
                alerts = check_risk_alerts(corr_matrix, var_info)
                if alerts:
                    for alert in alerts:
                        st.warning(alert)
                elif not corr_matrix.empty:
                    st.success("目前無風險警報")

            with _risk_tab2:
                st.subheader("產業集中度分析")
                # 取得各股產業分類
                _sector_cache_key = "_wl_sector_data"
                _sector_data = st.session_state.get(_sector_cache_key)

                if _sector_data is None:
                    if st.button("載入產業分類", key="wl_load_sectors",
                                 help="從 yfinance 取得各股票的產業分類"):
                        with st.spinner("載入產業分類..."):
                            from data.fetcher import get_stock_info
                            _sector_data = {}
                            for code in wl:
                                try:
                                    _info = get_stock_info(code)
                                    _sector_data[code] = _info.get("sector", "N/A")
                                except Exception:
                                    _sector_data[code] = "N/A"
                            st.session_state[_sector_cache_key] = _sector_data
                            st.rerun()
                    st.caption("點擊載入按鈕以取得產業分類資訊。")
                else:
                    conc_result = analyze_industry_concentration(_sector_data)

                    if conc_result["total_stocks"] > 0:
                        # 圓餅圖
                        _sectors = conc_result["sectors"]
                        _pcts = conc_result["sector_pcts"]
                        _labels = list(_pcts.keys())
                        _values = [len(_sectors[s]) for s in _labels]

                        fig_pie = go.Figure(data=go.Pie(
                            labels=_labels, values=_values,
                            hole=0.4,
                            textinfo="label+percent+value",
                        ))
                        fig_pie.update_layout(
                            height=350, template="plotly_dark",
                            margin=dict(t=20, b=20),
                        )
                        st.plotly_chart(fig_pie, use_container_width=True)

                        # 明細表
                        _sec_rows = []
                        for sector, codes in _sectors.items():
                            _names = [get_stock_name(c, all_stocks) for c in codes]
                            _sec_rows.append({
                                "產業": sector,
                                "股數": len(codes),
                                "佔比": f"{_pcts[sector]:.0%}",
                                "股票": ", ".join([f"{c} {n}" for c, n in zip(codes, _names)]),
                            })
                        st.dataframe(pd.DataFrame(_sec_rows), width="stretch", hide_index=True)

                        # 警報
                        if conc_result["alerts"]:
                            for alert in conc_result["alerts"]:
                                st.warning(alert)
                        else:
                            st.success("產業分散良好，無集中度警報")

            with _risk_tab3:
                st.subheader("Beta 曝險分析")
                try:
                    from data.fetcher import get_taiex_data
                    _taiex = get_taiex_data(period_days=180)
                    betas = calculate_portfolio_beta(_wl_data, _taiex, days=120)

                    if betas:
                        _beta_rows = []
                        for code, beta in sorted(betas.items(), key=lambda x: x[1], reverse=True):
                            _name = get_stock_name(code, all_stocks)
                            _beta_rows.append({
                                "代碼": code,
                                "名稱": _name,
                                "Beta": beta,
                            })

                        _avg_beta = np.mean(list(betas.values()))
                        st.metric("組合平均 Beta", f"{_avg_beta:.2f}",
                                   delta="高風險" if _avg_beta > 1.2 else (
                                       "低風險" if _avg_beta < 0.8 else "中等"),
                                   delta_color="inverse" if _avg_beta > 1.2 else "normal")

                        _beta_df = pd.DataFrame(_beta_rows)

                        def _color_beta(val):
                            if isinstance(val, (int, float)):
                                if val > 1.3:
                                    return "color: #FF1744; font-weight: bold"
                                elif val > 1.0:
                                    return "color: #FF9800"
                                elif val < 0.7:
                                    return "color: #2196F3"
                            return ""

                        st.dataframe(
                            _beta_df.style.map(_color_beta, subset=["Beta"]),
                            width="stretch", hide_index=True)

                        # 市場環境警告
                        _regime = st.session_state.get("_market_regime")
                        if _regime and _regime.get("regime") == "bear" and _avg_beta > 1.0:
                            st.error(
                                f"空頭市場 + 高 Beta（{_avg_beta:.2f}）= 高風險組合。"
                                f"建議降低高 Beta 股票持倉或增加防禦性配置。"
                            )
                        st.caption("Beta > 1：波動大於大盤 | Beta < 1：波動小於大盤 | "
                                   "Beta ≈ 0：與大盤無關（如生技股）")
                    else:
                        st.info("大盤資料不足，無法計算 Beta。")
                except Exception:
                    st.info("無法取得大盤資料以計算 Beta。")

    # --- 法人資料（從 cache 讀取，不額外 API call）---
    _inst_loaded = st.session_state.get("_wl_inst_loaded", False)
    if _inst_loaded:
        from data.cache import get_cached_institutional_data
        for row_data in dashboard_rows:
            code = row_data["代碼"]
            _inst = get_cached_institutional_data(code)
            if _inst is not None and not _inst.empty:
                _net5 = _inst.tail(5)["total_net"].sum()
                if _net5 > 0:
                    row_data["法人動向"] = f"買 {abs(_net5)/1000:,.0f}K"
                elif _net5 < 0:
                    row_data["法人動向"] = f"賣 {abs(_net5)/1000:,.0f}K"
                else:
                    row_data["法人動向"] = "—"
            else:
                row_data["法人動向"] = "—"

    # --- 摘要指標 ---
    _buy_n = sum(1 for r in dashboard_rows if r["訊號"] == "BUY")
    _sell_n = sum(1 for r in dashboard_rows if r["訊號"] == "SELL")
    _hold_n = sum(1 for r in dashboard_rows if r["訊號"] == "HOLD")
    _up_n = sum(1 for r in dashboard_rows if (r.get("_chg_raw") or 0) > 0)
    _dn_n = sum(1 for r in dashboard_rows if (r.get("_chg_raw") or 0) < 0)
    _flat_n = len(dashboard_rows) - _up_n - _dn_n
    _avg_chg = np.mean([r.get("_chg_raw", 0) or 0 for r in dashboard_rows])

    sum_cols = st.columns(5)
    with sum_cols[0]:
        st.metric("自選股", len(dashboard_rows))
    with sum_cols[1]:
        st.metric("漲", _up_n, delta=f"{_up_n}/{len(dashboard_rows)}")
    with sum_cols[2]:
        st.metric("跌", _dn_n)
    with sum_cols[3]:
        st.metric("均漲跌", f"{_avg_chg:+.1f}%")
    with sum_cols[4]:
        st.metric("買入訊號", _buy_n)

    # --- 總覽表格 ---
    # 保存 raw 值用於顏色判斷
    _raw_chg = [r.get("_chg_raw", 0) or 0 for r in dashboard_rows]
    _raw_rsi = [r.get("_rsi_raw", 50) or 50 for r in dashboard_rows]
    _raw_adx = [r.get("_adx_raw", 0) or 0 for r in dashboard_rows]
    _raw_vol = [r.get("_vol_raw", 0) or 0 for r in dashboard_rows]

    # 只保留顯示欄位
    _display_cols = ["代碼", "名稱", "收盤價", "漲跌%", "漲跌", "RSI", "ADX",
                     "訊號", "進場", "趨勢天數", "量比", "MA20距離"]
    if _inst_loaded:
        _display_cols.append("法人動向")
    df_dash = pd.DataFrame([{k: r[k] for k in _display_cols if k in r} for r in dashboard_rows])

    _sig_map = {"BUY": "🟢 買入", "SELL": "🔴 賣出", "HOLD": "🟡 觀望"}
    df_dash["訊號"] = df_dash["訊號"].map(lambda x: _sig_map.get(x, x))

    def _style_row(row):
        styles = [""] * len(row)
        cols = list(row.index)
        i = row.name  # row index

        chg = _raw_chg[i] if i < len(_raw_chg) else 0
        for c in ["漲跌%", "漲跌"]:
            if c in cols:
                idx = cols.index(c)
                if chg > 0:
                    styles[idx] = "color: #FF1744"
                elif chg < 0:
                    styles[idx] = "color: #00C853"

        rsi = _raw_rsi[i] if i < len(_raw_rsi) else 50
        if "RSI" in cols:
            idx = cols.index("RSI")
            if rsi >= 70:
                styles[idx] = "color: #FF1744; font-weight: bold"
            elif rsi <= 30:
                styles[idx] = "color: #00C853; font-weight: bold"

        adx = _raw_adx[i] if i < len(_raw_adx) else 0
        if "ADX" in cols:
            idx = cols.index("ADX")
            if adx >= 25:
                styles[idx] = "color: #2196F3; font-weight: bold"

        vol = _raw_vol[i] if i < len(_raw_vol) else 0
        if "量比" in cols:
            idx = cols.index("量比")
            if vol >= 2.0:
                styles[idx] = "color: #FF9800; font-weight: bold"
            elif vol >= 1.5:
                styles[idx] = "color: #FF9800"

        return styles

    st.dataframe(df_dash.style.apply(_style_row, axis=1), width="stretch", hide_index=True)

    # --- 績效比較圖 ---
    st.divider()
    st.subheader("績效比較圖")
    _comp_days = st.slider("比較天數", 30, 365, 90, key="wl_comp_days")

    fig_comp = go.Figure()
    for code in wl:
        try:
            _comp_df = _wl_data.get(code)
            if _comp_df is None or _comp_df.empty:
                continue
            _comp_close = _comp_df["close"].tail(_comp_days)
            if len(_comp_close) < 2:
                continue
            _base = _comp_close.iloc[0]
            _normalized = (_comp_close / _base - 1) * 100
            _cname = get_stock_name(code, all_stocks)
            fig_comp.add_trace(go.Scatter(
                x=_comp_close.index,
                y=_normalized,
                mode="lines",
                name=f"{code} {_cname}",
            ))
        except Exception:
            continue

    fig_comp.add_hline(y=0, line_dash="dash", line_color="white", opacity=0.3)
    fig_comp.update_layout(
        yaxis_title="報酬率 (%)",
        xaxis_title="日期",
        hovermode="x unified",
        template="plotly_dark",
        height=500,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(fig_comp, width="stretch")

    # --- 法人資料批次載入 ---
    st.divider()
    st.subheader("法人籌碼")
    if not _inst_loaded:
        if st.button("載入全部法人資料", key="wl_inst_load_all",
                     help="批次取得所有自選股的三大法人買賣超資料"):
            with st.spinner("批次載入法人資料..."):
                from data.fetcher import get_institutional_data
                for code in wl:
                    try:
                        get_institutional_data(code, days=20)
                    except Exception:
                        continue
                st.session_state["_wl_inst_loaded"] = True
                st.rerun()
        st.caption("載入後表格會新增「法人動向」欄位，顯示近 5 日三大法人淨買超。")
    else:
        st.caption("法人資料已載入，表格已顯示「法人動向」欄位。")

    # --- 快速分析 ---
    st.divider()
    st.subheader("快速分析")
    _wl_opts = [f"{r['代碼']} {r['名稱']}" for r in dashboard_rows]
    _wl_sel = st.selectbox("選擇股票", _wl_opts, key="wl_dash_jump")
    _wl_code = _wl_sel.split()[0] if _wl_sel else ""

    _wl_jcols = st.columns(3)
    with _wl_jcols[0]:
        if st.button("技術分析", key="wl_to_tech", width="stretch"):
            st.session_state["_pending_stock"] = _wl_code
            st.session_state["_pending_nav"] = "技術分析"
            st.rerun()
    with _wl_jcols[1]:
        if st.button("回測報告", key="wl_to_bt", width="stretch"):
            st.session_state["_pending_stock"] = _wl_code
            st.session_state["_pending_nav"] = "回測報告"
            st.rerun()
    with _wl_jcols[2]:
        if st.button("分析報告", key="wl_to_rpt", width="stretch"):
            st.session_state["_pending_stock"] = _wl_code
            st.session_state["_auto_report"] = True
            st.session_state["_pending_nav"] = "分析報告"
            st.rerun()

    # --- 批次回測 ---
    st.divider()
    st.subheader("批次回測")
    st.caption("對所有自選股執行 v4 策略回測，比較歷史績效。")
    _bt_days = st.slider("回測天數", 180, 1095, 730, key="wl_bt_days")

    if st.button("開始批次回測", key="wl_batch_bt", type="primary"):
        bt_rows = []
        _bt_est = len(wl) * 3
        _bt_prog = st.progress(0, text=f"批次回測中...（預估 {_bt_est} 秒）")

        def _bt_one(code):
            _bt_df = get_stock_data(code, period_days=_bt_days + 120)
            if _bt_df is None or _bt_df.empty:
                return None
            _bt_result = run_backtest_v4(_bt_df.tail(_bt_days + 60), initial_capital=initial_capital)
            return {
                "代碼": code,
                "名稱": get_stock_name(code, all_stocks),
                "總報酬率%": round(_bt_result.total_return * 100, 2),
                "年化報酬%": round(_bt_result.annual_return * 100, 2),
                "最大回撤%": round(_bt_result.max_drawdown * 100, 2),
                "Sharpe": round(_bt_result.sharpe_ratio, 2),
                "Sortino": round(_bt_result.sortino_ratio, 2),
                "Calmar": round(_bt_result.calmar_ratio, 2),
                "勝率%": round(_bt_result.win_rate * 100, 1),
                "交易次數": _bt_result.total_trades,
                "盈虧比": round(_bt_result.profit_factor, 2),
                "平均獲利%": round(_bt_result.avg_win * 100, 2),
                "平均虧損%": round(_bt_result.avg_loss * 100, 2),
            }

        _bt_done = 0
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {executor.submit(_bt_one, code): code for code in wl}
            for future in as_completed(futures):
                _bt_done += 1
                _bt_prog.progress(_bt_done / len(wl), text=f"回測 ({_bt_done}/{len(wl)})...")
                try:
                    result = future.result()
                    if result is not None:
                        bt_rows.append(result)
                except Exception:
                    continue

        _bt_prog.empty()
        st.session_state["_wl_bt_results"] = bt_rows
        st.session_state["_wl_bt_days_used"] = _bt_days

    # 顯示批次回測結果
    _wl_bt = st.session_state.get("_wl_bt_results")
    if _wl_bt:
        _bt_days_used = st.session_state.get("_wl_bt_days_used", 730)
        st.caption(f"回測期間：{_bt_days_used} 天")
        df_bt = pd.DataFrame(_wl_bt).sort_values("總報酬率%", ascending=False)

        def _color_return(val):
            if val is None or (isinstance(val, float) and np.isnan(val)):
                return ""
            if val > 0:
                return "color: #00C853"
            elif val < 0:
                return "color: #FF1744"
            return ""

        def _color_dd(val):
            if val is None or (isinstance(val, float) and np.isnan(val)):
                return ""
            if val > -10:
                return "color: #00C853"
            elif val < -20:
                return "color: #FF1744"
            return ""

        def _color_wr(val):
            if val is None or (isinstance(val, float) and np.isnan(val)):
                return ""
            if val >= 55:
                return "color: #00C853; font-weight: bold"
            elif val >= 50:
                return "color: #00C853"
            elif val < 40:
                return "color: #FF1744"
            return ""

        bt_styled = df_bt.style
        for col in ["總報酬率%", "年化報酬%"]:
            if col in df_bt.columns:
                bt_styled = bt_styled.map(_color_return, subset=[col])
        if "最大回撤%" in df_bt.columns:
            bt_styled = bt_styled.map(_color_dd, subset=["最大回撤%"])
        if "勝率%" in df_bt.columns:
            bt_styled = bt_styled.map(_color_wr, subset=["勝率%"])

        st.dataframe(bt_styled, width="stretch", hide_index=True)

        _avg_ret = np.mean([r["總報酬率%"] for r in _wl_bt])
        _pos_n = sum(1 for r in _wl_bt if r["總報酬率%"] > 0)
        st.caption(f"平均報酬率：{_avg_ret:+.2f}% | 獲利：{_pos_n}/{len(_wl_bt)} 檔")
