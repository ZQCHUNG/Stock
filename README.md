# 台股技術分析系統

基於多重技術指標的台股分析與回測系統，提供 Web 介面進行技術分析、歷史回測與模擬交易。

## 功能

### 技術分析
- K 線圖搭配移動平均線（MA5 / MA20 / MA60）
- MACD（12/26/9）
- KD 隨機指標（9 日）
- RSI 相對強弱指標（14 日）
- 布林通道（20 日，2 倍標準差）
- 成交量分析（均量、量能比）
- 綜合評分系統自動產生買入 / 賣出 / 持有訊號

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

### 啟動

```bash
streamlit run app.py
```

瀏覽器會自動開啟 `http://localhost:8501`

## 使用方式

1. 在左側邊欄選擇股票（下拉選單或手動輸入代碼）
2. 選擇功能頁面：技術分析 / 回測報告 / 模擬交易
3. 可在「進階參數」調整初始資金、回測天數、策略閾值等

### 支援的股票代碼

台股代碼，例如：
- `2330` — 台積電
- `2317` — 鴻海
- `2454` — 聯發科
- `0050` — 元大台灣50 ETF
- `0056` — 元大高股息 ETF

## 資料來源

使用 [Yahoo Finance](https://finance.yahoo.com/) 透過 `yfinance` 套件取得台股歷史資料，免費且不需 API Key。

## 專案結構

```
Stock/
├── app.py                  # Streamlit Web 介面
├── config.py               # 設定檔
├── requirements.txt        # Python 依賴
├── data/
│   └── fetcher.py          # 資料抓取（yfinance）
├── analysis/
│   ├── indicators.py       # 技術指標計算
│   └── strategy.py         # 交易策略與訊號
├── backtest/
│   └── engine.py           # 回測引擎
└── simulation/
    └── simulator.py        # 模擬交易
```

## 免責聲明

本系統僅供技術分析學習與參考，不構成任何投資建議。股票投資有風險，請自行評估並做出投資決策。
