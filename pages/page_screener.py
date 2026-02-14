"""條件選股頁面"""

import json
import streamlit as st
import pandas as pd
import numpy as np

from data.cache import get_cached_screener_results, set_cached_screener_results


def render(all_stocks, scan_stocks):
    st.header("條件選股")
    st.caption("依基本面 / 技術面條件篩選股票（類似財報狗）。勾選想要的條件、設定閾值，再按「開始選股」。")

    # ----- 快速選股策略 -----
    SCREENER_PRESETS = {
        "高殖利率": {
            "f_roe": True, "f_roe_val": 10.0,
            "f_dy": True, "f_dy_val": 4.0,
            "f_de": True, "f_de_val": 150.0,
            "f_fcf": True,
        },
        "價值低估": {
            "f_pe": True, "f_pe_val": 15.0,
            "f_pb": True, "f_pb_val": 2.0,
            "f_roe": True, "f_roe_val": 12.0,
            "f_dy": True, "f_dy_val": 2.0,
        },
        "高速成長": {
            "f_revg": True, "f_revg_val": 15.0,
            "f_earng": True, "f_earng_val": 15.0,
            "f_roe": True, "f_roe_val": 15.0,
            "f_eps": True, "f_eps_val": 2.0,
        },
        "穩健龍頭": {
            "f_mcap": True, "f_mcap_val": 500.0,
            "f_roe": True, "f_roe_val": 10.0,
            "f_beta": True, "f_beta_val": 1.2,
            "f_fcf": True,
        },
        "高獲利": {
            "f_roe": True, "f_roe_val": 20.0,
            "f_gross": True, "f_gross_val": 30.0,
            "f_eps": True, "f_eps_val": 3.0,
            "f_opm": True, "f_opm_val": 15.0,
        },
    }

    _ALL_FILTER_KEYS = [
        "f_roe", "f_roa", "f_gross", "f_opm", "f_npm", "f_eps",
        "f_revg", "f_earng", "f_de", "f_cr",
        "f_pe", "f_fpe", "f_pb", "f_dy",
        "f_fcf", "f_ocf", "f_mcap", "f_beta",
        "f_rsi", "f_adx",
    ]

    preset_cols = st.columns(len(SCREENER_PRESETS))
    for i, (preset_name, preset_cfg) in enumerate(SCREENER_PRESETS.items()):
        with preset_cols[i]:
            if st.button(preset_name, key=f"preset_{i}", width="stretch"):
                for k in _ALL_FILTER_KEYS:
                    st.session_state[k] = False
                for k, v in preset_cfg.items():
                    st.session_state[k] = v
                st.rerun()

    st.divider()

    # ----- 篩選條件 UI -----
    _FILTER_DEFAULTS = {
        "f_roe": True, "f_roe_val": 15.0,
        "f_roa": False, "f_roa_val": 5.0,
        "f_gross": False, "f_gross_val": 20.0,
        "f_opm": False, "f_opm_val": 10.0,
        "f_npm": False, "f_npm_val": 5.0,
        "f_eps": False, "f_eps_val": 2.0,
        "f_revg": False, "f_revg_val": 10.0,
        "f_earng": False, "f_earng_val": 10.0,
        "f_de": False, "f_de_val": 100.0,
        "f_cr": False, "f_cr_val": 1.5,
        "f_pe": False, "f_pe_val": 20.0,
        "f_fpe": False, "f_fpe_val": 15.0,
        "f_pb": False, "f_pb_val": 3.0,
        "f_dy": False, "f_dy_val": 3.0,
        "f_fcf": False, "f_ocf": False,
        "f_mcap": False, "f_mcap_val": 100.0,
        "f_beta": False, "f_beta_val": 1.5,
        "f_rsi": False, "f_rsi_lo": 30.0, "f_rsi_hi": 70.0,
        "f_adx": False, "f_adx_val": 20.0,
    }
    for _k, _v in _FILTER_DEFAULTS.items():
        if _k not in st.session_state:
            st.session_state[_k] = _v

    filter_cfg = {}

    with st.expander("獲利能力", expanded=True):
        col_a, col_b = st.columns(2)
        with col_a:
            f_roe = st.checkbox("ROE (%)", key="f_roe")
            f_roe_val = st.number_input("ROE >", step=1.0, key="f_roe_val", format="%.1f")
            f_roa = st.checkbox("ROA (%)", key="f_roa")
            f_roa_val = st.number_input("ROA >", step=1.0, key="f_roa_val", format="%.1f")
            f_gross = st.checkbox("毛利率 (%)", key="f_gross")
            f_gross_val = st.number_input("毛利率 >", step=1.0, key="f_gross_val", format="%.1f")
        with col_b:
            f_opm = st.checkbox("營業利益率 (%)", key="f_opm")
            f_opm_val = st.number_input("營業利益率 >", step=1.0, key="f_opm_val", format="%.1f")
            f_npm = st.checkbox("淨利率 (%)", key="f_npm")
            f_npm_val = st.number_input("淨利率 >", step=1.0, key="f_npm_val", format="%.1f")
            f_eps = st.checkbox("EPS (元)", key="f_eps")
            f_eps_val = st.number_input("EPS >", step=0.5, key="f_eps_val", format="%.1f")

    if f_roe:
        filter_cfg["return_on_equity"] = (">", f_roe_val / 100)
    if f_roa:
        filter_cfg["return_on_assets"] = (">", f_roa_val / 100)
    if f_gross:
        filter_cfg["gross_margins"] = (">", f_gross_val / 100)
    if f_opm:
        filter_cfg["operating_margins"] = (">", f_opm_val / 100)
    if f_npm:
        filter_cfg["profit_margins"] = (">", f_npm_val / 100)
    if f_eps:
        filter_cfg["trailing_eps"] = (">", f_eps_val)

    with st.expander("成長力"):
        col_a, col_b = st.columns(2)
        with col_a:
            f_revg = st.checkbox("營收成長率 (%)", key="f_revg")
            f_revg_val = st.number_input("營收成長 >", step=1.0, key="f_revg_val", format="%.1f")
        with col_b:
            f_earng = st.checkbox("獲利成長率 (%)", key="f_earng")
            f_earng_val = st.number_input("獲利成長 >", step=1.0, key="f_earng_val", format="%.1f")

    if f_revg:
        filter_cfg["revenue_growth"] = (">", f_revg_val / 100)
    if f_earng:
        filter_cfg["earnings_growth"] = (">", f_earng_val / 100)

    with st.expander("安全性"):
        col_a, col_b = st.columns(2)
        with col_a:
            f_de = st.checkbox("負債權益比 (%)", key="f_de")
            f_de_val = st.number_input("負債權益比 <", step=10.0, key="f_de_val", format="%.0f")
        with col_b:
            f_cr = st.checkbox("流動比率", key="f_cr")
            f_cr_val = st.number_input("流動比率 >", step=0.1, key="f_cr_val", format="%.1f")

    if f_de:
        filter_cfg["debt_to_equity"] = ("<", f_de_val)
    if f_cr:
        filter_cfg["current_ratio"] = (">", f_cr_val)

    with st.expander("價值評估"):
        col_a, col_b = st.columns(2)
        with col_a:
            f_pe = st.checkbox("本益比 (TTM)", key="f_pe")
            f_pe_val = st.number_input("本益比 <", step=1.0, key="f_pe_val", format="%.1f")
            f_fpe = st.checkbox("Forward PE", key="f_fpe")
            f_fpe_val = st.number_input("Forward PE <", step=1.0, key="f_fpe_val", format="%.1f")
            f_pb = st.checkbox("淨值比", key="f_pb")
            f_pb_val = st.number_input("淨值比 <", step=0.5, key="f_pb_val", format="%.1f")
        with col_b:
            f_dy = st.checkbox("殖利率 (%)", key="f_dy")
            f_dy_val = st.number_input("殖利率 >", step=0.5, key="f_dy_val", format="%.1f")

    if f_pe:
        filter_cfg["trailing_pe"] = ("<", f_pe_val)
    if f_fpe:
        filter_cfg["forward_pe"] = ("<", f_fpe_val)
    if f_pb:
        filter_cfg["price_to_book"] = ("<", f_pb_val)
    if f_dy:
        filter_cfg["dividend_yield"] = (">", f_dy_val / 100)

    with st.expander("現金流 & 規模"):
        col_a, col_b = st.columns(2)
        with col_a:
            f_fcf = st.checkbox("自由現金流 > 0", key="f_fcf")
            f_ocf = st.checkbox("營業現金流 > 0", key="f_ocf")
        with col_b:
            f_mcap = st.checkbox("市值 (億)", key="f_mcap")
            f_mcap_val = st.number_input("市值 >", step=50.0, key="f_mcap_val", format="%.0f", help="單位：億元台幣")
            f_beta = st.checkbox("Beta", key="f_beta")
            f_beta_val = st.number_input("Beta <", step=0.1, key="f_beta_val", format="%.1f")

    if f_fcf:
        filter_cfg["free_cashflow"] = (">", 0)
    if f_ocf:
        filter_cfg["operating_cashflow"] = (">", 0)
    if f_mcap:
        filter_cfg["market_cap"] = (">", f_mcap_val * 1e8)
    if f_beta:
        filter_cfg["beta"] = ("<", f_beta_val)

    with st.expander("技術面"):
        col_a, col_b = st.columns(2)
        with col_a:
            f_rsi = st.checkbox("RSI 區間", key="f_rsi")
            f_rsi_lo = st.number_input("RSI 下限", step=5.0, key="f_rsi_lo", format="%.0f")
            f_rsi_hi = st.number_input("RSI 上限", step=5.0, key="f_rsi_hi", format="%.0f")
        with col_b:
            f_adx = st.checkbox("ADX", key="f_adx")
            f_adx_val = st.number_input("ADX >", step=1.0, key="f_adx_val", format="%.0f")

    # ----- 掃描範圍 & 執行 -----
    st.divider()
    scan_scope_scr = st.radio(
        "掃描範圍",
        ["精選 25 檔（快速）", "全部股票（較慢）"],
        horizontal=True,
        key="scr_scope",
    )
    use_full_scr = scan_scope_scr.startswith("全部")
    scan_pool_scr = all_stocks if use_full_scr else scan_stocks

    has_any_filter = bool(filter_cfg) or f_rsi or f_adx
    if not has_any_filter:
        st.info("請至少勾選一項篩選條件。")

    def _build_conditions_hash() -> str:
        import hashlib
        parts = sorted(filter_cfg.items())
        if f_rsi:
            parts.append(("rsi", (f_rsi_lo, f_rsi_hi)))
        if f_adx:
            parts.append(("adx", f_adx_val))
        parts.append(("scope", "full" if use_full_scr else "select"))
        return hashlib.md5(str(parts).encode()).hexdigest()[:12]

    if st.button("開始選股", type="primary", key="scr_start", disabled=(not has_any_filter)):
        cond_hash = _build_conditions_hash()

        cached_results = get_cached_screener_results(cond_hash)
        if cached_results:
            st.info("使用快取結果（30 分鐘內相同條件）")
            results = cached_results
        else:
            import subprocess, tempfile, os

            pool_with_market = {}
            for code, info in scan_pool_scr.items():
                if isinstance(info, dict):
                    pool_with_market[code] = info
                else:
                    full = all_stocks.get(code, {})
                    pool_with_market[code] = {
                        "name": info if isinstance(info, str) else full.get("name", code),
                        "market": full.get("market", "上市"),
                    }

            worker_input = {
                "scan_pool": pool_with_market,
                "filter_cfg": {k: list(v) for k, v in filter_cfg.items()},
                "need_rsi": f_rsi,
                "rsi_lo": f_rsi_lo if f_rsi else 30,
                "rsi_hi": f_rsi_hi if f_rsi else 70,
                "need_adx": f_adx,
                "adx_val": f_adx_val if f_adx else 20,
            }

            tmp_dir = tempfile.mkdtemp()
            in_file = os.path.join(tmp_dir, "screener_in.json")
            out_file = os.path.join(tmp_dir, "screener_out.json")
            with open(in_file, "w", encoding="utf-8") as f:
                json.dump(worker_input, f, ensure_ascii=False)

            with st.spinner(f"並行掃描 {len(scan_pool_scr)} 檔中，請稍候（約 10-30 秒）..."):
                proc = subprocess.run(
                    ["python", "screener_worker.py", in_file, out_file],
                    capture_output=True, text=True, timeout=300,
                )

            if proc.returncode != 0:
                st.error(f"掃描失敗：{proc.stderr[:500]}")
                results = []
            else:
                with open(out_file, "r", encoding="utf-8") as f:
                    results = json.load(f)

            try:
                os.remove(in_file)
                os.remove(out_file)
                os.rmdir(tmp_dir)
            except Exception:
                pass

            if results:
                set_cached_screener_results(cond_hash, results)

        st.session_state["_screener_results"] = results
        st.session_state["_screener_filter_cfg"] = dict(filter_cfg)
        st.session_state["_screener_pool_size"] = len(scan_pool_scr)
        st.session_state["_screener_rsi"] = (f_rsi, f_rsi_lo, f_rsi_hi)
        st.session_state["_screener_adx"] = (f_adx, f_adx_val)

    # ----- 從 session_state 讀取結果並顯示 -----
    _scr_results = st.session_state.get("_screener_results")
    _scr_filter_cfg = st.session_state.get("_screener_filter_cfg", {})
    _scr_pool_size = st.session_state.get("_screener_pool_size", 0)
    _scr_rsi = st.session_state.get("_screener_rsi", (False, 30, 70))
    _scr_adx = st.session_state.get("_screener_adx", (False, 20))

    if _scr_results is not None:
        _render_results(_scr_results, _scr_filter_cfg, _scr_pool_size, _scr_rsi, _scr_adx)


def _render_results(results, filter_cfg, pool_size, scr_rsi, scr_adx):
    _FIELD_LABELS = {
        "return_on_equity": "ROE", "return_on_assets": "ROA",
        "gross_margins": "毛利率", "operating_margins": "營利率",
        "profit_margins": "淨利率", "trailing_eps": "EPS",
        "revenue_growth": "營收成長", "earnings_growth": "獲利成長",
        "debt_to_equity": "負債比", "current_ratio": "流動比",
        "trailing_pe": "PE", "forward_pe": "F.PE",
        "price_to_book": "PB", "dividend_yield": "殖利率",
        "free_cashflow": "FCF", "operating_cashflow": "OCF",
        "market_cap": "市值", "beta": "Beta",
    }
    cond_parts = []
    for field, (op, val) in filter_cfg.items():
        label = _FIELD_LABELS.get(field, field)
        if field in ("return_on_equity", "return_on_assets", "gross_margins",
                     "operating_margins", "profit_margins", "revenue_growth",
                     "earnings_growth", "dividend_yield"):
            cond_parts.append(f"{label} {op} {val*100:.0f}%")
        elif field == "market_cap":
            cond_parts.append(f"{label} {op} {val/1e8:.0f}億")
        elif field in ("free_cashflow", "operating_cashflow"):
            cond_parts.append(f"{label} {op} 0")
        else:
            cond_parts.append(f"{label} {op} {val}")
    if scr_rsi[0]:
        cond_parts.append(f"RSI {scr_rsi[1]:.0f}~{scr_rsi[2]:.0f}")
    if scr_adx[0]:
        cond_parts.append(f"ADX > {scr_adx[1]:.0f}")

    cond_summary = " + ".join(cond_parts) if cond_parts else "（無條件）"
    st.caption(f"篩選條件：{cond_summary}")

    if not results:
        st.warning(f"掃描完成（共 {pool_size} 檔），無股票符合所有條件。試著放寬條件再搜尋。")
        return

    st.success(f"掃描完成（共 {pool_size} 檔），找到 **{len(results)}** 檔符合條件！")

    display_rows = []
    for r in results:
        def _safe_round(v, d=1):
            return round(v, d) if v is not None else None
        def _pct_val(v):
            return round(v * 100, 1) if v is not None else None
        row = {
            "代碼": r["代碼"],
            "名稱": r["名稱"],
            "收盤價": _safe_round(r.get("收盤價"), 2),
            "PE": _safe_round(r.get("PE")),
            "F.PE": _safe_round(r.get("Forward PE")),
            "PB": _safe_round(r.get("PB")),
            "ROE%": _pct_val(r.get("ROE")),
            "ROA%": _pct_val(r.get("ROA")),
            "毛利%": _pct_val(r.get("毛利率")),
            "營利%": _pct_val(r.get("營利率")),
            "淨利%": _pct_val(r.get("淨利率")),
            "EPS": _safe_round(r.get("EPS")),
            "營收成長%": _pct_val(r.get("營收成長")),
            "獲利成長%": _pct_val(r.get("獲利成長")),
            "殖利率%": _pct_val(r.get("殖利率")),
            "負債比": _safe_round(r.get("負債比"), 0),
            "流動比": _safe_round(r.get("流動比")),
            "Beta": _safe_round(r.get("Beta"), 2),
            "市值億": _safe_round(r.get("市值(億)"), 0),
            "FCF億": _safe_round(r.get("自由現金流(億)")),
            "OCF億": _safe_round(r.get("營業現金流(億)")),
            "目標價": _safe_round(r.get("目標價"), 0),
            "RSI": _safe_round(r.get("RSI")),
            "ADX": _safe_round(r.get("ADX")),
        }
        display_rows.append(row)

    df_result = pd.DataFrame(display_rows)

    if "return_on_equity" in filter_cfg:
        df_result = df_result.sort_values("ROE%", ascending=False)
    elif "trailing_pe" in filter_cfg:
        df_result = df_result.sort_values("PE", ascending=True)
    elif "dividend_yield" in filter_cfg:
        df_result = df_result.sort_values("殖利率%", ascending=False)
    elif "revenue_growth" in filter_cfg:
        df_result = df_result.sort_values("營收成長%", ascending=False)

    def _color_positive(val):
        if val is None or (isinstance(val, float) and np.isnan(val)):
            return ""
        if isinstance(val, (int, float)):
            if val > 0:
                return "color: #00C853"
            elif val < 0:
                return "color: #FF1744"
        return ""

    def _color_roe(val):
        if val is None or (isinstance(val, float) and np.isnan(val)):
            return ""
        if val >= 15:
            return "color: #00C853; font-weight: bold"
        elif val >= 10:
            return "color: #00C853"
        elif val < 0:
            return "color: #FF1744"
        return ""

    def _color_pe(val):
        if val is None or (isinstance(val, float) and np.isnan(val)):
            return ""
        if val < 0:
            return "color: #FF1744"
        elif val <= 15:
            return "color: #00C853; font-weight: bold"
        elif val <= 20:
            return "color: #00C853"
        elif val > 40:
            return "color: #FF1744"
        return ""

    def _color_yield(val):
        if val is None or (isinstance(val, float) and np.isnan(val)):
            return ""
        if val >= 5:
            return "color: #00C853; font-weight: bold"
        elif val >= 3:
            return "color: #00C853"
        return ""

    def _color_rsi(val):
        if val is None or (isinstance(val, float) and np.isnan(val)):
            return ""
        if val >= 70:
            return "color: #FF1744"
        elif val <= 30:
            return "color: #00C853"
        return ""

    styled_df = df_result.style
    for col in ["ROE%", "ROA%", "毛利%", "營利%", "淨利%"]:
        if col in df_result.columns:
            styled_df = styled_df.map(_color_roe, subset=[col])
    for col in ["營收成長%", "獲利成長%"]:
        if col in df_result.columns:
            styled_df = styled_df.map(_color_positive, subset=[col])
    for col in ["PE", "F.PE"]:
        if col in df_result.columns:
            styled_df = styled_df.map(_color_pe, subset=[col])
    if "殖利率%" in df_result.columns:
        styled_df = styled_df.map(_color_yield, subset=["殖利率%"])
    for col in ["EPS", "FCF億", "OCF億"]:
        if col in df_result.columns:
            styled_df = styled_df.map(_color_positive, subset=[col])
    if "RSI" in df_result.columns:
        styled_df = styled_df.map(_color_rsi, subset=["RSI"])

    st.dataframe(styled_df, width="stretch", hide_index=True)

    csv_data = df_result.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        label="下載 CSV",
        data=csv_data,
        file_name="screener_results.csv",
        mime="text/csv",
    )

    # 快速跳轉
    st.divider()
    st.subheader("快速分析")
    st.caption("選取上方結果中的股票，快速跳轉到其他分析頁面。")
    scr_stock_options = [f"{r['代碼']} {r['名稱']}" for r in results]
    scr_selected = st.selectbox("選擇股票", scr_stock_options, key="scr_jump_stock")
    scr_jump_code = scr_selected.split()[0] if scr_selected else ""
    jump_cols = st.columns(3)
    with jump_cols[0]:
        if st.button("技術分析", key="scr_to_tech", width="stretch"):
            st.session_state["_pending_stock"] = scr_jump_code
            st.session_state["_pending_nav"] = "技術分析"
            st.rerun()
    with jump_cols[1]:
        if st.button("回測報告", key="scr_to_bt", width="stretch"):
            st.session_state["_pending_stock"] = scr_jump_code
            st.session_state["_pending_nav"] = "回測報告"
            st.rerun()
    with jump_cols[2]:
        if st.button("分析報告", key="scr_to_rpt", width="stretch"):
            st.session_state["_pending_stock"] = scr_jump_code
            st.session_state["_auto_report"] = True
            st.session_state["_pending_nav"] = "分析報告"
            st.rerun()
