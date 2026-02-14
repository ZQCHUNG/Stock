"""推薦股票頁面"""

import time as _time
import streamlit as st
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

from data.fetcher import get_stock_data
from data.cache import get_cached_scan_results, set_cached_scan_results
from analysis.strategy import get_latest_analysis
from analysis.strategy_v4 import get_v4_analysis
from pages.common import explain_signal


def render(use_v4, all_stocks, scan_stocks, strategy_params,
           buy_threshold, sell_threshold, save_watchlist_fn):
    if use_v4:
        st.header("推薦股票 — v4 趨勢動量掃描")
        st.caption("掃描股票池，篩選 v4 策略發出「買入」訊號的股票。只推薦真正值得進場的標的。")
    else:
        st.header("推薦股票 — v2 技術面綜合評分")
        st.caption("掃描股票池，篩選綜合評分達到買入閾值的股票。")

    # 掃描範圍選擇
    scan_scope = st.radio(
        "掃描範圍",
        ["全部股票（較慢，首次約 2-5 分鐘）", "精選 25 檔（約 10 秒）"],
        horizontal=True,
    )
    use_full_scan = scan_scope.startswith("全部")
    scan_pool = all_stocks if use_full_scan else scan_stocks

    def _resolve_name(name):
        return name.get("name", "") if isinstance(name, dict) else name

    def scan_stocks_v4(stock_dict: dict):
        cached = get_cached_scan_results()
        if cached and isinstance(cached, list) and len(cached) > 0 and "entry_type" in cached[0]:
            return cached

        results = []
        total = len(stock_dict)
        _est_sec = max(total * 2 // 5, 5)
        progress_bar = st.progress(0, text=f"掃描中...（預估 {_est_sec} 秒）")
        _scan_start = _time.time()

        def _scan_one(code, name):
            display_name = _resolve_name(name)
            df = get_stock_data(code, period_days=200)
            if df is None or len(df) < 60:
                return None
            analysis = get_v4_analysis(df)
            analysis["code"] = code
            analysis["name"] = display_name
            return analysis if analysis["signal"] == "BUY" else None

        _done = 0
        items = list(stock_dict.items())
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(_scan_one, code, name): code for code, name in items}
            for future in as_completed(futures):
                _done += 1
                progress_bar.progress(_done / total, text=f"掃描 ({_done}/{total})...")
                try:
                    result = future.result()
                    if result is not None:
                        results.append(result)
                except Exception:
                    continue

        _elapsed = _time.time() - _scan_start
        progress_bar.empty()
        st.caption(f"掃描完成，耗時 {_elapsed:.1f} 秒")

        if results:
            set_cached_scan_results(results, ttl=600)
        return results

    def scan_stocks_v2(stock_dict: dict):
        cached = get_cached_scan_results()
        if cached and isinstance(cached, list) and len(cached) > 0 and "composite_score" in cached[0]:
            return cached

        results = []
        total = len(stock_dict)
        _est_sec = max(total * 2 // 5, 5)
        progress_bar = st.progress(0, text=f"掃描中...（預估 {_est_sec} 秒）")
        _scan_start = _time.time()

        def _scan_one_v2(code, name):
            display_name = _resolve_name(name)
            df = get_stock_data(code, period_days=200)
            if df is None or len(df) < 60:
                return None
            analysis = get_latest_analysis(df)
            analysis["code"] = code
            analysis["name"] = display_name
            return analysis

        _done = 0
        items = list(stock_dict.items())
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(_scan_one_v2, code, name): code for code, name in items}
            for future in as_completed(futures):
                _done += 1
                progress_bar.progress(_done / total, text=f"掃描 ({_done}/{total})...")
                try:
                    result = future.result()
                    if result is not None:
                        results.append(result)
                except Exception:
                    continue

        _elapsed = _time.time() - _scan_start
        progress_bar.empty()
        st.caption(f"掃描完成，耗時 {_elapsed:.1f} 秒")

        if results:
            set_cached_scan_results(results, ttl=600)
        return results

    _rec_btn_cols = st.columns([1, 1, 4])
    with _rec_btn_cols[0]:
        _do_scan = st.button("開始掃描", type="primary")
    with _rec_btn_cols[1]:
        if st.session_state.get("_rec_results") is not None:
            if st.button("清除結果"):
                st.session_state.pop("_rec_results", None)
                st.session_state.pop("_rec_mode", None)
                st.rerun()

    if _do_scan:
        if use_v4:
            buy_results = scan_stocks_v4(scan_pool)
            st.session_state["_rec_results"] = buy_results
            st.session_state["_rec_mode"] = "v4"
            st.session_state["_rec_pool_size"] = len(scan_pool)
        else:
            all_scan = scan_stocks_v2(scan_pool)
            st.session_state["_rec_results"] = all_scan
            st.session_state["_rec_mode"] = "v2"
            st.session_state["_rec_pool_size"] = len(scan_pool)

    # 從 session_state 讀取結果
    _rec_results = st.session_state.get("_rec_results")
    _rec_mode = st.session_state.get("_rec_mode")
    _rec_pool_size = st.session_state.get("_rec_pool_size", 0)

    if _rec_results is not None and _rec_mode == "v4":
        _render_v4_results(_rec_results, _rec_pool_size, save_watchlist_fn)

    elif _rec_results is not None and _rec_mode == "v2":
        _render_v2_results(_rec_results, _rec_pool_size, strategy_params,
                           buy_threshold, sell_threshold)


def _render_v4_results(buy_results, pool_size, save_watchlist_fn):
    if not buy_results:
        st.warning(
            f"掃描完成（共 {pool_size} 檔），目前沒有任何股票符合 v4 買入條件。\n\n"
            "v4 進場條件較嚴格（ADX≥18 + MA20>MA60 連續10天 + 支撐反彈或動量突破），"
            "代表目前市場可能缺乏明確趨勢機會，建議耐心等待。"
        )
        return

    st.success(f"掃描完成（共 {pool_size} 檔），找到 **{len(buy_results)}** 檔符合 v4 買入條件！")

    buy_results.sort(key=lambda x: x.get("uptrend_days", 0), reverse=True)
    entry_type_map = {"support": "支撐反彈", "momentum": "動量突破"}

    for rank, stock in enumerate(buy_results[:10], 1):
        st.subheader(f"第 {rank} 名：{stock['code']} {stock['name']}")

        _entry_short = {"support": "支撐", "momentum": "動量"}
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("收盤價", f"${stock['close']:.2f}")
        with col2:
            st.metric("進場類型", _entry_short.get(stock.get("entry_type", ""), "—"))
        with col3:
            st.metric("趨勢天數", f"{stock.get('uptrend_days', 0)} 天")
        with col4:
            st.metric("MA20距離", f"{stock.get('dist_ma20', 0):.1%}")

        ind = stock.get("indicators", {})
        ind_cols = st.columns(5)
        for j, label in enumerate(["ADX", "RSI", "+DI", "-DI", "ROC"]):
            with ind_cols[j]:
                val = ind.get(label)
                st.metric(label, f"{val:.1f}" if val is not None and not pd.isna(val) else "—")
        st.divider()

    # 批次加入自選股
    _rec_codes = [s["code"] for s in buy_results]
    _rec_not_in_wl = [c for c in _rec_codes if c not in st.session_state.get("watchlist", [])]
    if _rec_not_in_wl:
        if st.button(f"全部加入自選股（{len(_rec_not_in_wl)} 檔）", key="rec_add_all_wl"):
            for c in _rec_not_in_wl:
                if c not in st.session_state.watchlist:
                    st.session_state.watchlist.append(c)
            save_watchlist_fn(st.session_state.watchlist)
            st.rerun()

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
    st.dataframe(pd.DataFrame(table_data), width="stretch", hide_index=True)

    # 快速跳轉
    st.divider()
    st.subheader("快速分析")
    _rec_opts = [f"{s['code']} {s['name']}" for s in buy_results]
    _rec_sel = st.selectbox("選擇股票", _rec_opts, key="rec_jump_stock")
    _rec_code = _rec_sel.split()[0] if _rec_sel else ""
    _rec_jcols = st.columns(3)
    with _rec_jcols[0]:
        if st.button("技術分析", key="rec_to_tech", width="stretch"):
            st.session_state["_pending_stock"] = _rec_code
            st.session_state["_pending_nav"] = "技術分析"
            st.rerun()
    with _rec_jcols[1]:
        if st.button("回測報告", key="rec_to_bt", width="stretch"):
            st.session_state["_pending_stock"] = _rec_code
            st.session_state["_pending_nav"] = "回測報告"
            st.rerun()
    with _rec_jcols[2]:
        if st.button("分析報告", key="rec_to_rpt", width="stretch"):
            st.session_state["_pending_stock"] = _rec_code
            st.session_state["_auto_report"] = True
            st.session_state["_pending_nav"] = "分析報告"
            st.rerun()


def _render_v2_results(all_scan, pool_size, strategy_params, buy_threshold, sell_threshold):
    if not all_scan:
        st.error("無法取得任何股票資料")
        return

    buy_only = [s for s in all_scan if s["signal"] == "BUY"]

    if not buy_only:
        st.warning(
            f"掃描完成（共 {pool_size} 檔），目前沒有股票綜合評分達到買入閾值（≥ {strategy_params['buy_threshold']}）。\n\n"
            "建議耐心等待更好的進場時機。以下為全部股票評分排行僅供參考。"
        )
        sorted_results = sorted(all_scan, key=lambda x: x["composite_score"], reverse=True)
    else:
        st.success(f"掃描完成（共 {pool_size} 檔），找到 **{len(buy_only)}** 檔發出買入訊號！")
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
            explanation = explain_signal(stock, buy_threshold, sell_threshold)
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
    st.dataframe(pd.DataFrame(ranking_data), width="stretch", hide_index=True)
