# 台股技術分析系統

基於多重技術指標的台股分析與回測系統，提供 Web 介面進行技術分析、歷史回測、模擬交易與股票推薦。

支援所有上市（TWSE）與上櫃（TPEX）股票，共 2000+ 隻。

## 功能

### 技術分析
- K 線圖搭配移動平均線（MA5 / MA20 / MA60）
- MACD（12/26/9）
- KD 隨機指標（9 日）
- RSI 相對強弱指標（14 日）
- 布林通道（20 日，2 倍標準差）
- 成交量分析（均量、量能比）
- 綜合評分系統自動產生買入 / 賣出 / 持有訊號
- **訊號原因說明**：詳列各指標偏多/偏空/中性因素

### 回測
- 自訂回測期間（90～730 天）
- 台股手續費 0.1425% + 交易稅 0.3%
- 績效指標：總報酬率、年化報酬率、最大回撤、Sharpe Ratio、勝率、盈虧比
- 權益曲線與每日報酬分布圖
- 完整交易紀錄

### 模擬交易
- 模擬最近 N 個交易日的策略執行結果（預設 30 天）
- 每日追蹤持倉、現金、總權益變化
- 每日損益圖表
- 交易明細與模擬紀錄表

### 推薦股票
- 從股票池掃描 25+ 隻熱門股
- 依技術面綜合評分排序，推薦 Top 3
- 每隻附完整推薦原因與各指標評分
- 全部股票排行表

## 策略邏輯

使用六大技術指標的加權評分系統：

| 指標 | 權重 | 多頭訊號 | 空頭訊號 |
|------|------|----------|----------|
| MA 移動平均線 | 20% | MA5 > MA20 > MA60（多頭排列） | MA5 < MA20 < MA60（空頭排列） |
| RSI | 20% | RSI < 30（超賣） | RSI > 70（超買） |
| MACD | 20% | MACD > Signal + 柱狀增加 | MACD < Signal + 柱狀減少 |
| KD | 20% | K > D 且 K < 80 | K < D 且 K > 20 |
| 布林通道 | 10% | 價格靠近下軌 | 價格靠近上軌 |
| 成交量 | 10% | 量增價漲 | 量增價跌（出貨） |

- 綜合評分 > 0.3 → **買入**
- 綜合評分 < -0.3 → **賣出**
- 其他 → **持有**

閾值可在介面側邊欄調整。

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

1. 在左側邊欄搜尋/選擇股票（支援代碼或中文名稱搜尋，2000+ 隻）
2. 選擇功能頁面：技術分析 / 回測報告 / 模擬交易 / 推薦股票
3. 可在「進階參數」調整初始資金、回測天數、策略閾值等

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
| Yahoo Finance (yfinance) | 股價歷史資料 |
| TWSE 公開 API | 上市股票清單 |
| TPEX 公開 API | 上櫃股票清單 |
| twstock | 離線股票代碼備援 |

## 架構

```
Stock/
├── app.py                  # Streamlit Web 介面（4 個功能頁面）
├── config.py               # 設定檔（指標參數、策略參數、費率）
├── requirements.txt        # Python 依賴
├── data/
│   ├── fetcher.py          # 資料抓取（yfinance + Redis 快取）
│   ├── stock_list.py       # 完整股票清單（TWSE/TPEX API + twstock）
│   └── cache.py            # Redis 快取層
├── analysis/
│   ├── indicators.py       # 技術指標計算（MA/RSI/MACD/KD/布林/量能）
│   └── strategy.py         # 綜合交易策略與訊號產生
├── backtest/
│   └── engine.py           # 回測引擎（含台股費率）
├── simulation/
│   └── simulator.py        # 模擬交易
└── redis-data/             # Redis 持久化資料（gitignore）
```

## 快取策略（Redis）

| 資料 | TTL | 說明 |
|------|-----|------|
| 股價資料 | 5 分鐘 | 盤中即時性 |
| 分析結果 | 5 分鐘 | 隨股價更新 |
| 推薦掃描 | 10 分鐘 | 掃描 25 隻較耗時 |
| 股票清單 | 24 小時 | 清單變化頻率低 |

可在側邊欄「快取狀態」查看 Redis 連線與記憶體使用，並手動清空快取。

## 免責聲明

本系統僅供技術分析學習與參考，不構成任何投資建議。股票投資有風險，請自行評估並做出投資決策。
