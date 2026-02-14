# Gemini Review Request: Vue.js 3 + FastAPI Frontend Migration

**Date**: 2026-02-14
**Author**: Claude (Opus 4.6)
**Context**: Gemini UI review scored Streamlit 3/10 (P0 blocker). This is the complete replacement.

---

## 1. What Was Done

Replaced entire Streamlit UI with:
- **Backend**: FastAPI REST API wrapping all existing Python modules
- **Frontend**: Vue 3 + Vite + TypeScript + Naive UI SPA

**Critical constraint**: Zero changes to `analysis/`, `backtest/`, `data/`, `simulation/`, `config.py`. All 345 existing tests pass unchanged.

---

## 2. Architecture

```
backend/                          (1,269 lines total)
  app.py                 (44L)    FastAPI entry, CORS, 8 router includes, static serve
  dependencies.py        (69L)    df_to_response(), make_serializable(), _safe_float()
  schemas/common.py      (20L)    Pydantic: TimeSeriesResponse, SeriesResponse
  routers/
    stocks.py           (112L)    10 endpoints: list/search/data/info/name/fund/news/inst/div/taiex
    analysis.py         (137L)    7 endpoints: indicators/v4-signal/v4-enhanced/v4-full/S&R/vol-patterns/regime
    backtest.py         (283L)    6 POST endpoints: v4/portfolio/simulation/rolling/sensitivity/alpha-beta
    report.py           (153L)    1 POST: full report generation + serialization
    recommend.py         (63L)    1 POST: v4 scan with cache
    screener.py         (163L)    1 POST: condition screener (12 filter fields, max 200 stocks)
    watchlist.py        (153L)    6 endpoints: CRUD + overview + batch backtest
    system.py            (72L)    6 endpoints: cache stats/flush, recent stocks, worker, v4 params

frontend/src/                     (1,788 lines total)
  api/                   (143L)   Axios client + 8 domain-specific API modules
  stores/                (361L)   9 Pinia stores (app, technical, backtest, watchlist, report, recommend, screener, cache)
  router/                 (46L)   6 lazy-loaded routes, / redirects to /technical
  utils/                  (39L)   fmtPct, fmtNum, fmtMoney, priceColor (漲紅跌綠), signalColor
  components/            (375L)   7 components: AppSidebar, CandlestickChart, MacdChart, KdChart,
                                  MetricCard, SignalBadge, ColoredNumber
  views/                 (813L)   6 page views (below)
  App.vue                 (43L)   NLayout has-sider shell
  main.ts                 (11L)   createApp + Pinia + Router + Naive UI
```

**Total new code**: ~3,057 lines (backend 1,269 + frontend 1,788)

---

## 3. Tech Stack Decisions

| Choice | Rationale |
|--------|-----------|
| **Naive UI** | TypeScript-native, tree-shakable, good CJK support |
| **vue-echarts** | Better perf than Plotly, smaller bundle, native Vue integration |
| **Pinia** | Official Vue state management, TypeScript support |
| **Axios** | Request interceptor for error handling, response unwrap |
| **Vite proxy** | Dev: `/api` -> `localhost:8000`. Prod: FastAPI serves `dist/` |

---

## 4. Six Pages — Feature Summary

### 4.1 技術分析 (TechnicalView.vue, 167L)
- V4 signal summary: 4 MetricCards (signal badge, price, uptrend days, confidence)
- V4 indicator panel: 8 indicators (ADX, +DI, -DI, RSI, ROC, MA5/20/60)
- **Candlestick chart** (ECharts): K-line + MA5/20/60 + BB bands + buy/sell markers + S/R lines + dataZoom
- MACD chart (line + signal + histogram) + KD chart (K/D + 80/20 reference lines) — side by side
- Support/Resistance levels (5 supports + 5 resistances with source labels)
- Volume pattern summary (6 metrics in NDescriptions)
- Institutional data table (外資/投信/自營 with 漲紅跌綠 coloring)
- **Data loading**: 7 API calls in parallel via `Promise.allSettled`

### 4.2 回測報告 (BacktestView.vue, 129L)
- Input controls: period days + initial capital
- 12 metric cards: total return, annual return, max drawdown, Sharpe, win rate, profit factor, trades, avg holding days, Sortino, Calmar, max consecutive wins/losses
- Tabs: Equity curve (area chart), Exit reason pie chart, Trade table (NDataTable)
- Strategy params description shown at bottom

### 4.3 自選股總覽 (WatchlistView.vue, 106L)
- Overview table: code, name, price, change%, volume, signal (colored NTag), RSI, remove button
- Batch backtest results table (NDataTable with sortable columns)
- Click row → selectStock (navigate to technical)

### 4.4 推薦股票 (RecommendView.vue, 116L)
- Auto-scan on mount
- BUY signals: 3-column card grid (code, name, price, change%, entry type, trend days, ADX, RSI)
- HOLD: compact table
- SELL: compact table
- Add to watchlist buttons

### 4.5 分析報告 (ReportView.vue, 154L)
- Rating banner (NTag: 強力買進/買進/中立/賣出 + price + date)
- Investment summary (pre-wrapped text)
- 7 tabs: 價格表現 (5 period MetricCards + 52w range), 技術面 (NDescriptions), 目標價 (table), 基本面 (dynamic key-value), 消息面 (links + sentiment), 行動建議 (entry/SL/TP/position/rationale), 風險 (level + drawdown + risk/reward)

### 4.6 條件選股 (ScreenerView.vue, 141L)
- 10 filter fields: price range, min volume (500), min ADX (18), RSI range, signal filter, market filter, MA20>MA60 toggle, min uptrend days
- Results table: code, name, market, price, change%, volume, signal, add to watchlist

---

## 5. API Endpoint Catalog (38 endpoints)

| Router | Count | Methods |
|--------|-------|---------|
| stocks | 10 | All GET |
| analysis | 7 | All GET |
| backtest | 6 | All POST |
| report | 1 | POST |
| recommend | 1 | POST |
| screener | 1 | POST |
| watchlist | 6 | GET/POST/DELETE |
| system | 6 | GET/POST |
| **Total** | **38** | |

### Key Serialization Pattern
```python
def df_to_response(df, tail=None) -> dict:
    """DataFrame -> {dates: str[], columns: {col_name: float[]}}"""
    # Handles: NaN -> null, numpy types -> Python natives, Timestamp -> isoformat

def make_serializable(obj):
    """Recursive deep clean for JSON serialization"""
    # Handles: dataclass, dict, list, pd.Series, np.int64, np.float64, pd.Timestamp, NaN
```

---

## 6. Bugs Found & Fixed During Runtime Verification

### Bug 1: MetricCard required prop warning
- **Symptom**: Vue warning "Missing required prop: value" when using slot-based content
- **Root cause**: `value` prop was required but V4 signal card uses `<slot>` instead
- **Fix**: Made `value` optional, added `<slot>{{ value }}</slot>` fallback

### Bug 2: yf.download thread-safety (Critical)
- **Symptom**: Watchlist overview returned identical data (台積電's price) for ALL stocks
- **Root cause**: `yf.download()` is not thread-safe. `ThreadPoolExecutor` concurrent calls cause data cross-contamination. Corrupted data then gets cached, persisting the bug.
- **Fix**: Changed watchlist overview + batch backtest from `ThreadPoolExecutor` to sequential `for` loop
- **Impact**: Overview load time ~6x slower (sequential vs parallel), but data is correct
- **Future mitigation**: Could use `yf.Ticker(code).history()` instead of `yf.download()` (more thread-safe), but that requires changing `data/fetcher.py` which is out of scope

---

## 7. What's NOT Implemented (vs Plan)

| Feature | Status | Priority |
|---------|--------|----------|
| Portfolio backtest UI | Backend endpoint exists, frontend view not built | P2 |
| Simulation mode UI | Backend endpoint exists, frontend view not built | P2 |
| Rolling/Sensitivity UI | Backend endpoints exist, frontend views not built | P3 |
| Monthly heatmap chart | Planned but not implemented | P3 |
| Drawdown chart | Planned but not implemented | P3 |
| Trade mark overlay on candlestick | Planned but not implemented | P3 |
| CSV export | Not implemented | P3 |
| HTML report download | Not implemented | P3 |
| Cross-page quick nav buttons | Partial (sidebar nav works) | P3 |
| NSelect default values | Shows "Please Select" instead of "不限" | P4 (cosmetic) |
| Dark mode | Not implemented | P4 |

---

## 8. Known Limitations

1. **No WebSocket/SSE**: Long operations (scan, screener, batch BT) block with loading spinner. No progress indication.
2. **No error toast notifications**: Errors shown inline via NAlert, not via Naive UI's message/notification system.
3. **Bundle size**: `npm run build` produces 1,460 KB JS chunk (Naive UI is large). No code splitting beyond route-level lazy loading.
4. **No responsive design**: Fixed 280px sidebar, grid layouts assume wide screen.
5. **Screener stock pool**: Scans all_stocks (potentially thousands) sequentially. Could be very slow without Redis cache.
6. **V4 signal card missing signal color**: The first MetricCard in TechnicalView shows the signal badge via slot, but the card background doesn't change color based on signal.

---

## 9. Questions for Gemini

1. **UX scoring**: What score would you give this Vue 3 version vs the old Streamlit 3/10? What specific improvements are needed for 8+/10?

2. **Component granularity**: I have 7 components. The plan called for ~15 (including ChartContainer, ProgressBar, DownloadButton, QuickNavButtons, etc.). Is the current granularity sufficient or should I extract more?

3. **State management**: Each page loads its own data on mount/watch. There's no global data prefetching or cross-page caching. Is this acceptable or should stock data be shared across pages?

4. **Chart interaction**: Current charts are display-only (no crosshair sync between K-line/MACD/KD, no click-to-inspect). How important is chart interactivity for a technical analysis tool?

5. **Table vs Card layout**: Watchlist uses raw `<table>`, backtest uses NDataTable. Should I standardize on NDataTable everywhere for consistency + sorting + pagination?

6. **yfinance thread-safety workaround**: Sequential loading means watchlist overview takes ~30s for 6 stocks. Should we:
   - (a) Accept the slowness
   - (b) Switch to `yf.Ticker().history()` (requires data/fetcher.py change)
   - (c) Pre-fetch on app startup
   - (d) Use a queue-based worker

7. **Missing features priority**: Portfolio backtest UI, simulation UI, CSV export, dark mode — what should be P1?

---

## 10. How to Run

```bash
# Terminal 1: Backend
cd D:\Mine\Stock
python -m uvicorn backend.app:app --port 8000

# Terminal 2: Frontend (dev)
cd D:\Mine\Stock\frontend
npm run dev

# Production build
cd D:\Mine\Stock\frontend
npm run build
# Then just run uvicorn — it serves frontend/dist/ at localhost:8000
```

---

## 11. File Tree (Complete)

```
backend/
  __init__.py
  app.py
  dependencies.py
  schemas/
    __init__.py
    common.py
  routers/
    __init__.py
    stocks.py
    analysis.py
    backtest.py
    report.py
    recommend.py
    screener.py
    watchlist.py
    system.py

frontend/
  vite.config.ts
  src/
    main.ts
    App.vue
    api/
      client.ts
      stocks.ts
      analysis.ts
      backtest.ts
      report.ts
      recommend.ts
      screener.ts
      watchlist.ts
      system.ts
    stores/
      app.ts
      technical.ts
      backtest.ts
      watchlist.ts
      report.ts
      recommend.ts
      screener.ts
      cache.ts
    router/
      index.ts
    utils/
      format.ts
    components/
      AppSidebar.vue
      MetricCard.vue
      SignalBadge.vue
      ColoredNumber.vue
      CandlestickChart.vue
      MacdChart.vue
      KdChart.vue
    views/
      TechnicalView.vue
      BacktestView.vue
      WatchlistView.vue
      RecommendView.vue
      ReportView.vue
      ScreenerView.vue
```
