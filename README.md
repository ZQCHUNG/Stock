# 台股技術分析系統

Vue 3 + FastAPI 全端台股技術分析與量化回測系統。支援所有上市（TWSE）與上櫃（TPEX）股票，共 2300+ 檔。

## 架構

```
Stock/
├── backend/                  # FastAPI (13 routers, Pydantic schemas)
│   ├── app.py                # Entry + CORS + static serve
│   ├── routers/              # stocks, analysis, backtest, report, recommend,
│   │                         # screener, watchlist, system, simulation,
│   │                         # fitness, alerts, forward_testing, risk
│   ├── schemas/              # Pydantic response models
│   └── dependencies.py       # DataFrame→JSON helpers
├── frontend/                 # Vue 3 + Vite + TypeScript + Naive UI
│   └── src/
│       ├── views/            # 11 page components
│       ├── components/       # ~30 reusable components
│       ├── stores/           # Pinia stores
│       ├── api/              # Axios service layer
│       └── router/           # Vue Router 4
├── analysis/                 # Technical analysis (UNTOUCHED by frontend migration)
│   ├── indicators.py         # MA/RSI/MACD/KD/BB/ADX/ATR/ROC
│   ├── strategy_v4.py        # V4 趨勢動量策略 (main)
│   ├── strategy_v5.py        # V5 均值回歸策略
│   ├── strategy_adaptive.py  # Adaptive 混合策略
│   ├── strategy_bold.py      # Bold 大膽策略 (R66)
│   ├── scoring.py            # SQS 信號品質評分 (8 dimensions)
│   ├── pattern_matcher.py    # DTW 相似線型比對 (R64)
│   ├── signal_tracker.py     # Forward testing (SQLite)
│   └── market_regime.py      # Bull/Bear/Sideways detection
├── backtest/
│   ├── engine.py             # Backtest engine (v4/v5/bold/portfolio)
│   ├── sqs_backtest.py       # SQS effectiveness validation
│   └── bold_parameter_sweep.py  # Parameter sensitivity analysis (R67)
├── data/
│   ├── fetcher.py            # yfinance + FinMind + TWSE + Redis cache
│   ├── twse_provider.py      # TWSE/TPEX unified provider + SQLite
│   └── stock_list.py         # 2300+ stock list (TWSE/TPEX API)
├── simulation/               # Trade simulation
├── tests/                    # 400+ tests (pytest, synthetic fixtures)
└── config.py                 # Strategy params, fee rates
```

**Tech Stack**: Vue 3 + Vite + TypeScript + Naive UI + vue-echarts + Pinia + Vue Router 4 + Axios | FastAPI + Pydantic | yfinance + FinMind + TWSE API | Redis caching

---

## 功能頁面 (11 Pages)

| 頁面 | 路由 | 說明 |
|------|------|------|
| **Dashboard** | `/` | 系統總覽、市場概況 |
| **技術分析** | `/technical` | K 線 + 6 大指標 + V4 買賣訊號 + SQS 雷達圖 |
| **自選股總覽** | `/watchlist` | 多股比較、批次回測、風險概覽 |
| **回測報告** | `/backtest` | 單股/投資組合/模擬/一致性/SQS 驗證 |
| **推薦股票** | `/recommend` | V4 掃描 + SQS 評分 + 批次加入自選 |
| **分析報告** | `/report` | 技術面 + 基本面 + 消息面三維度報告 |
| **條件選股** | `/screener` | 23 項條件篩選（類財報狗） |
| **模擬倉位** | `/simulation` | 策略模擬執行 + 績效追蹤 |
| **風險監控** | `/risk` | VaR + 集中度 + 回撤 + 熔斷 + 壓力測試 |
| **策略適配** | `/fitness` | SQS 分布 + Forward Test 追蹤 |
| **相似線型** | `/pattern` | DTW 比對 + 概率雲圖 + 勝率統計 |

---

## 策略版本

| 版本 | 方法 | 定位 |
|------|------|------|
| **V4** | 趨勢動量 + 移動停利 | 核心策略 (Core 80%) |
| **V5** | 均值回歸 + RSI 超賣 | 震盪市場備選 |
| **Adaptive** | V4+V5 市場 regime 自動切換 | 混合策略 |
| **Bold** | 能量擠壓突破 + 階梯式停利 | 衛星倉位 (Satellite 15-20%) |

### Bold 大膽策略 (R66-R67)

專為爆發性波段設計（如 6139 亞翔 +3141%、6442 光聖 +7185%）：

**進場**:
- A) Energy Squeeze Breakout: BB 擠壓釋放 + 量能暴增
- B) Oversold Bounce: RSI < 30 + 52 週低點 + 恐慌量
- C) Volume Ramp: 小型股發現（30 張門檻 + 量能爬坡 2x）

**出場 (Step-up Buffer)**:
- Level 1 (< 30% gain): trailing -15%
- Level 2 (30-50% gain): 鎖住成本 +10%
- Level 3 (> 50% gain): trailing -25%/-30%/-35%
- Ultra-Wide Conviction: MA200 上升時 -35% trail, gain > 100% + 200d 跳過 max_hold

---

## SQS 信號品質評分 (Signal Quality Score)

8 維度加權評分系統，為每個交易信號打分：

| 維度 | 權重 | 說明 |
|------|------|------|
| Institutional | 20% | 法人 5 日淨買超比 |
| Growth | 15% | 月營收 YoY 成長率 |
| Fitness | 15% | 參數適配度（敏感度分析） |
| Valuation | 10% | PE/PB/殖利率百分位 |
| Regime | 10% | 市場環境（Bull/Bear/Sideways） |
| EV | 10% | 淨期望值（扣除交易成本 0.785%） |
| Heat | 10% | 信號密度（過熱偵測） |
| Maturity | 10% | 歷史信號前瞻績效 |

等級: Diamond >= 80 | Gold >= 60 | Silver >= 40 | Noise < 40

---

## 資料來源

| 來源 | 用途 | 備援 |
|------|------|------|
| TWSE/TPEX API | 日K線、法人、PE/PB/殖利率、月營收 | yfinance |
| yfinance | 歷史股價（auto_adjust=True）、基本面 | FinMind |
| FinMind | 法人買賣超、除權息 | — |
| Google News RSS | 個股新聞（中文） | — |
| Redis | 快取層（TTL 5m~24h） | — |
| SQLite | TWSE 資料持久化 (`data/market_data.db`) | — |

---

## 安裝與執行

### 環境需求
- Python 3.10+
- Node.js 18+
- Docker（Redis 快取，可選）

### 安裝

```bash
git clone https://github.com/ZQCHUNG/Stock.git
cd Stock

# Python 依賴
pip install -r requirements.txt

# Frontend 依賴
cd frontend && npm install && cd ..
```

### 啟動（開發模式）

```bash
# Backend (port 8000)
uvicorn backend.app:app --reload --port 8000

# Frontend (port 5173, proxy → 8000)
cd frontend && npm run dev
```

### 啟動（Production）

```bash
cd frontend && npm run build && cd ..
uvicorn backend.app:app --port 8000
# FastAPI 自動 serve frontend/dist/
```

### Redis（可選）

```bash
docker run -d --name stock-redis -p 6379:6379 redis:7-alpine redis-server --appendonly yes
```

### 測試

```bash
python -m pytest tests/ -q
# 400+ tests, all synthetic fixtures, no network dependency
```

---

## 開發進度

### 已完成

| Round | 內容 | 狀態 |
|-------|------|------|
| R1-R40 | Vue 3 + FastAPI migration, 9 pages, V4/V5/Adaptive strategies | Done |
| R41-R44 | SQS 6-dim, Alert system, Forward testing | Done |
| R45-R50 | Scheduler, risk dashboard, SQS 8-dim, strategy center | Done |
| R51-R55 | Fugle WebSocket, PDF export, data quality, event system | Done |
| R56-R58 | Factor analysis, performance attribution, data consolidation | Done |
| R59-R61 | Forward testing automation, risk framework (VaR/DD/stress) | Done |
| R62 | SQS v2 (8 dimensions: Valuation + Growth) | Done |
| R63 | TWSE/TPEX data provider + SQLite + Shadow mode | Done |
| R64-R65 | DTW pattern matching + PatternView UI | Done |
| R66 | Bold strategy (Energy Squeeze + Step-up Buffer) | Done |
| R67 | Ultra-Wide → Conviction 2.0 (Regime-Based Trail) + Sweep | Done |
| R68 | Frontend Bold strategy toggle UI (回測+技術分析) | Done |

### R67 完成摘要

- [x] Bold 策略核心：能量擠壓突破 + 階梯式停利
- [x] Ultra-Wide Conviction 模式（MA200 斜率保護）
- [x] Volume Ramp 進場（小型股 30 張門檻）
- [x] API endpoints (backtest + analysis)
- [x] 27 unit tests passing
- [x] Gemini 討論：假精確 feedback + 實驗導向型對話協議
- [x] **Parameter Sweep 完成** — conviction_hold_gain × trail_level3_pct × ATR × SL
- [x] Sweep 結果分析 + robustness band + cross-stock overlap
- [x] 參數標記 VALIDATED/HYPOTHESIS/DEAD_PARAMETER
- [x] **Conviction 2.0**: 移除 DEAD `conviction_hold_gain`，改為 Regime-Based Trail

### Conviction 2.0 (Regime-Based Trail)

Sweep 證明 `conviction_hold_gain` 是 **DEAD PARAMETER**（Mechanism Pre-emption: trail stop 永遠先觸發）。
Gemini 提議 Conviction 2.0：基於 MA200 斜率的動態 trail 寬度。

**變更**:
- 移除: `conviction_hold_gain`, `conviction_hold_min_days`, `ma_slope_protection`, `trail_ultra_wide_pct`
- 新增: `regime_trail_enabled` (bool), `trail_regime_wide_pct` (0.20, VALIDATED)
- 邏輯: MA200 slope > 0 AND gain > 50% → trail 從 0.15 放寬至 0.20
- 簡化: max_hold_days 無 bypass（conviction_hold 已移除）

### Regime Trail Sweep 結果 (Conviction 2.0 驗證)

| Stock | regime=OFF | regime=0.15 | regime=0.20 | regime=0.25 | regime=0.35 |
|-------|-----------|-------------|-------------|-------------|-------------|
| 6748 | 11.6% | 11.6% | 11.6% | 11.6% | 11.6% |
| 6139 | 44.4% | 80.7% | **273.5%** | 273.5% | 273.5% |
| 6442 | **35.0%** | 35.0% | 32.3% | 29.5% | 23.9% |

**發現**:
- 6748: regime trail 無效果（Level 3 never reached）
- 6139: regime trail **至關重要**（OFF=44% vs ON=274%），0.20 是最低有效值
- 6442: regime trail **略微有害**（越寬越差），最佳=0.15（不放寬）
- **0.20 是折衷最優**：完整捕獲 6139 爆發，6442 僅損失 -2.7pp

### 參數驗證總結

| 參數 | 狀態 | 值 |
|------|------|-----|
| trail_level3_pct | VALIDATED(n=3, 2021-2026) | 0.15 optimal, 0.15-0.35 robust |
| regime_trail_enabled | VALIDATED(n=3) | 6139: 44%→274% 巨大提升 |
| trail_regime_wide_pct | VALIDATED(n=3, 2021-2026) | **0.20** optimal, 0.15-0.25 robust |
| conviction_hold_gain | DEAD_PARAMETER → **已移除** | Regime-Based Trail 取代 |
| ATR multiplier | NEEDS_MORE_DATA | 方向不一致 |
| stop_loss_pct | VALIDATED(n=3) | 15-18% sweet spot |
| Cross-stock overlap | ONE_SIZE_FITS_ALL | 80-100% overlap |

### 待辦

- ATR/Price 分群自動調整 trail（Gemini HYPOTHESIS）
- Liquidity Score calculation

---

## 假精確 Protocol (R67)

Joe 的核心要求：**先做實驗，再下結論。不要「先結論，再找數據支持」。**

所有策略參數必須標記：
- `VALIDATED(n=X, period=Y)` — 有 sweep 數據支持
- `HYPOTHESIS` — 有邏輯推導但無數據驗證
- `PLACEHOLDER_NEEDS_DATA` — 純猜測，等待實驗
- `DEAD_PARAMETER` — sweep 證明無效（如 conviction_hold_gain）

---

## 免責聲明

本系統僅供技術分析學習與參考，不構成任何投資建議。股票投資有風險，請自行評估並做出投資決策。
