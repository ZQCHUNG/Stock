# 台股技術分析系統

基於多重技術指標的台股分析與回測系統，提供 Web 介面進行技術分析、歷史回測、模擬交易、股票推薦、分析報告與條件選股。

支援所有上市（TWSE）與上櫃（TPEX）股票，共 2300+ 隻。

## 功能總覽

| 頁面 | 說明 |
|------|------|
| **技術分析** | K 線圖 + 6 大技術指標 + 買賣訊號 |
| **回測報告** | 歷史績效驗證（v2 評分 / v4 趨勢動量） |
| **模擬交易** | 近 N 日策略模擬執行 |
| **推薦股票** | 自動掃描 25 檔 → Top 3 推薦 |
| **分析報告** | 三維度分析（技術面 + 基本面 + 消息面） |
| **條件選股** | 23 項基本面 / 技術面篩選（類似財報狗） |

---

## 1. 技術分析

- K 線圖搭配移動平均線（MA5 / MA20 / MA60）
- MACD（12/26/9）
- KD 隨機指標（9 日）
- RSI 相對強弱指標（14 日）
- 布林通道（20 日，2 倍標準差）
- ADX / +DI / -DI 趨勢指標（14 日）
- 成交量分析（均量、量能比）
- 綜合評分系統自動產生買入 / 賣出 / 持有訊號
- **訊號原因說明**：詳列各指標偏多/偏空/中性因素

## 2. 回測報告

- 自訂回測期間（90～730 天）
- 台股手續費 0.1425% + 交易稅 0.3%
- 績效指標：總報酬率、年化報酬率、最大回撤、Sharpe Ratio、勝率、盈虧比
- 權益曲線與每日報酬分布圖
- 完整交易紀錄
- **雙策略版本**：v2（評分系統）/ v4（趨勢動量，推薦）

## 3. 模擬交易

- 模擬最近 N 個交易日的策略執行結果（預設 30 天）
- 每日追蹤持倉、現金、總權益變化
- 每日損益圖表
- 交易明細與模擬紀錄表

## 4. 推薦股票

- 從股票池掃描 25+ 隻熱門股
- 依技術面綜合評分排序，推薦 Top 3
- 每隻附完整推薦原因與各指標評分
- 全部股票排行表

## 5. 分析報告

三維度深度分析，輸出專業報告：

| 維度 | 內容 |
|------|------|
| 技術面 | 趨勢、動量、支撐壓力、訊號強度 |
| 基本面 | PE/PB/ROE/殖利率/營收成長、產業別評分（生技/金融/傳產特殊規則） |
| 消息面 | Google News + yfinance 新聞情緒分析 |

- 法人目標價整合（過濾低可信度：分析師 >= 2 人且偏離 < 200%）
- 綜合評等：強力買進 / 買進 / 中性 / 賣出 / 強力賣出

## 6. 條件選股

類似財報狗的基本面 / 技術面條件篩選，共 **23 項條件、7 大分類**：

| 分類 | 條件 |
|------|------|
| **獲利能力** (6) | ROE、ROA、毛利率、營業利益率、淨利率、EPS |
| **成長力** (2) | 營收成長率、獲利成長率 |
| **安全性** (2) | 負債權益比、流動比率 |
| **價值評估** (4) | 本益比 (TTM)、Forward PE、淨值比、殖利率 |
| **現金流 & 規模** (4) | 自由現金流 > 0、營業現金流 > 0、市值、Beta |
| **技術面** (2) | RSI 區間、ADX |
| **結果表新增** | Forward PE、ROA、EPS、Beta、市值(億)、FCF(億)、OCF(億)、目標價 |

- 掃描範圍：精選 25 檔（~30 秒）或全部 2300+ 檔
- 結果表 24 欄，可排序、可匯出 CSV
- Redis 快取 30 分鐘（相同條件組合）

### 架構說明

條件選股使用 **subprocess + ThreadPoolExecutor** 架構：

```
app.py (Streamlit) → subprocess → screener_worker.py (獨立進程)
                                    ├── populate_ticker_cache() (預填上市/上櫃 suffix)
                                    ├── ThreadPoolExecutor(5) (並行抓取)
                                    └── get_stock_fundamentals_safe() per stock
```

為什麼不直接在 Streamlit 中用 ThreadPoolExecutor？因為 **Streamlit 的 script runner 會與 Python threading 產生 deadlock**。用獨立進程完全隔離 threading 才能穩定執行。

---

## 策略版本

系統包含 4 個策略版本（v1→v4 演進），可在側邊欄切換 v2/v4：

| 版本 | 方法 | 結果（30 股 3 年回測） |
|------|------|----------------------|
| v1 | 六指標加權評分 | 基礎版，無停損 |
| v2 | v1 + 停損停利 + 訊號確認 | 9/30 獲利，-0.05% |
| v3 | v2 + ATR 動態停損（實驗） | 效果不如 v2 |
| **v4** | **趨勢動量 + 移動停利** | **26/30 獲利，+87.7%** |

詳見 [STRATEGY.md](STRATEGY.md)。

---

## 安裝與執行

### 環境需求
- Python 3.10+
- Docker（用於 Redis 快取，可選）

### 安裝

```bash
# 複製專案
git clone https://github.com/ZQCHUNG/Stock.git
cd Stock

# 建立虛擬環境（建議）
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # macOS/Linux

# 安裝依賴
pip install -r requirements.txt
```

### 啟動 Redis（可選，大幅提升速度）

```bash
docker run -d \
  --name stock-redis \
  -p 6379:6379 \
  -v ./redis-data:/data \
  redis:7-alpine \
  redis-server --appendonly yes --save 60 1
```

Redis 快取效果：股價資料載入從 ~0.8s 降至 ~0.007s（快 117 倍）。
不啟動 Redis 系統也能正常運作，只是每次都會重新從 Yahoo Finance 抓資料。

### 啟動 Web 介面

```bash
python -m streamlit run app.py
```

瀏覽器會自動開啟 `http://localhost:8501`

## 使用方式

1. 在左側邊欄搜尋/選擇股票（支援代碼或中文名稱搜尋，2300+ 隻）
2. 選擇功能頁面：技術分析 / 回測報告 / 模擬交易 / 推薦股票 / 分析報告 / 條件選股
3. 可在「進階參數」調整初始資金、回測天數、策略閾值等
4. 條件選股：勾選條件 → 設定閾值 → 點「開始選股」

### 支援的股票

所有上市（TWSE）與上櫃（TPEX）股票皆可查詢，例如：
- `2330` — 台積電（上市）
- `2317` — 鴻海（上市）
- `6748` — 亞果生醫（上櫃）
- `6618` — 永虹（上櫃）
- `0050` — 元大台灣50 ETF

輸入代碼或名稱即可搜尋，系統自動判斷上市/上櫃。

## 資料來源

| 來源 | 用途 |
|------|------|
| Yahoo Finance (yfinance) | 股價歷史資料、基本面數據 |
| Google News RSS | 個股新聞（中文） |
| TWSE 公開 API | 上市股票清單 |
| TPEX 公開 API | 上櫃股票清單 |
| twstock | 離線股票代碼備援 |

## 專案架構

```
Stock/
├── app.py                  # Streamlit Web 介面（6 個功能頁面）
├── config.py               # 設定檔（指標參數、策略參數、費率）
├── screener_worker.py      # 條件選股 worker（獨立進程，並行抓取）
├── requirements.txt        # Python 依賴
├── STRATEGY.md             # 策略詳細說明（v1~v4）
├── data/
│   ├── fetcher.py          # 資料抓取（yfinance + Google News + Redis 快取）
│   ├── stock_list.py       # 完整股票清單（TWSE/TPEX API + twstock）
│   └── cache.py            # Redis 快取層
├── analysis/
│   ├── indicators.py       # 技術指標計算（MA/RSI/MACD/KD/布林/量能/ADX/ROC）
│   ├── strategy.py         # v1-v3 綜合評分策略
│   ├── strategy_v4.py      # v4 趨勢動量策略
│   └── report.py           # 三維度分析報告產生器
├── backtest/
│   └── engine.py           # 回測引擎（v2 + v4，含台股費率）
├── simulation/
│   └── simulator.py        # 模擬交易（v2 + v4）
├── tests/                  # 171 個單元測試
│   ├── conftest.py         # 合成資料 fixtures（無網路依賴）
│   ├── test_indicators.py  # 指標計算測試
│   ├── test_strategy.py    # v1-v3 策略測試
│   ├── test_strategy_v4.py # v4 策略測試
│   ├── test_backtest.py    # 回測引擎測試
│   ├── test_simulator.py   # 模擬交易測試
│   └── test_report.py      # 報告產生器測試
└── redis-data/             # Redis 持久化資料（gitignore）
```

## 快取策略（Redis）

| 資料 | TTL | 說明 |
|------|-----|------|
| 股價資料 | 5 分鐘 | 盤中即時性 |
| 分析結果 | 5 分鐘 | 隨股價更新 |
| 推薦掃描 | 10 分鐘 | 掃描 25 隻較耗時 |
| 條件選股 | 30 分鐘 | 基本面資料變化慢，按條件 hash 分開快取 |
| 股票清單 | 24 小時 | 清單變化頻率低 |

可在側邊欄「快取狀態」查看 Redis 連線與記憶體使用，並手動清空快取。

## 測試

```bash
python -m pytest tests/ -q
```

171 個測試，全部使用合成 fixtures（`conftest.py`），不依賴網路。
覆蓋範圍：指標計算、策略訊號、回測引擎、模擬交易、報告產生。

## 免責聲明

本系統僅供技術分析學習與參考，不構成任何投資建議。股票投資有風險，請自行評估並做出投資決策。
