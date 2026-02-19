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
│       ├── views/            # 12 page components
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

## 功能頁面 (12 Pages)

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
| R88.7P5 | Parquet Integration — 50→60 features, brokerage 4→14 (Gene Map Ready) | Done |
| R88.7P6 | Trader Rulings: Warmup Mask + Cron 18:30 + Weekly Registry (Trader APPROVED) | Done |
| R88.7P7 | Trader Bulletproof: Canary Check + Atomic Swap + Rate Jitter + Gene Mutation Scanner (Trader APPROVED) | Done |
| R88.7P8 | Gene Mutation Scanner UI + Circuit Breaker + Atomic Swap Report (Trader APPROVED) | Done |
| R88.7P9 | Night Watchman Health Check + Mutation Tooltips (Trader APPROVED) | Done |
| R88.7P10 | Auto-Summary: Daily Report Generator + UI (Pipeline Health + Market Pulse + Narrative) | Done |
| R88.7P11 | Hot Sectors + Confidence Score + Activity Percentile (Architect Critic Approved) | Done |

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
- `build_features.py` 升級: 50→60 features, brokerage 4→14
- 109K 月頻分點 + 66 日頻分點 → 14 特徵 → 前填(forward-fill)到日線
- 109,195 broker records → merged into 1,628,668 daily rows
- 292.5 MB features_all.parquet (1096 stocks, 2020-2026)
- Cluster search auto-adapts: 60 features, 6 dimensions, Gene Map ready

**Trader Rulings (R88.7 Phase 6)** [APPROVED — Wall Street Trader 2026-02-18]:
- **Warmup Mask**: 4 sparse features (branch_overlap, volatility, price_divergence, winner_momentum) → zero weight in cosine similarity. Frontend shows &#9203; "Data Accumulating" markers
- **Cron Schedule**: Daily broker fetch at 18:30, Parquet rebuild at 19:00 (Mon-Fri)
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

**Auto-Summary (R88.7 Phase 10-11)** — 每日自動報告 v1.1:
- `generate_daily_summary()`: Scheduler 跑完後自動生成 JSON 摘要
- **Pipeline Health**: Swap 狀態 + Night Watchman 健康度 + Row Count Drift 偏差偵測
- **Market Pulse**: 突變統計 + 偏向分析 (出貨/吸貨/均衡) + Activity Percentile (20日歷史比較)
- **Hot Sectors**: 族群級資金流向聚合 — 使用 sector_mapping (108股) + industry chain (1965股) 雙層映射
- **Confidence Score**: `H × S` — Data Health(RowIntegrity+Watchman+BrokerActivity) × Signal Strength(Intensity+Conviction+Concentration)
- **Top Mutations**: Top 5 匿蹤吸貨 + Top 5 誘多派發，每檔標註產業別
- **Narrative**: 自動生成中文摘要 + 族群集體吸貨/出貨警示 + 活躍度標籤
- API: `GET /api/cluster/daily-summary` (cached + `?regenerate=true`)
- Frontend: ClusterView 頁面頂部 — 信心分數 badge + 族群熱點 tags + 產業別標籤

**檔案**:
- `data/build_features.py` — 8 原始 JSON → 60 features Parquet (292.5 MB, 1096 stocks)
- `data/fetch_broker_daily.py` — R88.7 日頻分點爬蟲 (Fubon DJhtm, 10 workers)
- `analysis/cluster_search.py` — Dual-Pipeline + Per-Dimension Similarity 引擎
- `analysis/broker_features.py` — R88.7 14 日頻分點特徵計算引擎
- `analysis/winner_registry.py` — R88.7 Tiered Winner Branch Registry
- `backend/routers/cluster.py` — 6 API endpoints (similar-dual, similar, dimensions, feature-status, mutations, daily-summary)
- `frontend/src/views/ClusterView.vue` — Dual Block + Gene Map + Dimension Lens UI

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
Phase 1: 資料蒐集 + 儲存 (8/8 已驗證，R88.2 Dual Block 引擎已完成)
Phase 2: 標記歷史案例（漲50%+/30%+的股票，標記起漲點 + 失敗對照組）
Phase 3: Pattern 分群（技術面/基本面/籌碼面 聯合特徵）
Phase 4: 建立 Pattern 績效資料庫
         → 每個 pattern × 持有天數（7d/21d/30d/90d/180d/365d）→ 勝率 + 平均報酬 + Expectancy
Phase 5: 即時比對引擎（新線型出現 → 匹配 pattern → 顯示歷史勝率）
Phase 6: 決策輔助 UI（勝率 > 門檻 → 建議進場）
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
