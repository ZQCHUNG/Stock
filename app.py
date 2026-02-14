"""台股技術分析系統 - Streamlit Web 介面"""

import json
from pathlib import Path

import streamlit as st
import pandas as pd

from config import SCAN_STOCKS, BACKTEST_PARAMS, STRATEGY_PARAMS, RISK_PARAMS, STRATEGY_V4_PARAMS
from data.fetcher import get_stock_data, populate_ticker_cache
from data.stock_list import get_all_stocks, get_stock_name
from data.cache import get_cache_stats, flush_cache, get_worker_heartbeat
from analysis.market_regime import detect_market_regime, get_regime_color, get_regime_emoji

# 頁面模組
from pages import page_technical, page_backtest
from pages import page_recommend, page_report, page_screener, page_watchlist

# ===== 最近查詢持久化 =====
_RECENT_FILE = Path(__file__).parent / "data" / "recent_stocks.json"

def _load_recent_stocks() -> list:
    try:
        return json.loads(_RECENT_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def _save_recent_stocks(stocks: list):
    _RECENT_FILE.write_text(json.dumps(stocks, ensure_ascii=False), encoding="utf-8")

# ===== 自選股清單持久化 =====
_WATCHLIST_FILE = Path(__file__).parent / "data" / "watchlist.json"

def _load_watchlist() -> list:
    try:
        return json.loads(_WATCHLIST_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def _save_watchlist(stocks: list):
    _WATCHLIST_FILE.write_text(json.dumps(stocks, ensure_ascii=False), encoding="utf-8")

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

@st.cache_data(ttl=3600)
def build_select_options(stocks_dict):
    return sorted(
        [f"{code} {info['name']}" for code, info in stocks_dict.items()],
        key=lambda x: x.split()[0],
    )

all_stocks = load_stock_list()
populate_ticker_cache(all_stocks)  # 預填 .TW/.TWO 後綴，避免逐一 resolve
stock_select_options = build_select_options(all_stocks)

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

    # 最近搜尋紀錄（從 JSON 檔案載入）
    if "recent_stocks" not in st.session_state:
        st.session_state.recent_stocks = _load_recent_stocks()

    def _add_recent(code):
        recents = st.session_state.recent_stocks
        if code in recents:
            recents.remove(code)
        recents.insert(0, code)
        st.session_state.recent_stocks = recents[:5]
        _save_recent_stocks(recents[:5])

    # 處理快捷按鈕跳轉（必須在 text_input 渲染之前設定）
    if st.session_state.get("_pending_stock"):
        st.session_state.custom_code_input = st.session_state.pop("_pending_stock")

    custom_code = st.text_input(
        "或直接輸入股票代碼",
        placeholder="例如: 2330、6748",
        key="custom_code_input",
    )
    stock_code = custom_code.strip() if custom_code.strip() else default_code

    # 自選股（加入/移除）
    if "watchlist" not in st.session_state:
        st.session_state.watchlist = _load_watchlist()
    _in_watchlist = stock_code in st.session_state.watchlist
    wl_col1, wl_col2 = st.columns([3, 1])
    with wl_col1:
        stock_name_display = get_stock_name(stock_code, all_stocks)
        st.caption(f"目前：{stock_code} {stock_name_display}")
    with wl_col2:
        if _in_watchlist:
            if st.button("★", key="wl_remove", help="從自選股移除", width="stretch"):
                st.session_state.watchlist.remove(stock_code)
                _save_watchlist(st.session_state.watchlist)
                st.rerun()
        else:
            if st.button("☆", key="wl_add", help="加入自選股", width="stretch"):
                st.session_state.watchlist.insert(0, stock_code)
                _save_watchlist(st.session_state.watchlist)
                st.rerun()

    # 自選股清單
    if st.session_state.watchlist:
        with st.expander(f"自選股（{len(st.session_state.watchlist)} 檔）"):
            for wl_code in st.session_state.watchlist:
                wl_name = get_stock_name(wl_code, all_stocks)
                if st.button(f"{wl_code} {wl_name}", key=f"wl_{wl_code}", width="stretch"):
                    st.session_state["_pending_stock"] = wl_code

    if st.session_state.recent_stocks:
        st.caption("最近查詢")
        for code in st.session_state.recent_stocks:
            name = get_stock_name(code, all_stocks)
            if st.button(f"{code} {name}", key=f"recent_{code}", width="stretch"):
                st.session_state["_pending_stock"] = code

    st.divider()

    # 頁面選擇
    _PAGES = ["技術分析", "自選股總覽", "回測報告", "推薦股票", "分析報告", "條件選股"]
    # 處理跨頁導航請求（從條件選股快速分析 → 其他頁面）
    _pending_nav = st.session_state.pop("_pending_nav", None)
    _nav_ver = st.session_state.get("_nav_ver", 0)
    if _pending_nav and _pending_nav in _PAGES:
        _nav_ver += 1
        st.session_state["_nav_ver"] = _nav_ver
        st.session_state[f"_nav_page_{_nav_ver}"] = _pending_nav
    page = st.radio(
        "功能",
        options=_PAGES,
        key=f"_nav_page_{_nav_ver}",
    )

    # 延遲 rerun：等 radio 渲染完（保留 page 狀態）再觸發跳轉
    if st.session_state.get("_pending_stock"):
        st.rerun()

    st.divider()

    use_v4 = True  # v4 為唯一策略（v2 已移除）
    buy_threshold = STRATEGY_PARAMS["buy_threshold"]
    sell_threshold = STRATEGY_PARAMS["sell_threshold"]

    # 參數設定
    with st.expander("進階參數", expanded=False):
        initial_capital = st.number_input(
            "初始資金 (TWD)",
            min_value=100_000,
            max_value=100_000_000,
            value=BACKTEST_PARAMS["initial_capital"],
            step=100_000,
        )
        backtest_days = st.slider("回測天數", 90, 1095, 730, help="v4 策略建議 730 天以上效果最佳")
        sim_days = st.slider("模擬交易天數", 10, 60, 30)

        st.caption("v4 策略參數")
        v4_tp = st.slider("停利 (%)", 3, 30, int(STRATEGY_V4_PARAMS["take_profit_pct"] * 100), 1)
        v4_sl = st.slider("停損 (%)", 2, 15, int(STRATEGY_V4_PARAMS["stop_loss_pct"] * 100), 1)
        v4_trail = st.slider("移動停利 (%)", 1, 10, int(STRATEGY_V4_PARAMS["trailing_stop_pct"] * 100), 1)
        v4_hold = st.number_input("最短持有天數", min_value=0, max_value=15, value=STRATEGY_V4_PARAMS["min_hold_days"])
        v4_adx = st.slider("ADX 最低要求", 10, 35, STRATEGY_V4_PARAMS["adx_min"], 1)

    # Worker 狀態
    _heartbeat = get_worker_heartbeat()
    if _heartbeat:
        _last_scan = _heartbeat.get("last_scan_time", "")
        _scan_count = _heartbeat.get("scan_count", 0)
        _buy_signals = _heartbeat.get("buy_signals", 0)
        # 判斷是否在線（30 分鐘內有心跳）
        try:
            from datetime import datetime as _dt
            _last_dt = _dt.fromisoformat(_last_scan)
            _mins_ago = (_dt.now() - _last_dt).total_seconds() / 60
            if _mins_ago < 30:
                st.success(f"Worker 運作中（{_mins_ago:.0f} 分鐘前掃描）")
            else:
                st.warning(f"Worker 離線（{_mins_ago:.0f} 分鐘前最後掃描）")
        except Exception:
            st.info(f"Worker: 掃描 {_scan_count} 次")
        st.caption(f"掃描 {_scan_count} 次 | 買入訊號 {_buy_signals} 檔")

    # 市場環境偵測
    try:
        from data.fetcher import get_taiex_data as _get_taiex
        _taiex_df = _get_taiex(period_days=120)
        if _taiex_df is not None and len(_taiex_df) >= 60:
            _regime = detect_market_regime(_taiex_df)
            _r_emoji = get_regime_emoji(_regime["regime"])
            _r_label = _regime["regime_label"]
            _r_mult = _regime["position_multiplier"]
            if _regime["regime"] == "bull":
                st.success(f"{_r_emoji} 大盤環境：{_r_label}（建議部位 {_r_mult:.0%}）")
            elif _regime["regime"] == "bear":
                st.error(f"{_r_emoji} 大盤環境：{_r_label}（建議部位 {_r_mult:.0%}）")
            else:
                st.warning(f"{_r_emoji} 大盤環境：{_r_label}（建議部位 {_r_mult:.0%}）")
            st.caption(_regime["detail"])
            st.session_state["_market_regime"] = _regime
    except Exception:
        pass

    # 快取狀態
    with st.expander("快取狀態", expanded=False):
        stats = get_cache_stats()
        if stats["status"] == "connected":
            st.success("Redis 已連線")
            st.caption(f"快取鍵數：{stats['keys']} | 記憶體：{stats['memory_used']}")
        elif stats["status"] == "memory_fallback":
            st.info(f"記憶體快取模式（{stats['keys']} 筆）")
            st.caption("Redis 未連線，使用 in-memory 快取。重啟後快取會清空。")
        else:
            st.warning("快取異常")
        if st.button("清空快取"):
            flush_cache()
            st.cache_data.clear()
            st.rerun()

    # 顏色圖例（移到主頁面底部，sidebar 保持簡潔）


# ===== 資料載入 =====
@st.cache_data(ttl=900)  # 快取 15 分鐘
def load_data(code: str, days: int):
    return get_stock_data(code, period_days=days)


# 推薦股票/分析報告/條件選股頁面不需要預先載入單一股票
if page not in ("推薦股票", "分析報告", "條件選股", "自選股總覽"):
    try:
        fetch_days = max(backtest_days, 365) + 120
        raw_df = load_data(stock_code, fetch_days)
        stock_name = get_stock_name(stock_code, all_stocks)
        _add_recent(stock_code)
        # 顯示即時價格與漲跌
        if len(raw_df) >= 2:
            _last_close = raw_df["close"].iloc[-1]
            _prev_close = raw_df["close"].iloc[-2]
            _chg = _last_close - _prev_close
            _chg_pct = _chg / _prev_close * 100
            _chg_icon = "🔴" if _chg > 0 else ("🟢" if _chg < 0 else "⚪")
            st.sidebar.success(f"已載入 {stock_code} {stock_name}")
            st.sidebar.markdown(f"**{_chg_icon} \\${_last_close:.2f}** ({_chg:+.2f}, {_chg_pct:+.2f}%)")
        else:
            st.sidebar.success(f"已載入 {stock_code} {stock_name}")
    except Exception as e:
        st.error(f"無法載入股票 {stock_code} 的資料：{e}")
        st.stop()

# ===== 覆寫 v4 策略參數 =====
STRATEGY_V4_PARAMS["take_profit_pct"] = v4_tp / 100
STRATEGY_V4_PARAMS["stop_loss_pct"] = v4_sl / 100
STRATEGY_V4_PARAMS["trailing_stop_pct"] = v4_trail / 100
STRATEGY_V4_PARAMS["min_hold_days"] = v4_hold
STRATEGY_V4_PARAMS["adx_min"] = v4_adx


# ===== 頁面路由 =====
if page == "技術分析":
    page_technical.render(
        stock_code=stock_code,
        stock_name=stock_name,
        raw_df=raw_df,
        use_v4=use_v4,
        all_stocks=all_stocks,
        v4_params=STRATEGY_V4_PARAMS,
        buy_threshold=buy_threshold,
        sell_threshold=sell_threshold,
        initial_capital=initial_capital,
        backtest_days=backtest_days,
        save_watchlist_fn=_save_watchlist,
        load_data_fn=load_data,
    )

elif page == "回測報告":
    page_backtest.render(
        stock_code=stock_code,
        stock_name=stock_name,
        raw_df=raw_df,
        use_v4=use_v4,
        initial_capital=initial_capital,
        backtest_days=backtest_days,
        all_stocks=all_stocks,
        load_data_fn=load_data,
        sim_days=sim_days,
    )

elif page == "推薦股票":
    page_recommend.render(
        use_v4=use_v4,
        all_stocks=all_stocks,
        scan_stocks=SCAN_STOCKS,
        strategy_params=STRATEGY_PARAMS,
        buy_threshold=buy_threshold,
        sell_threshold=sell_threshold,
        save_watchlist_fn=_save_watchlist,
    )

elif page == "分析報告":
    page_report.render(
        stock_code=stock_code,
        add_recent_fn=_add_recent,
    )

elif page == "條件選股":
    page_screener.render(
        all_stocks=all_stocks,
        scan_stocks=SCAN_STOCKS,
    )

elif page == "自選股總覽":
    page_watchlist.render(
        all_stocks=all_stocks,
        initial_capital=initial_capital,
        load_data_fn=load_data,
    )


# ===== Footer =====
st.divider()
st.caption(
    "⚠️ 本系統僅供技術分析參考，不構成投資建議。投資有風險，請自行判斷。"
    " | 資料來源：Yahoo Finance | v2.0"
)
