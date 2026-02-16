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
│   ├── liquidity.py          # Liquidity Score (DTL + Spread + Tick Size) (R69)
│   └── market_regime.py      # Bull/Bear/Sideways detection
├── backtest/
│   ├── engine.py             # Backtest engine (v4/v5/bold/portfolio)
│   ├── risk_manager.py       # VaR + Sizing + Concentration + Circuit Breaker (R60/R80)
│   ├── sqs_backtest.py       # SQS effectiveness validation
│   └── bold_parameter_sweep.py  # Parameter sensitivity analysis (R67)
├── data/
│   ├── fetcher.py            # yfinance + FinMind + TWSE + Redis cache
│   ├── twse_provider.py      # TWSE/TPEX unified provider + SQLite
│   ├── sector_mapping.py     # 108 stocks → 14 L1 sectors (R82)
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
| R66-R68 | Bold strategy + Conviction 2.0 + Frontend UI | Done |
| R69 | Liquidity Score (DTL + Spread + ADV_Ratio + Tick Size) | Done |
| R72 | V4 Vol Guard + V5 Z-Score 動態進場 + 策略選擇器 | Done |
| R73 | Stock Split Detector + Dynamic Trail 實驗 (REJECTED) | Done |
| R74 | ATR-Adaptive Trail 實驗 + 成本壓力測試 | Done |
| R75 | Auto Trail Classifier (WFO-validated, ATR% 1.8% threshold) | Done |
| R76 | Regime Badge UI — 股票性格分類視覺化 | Done |
| R77 | Full SCAN_STOCKS 驗證 (108 stocks, 1.8% threshold) | Done |
| R78 | Mode Switching Frequency Analysis | Done |
| R79 | Hysteresis Buffer + BacktestView Mode 欄位 | Done |
| R80 | Risk-Adaptive Position Sizing (Equal Risk + 1-Lot Floor) | Done |
| R81 | Sizing Advisor UI — Traffic Light System | Done |
| R82 | Portfolio-Aware Sizing — 板塊集中度 + 零股模式 | Done |
| R82.2 | Concentration-Cap 取代 binary 0.6x (Protocol v2 首次交付) | Done |

### Auto Trail Classifier (R73-R79)

以 Walk-Forward Optimization 驗證的波動率自適應移動停利系統：

| 模式 | 條件 | Trail 策略 | 適用 |
|------|------|-----------|------|
| **Momentum Scalper** | ATR% ≥ 1.8% | Flat 2% trail | 高波動（小型電子、生技）|
| **Precision Trender** | ATR% < 1.8% | ATR k=1.0 trail | 低波動（金融、大型權值）|

- R77 全市場驗證：108 stocks，Momentum Scalper 佔 60%，Precision Trender 佔 40%
- R79 Hysteresis Buffer: 0.2% 緩衝避免邊界頻繁切換
- UI: Fire Red badge (Scalper) / Deep Blue badge (Trender) on TechnicalView

### Risk-Adaptive Position Sizing (R80-R82.2)

Equal Risk 倉位計算 + Portfolio-Aware 風險控制：

```
Position% = Max_Risk_Per_Trade / Stop_Loss% × Regime_Multiplier
Shares = floor(Position% × Equity / Entry_Price / 1000) × 1000
```

| 參數 | 值 | 標記 |
|------|-----|------|
| max_risk_per_trade | 3.0% | VALIDATED (Gemini CTO R80) |
| hard_stop_loss | 7.0% | VALIDATED (V4 default) |
| ATR% threshold | 1.8% | VALIDATED (R77 全市場) |
| sector penalty (old 0.6x) | **REMOVED** | [VERIFIED: HARMFUL] |
| Concentration-Cap T_cap | 1.0 (disabled) | [VERIFIED: 實測無益] |

**R82.2 實證** (102 stocks, 3040 trades, 3 年回測):
- Disabled (no penalty): Calmar **115.36** (最佳)
- Binary 0.6x: Calmar **94.63** (-18%, 有害)
- 14 L1 sectors 自然分散已足夠 (max ~21%)

Traffic Light System (UI):
- 🟢 GREEN: 標準倉位
- 🟡 YELLOW: 高集中度 / 1-Lot Floor 超出風險預算
- 🔴 RED: 資金不足（買不起 1 張）

### AI Multi-Agent Collaboration Protocol v2

三方協作模式，所有參數必須通過實證審查：

| 角色 | Agent | 職責 |
|------|-------|------|
| **Lead Developer** | Claude Code | 代碼實作、架構設計 |
| **Architect Critic** | Gemini Pro | 紅隊演習（性能、過擬合、邏輯漏洞）|
| **Execution Secretary** | Gemini Deep Think | 監控假精確、環境認知錯誤 |

**工作流**: Plan → Debate (≥2 反對意見) → Audit → Delivery

**參數標記制度**:
- `[VERIFIED]` — 有回測/sweep 數據支持
- `[HYPOTHESIS]` — 有邏輯推導但無數據驗證
- `[PLACEHOLDER_NEEDS_DATA]` — 等待實驗

### 待辦 (Backlog)

| 優先級 | 項目 | 說明 |
|--------|------|------|
| P1 | Sector Correlation Monitor | 監控板塊間相關性，> 0.85 時警報（Gemini 建議）|
| P1 | Risk Dashboard R_sector 可見度 | 顯示板塊集中度 > 30% 但不懲罰（Visibility without Interference）|
| P2 | Financials Strategy Gap | V4 不適用金融股，需探索替代策略 |
| P2 | ADV-Liquidity Cap | 倉位上限 = k_liq% × 20 日均量（防止流動性風險）|
| P3 | ATR/Price 分群自動調整 trail | Gemini HYPOTHESIS，需實驗 |
| P3 | Sector-Specific T_cap | 不同板塊不同上限（半導體 vs 金融 VaR 差異大）|

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
