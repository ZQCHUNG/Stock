# 台股技術分析系統

Vue 3 + FastAPI 全端台股技術分析與量化回測系統。支援所有上市（TWSE）與上櫃（TPEX）股票，共 2300+ 檔。

## 架構

```
Stock/
├── backend/                  # FastAPI (14 routers, Pydantic schemas)
│   ├── app.py                # Entry + CORS + static serve
│   ├── routers/              # stocks, analysis, backtest, report, recommend,
│   │                         # screener, watchlist, system, simulation,
│   │                         # fitness, alerts, forward_testing, risk, cluster
│   ├── schemas/              # Pydantic response models
│   └── dependencies.py       # DataFrame→JSON helpers
├── frontend/                 # Vue 3 + Vite + TypeScript + Naive UI
│   └── src/
│       ├── views/            # 14 page components
│       ├── components/       # ~30 reusable components
│       ├── stores/           # Pinia stores
│       ├── api/              # Axios service layer
│       └── router/           # Vue Router 4
├── analysis/                 # Technical analysis (UNTOUCHED by frontend migration)
│   ├── indicators.py         # MA/RSI/MACD/KD/BB/ADX/ATR/ROC
│   ├── strategy_v4.py        # V4 趨勢動量策略 (main)
│   ├── strategy_v5.py        # V5 均值回歸策略
│   ├── strategy_adaptive.py  # Adaptive 混合策略
│   ├── strategy_bold.py      # Bold 大膽策略 (R66, Phase 10 PIT RS)
│   ├── strategy_aggressive.py # Aggressive 真大膽 — WarriorExitEngine (R88)
│   ├── pit_rs.py              # Point-in-Time RS Engine (1939 stocks, 664 dates) (R93)
│   ├── scoring.py            # SQS 信號品質評分 (8 dimensions)
│   ├── rs_scanner.py         # Full-market RS Scanner (927 stocks) (R83)
│   ├── sector_rs.py          # Sector RS + Peer Alpha + Cluster Risk (R84)
│   ├── pattern_matcher.py    # DTW 相似線型比對 (R64)
│   ├── cluster_search.py     # Multi-Dim Similarity Search (R88)
│   ├── broker_features.py    # Daily Brokerage 14 Features (R88.7 P4)
│   ├── winner_registry.py    # Tiered Winner Registry (R88.7 P3-P4)
│   ├── signal_tracker.py     # Forward testing (SQLite)
│   ├── vcp_detector.py       # VCP Detection (Minervini-style) (R85)
│   ├── stop_loss.py          # ATR-Based Stop Calculator (R86)
│   ├── r_tracker.py          # R-Multiple Tracker (R86)
│   ├── portfolio_heat.py     # Correlation-Adjusted Heat Map (R86)
│   ├── sector_correlation.py # Sector Correlation Monitor (R87)
│   ├── liquidity.py          # Liquidity Score (DTL + Spread + Tick Size) (R69)
│   ├── market_regime.py      # Bull/Bear/Sideways detection
│   ├── accumulation_scanner.py # Wyckoff Accumulation Scanner — 洗盤偵測 (R95)
│   ├── financial_screener.py  # 財報狗-style Screener V2 — SQLite snapshot engine (Phase 1)
│   ├── pattern_simulator.py   # Pattern Simulator — multi-horizon win rates (Phase 2)
│   ├── auto_sim.py            # Auto-Sim Pipeline — screener→dual-sim→LINE (P2-B)
│   ├── signal_log.py          # Trade Signal Log — SQLite accountability (P3)
│   ├── drift_detector.py      # Drift Detection — In-Bounds Rate + Z-Score + Post-mortem (P3)
│   ├── failure_analyst.py     # Rule-based Failure Post-Mortem — 4 categories (Phase 6 P2)
│   ├── market_guard.py       # Market Regime Global Switch — 全局斷路器 (R89)
│   ├── pattern_labeler.py    # Phase 2: Historical Winner DNA 標記 (R90)
│   └── winner_dna.py         # Phase 3-5: UMAP + HDBSCAN + k-NN + DTW Matcher (R90)
├── backtest/
│   ├── engine.py             # Backtest engine (v4/v5/bold/aggressive/portfolio)
│   ├── portfolio_runner.py   # Portfolio Backtester — 108 stocks + 3-Layer Defense (R14.14-16)
│   ├── risk_manager.py       # VaR + Sizing + Concentration + Circuit Breaker (R60/R80)
│   ├── sqs_backtest.py       # SQS effectiveness validation
│   ├── accumulation_backtest.py # R95.2 Velocity Protocol: 20d Time-Stop + metadata ranking
│   ├── parameter_heatmap.py    # P2-A: 2D Parameter Sensitivity Heatmap (Phase 5)
│   └── bold_parameter_sweep.py  # Parameter sensitivity analysis (R67)
├── data/
│   ├── fetcher.py            # yfinance + FinMind + TWSE + Redis cache
│   ├── twse_provider.py      # TWSE/TPEX unified provider + SQLite
│   ├── fetch_google_news.py  # Google News RSS fetcher (6 TW finance sites) (R88.7P12)
│   ├── build_features.py     # 8 sources → 65 features Parquet (R88)
│   ├── sector_mapping.py     # 108 stocks → 14 L1 sectors (R82)
│   ├── daily_update.py       # Daily Pipeline V5: 9-step (close + sanitizer + RS + screener + fwd + realize + trailing stops + auto-sim + weekly audit)
│   └── stock_list.py         # 2300+ stock list (TWSE/TPEX API)
├── simulation/               # Trade simulation
├── tests/                    # 560+ tests (pytest, synthetic fixtures)
└── config.py                 # Strategy params, fee rates
```

**Tech Stack**: Vue 3 + Vite + TypeScript + Naive UI + vue-echarts + Pinia + Vue Router 4 + Axios | FastAPI + Pydantic | yfinance + FinMind + TWSE API | Redis caching

---

## 功能頁面 (14 Pages)

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
| **多維度分群** | `/cluster` | Dual Block + Dimension Lens + Gene Map + Spaghetti Chart |
| **Pattern 模擬** | `/pattern-simulator` | Spaghetti Chart + Confidence Scoring + 8-horizon win rates + similar cases |
| **策略控制塔** | `/control-tower` | Signal Log + Drift Detection + Risk Flag + Pipeline Monitor |

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
- Level 1 (< 30% gain): trailing -8% [VALIDATED R14.8]
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
# 470+ tests, all synthetic fixtures, no network dependency
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
| R83 | RS Rating System — 全市場相對強度掃描 (927 stocks) | Done |
| R84 | Sector RS + Peer Alpha + Cluster Risk (Gemini CTO Approved) | Done |
| R85 | VCP Detection — Minervini VCP + Ghost Day + Context Qualifier | Done |
| R86 | Risk Management — ATR Stop-Loss + R-Multiple + Portfolio Heat | Done |
| R87 | Sector Correlation Monitor — Cap-Weighted Matrix + Systemic Flush | Done |
| R88 | Multi-Dimensional Similarity Clustering (Gemini CTO Approved) | Done |
| R88.2 | Dual Block Redesign — Facts vs Opinion (Architect Critic Approved) | Done |
| R88.3 | Dimension Lens + Gene Map Attribution (Architect Critic Approved) | Done |
| R88.5 | Sniper Confidence Tiering — 6-year stress test validated (Wall Street Trader Approved) | Done |
| R88.6 | Brokerage Dimension Split — 分點面獨立第6維度 (Wall Street Trader Approved) | Done |
| R88.7 | Method C: Daily Brokerage Scraper + 14 Features (Wall Street Trader Approved) | Done |
| R88.7P3 | Winner Branch Registry — Bootstrap CI + Ghost Bias (Wall Street Trader Approved) | Done |
| R88.7P4 | Tiered Registry + broker_winner_momentum (14th feature) (Trader CONVERGED) | Done |
| R88.7P5 | Parquet Integration — 50→65 features, brokerage 4→14, attention 2→7 (Gene Map Ready) | Done |
| R88.7P6 | Trader Rulings: Warmup Mask + Cron 18:30 + Weekly Registry (Trader APPROVED) | Done |
| R88.7P7 | Trader Bulletproof: Canary Check + Atomic Swap + Rate Jitter + Gene Mutation Scanner (Trader APPROVED) | Done |
| R88.7P8 | Gene Mutation Scanner UI + Circuit Breaker + Atomic Swap Report (Trader APPROVED) | Done |
| R88.7P9 | Night Watchman Health Check + Mutation Tooltips (Trader APPROVED) | Done |
| R88.7P10 | Auto-Summary: Daily Report Generator + UI (Pipeline Health + Market Pulse + Narrative) | Done |
| R88.7P11 | Hot Sectors + Confidence Score + Activity Percentile (Architect Critic Approved) | Done |
| R88.7P11.5 | Cold Start Warming Up + Wall Street Narrative + H<0.4 Critical Warning | Done |
| R88.7P12 | Attention Dim 2→7 Features + Google News RSS + Daily Schedule 18:45 (Trader CONVERGED) | Done |
| R88.7P13 | Polarity Divergence Warning + Cross-Source Fuzzy Dedup (Trader R6 CONVERGED) | Done |
| R88.7P14 | Maiden Voyage: Toxic Volatility + Cold Start + Weekend Effect (Trader R7 CONVERGED) | Done |
| R88.8 | Aggressive Mode — WarriorExitEngine (ATR 3x Trail + Pyramiding + Regime Gate) | Done |
| R89 | Market Guard — 全局斷路器 (ADL + Breadth + Gap Detection) | Done |
| R90 | Pattern Recognition Phase 2-6 — Winner DNA Full Pipeline (Label → Cluster → Perf DB → Matcher → UI) | Done |
| R93 Phase 10 | **Point-in-Time RS Engine** — eliminates look-ahead bias (1939 stocks, 664 dates, WR 37%→46%) | Done |
| R93 Phase 11 | **VCP Hard Gate + RS ROC Gate + RS Drop Alert** — RS Decile validated (200 stocks, 928 trades) | Done |
| R14 Group 1-2 | **Parameter Sweep** — rs_hard=55, structural_stop=False, clc=3 VALIDATED (200 stocks, 32 combos) | Done |
| R14 Group 3-4 | **Parabolic Refactor + Exit Params** — tl1=0.08, pg=0.10 VALIDATED; Phase A ABORTED → Entry Audit | Done |
| R14.13 | **VCP Safety Valve + Dynamic PTS** — Entry quality audit complete; PF=4.67, WR=46.7%, 45 trades (CTO APPROVED) | Done |
| R14.14 | **Phase B: Portfolio Backtester** — 108 stocks, Vol-Adjusted Sizing, Config C APPROVED (CTO R14.14v2) | Done |
| R14.15-16 | **3-Layer Risk Defense** — Sector Cap + Corr Heat + Global Brake, Config B VALIDATED (Zero-cost Insurance) | Done |
| R14.17 | **Aggressive Mode Acid Test** — WarriorExitEngine KILLED (all 3 periods), Sniper B (1.5%/0.5%) VALIDATED | Done |
| R14.18 | **Final Production Baseline** — Sniper B + Config B + Bold Exits LOCKED (OOS Calmar 8.06) | Done |
| R14.18-8B | **Phase 8B: Sniper Scanner Dashboard** — POST /api/screener/bold-scan + SniperScannerTab.vue (CTO P0 priority) | Done |
| R14.18-8A | **Phase 8A: Portfolio Bold Visualization** — Equity curve + TAIEX benchmark + Drawdown + Monthly Heatmap + MDD info | Done |
| R14.18-8C | **Phase 8C: Trade Replay** — Click-to-zoom + markArea + rich tooltips on CandlestickChart (CTO enhancement) | Done |
| R14.18-9A | **Phase 9A: TransactionCostCalculator** — Broker discount + Kyle Lambda dynamic slippage + Asymmetric exit (1.5x panic) + Gross vs Net equity + CAR metric + Liquidity Stress Alert in Scanner (CTO 3 amendments) | Done |
| R14.18-10A | **Phase 10A: Rolling WFA + Drift Monitor** — 3-month rolling windows, per-window Calmar/Sharpe/Expectancy, IS/OOS Efficiency Ratio, Drift Monitor tab (CTO APPROVED) | Done |
| R14.18-10C | **Phase 10C: Attribution Analysis** — Per-trade forensic breakdown across WFA windows, exit reason evolution, sector/SQS/RS stats, TAIEX regime correlation (CTO directive) | Done |
| R14.18-10D | **Phase 10D: Breadth-based Dynamic Exposure** — MaxSlots_adj = MaxSlots × (Breadth/50%), [VERIFIED: HARMFUL] Calmar 5.10→3.60, disabled by default | Done |
| R14.18-11 | **Phase 11: Regime Barometer** — Hunting Index (Parabolic%/(PTS%+Disaster%)), regime classification (Flash Crash/Chop/Hot/Normal), Sector Alpha Drift, gauge+pie UI (CTO directive) | Done |
| R95 | **Accumulation Scanner** — Wyckoff 洗盤偵測 (5 conditions: Higher Lows + Volume Test + Post-test Confirm + Low ADX + RS Strength), 3-phase Alpha/Beta/Invalidated, 57 tests (Wall Street Trader + Architect APPROVED) | Done |
| R95.1 | **AQS (Accumulation Quality Score)** — Brokerage DNA integration (WM 40% + NBP 25% + BC 20% + ADR 15%), Phase downgrade BETA→ALPHA on low AQS, MAX_CONSOLIDATION 120→60d, 72 tests (Wall Street Trader + Architect APPROVED) | Done |
| R95.1 P0.2 | **Accumulation Backtest** — TTB (Time to Breakout) 4-condition validation, 5 Kill Switches (WR≥45%/PF≥1.5/TTB≤30d/D21>0/Alpha Decay), Busted 3-day Hysteresis, AQS Stratification, Year Stress Test, Consistency Guard, 31 tests (Wall Street Trader + Architect APPROVED) | Done |
| R95.2 | **Velocity Protocol** — 20d Time-Stop as ONLY hard gate (PF 0.90→3.28, WR 44.9%→71.2%), Spring/VCP/ATR as ranking metadata, TAIEX>MA200 macro filter [HYPOTHESIS], 50M TWD liquidity filter [HYPOTHESIS], 41 tests (Wall Street Trader R4 + Architect OFFICIALLY APPROVED) | Done |
| Phase 1 | **Financial Screener V2** — 財報狗-style instant screening (SQLite snapshot, 7 categories, 27 conditions, 6.8ms/query, 2361 stocks, range+ranking, V2 frontend w/ presets) (CTO/PM Gemini APPROVED) | Done |
| Phase 2 | **Pattern Simulator** — Multi-horizon win rate analysis (d3/d5/d7/d14/d21/d30/d90/d180), reuses find_similar_dual 65-feature engine, close matrix forward returns, new page "C Pattern 模擬" | Done |
| Phase 3 | **Daily Pattern Update Pipeline** — 20:15 cron: close matrix extend + RS recompute + screener refresh (66s/day vs 30min full rebuild), manual trigger API, status endpoint | Done |
| Phase 4 | **Spaghetti Chart + Confidence Scoring + Forward Returns Rollover** — P0: auto-backfill NaN forward returns (193K cells filled); P1: Spaghetti Chart (T+90 overlay, mean/median/worst/best paths, P25-P75 band); Confidence scoring (3-factor: sample+consistency+direction, 95% CI) (Gemini CTO roadmap P0-P4) | Done |
| Phase 5 | **P2-A: Parameter Sensitivity Heatmap** — Grid-search Bold Entry D params across 20-stock sample; 2 presets (Near-High×MA20 Slope, RSI×Volume); Zone classification (Plateau/Island/Desert); echarts heatmap + tooltip + summary stats; "策略中心 → 參數熱圖" tab (CTO directive: "Entry D 容錯空間") | Done |
| Phase 5 | **P2-B: Auto-Sim Pipeline** — Screener (RS>=80) → find_similar_dual → Industry diversify (max 2/sector) → Top 5 → LINE Notify (Score/CI/MeanPath/WorstCase/Advice); daily_update.py step 5/5; POST /api/system/auto-sim manual trigger | Done |
| Phase 5 | **P3: Signal Log + Drift Detection** — SQLite trade_signals_log (26 fields, auto-log on Auto-Sim); T+5/T+10/T+21 actual returns backfill; Drift Detector: In-Bounds Rate + Z-Score failure (3 consecutive worst-case breaches); Post-mortem analysis (tier/industry/direction bias); Risk circuit breaker (global_risk_on flag); Weekly Saturday 09:00 audit + LINE report; 6 API endpoints (CTO directive: "讓 AI 對自己發出的信號負責") | Done |
| Phase 5 | **P4: Strategy Control Tower + Weekly Sentinel + Scoring V2** — Frontend "策略控制塔" page (Signal History table with color-coded T+21 results, Drift Dashboard with In-Bounds/Z-Score/Risk Flag, audit actions); Weekly Parameter Scan (Sunday 22:00, Plateau ratio drift alert >15%); Market Context Factor (TAIEX<MA20 → Score -10, RS>90 bonus +5); sidebar menu D | Done |
| Phase 5 | **P5: Position Sizing V1 + Pipeline Monitor** — Risk-based position sizing: PositionSize = (Equity×2%) / (Entry - WorstCase), MAX 20% per stock, confidence-adjusted (HIGH=full, MEDIUM=70%, LOW=50%), TW lot rounding; LINE message includes "建議倉位: X% (Y 張)"; Pipeline Monitor: 9 data files freshness check (close/RS/screener/features/price/fwd/signal/drift/param), scheduler heartbeat, overall health (healthy/degraded/critical); Control Tower 3rd tab with file freshness table + color indicators | Done |
| Phase 6 | **P0: Trailing Stop Integration** — Wire R86 ATR-based 4-phase trailing stop to Signal Log active signals; daily_update.py Step 6/8; LINE Notify "🛡️ 移動止盈價" for active positions; Control Tower Stop column (color-coded phase: Init/Breakeven/ATR Trail/Tight); POST /system/trailing-stops/update endpoint (Architect approved: "[INTEGRATION] not new development") | Done |
| Phase 6 | **P1: Ask My System API** — GET /system/daily-summary: health status + active signals with stops + risk flag + pipeline freshness + latest 5 signals; structured JSON for Gemini Live integration (Architect: "[INFRA] 安全的唯讀 endpoint") | Done |
| Phase 6 | **P2: Rule-based Failure Attribution** — `analysis/failure_analyst.py`: 4-category post-mortem (EARNINGS/SYSTEMIC/NEWS/TECHNICAL); physical facts checker (TAIEX drop >2%, earnings T±2, news keywords); physical data always shown (Entry/Exit/ATR); Drift Detection tab shows failure cards; GET /system/failure-analysis endpoint; AI opinion reserved for P3 (default OFF) (Architect: "[DEFENSE] Rule-based 第一, AI 第二") | Done |
| Phase 7 | **P0: Energy Score** — Signal quality filter in auto_sim: TR>2.5×ATR20 "overheat" (Conf×0.8) + Vol<1.5×5d avg "weak breakout" (Conf×0.9); penalty factors stack; LINE "⚠️ 訊號品質警示 (過熱/量縮)" annotation; [HYPOTHESIS: SIGNAL_QUALITY_V1] (Architect OFFICIALLY APPROVED) | Done |
| Phase 7 | **P1: Scale-out +1R Notice** — target_1r = Entry + (Entry - Stop); scale_out_triggered boolean in signal_log; LINE Notify "💎 建議動作：利潤鎖定" when Price ≥ +1R; "利潤保護期" status; Control Tower +1R column (Architect: "[INCREMENTAL INTEGRATION]") | Done |
| Phase 7 | **P2: Missed Opportunities Log** — SQLite filtered_signals table (code/date/raw_score/final_score/filter_reason/tr_ratio/vol_ratio); auto-log when Energy Score penalizes; GET /system/missed-opportunities; Drift Detection tab table with color-coded TR/Vol ratios (Secretary: "子彈還是炸彈？") | Done |
| Phase 8 | **P0: Self-Healing Pipeline** — Outlier Sanitizer in daily_update Step 1.5: \|Change\|>15% + exclude ex-div/IPO → auto-retry yfinance 1x; healed/flagged events counter (JSON); Pipeline Monitor "Self-Healed Events" card; Pipeline V4→V5 (9-step); [HYPOTHESIS: ANOMALY_THRESHOLD=15%] (Architect OFFICIALLY APPROVED) | Done |
| Phase 8 | **P1: Sector RS Heatmap + Auto-Sim Bonus** — Reuse R84 sector_rs.py; Top 3 sectors → Confidence +5 in auto_sim Step 2.4; Control Tower 4th tab "Sector Rotation": RS bar chart (color-coded gradient) + Diamond Concentration grid; LINE "🔥 強勢產業加成" annotation; GET /system/sector-heatmap endpoint; [HYPOTHESIS: SECTOR_MOMENTUM_BONUS_V1] (Architect OFFICIALLY APPROVED) | Done |
| Phase 9 | **P0: History Success Rate Back-weighting** — Industry-level 90-day In-Bounds Rate in auto_sim Step 2.6; >70% → +3, <40% → -5 confidence; min 3 samples to prevent small-sample bias; LINE "產業勝率加成/警示" annotation; GET /system/industry-success-rates; [HYPOTHESIS: INDUSTRY_EXPERIENCE_WEIGHTS_V1] (Architect OFFICIALLY APPROVED) | Done |
| Phase 9 | **P1: War Room View (Virtual Portfolio)** — Assumes every recommendation followed with vol-adjusted position sizing; Cumulative equity curve + drawdown area chart (vue-echarts); Stats cards: Total Signals, System Win Rate, Virtual Expectancy, Max Drawdown; MDD >15% volatility warning; [VIRTUAL: ALL_SIGNALS_TRACKED]; GET /system/war-room; Control Tower 5th tab "War Room" (Architect OFFICIALLY APPROVED) | Done |
| Phase 10 | **P0: Flash Crash Stress Test** — analysis/stress_tester.py; 3-day consecutive limit-down (10%/day) + 5% slippage gap-down; stressed_equity + bust check (<50% initial); War Room "Stress Test Mode" toggle with per-position detail table; GET /system/stress-test; [HYPOTHESIS: STRESS_TEST_PARAMS_V1] (Architect OFFICIALLY APPROVED) | Done |
| Phase 10 | **P1: Aggressive Index (System Temperature Gauge)** — Market Context (30) + Sector RS (25) + In-Bounds Rate (25) + Signal Quality (20) → 0-100 score; <40 Defensive/blue, 40-70 Normal/green, >70 Aggressive/red; Control Tower header badge with tooltip breakdown; LINE header "🔥 今日市場熱度"; GET /system/aggressive-index; [HYPOTHESIS: AGGRESSIVE_INDEX_WEIGHTS_V1] (Architect OFFICIALLY APPROVED) | Done |
| Phase 11 | **P0: Emergency Kill Switch** — Red pulsing EMERGENCY STOP button on Control Tower header; Sets global_risk_on=False (LOCKDOWN), sends LINE emergency notification; Confirm dialog; Must manually re-enable to resume (Architect OFFICIALLY APPROVED) | Done |
| Phase 11 | **P1: Live Trade Sync + Performance Gap** — signal_log: is_live/actual_entry_price/live_date columns; POST /system/signal/{id}/confirm-live; Signal Log table: Live status (✓), Slippage % column (red=positive slip, green=negative), "Confirm Live" button for active non-live signals; Enables Joe to track real execution vs system price (Architect OFFICIALLY APPROVED) | Done |

### R14.18: Final Production Baseline (CTO LOCKED)

R14 參數清洗與系統強化 **階段圓滿結束**。最終生產基線：

| 模組 | 設定 | 核心參數 |
|------|------|---------|
| **Strategy Logic** | Bold + R14.13 Filter | (ATR<0.60 OR dry>=1) AND (ATR<0.85) |
| **Exit Engine** | TimidExitEngine | PTS 8d + trail_level1 0.08 + parabolic 0.10 |
| **Position Sizing** | Sniper B (1.5%) | 1.5% Standard / 0.5% Defensive |
| **Portfolio Defense** | Config B (VALIDATED) | L1 Sector Cap 30% / Corr Penalty 0.7 / Global Brake 0.75 |
| **Pyramiding** | KILLED R14.17.3 | OOS Calmar 8.06→7.46 (WORSE), MDD increased |

**最終成績單 (108 stocks, Sniper B):**

| Period | Return | MaxDD | Sharpe | Calmar | WR | Trades | PF |
|--------|--------|-------|--------|--------|-----|--------|-----|
| **OOS (2025-2026)** | **+34.89%** | **-3.97%** | **2.30** | **8.06** | **47%** | **89** | **3.95** |
| IS (2023-2024) | +26.23% | -9.14% | 1.25 | 1.42 | 39% | 197 | 1.60 |
| Stress (2022) | -5.72% | -6.36% | -2.25 | -0.92 | 29% | 52 | 0.18 |

**R14.17 Aggressive Mode Acid Test — KILLED:**
- WarriorExitEngine: 108 stocks, only 12% outperform Bold (IS), 11% (OOS), 5% (Stress)
- Root cause: TW market convexity = rotation speed, NOT holding time (wide stops waste energy)
- Sniper Mode replaces it: Bold exits + higher sizing = genuine convexity improvement
- Pyramiding (R14.17.3): KILLED — OOS Calmar dropped 8.06→7.46, MDD rose proportionally
- CTO: "TW fast-bull = chasing last leg. Phase 1 (sizing) wins over Phase 2 (pyramiding)."

### Phase 8B: Sniper Scanner Dashboard (CTO R14.18)

每日收盤後全市場掃描工具，整合到策略中心第 4 個 tab「狙擊名單」。

- **Backend**: `POST /api/screener/bold-scan` — 掃描 108 SCAN_STOCKS
- **Sniper Score** = RS_120D × 0.5 + SQS × 0.3 + RS_Mom × 0.2 (CTO 公式)
- **Filters**: Min RS (default 60), Min Volume (default 50 張), No Signal toggle
- **Frontend**: `SniperScannerTab.vue` — Stats cards + DataTable with RS/VCP/SQS/Sniper badges
- **Next**: Phase 8C (Trade Replay)

### Phase 8A: Portfolio Bold Visualization (CTO R14.18)

Portfolio-level 回測視覺化，整合到回測頁面「Portfolio Performance」tab。

- **Backend**: `POST /api/backtest/portfolio-bold` — 跑 PortfolioBacktester (108 stocks, R14.18 config)
- **Response**: equity curve + TAIEX benchmark + drawdown + holdings_count + monthly returns + MDD info
- **Equity Curve**: Strategy (green) vs TAIEX Benchmark (grey dashed), log scale toggle, dataZoom
- **Drawdown**: Underwater chart (red fill), MDD peak-to-trough pin marker
- **Monthly Heatmap**: Year × Month grid with yearly totals, red-green color scale
- **MDD Banner**: Peak/Trough/Recovery dates, drawdown days, total underwater days
- **Synced Tooltips**: Date + Strategy value + Benchmark value + Holdings count

### Phase 8C: Trade Replay (CTO R14.18)

BacktestBold 的 K 線交易複盤功能（增強模式，非獨立組件）。

- **Click-to-Zoom**: Trade table >> button → K-line auto-zooms to [entry-20d, exit+10d]
- **markArea**: Green (profit) / Red (loss) holding period overlay on candlestick
- **Rich Tooltips**: Entry = SQS + RS + entry_type; Exit = reason + return% + held days
- **Hold Days Column**: Added to trade table with color-coded return %
- **Phase 8 Complete**: Scanner (8B) + Visualization (8A) + Replay (8C) — full closed loop

### R14.15-16: 3-Layer Risk Defense (CTO VALIDATED — Config B Locked)

108 檔 Portfolio-level 風險防禦系統。三層防護：L1 Sector Cap + Correlation Heat Penalty + Global Brake。

**Config B (Production — CTO VALIDATED as "Zero-cost Insurance"):**
- Layer 1: L1 Sector Exposure Cap 30% + Soft Scaling 0.5^(n-1)
- Layer 2: 20D Rolling Corr > 0.7 → Rank Penalty ×0.8 (with Vol Filter 1.2×)
- Layer 3: Global Brake — >50% holdings pairwise corr > 0.75 → stop entries

**4-Way Comparison (R14.15 + R14.16 CTO Load Test):**

| Config | Period | Return | MaxDD | Sharpe | Calmar | Trades |
|--------|--------|--------|-------|--------|--------|--------|
| A: Baseline (no defense) | OOS | +14.48% | -2.95% | 2.04 | 4.53 | 83 |
| A: Baseline | Stress | -3.98% | -4.96% | -2.28 | -0.82 | 52 |
| **B: Config B (LOCKED)** | **OOS** | **+13.88%** | **-2.28%** | **2.09** | **5.61** | **83** |
| **B: Config B** | **Stress** | **-3.63%** | **-4.15%** | **-2.35** | **-0.90** | **50** |
| C: L2 20% + corr 0.55 | IS | +10.16% | -5.86% | 1.06 | 0.89 | 185 |
| D: L2 15% + corr 0.55 | IS | +10.16% | -5.86% | 1.06 | 0.89 | 185 |

**CTO Key Rulings:**
- Config B = "Zero-cost Insurance" — OOS Calmar 4.53→5.61, MaxDD -2.95%→-2.28%, return only -0.60%
- Config C/D REJECTED — corr 0.55 causes IS -2.69% damage (punishes normal market co-movement)
- L1/L2 Sector Caps never bind naturally (14 L1 sectors + avg 3.6 positions = auto-diversified)
- Defense is "air filter" — invisible normally, blocks extreme cluster crashes
- **Defense Phase COMPLETE** — CTO: "再刷 Defense 參數已無邊際效益"

### Phase B: Portfolio Backtester (R14.14, CTO R14.14v2 APPROVED)

108 檔 SCAN_STOCKS 全市場日頻投組回測。從 Equal Weight baseline 迭代到 CTO 核准的 Config C。

**Config C (Production Baseline — CTO APPROVED):**
- Sizing: Vol-Adjusted Fixed Risk — `Shares = (Equity × Risk%) / (Entry × Stop%)`
- Risk: 0.8% standard, 0.4% defensive (TAIEX < MA200)
- Lunger Filter: **DISABLED** — kills convexity (8% OOS collapse: +55%→+0.07%)
- Vol Breakout Gate: breakout volume > MA5 × 1.5 (anti-false breakout)
- TAIEX Guard: 3-tier (10/5/3 slots) based on MA200

**Config C 回測結果:**

| Period | Return | MaxDD | Sharpe | Calmar | WR | Trades | PF |
|--------|--------|-------|--------|--------|-----|--------|-----|
| **OOS (2025-2026)** | +19.24% | -8.02% | 1.51 | 2.21 | 48% | 85 | 2.33 |
| **IS (2023-2024)** | +35.98% | -8.56% | 1.40 | 2.04 | 37% | 171 | 2.14 |
| **Stress (2022)** | -3.84% | -4.37% | — | — | 31% | 51 | 0.59 |

**Key Findings:**
- 2022 Stress: -3.84% (target < -10%) ✅ — Vol-Adjusted Sizing 大幅壓縮損失 (from EW -21.87%)
- pts_abandon 8-13%: WR=0%, AvgRet=-8% — CTO accepted as "friction cost"
- Lunger Filter harmful: 殺死右尾報酬 (Config A OOS +12.75% vs Config C +19.24%)
- Vol Breakout Gate effective: reduces false breakout entries without killing convexity

**3-Way Comparison (A/B/C):**

| Config | OOS Return | OOS MaxDD | Stress Return | Stress MaxDD |
|--------|-----------|-----------|---------------|-------------|
| A: Lunger 15% | +12.75% | -5.10% | -3.29% | -3.84% |
| B: Dynamic Lunger | +16.67% | -5.76% | -3.29% | -3.84% |
| **C: No Lunger (APPROVED)** | **+19.24%** | **-8.02%** | **-3.84%** | **-4.37%** |

**CTO Next Directive**: Sector Concentration (sub-sector cap 20%) + Correlation Heat

### R14 Parameter Sweep — Bold PLACEHOLDER Cleanup (Gemini R14.1-R14.5)

39 個 PLACEHOLDER/HYPOTHESIS 參數系統性驗證。200 stocks stratified sampling, IS/OOS/Stress 三期驗證。

**Gemini R14 Protocol:**
- Anchored Sensitivity Analysis (2D/3D grid, not single sweep)
- Parameter Plateau (neighbors drop >15% = Sharp Peak → discard)
- Kill Switch: WR<20% OR ER<1.2 OR Outlier Sensitivity fail → ABORT
- Metric Top 3: Calmar (50%) + ES/CVaR (30%) + Expectancy (20%)

**Group 1 動態防禦組 (COMPLETE):**
- `rs_hard_exit=55` [VALIDATED] — plateau confirmed (8% drop < 15%), best IS+OOS
- `rs_soft_exit=75` [DEFERRED_TO_PORTFOLIO] — zero differentiation in single-stock
- `rs_no_pyramid=75` [DEFERRED_TO_PORTFOLIO] — same, needs portfolio-level test

**Group 2 壓力測試組 (COMPLETE):**
- `structural_stop=False` [VALIDATED] — True causes 18.9% early exits, CTO accepted data
- `consecutive_loss_cap=3` [VALIDATED] — plateau at 2-3, CTO predicted correctly
- `time_stop_extended_days` [NON-FUNCTIONAL] — PTS Case 4 logic contradiction masks parameter

**Key Findings:**
- Bold WR=26% is NORMAL for momentum breakout (convexity, not win rate)
- Single-stock Calmar 0.34 = Professional Grade; 0.8 target is portfolio-level
- Edge Ratio 1.72 > 1.2 = system has edge, outlier-robust (ExpEx2% > 0)

**Group 3 獲利保護組 (COMPLETE — Architecture Bugs Found):**
- `parabolic_gain_trigger` — ALL 12 combos identical (parabolic only checked inside Level 2+, making trigger useless)
- `momentum_lag_gain_threshold` [DELETED] — PTS Case 4 vol_shrinking contradiction = dead code
- **R14.8 Fix**: Parabolic Option C refactor — extracted as pre-Level "global monitor" (CTO APPROVED)

**Group 4 出場核心組 (COMPLETE — CTO R14.8 VALIDATED):**
- `trail_level1_pct=0.08` [VALIDATED] — plateau confirmed, best OOS robustness
- `parabolic_gain_trigger=0.10` [VALIDATED] — differentiation confirmed post-refactor
- 12 combos (4×3), IS Calmar 3.55-4.32, ALL OOS negative (-0.28 to -0.34)
- CTO REJECTED tl1=0.12 (Sharp Peak 17.9%), chose tl1=0.08 (most robust)

**Phase A ABORTED → Entry Quality Audit (R14.9-R14.13):**
- OOS Calmar negative across ALL param combos → structural Entry problem, not Exit
- CTO: "Exit 不能修復 Entry 的錯誤" — pivot to VCP Failure Mode Analysis
- **VCP OR→AND experiment (R14.11)**: 6 trades, 0 wins — Over-optimization trap (AND too aggressive)
- **Safety Valve (R14.12)**: ATR ceiling 0.75 — 33 trades, PF=1.99, but convexity killed (+24.6% vs +263%)
- **R14.13 FINAL (CTO APPROVED)**: `(ATR<0.60 OR dry>=1) AND (ATR<0.85)` + volume_ramp ATR<0.50 + PTS 8d
  - 45 trades, WR=46.7%, AvgRet=+4.21%, PF=4.67, Best=+51.4%
  - Key insight: PTS 8-day extension rescued "slow-heat" big winners (5d→8d for ATR≥0.60)
  - **Phase A COMPLETE** — CTO declared R14.13 as VALIDATED baseline

### Phase 11: VCP Hard Gate + RS ROC + RS Drop Alert (R93, Gemini R13 + Architect APPROVED)

RS Decile Analysis (200 stocks, 928 trades) 驗證：RS 價值在 Convexity（右尾報酬），非勝率。

**RS Decile 驗證結果：**
- Median Return Spearman rho=0.576, p=0.082 (borderline significant)
- Avg Win 單調遞增: RS 0-10 = +13.10% → RS 90-100 = +22.27%
- Expectancy: RS 90-100 = +4.19 vs RS 0-10 = +2.85 (47% higher)

**11A: VCP Hard Gate (Entry Quality) [UPDATED R14.13]**
- VCP filter: `(ATR < 0.60 OR vol_dryup >= 1) AND (ATR < 0.85)` — Safety Valve architecture
- Track A 需同時 RS>=80 AND VCP compressed
- VCP 未就緒 → 降級為 Track B (0.7x position)

**11B: RS ROC Acceleration Gate (Entry Timing)**
- 進場需 RS_ROC_20d > 0（RS 加速中）
- 阻擋減速動量進場（6442 RS 24 時 ROC=-0.12 被正確擋掉）

**11C: RS Drop Alert (Exit Defense)**
- 3 級防禦 + Hysteresis 連續 3 天（Architect mandate，anti-chatter）:
  - RS < 75: 停止加碼
  - RS < 70: Soft Exit（收緊至 swing low/10MA）
  - RS < 60: Hard Exit（無條件出場，清除殭屍持倉）

### Point-in-Time RS Engine (R93 Phase 10, Gemini R10-R12 APPROVED)

消除 RS 前瞻偏差的核心引擎。靜態 RS 用 2026 年數據回看 2024 年進場決定 = 作弊。

**驗證結果（24 檔，3 年回測）：**

| Config | Active | Trades | Invested% | Win Rate |
|--------|--------|--------|-----------|----------|
| Baseline (no RS) | 20 | 114 | +511.4% | 41% |
| Static RS (BIASED) | 15 | 68 | +421.5% | 37% |
| **PIT RS (CORRECT)** | **14** | **52** | **+207.9%** | **46%** |

- 6442 光聖 PIT RS=24 at 2024-01-26（靜態 98.6）→ PIT 正確擋掉 +97.1% trade
- 6139 亞翔 PIT RS=97-99 → PIT 正確放行（真正強勢股）
- `analysis/pit_rs.py`: yf.download() 批量下載，1943 stocks 63 秒
- 整合 strategy_bold.py (per-bar PIT RS) + backtest/engine.py (pass-through)
- float32 parquet cache: `data/pit_rs_matrix.parquet`, `pit_rs_percentile.parquet`
- Gemini R12: "我寧願要 200%/46% 的穩定系統，也不要 500%/41% 的雲霄飛車"

### RS Rating & Sector Context (R83-R84)

全市場相對強度排名 + 行業同儕比較系統：

**RS Rating (R83):**
- 927 檔全市場掃描，加權 RS: `(base_return)^0.6 × (recent_return)^0.4`
- 百分位排名 0-100，等級: Diamond ≥80 / Gold ≥60 / Silver ≥40 / Noise <40
- Entry D 過濾器: Bold 策略 momentum breakout 需 RS ≥ 80

**Sector RS & Peer Alpha (R84):**
- Sector RS: L1 行業中位數 (Median, 非 Mean — Gemini mandate)
- Peer Alpha = Stock RS / Sector RS → Leader(≥1.2) / Rider / Laggard(<0.8)
- Beta Trap 保護: Peer Alpha < 0.8 → Diamond 降級為 Gold
- Cluster Risk 三級警報: Normal / Caution(30%+0.6) / Danger(50%+0.75)
- Blind Spot Protocol: 820 未分類股票顯示灰色 "Sector Blind Spot" 徽章

| 指標 | 閾值 | 意義 |
|------|------|------|
| Peer Alpha ≥ 1.2 | Leader | 真正領先同業 |
| Peer Alpha 0.8-1.2 | Rider | 隨行業同步 |
| Peer Alpha < 0.8 | Laggard | 落後同業（Beta Trap）|
| Cluster Normal | <30% Diamond + <0.6 Heat | 正常 |
| Cluster Caution | 30-50% + 0.6-0.75 | 行業過熱中 |
| Cluster Danger | >50% + >0.75 | 拋物線風險 |

### Multi-Dimensional Similarity Clustering (R88-R88.3)

多維度相似股分群系統：60 特徵 × 1096 檔股票 × 6 年歷史，Cosine Similarity 找出最相似案例。

**Gemini CTO + Architect Critic 雙重審核通過。** Protocol v3 全流程交付。

**R88.2 Dual Block 設計 — Facts vs Opinion (Joe 核心要求)**:

| 區塊 | 用途 | 方法 |
|------|------|------|
| **區塊 1 原始數據** | 純事實，讓 Joe 自己判斷 | 用戶選擇維度，等權重，無環境過濾 |
| **區塊 2 系統分析** | AI 加工後的建議 | 動態特徵加權 + Regime 過濾 + Time Decay + Opinion |

兩區塊並列，Joe 可比較「原始事實」vs「系統觀點」來校準信任度。D21 勝率差異 >15% 時顯示 [DIVERGE] 警告。

**R88.3 Dimension Lens + Gene Map (Joe Feedback)**:

| 功能 | 說明 |
|------|------|
| **Dimension Lens** | Checkable Tags 選擇維度 (Block 1)，可任意組合 5 維度 |
| **Gene Map** | 每案例顯示 5 維度 cosine similarity 分解 + 色彩長條圖 |
| **Similarity Summary** | 模板文字: 主要驅動維度 + 背離維度 [HEURISTIC: SIMILARITY_DRIVER_V1] |
| **Dimension Island Guard** | 未選維度 < 40% 顯示 [!] 警告 (紅色粗體) |
| **Weight Transparency** | Block 2 顯示系統加權倍率 (e.g., 技術面 1.5x, 籌碼面 1.3x) |

**R88.5 Sniper Confidence Tiering (Wall Street Trader 壓力測試通過)**:

6 年跨環境壓力測試（2020-2025，55 檔股票，2970 筆記錄），從 PF 3.92（2024牛市膨脹）修正到跨環境實證。

| 參數 | 值 | 標記 |
|------|-----|------|
| Sniper Sim 門檻 | >= 88% | [CONVERGED] 從 90% 修正 |
| 基本面門檻 (Sniper) | >= 50% | [CONVERGED] |
| 基本面門檻 (Tactical) | >= 40% | [CONVERGED] 輕倉參與 |
| Spearman ρ (6 年跨環境) | 0.2553 | [VERIFIED] p < 0.000001 |
| PF (Sniper tier) | 1.65 | [VERIFIED] n=45 |
| 上線標籤 | [EXPERIMENTAL] | n < 50，待更多數據 |

三級信心分層:
- **Sniper** (金色): Sim >= 88% + Fund >= 50% — 高信心，歷史 PF 1.65
- **Tactical** (藍色): Fund >= 40% — 中等信心，建議輕倉
- **Avoid** (灰色): Fund < 40% — 低信心，建議觀望

2022 熊市零訊號 = 系統保護機制（特徵，非缺陷）。

**6 維度 × 60 特徵** (R88.7P5 升級):

| 維度 | 特徵數 | 涵蓋 |
|------|--------|------|
| 技術面 | 20 | MA/RSI/MACD/KD/BB/ATR/Vol/Trend/RS |
| 籌碼面 | 11 | 三大法人/融資融券/集保 |
| 分點面 | **14** | HHI/Top3集中/淨買超/Purity/外資/Overlap/波動/背離/Winner動能 (R88.7 升級完成) |
| 產業面 | 5 | Sector RS/Peer Alpha/產業鏈位置 |
| 基本面 | 8 | EPS/ROE/營收/PE/PB/營益率/負債比 |
| 關注度 | 2 | 新聞量指數/新聞爆發度 |

**收斂設計 (R88 → R88.2 → R88.3)**:
1. **Single-Point Cosine Similarity** [CONVERGED]: Z-scored 特徵向量直接比較（5min→6sec）
2. **Dynamic Feature Weighting** [CONVERGED]: ATR/Vol 1.5x, RSI/法人 1.3x (Block 2 only)
3. **Regime Filter** [CONVERGED]: Bull/Range/Bear (MA200), Block 2 同 regime 限定
4. **Time Decay** [CONVERGED]: 指數衰減, half-life 2 年 (Block 2 only)
5. **Spaghetti Chart** [CONVERGED]: 前瞻價格路徑圖 (中位數 + P25-P75 信心帶)
6. **Opinion Generator** [ARCHITECT]: regime-aware 文字建議 + [VERIFIED] 標籤
7. **交易成本扣除** [ARCHITECT]: 所有報酬扣 TRANSACTION_COST 0.785%
8. **Per-Dimension Breakdown** [ARCHITECT R88.3]: 5 維度各自 cosine similarity 分解
9. **Dimension Filter** [ARCHITECT R88.3]: Block 1 用戶控制維度，Block 2 系統控制

**R88.7 Daily Brokerage (Method C — Wall Street Trader APPROVED)**:

日頻分點爬蟲 + 14 特徵引擎。從月頻 4 特徵升級為日頻 14 特徵，完整整合進 Parquet。

| 類別 | 特徵 | 說明 |
|------|------|------|
| 集中度 | broker_hhi_daily | 前15大分點 HHI 指數 |
| 集中度 | broker_top3_pct | 前3名買超佔比 |
| 集中度 | broker_hhi_delta | 日間 HHI 變化 |
| 流量 | broker_net_buy_ratio | 前5名淨買超/總量 |
| 流量 | broker_spread | 淨買超/淨賣超分點數比 |
| 流量 | broker_net_momentum_5d | 5日淨買超滑動平均 |
| Smart Money | broker_purity_score | 集中度 × Winner Branch Overlap |
| Smart Money | broker_foreign_pct | 外資券商買超佔比 |
| Smart Money | branch_overlap_count | 同分點跨股買超數 |
| 波動性 | daily_net_buy_volatility | 20日淨買超波動率 |
| 波動性 | broker_turnover_chg | 日分點成交量變化率 |
| 持續性 | broker_consistency_streak | 連續淨買超天數 (signed) |
| 量價背離 | broker_price_divergence | (Close-VWAP)/ATR_14 |
| Winner動能 | broker_winner_momentum | Tier 1 鋼鐵核心分點出現次數 → 0/50/100 |

- 吞吐量: 10 workers → 1096 stocks in 52 秒 [VALIDATED]
- Timestamp 校驗: response.end_date == query_date [CONVERGED]
- 缺失降級: >50% NaN → 維度不計入, 25-50% → 50% discount [CONVERGED]
- 49 tests (features) + 35 tests (winner) 全通過

**Winner Branch Registry (R88.7 Phase 3-4)**:
- 109K 月頻分點檔案掃描 → 545K 買超實例 → 806 分點代碼
- Winner Score = Win Rate × (Avg D21 Profit / |Avg D21 Loss|)
- Bootstrap CI (1000 iterations, per-broker deterministic seed)
- **Tiered CI System** [CONVERGED — Trader 裁定]:
  - **Tier 1** (CI >= 1.0, Sniper Ready): 1 winner — 統一-南京 (Score 2.237)
  - **Tier 2** (CI >= 0.7, Observer): 15 winners — 含美商高盛×2, 臺銀-高雄
- Ghost Bias 偵測: 單一產業 > 50% 則標記打折 (跨 38 產業鏈 + 14 L1 行業)
- broker_winner_momentum: 只計 Tier 1 鋼鐵核心 → 0/50/100 [CONVERGED]
- 存檔: `data/pattern_data/winner_branches.json`

**Parquet Integration (R88.7 Phase 5)**:
- `build_features.py` 升級: 50→65 features, brokerage 4→14, attention 2→7
- 109K 月頻分點 + 66 日頻分點 → 14 特徵 → 前填(forward-fill)到日線
- 109,195 broker records → merged into 1,628,668 daily rows
- 306.7 MB features_all.parquet (1096 stocks, 2020-2026)
- Cluster search auto-adapts: 65 features, 6 dimensions, Gene Map ready

**Trader Rulings (R88.7 Phase 6)** [APPROVED — Wall Street Trader 2026-02-18]:
- **Warmup Mask**: 4 sparse features (branch_overlap, volatility, price_divergence, winner_momentum) → zero weight in cosine similarity. Frontend shows &#9203; "Data Accumulating" markers
- **Cron Schedule**: Daily broker fetch 18:30 → Google News RSS 18:45 → Parquet rebuild 19:00 (Mon-Fri)
- **Weekly Registry**: Winner Registry auto-recalculates Saturday 02:00. CI >= 1.0 threshold maintained — "寧可整天不開火，也不要打歪"

**Trader Bulletproof (R88.7 Phase 7)** [APPROVED — Wall Street Trader 2026-02-18]:
- **Canary Check**: Before full market fetch, test 2330 (TSMC) + 2317 (Hon Hai). If timestamps are stale → abort entire run, save API quota
- **Atomic Swap**: Write `features_all_temp.parquet` first, validate row count & file size within ±5% of previous, then `mv` to replace. Prevents mid-rebuild corruption
- **Rate Limit Jitter**: `random.uniform(0.1, 0.5)` between each request to avoid WAF detection on government APIs
- **Gene Mutation Scanner**: `scan_gene_mutations()` — Δ_div = Score_brokerage - Score_technical. >1.5σ = "匿蹤吸貨", <-1.5σ = "誘多派發". Weighted Z-score with warmup exclusion. API: GET `/api/cluster/mutations`

**Mutation Scanner UI + Circuit Breaker (R88.7 Phase 8-9)** [APPROVED — Wall Street Trader 2026-02-19]:
- **Circuit Breaker (Global Shift Check)**: >30% 股票同時 >2σ 突變 → 判定為資料異常，非 alpha。自動暫停 Atomic Swap
- **Mutation Scanner UI**: 掃描全市場 1096 檔 → Δ_div 分佈直方圖 + Top 20 突變股表格 + 5 統計卡
- **Mutation Tooltips**: 滑鼠懸停顯示「匿蹤吸貨：主力正在低位建倉」「誘多派發：主力正在倒貨」
- **Atomic Swap Report**: `swap_report.json` 記錄新舊檔案大小、Row 差異、穩定性追蹤
- **Night Watchman**: Post-swap 健康檢查 — 驗證最新日期 + 分點維度非零率 (brokerage_nonzero_rate > 1%)

**Auto-Summary (R88.7 Phase 10-11.5)** — 每日自動報告 v1.2:
- `generate_daily_summary()`: Scheduler 跑完後自動生成 JSON 摘要
- **Pipeline Health**: Swap 狀態 + Night Watchman 健康度 + Row Count Drift 偏差偵測
- **Market Pulse**: 突變統計 + 偏向分析 (出貨/吸貨/均衡) + Activity Percentile (20日歷史比較)
- **Hot Sectors**: 族群級資金流向聚合 — 使用 sector_mapping (108股) + industry chain (1965股) 雙層映射
- **Confidence Score**: `H × S` — Data Health(RowIntegrity+Watchman+BrokerActivity) × Signal Strength(Intensity+Conviction+Concentration)
- **Cold Start**: `warming_up` flag (history < 5 days), s1 defaults to 0.5, UI "Warming Up" badge
- **H < 0.4 Critical**: `data_health_critical` flag → frontend red alert overlay, blocks hasty decisions
- **Top Mutations**: Top 5 匿蹤吸貨 + Top 5 誘多派發，每檔標註產業別
- **Narrative v2**: Wall Street persona — [核心定調]+[族群熱點]+[個股異常]+[風險警示] 結構化模板
- API: `GET /api/cluster/daily-summary` (cached + `?regenerate=true`)
- Frontend: ClusterView 頁面頂部 — 信心分數 badge + 族群熱點 tags + 產業別標籤 + Warming Up + Critical Warning

**Attention Dimension Upgrade (R88.7 Phase 12)** [HYPOTHESIS — pending IC validation]:
- 從 2 → 7 個注意力特徵（60 → 65 total features）— Parquet rebuilt + verified
- `attention_index_7d` (量), `attention_spike` (量突變), `source_diversity` (廣度), `news_velocity` (加速度), `polarity_filter` (三態極性), `news_recency` (時效性), `co_occurrence_score` (共現頻率)
- NaN-aware: 無新聞股票 → NaN（不是 0），防止稀疏聚類扭曲
- Polarity Filter: 三態關鍵字分類 (Breaking/Growth=+1, Risk/Legal=-1, Neutral=0)
- Co-occurrence: asymmetric "大哥帶小弟" 設計 — co_articles/total 自然權重小型股
- Noise Filter: 過濾「盤後/摘要/名單/一覽/三大法人」等非事件源頭文章
- Google News RSS: 搜索 6 個台灣財經新聞網站，階層式覆蓋 (Top 500 優先)
- cnyes 覆蓋率: 284 → 448 stocks (+58%)，改用 API 原生 `stock` 欄位
- Daily Schedule: 18:30 broker → **18:45 news** → **20:00 parquet** (Mon-Fri) [Trader R6: 75-min buffer]
- First batch: 504 Google News files fetched (2026-02-19)
- IC 實驗: INCONCLUSIVE (僅 11 天數據)，需累積 30+ 天後驗證

**Polarity Divergence Warning (R88.7 Phase 13)** [CONVERGED — Trader R6]:
- Cross-source fuzzy dedup: title similarity >80% → count once (946 articles removed, SequenceMatcher)
- Polarity calibration: removed 調查/賣出/風險/cut (false positives), added 調查局/掏空/背信
- L1 Warning: polarity Z-score gap > 1.0 → "[POLARITY] 輿論環境差異較大"
- L2 Penalty: opposite polarity (query Z>1.0 vs cases Z<-1.0) → confidence downgrade + "x0.8" flag
  - [CONVERGED R7]: Raised from Z=0.5 to Z=1.0 — "Z=0.5 only top 30%, too much noise"
- Final distribution: 87% neutral, 10.2% positive, 2.0% negative — all genuine signals

**Maiden Voyage Prep (R88.7 Phase 14)** [CONVERGED — Trader R7]:
- Toxic Volatility scanner: `attention_spike > 2.0` AND `polarity_filter < -1.0` → `[CRITICAL_ALERTS]`
  - Forced to top of daily summary narrative — prevent buying into negative attention stocks
- Cold Start warning: tracks news accumulation days (X/30), shows "Data Accumulating" in summary
- Weekend Effect filter: Sat/Sun article dates shifted to next Monday before attention computation
- Daily Summary v1.3: Critical alerts prefix + cold start prefix + fallback NaN handling

**檔案**:
- `data/build_features.py` — 8 原始 JSON → 65 features Parquet (292.5 MB, 1096 stocks)
- `data/fetch_broker_daily.py` — R88.7 日頻分點爬蟲 (Fubon DJhtm, 10 workers)
- `data/fetch_google_news.py` — Google News RSS 爬蟲 (6 台灣財經網站, 階層覆蓋)
- `analysis/cluster_search.py` — Dual-Pipeline + Per-Dimension Similarity 引擎
- `analysis/broker_features.py` — R88.7 14 日頻分點特徵計算引擎
- `analysis/winner_registry.py` — R88.7 Tiered Winner Branch Registry
- `backend/routers/cluster.py` — 6 API endpoints (similar-dual, similar, dimensions, feature-status, mutations, daily-summary)
- `frontend/src/views/ClusterView.vue` — Dual Block + Gene Map + Dimension Lens UI

### Aggressive Mode — WarriorExitEngine (R88.8) [KILLED R14.17]

> **KILLED BY CTO R14.17 ACID TEST (2026-02-23)**
> Kill Switch TRIGGERED in ALL 3 periods (IS/OOS/Stress). Only 5-12% of stocks outperformed Bold.
> Root cause: TW market convexity = rotation speed, NOT holding time. Wide stops waste energy.
> **REPLACEMENT**: Sniper Mode (R14.17.2) — Bold exits + higher sizing (1.5% risk).

原設計（已停用）：

**Exit Hierarchy** (寬止損，坐穩大波段):
1. **Gap-Down Guard**: 開盤跳空低於 -20% → 立即出場
2. **Disaster Stop**: -20% hard limit
3. **ATR 3x Trailing**: peak - 3×ATR
4. **MA20 Slope Combo**: MA20 斜率轉負 + 股價 < 上週最低
5. **MA50 Death Cross**: 股價跌破 MA50
6. **Max Hold 60d**: 強制平倉

**41 tests** in `tests/test_strategy_aggressive.py` (preserved for regression)

### Market Guard — 全局斷路器 (R89)

市場環境全局開關，兩級曝險限制器：

| Level | 條件 | 曝險上限 | 意義 |
|-------|------|---------|------|
| **0 Normal** | 無觸發 | 100% | 正常交易 |
| **1 CAUTION** | ADL 連跌 ≥5 天 OR 市場寬度 <30% | 50% | 減半曝險 |
| **2 LOCKDOWN** | ADL 連跌 ≥10 天 AND 寬度 <20% AND 缺口 >-3% | 0% | 全面停止進場 |

- ADL (Advance-Decline Line): 上漲家數 - 下跌家數 累積
- Market Breadth: 收盤 > MA20 的股票比例
- Gap Detection: 指數開盤跳空幅度
- 所有閾值標記 `[HYPOTHESIS: MARKET_SENTIMENT_V1]` — 待實證
- 23 tests in `tests/test_market_guard.py`

### Pattern Recognition Phase 2-3 — Winner DNA (R90)

**Phase 2: Historical Winner DNA Labeling** (`analysis/pattern_labeler.py`)

從 6 年歷史中找出 Super Stock，標記起漲前的 DNA 特徵：

| 步驟 | 說明 | 標記 |
|------|------|------|
| 1. 掃描歷史價格 | 3mo >50% AND 1yr >100% | [HYPOTHESIS: SUPER_STOCK_TARGET] |
| 2. 定位 Epiphany Point | 起漲前 21 天（結構轉變點）| [HYPOTHESIS: EPIPHANY_LOOKBACK_21D] |
| 3. 提取 65 特徵 DNA | 從 features_all.parquet 快照 | [VERIFIED: GENE_MUTATION_SCANNER] |
| 4. 計算前瞻報酬 | 7d/21d/30d/60d/90d/180d/365d | — |
| 5. 建立失敗對照組 | Hot-but-Failed (量價有動靜但 d90<0) | — |
| 6. Super Stock Flag | Gene Mutation \|Δ_div\| > 2σ | — |

**Phase 3: UMAP + HDBSCAN Winner Clustering** (`analysis/winner_dna.py`)

將標記後的 Winner DNA 降維聚類，建立 DNA 圖書館：

| 步驟 | 說明 |
|------|------|
| 1. 降維 | UMAP/PCA: 65 features → 8 components |
| 2. 聚類 | HDBSCAN: 密度聚類，自動偵測群數 + 噪音過濾 |
| 3. 群落剖析 | 每群: Centroid + Top Features + Multi-horizon Stats |
| 4. 自動標籤 | MomentumBreak / VolumeExplosion / Cluster_X |
| 5. DNA 匹配 | Stage 1 Cosine: 新股 vs Cluster Centroids (>85%) |

**Phase 4: Pattern Performance DB** (`analysis/winner_dna.py` upgraded)

| 功能 | 說明 | 標記 |
|------|------|------|
| Recency Weighting | 指數衰減 w=2^(-ΔT/halflife)，近期樣本權重更高 | [PLACEHOLDER: RECENCY_HALFLIFE_2Y] |
| Confidence Level | n_samples < 30 → "speculative" (投機性匹配) | [HYPOTHESIS: MIN_SAMPLE_30] |
| Persist Library | winner_dna_library.json + reducer.pkl + scaler.pkl | — |
| Winner Ratio | 每群 winner 佔比統計 | — |

**Phase 5: Two-Stage Matcher** (`analysis/winner_dna.py` upgraded)

| 功能 | 說明 | 標記 |
|------|------|------|
| k-NN (k=5) | 取代靜態 centroid，找 5 個最像前輩 | Trader mandate |
| Multi-scale DTW | 60d 結構 + 20d 動能，兩者一致 → 信心加倍 | [PLACEHOLDER: MULTISCALE_BOOST] |
| Final Score | 0.7×cosine + 0.3×(1/(1+dtw)) | [PLACEHOLDER: STAGE2_WEIGHT_070_030] |
| Failed Pattern Warning | >60% k-NN 是 losers → 紅色警告 | — |
| Amber Warning | speculative + Failed Pattern → Diamond 降級 | Architect mandate |

- Wall Street Trader APPROVED: k-NN > centroid, 0.7/0.3 weight, multi-scale DTW
- Architect Critic OFFICIALLY APPROVED: 物理一致性 PASS + 參數實證 PASS + 財務安全 PASS
- 25 tests (labeler) + 48 tests (winner_dna) + 23 tests (market_guard) ALL PASSING
- API: `GET /{code}/winner-dna-match`, `GET /{code}/super-stock-flag`, `GET /pattern-library`

**Phase 6: Decision Assist UI** (`frontend/src/components/WinnerDnaCard.vue`)

| 功能 | 說明 | 來源 |
|------|------|------|
| Decision Header | Traffic Light: Red (Failed) / Gold (Super) / Green (Match) / Gray (No Match) | Trader Phase 6 |
| Final Score Gauge | 圓形進度條顯示 blended score (0-100%) | Trader mandate |
| Confidence Badge | Confident (gold) / Speculative (amber) — based on sample size | Architect mandate |
| Feature Attribution | Top 5 匹配特徵 Z-score 標籤 | Trader: "match reasons" |
| k-NN Neighbors Table | 5 個最相似前輩 + 30d 報酬 | Phase 5 data |
| Multi-scale DTW | 60d + 20d shape match badges + agreement indicator | Trader mandate |
| Failed Pattern Warning | Red banner when >60% k-NN are losers | Trader: "Failed Patterns Library" |
| Cluster Performance | Multi-horizon win rate + avg return cards | Phase 4 data |

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

### AI Multi-Agent Collaboration Protocol v3

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

---

## 🎯 Pattern Recognition 訓練計畫（進行中）

### 目標

訓練模型辨識**所有顯著價格波動的 pattern**，包含：
- **趨勢成長股**：漲 50%+ 並維持（如光聖、亞翔）
- **短線炒作股**：短時間漲 30%+，之後大回調 → 吃上漲波段，回調時賣出
- **回調/崩跌 pattern**：辨識主力出貨、即將大跌的訊號

分群所有 pattern 類型，儲存每個 pattern 在不同持有天數的**績效與勝率**。
當新線型出現時，比對 pattern 資料庫，依歷史勝率決定是否進場及持有策略。

### 資料蒐集清單

> Joe 提供一項就打 ✅，**全部到齊才開始動工**。

| # | 資料類型 | 來源 | 狀態 |
|---|---------|------|------|
| 1 | 三大法人每日買賣超 | TWSE T86 + TPEx API | ✅ |
| 2 | 融資融券歷史 | TWSE MI_MARGN + TPEx API | ✅ |
| 3 | 營收/EPS 月報歷史 | MOPS 靜態 HTML | ✅ |
| 4 | 產業分類對照表 | TWSE OpenAPI + ic.tpex.org.tw | ✅ |
| 5 | 集保戶數/股權分散表 | TDCC CSV + FinMind | ✅ |
| 6 | 分點分佈 (Broker Data) | Fubon DJhtm + TPEx 官方 | ✅ |
| 7 | 庫存循環 (替代B/B Ratio) | FinMind 季報(Inventories+COGS) | ✅ |
| 8 | 法說會/新聞語意資料 | cnyes API + FinMind | ✅ |

### 各資料源 API 端點 + 欄位 + 可衍生特徵

#### 1. 三大法人每日買賣超

| 項目 | 內容 |
|------|------|
| **TWSE 端點** | `https://www.twse.com.tw/rwd/zh/fund/T86?response=json&date=YYYYMMDD&selectType=ALL` |
| **TPEx 端點** | `https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php?l=zh-tw&o=json&d=YYY/MM/DD&se=EW&t=D` |
| **格式** | JSON，免費，無認證 |
| **歷史** | 2012+（我們用 2020+），TPEx 2018+ |
| **欄位 (19)** | 證券代號、外資買/賣/淨、外資自營商買/賣/淨、投信買/賣/淨、自營商(自行)買/賣/淨、自營商(避險)買/賣/淨、三大法人合計 |
| **可衍生特徵** | 法人連續買超天數、投信佔量比、三大方向一致性、法人買超轉折點 |

#### 2. 融資融券歷史

| 項目 | 內容 |
|------|------|
| **TWSE 端點** | `https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?response=json&date=YYYYMMDD&selectType=ALL` |
| **格式** | JSON，免費 |
| **欄位 (16)** | 融資：前日餘額/買進/賣出/現償/今日餘額/限額、融券：前日餘額/賣出/買進/現券償還/今日餘額/限額、資券互抵、註記 |
| **可衍生特徵** | 融資使用率(餘額/限額)、融資3日爆發率(>15%=炒作訊號)、券資比(>30%=軋空)、資券互抵→當沖比 |

#### 3. 營收/EPS 月報歷史

| 項目 | 內容 |
|------|------|
| **端點** | `https://mopsov.twse.com.tw/nas/t21/{sii\|otc}/t21sc03_{民國年}_{月}_0.html` |
| **格式** | HTML 表格（需 parse），sii=上市、otc=上櫃 |
| **欄位 (10)** | 公司代號、當月營收、上月營收、去年同月營收、MoM%、YoY%、當月累計、去年累計、累計增減% |
| **可衍生特徵** | YoY 連續成長月數(Earnings Acceleration)、營收創新高 flag、驚喜度(實際 vs 前3月均值)、累計趨勢斜率 |

#### 4. 產業分類對照表

| 項目 | 內容 |
|------|------|
| **TWSE 端點** | `https://openapi.twse.com.tw/v1/opendata/t187ap03_L` (JSON，全部上市公司) |
| **ic.tpex.org.tw** | `https://ic.tpex.org.tw/introduce.php?ic={CODE}` (47條產業鏈) |
| **47 鏈代碼** | 半導體 D000、PCB L000、被動元件 J000、AI 5300、金融 U000 等 |
| **層次結構** | 每條鏈分上游(原料) → 中游(製造) → 下游(應用)，含子分類 |
| **TWSE 欄位** | 公司代號、產業別代碼(01=水泥,02=食品,06=電子...)、已發行股數 |
| **ic.tpex 額外** | 公司基本頁有現金流量表、資產負債表、損益表、每股淨值、會計師意見 |
| **可衍生特徵** | 供應鏈位置(類別特徵)、鏈內同方向比例、產業傳導 lag、產業熱度 |

#### 5. 集保戶數/股權分散表

| 項目 | 內容 |
|------|------|
| **即時端點** | `https://opendata.tdcc.com.tw/getOD.ashx?id=1-5` (CSV, 2.2MB, 週頻) |
| **歷史** | 即時只有最近1年 → FinMind `TaiwanShareHolding` 補 2020-2025 |
| **涵蓋** | 3924 檔（上市+上櫃+興櫃） |
| **欄位** | 資料日期、證券代號、持股分級(1-15)、人數、股數、占集保庫存數比例% |
| **15 級距** | 1-999股 / 1K-5K / 5K-10K / ... / 400K-600K / 600K-800K / 800K-1M / 1M以上 |
| **可衍生特徵** | 大戶(>400張)持股週變化→籌碼集中度、散戶追高指標(<1000股人數增)、Gini 係數、大戶連增週數 |

#### 6. 分點分佈 (Broker Data)

| 項目 | 內容 |
|------|------|
| **Fubon (主力)** | `https://fubon-ebrokerdj.fbs.com.tw/z/zg/zgb/zgb_.djhtm?a={stock}&b={broker}` |
| **TPEx 官方 (補充)** | `https://www.tpex.org.tw/zh-tw/mainboard/trading/info/brokerBS.html` (有CSV下載) |
| **查詢方向** | 股票→券商級(`?a={stock}`)、股票→分點級(`?a={stock}&b={broker}`)、分點→股票(`zgb0?a={broker}&b={branch}`) |
| **格式** | HTML 爬蟲 (Big5)，免費不需登入，TPEx 需 Cloudflare session |
| **欄位** | 分點名稱(如「元大-永和」)、買進成交數、賣出成交數、淨買賣超 |
| **可衍生特徵** | 主力集中度(Top3淨買超/總量)、神秘分點連買天數、集中→分散=出貨訊號、同分點跨股票行為 |

#### 7. 庫存循環（季報推算，替代 B/B Ratio）

| 項目 | 內容 |
|------|------|
| **FinMind 端點** | `dataset=TaiwanStockBalanceSheet` (Inventories) + `TaiwanStockFinancialStatements` (CostOfGoodsSold) |
| **格式** | JSON，免費，季頻（每季末：3/31, 6/30, 9/30, 12/31） |
| **欄位** | Inventories(存貨金額)、Inventories_per(存貨佔比%)、CostOfGoodsSold(營業成本)、Revenue、GrossProfit、EPS 等 101+17 欄位 |
| **庫存週轉天數** | = Inventories ÷ (CostOfGoodsSold ÷ 90) |
| **可衍生特徵** | 庫存週轉天數趨勢(↑=庫存堆積)、存貨佔比變化、庫存循環4階段判定(營收YoY×存貨QoQ象限)、毛利率變化 |
| **原 B/B Ratio** | SEMI 月報付費，改用個股財報免費替代，覆蓋所有產業(非僅電子) |

#### 8. 法說會/新聞語意資料

| 項目 | 內容 |
|------|------|
| **cnyes 端點** | `https://api.cnyes.com/media/api/v1/newslist/category/tw_stock?limit=30&page=1` |
| **FinMind 端點** | `dataset=TaiwanStockNews&data_id={code}&start_date=2020-04-01` |
| **格式** | JSON，免費，無認證，cnyes 有分頁(132頁+) |
| **cnyes 欄位** | newsId、title、summary、**content(完整文章)**、publishAt、**stock[]**(關聯股票代號)、**keyword[]**(主題標籤)、market[] |
| **FinMind 欄位** | date、stock_id、title、description、link、source |
| **法說會** | MOPS `ajax_t100sb02_q1`(需爬蟲) + IR Engage 行事曆(300+場，需爬蟲) |
| **可衍生特徵** | NLP 情緒分數、新聞量爆發度、關鍵字共現矩陣、新聞-股價 lead/lag、付費牆比例(重要性代理) |

### 儲存架構（Gemini CTO 建議，Joe 核准）

```
Google Drive / Colab Pro+
├── raw/                     # Raw Layer — 原始下載檔案（JSON/HTML/CSV）
│   ├── institutional/       # 三大法人 (按日期: 20200102.json ...)
│   ├── margin/              # 融資融券
│   ├── revenue/             # 月營收
│   ├── tdcc/                # 集保戶數
│   ├── broker/              # 分點分佈
│   ├── financials/          # 季報（存貨/損益）
│   ├── news/                # 新聞語意
│   └── industry/            # 產業分類
├── features/                # Feature Layer — 清理+對齊後的 Parquet 檔
│   ├── daily_features_{year}.parquet    # 日頻特徵（法人/融資/分點）
│   ├── weekly_features_{year}.parquet   # 週頻特徵（集保戶數）
│   ├── monthly_features_{year}.parquet  # 月頻特徵（營收）
│   └── quarterly_features_{year}.parquet # 季頻特徵（庫存循環）
└── metadata.db              # SQLite — 抓取狀態/斷點/版本紀錄
```

- **格式**：Parquet（列式存儲，壓縮率高，讀取快）
- **歷史資料拉一次就存**，不重複拉
- **每天自動增量更新**當日最新資料
- **metadata.db** 紀錄每個資料源最後抓取日期，增量更新從斷點續抓

### 訓練階段（Gemini CTO 建議，先做再驗證）

```
Phase 1: 資料蒐集 + 儲存 (8/8 已驗證，R88.2 Dual Block 引擎已完成) ✅
Phase 2: 標記歷史案例 — Winner DNA Labeling (R90) ✅
         → 3mo >50% AND 1yr >100% = Super Stock
         → Epiphany Point (起漲前 21 天) + 65 特徵 DNA 快照
         → 失敗對照組: Hot-but-Failed (ma20_ratio>0.5 + vol_ratio>0.5 + d90<0)
         → Super Stock Flag: Gene Mutation |Δ_div| > 2σ
Phase 3: Pattern 分群 — UMAP + HDBSCAN Winner Clustering (R90) ✅
         → UMAP/PCA 降維 (65→8 components)
         → HDBSCAN 密度聚類 → 5-8 Winner DNA 群落
         → 每群: Centroid + Top Features + Multi-horizon 勝率/Expectancy/PF
         → Auto-Label: MomentumBreak / VolumeExplosion / Cluster_X
Phase 4: 建立 Pattern 績效資料庫 (R90) ✅
         → Recency-weighted performance (half-life 2yr)
         → Confidence levels: Confident (≥30 samples) / Speculative (<30)
         → Winner ratio per cluster + regime distribution
Phase 5: 即時比對引擎 — k-NN + Multi-scale DTW (R90) ✅
         → Stage 1: k-NN (k=5) in reduced space (Trader: replace centroid)
         → Stage 2: Multi-scale DTW (60d structure + 20d momentum)
         → Final Score: 0.7×cosine + 0.3×(1/(1+dtw))
         → Failed Pattern Warning: >60% k-NN losers → red alert
Phase 6: 決策輔助 UI — WinnerDnaCard (R90) ✅
         → Traffic Light Decision Header + Final Score Gauge
         → Feature Attribution + k-NN Table + DTW Badges
         → Integrated into TechnicalView
```

### 訓練資料優先級（分批餵入，不一次全上）

| Phase | 資料 | 目的 |
|-------|------|------|
| **Phase 1 (MVP)** | yfinance 價量 + 三大法人 + 融資融券 + RS Rating | 辨識 VCP 與趨勢成長股 |
| **Phase 2** | + 分點分佈 + 集保週統計 | 辨識短線炒作 + 出貨 pattern |
| **Phase 3** | + 月營收 + 新聞語意 + 庫存循環 + 產業分類 | 過濾無基本面的純投機標的 |

### ML 架構（Gemini CTO 建議）

| 模型 | 處理維度 | 用途 |
|------|---------|------|
| **CNN** | 技術面 (K線圖→圖片/矩陣) | VCP、杯柄型態等視覺特徵辨識 |
| **XGBoost / LightGBM** | 結構化數據 | 籌碼集中度、營收成長率、毛利變動 |
| **Temporal Fusion Transformer** | 時間序列 | 長短期記憶交織，學習跨月因果關係 |
| **HDBSCAN** | Pattern 分群 | 自動偵測群數 + 噪音過濾（Gemini 建議取代 K-Means）|

### Gemini CTO 提出的待驗證風險（先訓練，不準確再補資料）

| 風險 | Gemini 觀點 | Joe 回應 | 狀態 |
|------|------------|---------|------|
| 缺美股/匯率宏觀因子 | 台股與費半連動高，缺此會漏系統性風險 | 飆股面前未必受美股影響，**先訓練再驗證** | ⏳ 待驗證 |
| 缺盤中 Tick data | 短線炒作轉折在盤中，日頻不夠 | 先用日頻做波段，不夠再補 | ⏳ 待驗證 |
| 季報庫存嚴重滯後 | 股價已跌3個月才看到存貨上升 | 用月營收YoY+法人買超當領先代理，季報當長線濾網 | ✅ 已有替代 |
| Fubon 爬蟲脆弱 | 改版就斷，建議付費 API | **先爬了再說，壞了再處理，不要沒事就想付費** | 🔨 先做 |
| 生存者偏差 | 2020-2021 多頭+2022 回檔，模型可能偏樂觀 | 確保包含失敗案例 | ⚠️ 注意 |
| Look-ahead Bias | 分點/集保公告時間不同，需 Shift(1) | 訓練時嚴格執行 | ⚠️ 注意 |

---

### 待辦 (Backlog — 暫停中)

> ⚠️ 以下功能開發暫停，等 Pattern Recognition 資料到齊後再決定優先順序。

| 優先級 | 項目 | 說明 |
|--------|------|------|
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
