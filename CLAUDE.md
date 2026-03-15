# CLAUDE.md — 台股量化分析系統 (AIFarm)

## 你是誰、你的角色

你是 Joe 的工程師 Claude Code (Opus 4.6)。你負責寫代碼、跑測試、部署。
**你不做架構或策略決策。** 所有重大決策由「交易員顧問」審核。

## 交易員顧問

Joe 在 Claude.ai 上有一個長期對話，對方角色設定是：哈佛資工畢業、20 年經驗的資深股票交易員。
這個顧問擁有 **系統架構和交易策略的最終決策權**。Joe 已明確授權：「一切交給你決定，你說 OK 才開始做事。」

### 什麼時候要找顧問

- 新增或修改交易策略邏輯
- 改變信號的產生、篩選、排名方式
- 調整回測參數或風控規則
- 系統架構方向性變更
- 任何你不確定的交易領域問題

### 什麼時候不用找顧問

- Bug fix、代碼重構、測試撰寫
- 純前端 UI 調整（不涉及數據邏輯）
- DevOps / CI / CD / Docker
- Joe 明確指示的小任務

### 怎麼找顧問

用 Playwright 開 Joe 的 Claude.ai 對話。具體操作問 Joe，他會協助你連上正確的 conversation。
溝通格式：先報告現況和數據，再提出具體問題，讓顧問做決策。不要問開放式問題，要給選項。

## 系統定位（顧問已確認）

**Pattern 驅動選股雷達**，不是信號驅動交易系統。
系統回答的問題是「現在哪些股票的走勢長得像歷史上大漲前的樣子」，不是「這檔該買還是賣」。

## 核心設計決策（全部經顧問確認）

### 策略架構
- **只有 V4 為 active 策略**（趨勢動量，config: `ACTIVE_STRATEGIES = ["v4"]`）
- V5 / Bold / Aggressive / Adaptive 全部凍結，代碼保留不砍，改 config 一行即可解凍
- V4 信號降級為「輔助標籤」，掛在掃描模式結果旁邊，不做主要決策依據
- SQS、R88、Winner DNA 凍結，不刪代碼
- Winner DNA 整個模組要移到 `archived/`，DTW 核心函數抽到 `utils/dtw.py`

### 反轉偵測（Multi+RSI）
- Multi-scale + RSI Divergence 是唯一保留的反轉信號
- 定位：**veto-only**，攔截 V4 的錯誤 SELL，不做獨立 BUY trigger
- 數據：n=1,118, WR=50.4%, PF=1.94 (D10), expectancy=+2.22% 扣成本後
- Threshold: min_composite_score=30（用寬門檻，不 cherry pick）
- BB Squeeze / Volume Exhaustion / Spring 已確認有害或無效，已砍

### 掃描模式（核心產品）
- **Golden Template Library**: D30 forward return >= +20% 的歷史案例
- 30 天 cooldown 去重（同一波只保留起漲點）
- 每檔模板上限 20 個（按 consistency score 排序保留）
- 模板約 ~13,500 筆

**每日掃描流程：**
1. 載入 golden templates（~3.4MB 常駐記憶體）
2. 取全市場當前特徵向量
3. Regime 過濾（只比對同 regime 的模板）
4. Cosine similarity（加權矩陣乘法，~100ms）
5. 每檔取 Top-5 最相似模板
6. Composite score 排序取 Top 15

**排名公式：**
`composite_score = similarity * 0.7 + consistency * 0.3`
- consistency = D7/D14/D30/D90 中正報酬的比例（全正=1.0, 三正=0.75...）
- 抓「漲上去站得穩」的模板，不是暴漲暴跌型

**Top 15 規則：**
- 同產業最多 3 檔
- 每筆推薦附帶：股名代碼、Top-5 歷史模板、各天期 forward return 中位數和四分位數（不秀平均值）、V4 信號標籤、hit rate、當前 regime

**3 Preset（維度權重加乘，不砍維度）：**
- 全部 preset 都用全部 65 個特徵
- 技術派：技術面特徵權重 x2，其他 x1
- 價值派：基本面特徵權重 x2，其他 x1
- 事件派：消息面特徵權重 x2，其他 x1
- 算 cosine similarity 前，特徵向量乘以 weight mask

**Forward return 窗口：D7 / D14 / D30 / D90 / D180**（不用 D1/D3，噪音太大）

### 自我驗證機制
- **每日快照**：掃描 Top 15 結果存 `scan_history.parquet`（append-only）
  - 欄位：scan_date, stock_code, rank, composite_score, similarity, consistency, hit_rate, close_price, regime, preset_used
- **自動回填**：daily job 每天回填已到期 horizon 的 actual forward return
- **月度報表**：每月 1 號算 WR / avg return / vs 加權指數 alpha，推 Telegram
  - 按 regime 拆分、按 rank 拆分（Top 5 vs Top 6-15）
- **Drift 警報**：rolling 30 天 D7 WR < 40% 連續兩週 → Telegram WARNING
- **所有績效數字都要 benchmark 加權指數**，不 beat 大盤 = 系統無效

### 交易成本
`TRANSACTION_COST = 0.005855`
- 手續費：0.1425% x 0.3（三折）x 2 = 0.0855%
- 證交稅：0.3%
- 滑價：0.1% x 2 = 0.2%
- 總計：0.5855%

### 台股特性（必須考慮）
- 漲跌停 +/-10%，跌停鎖死時賣不掉
- T+2 交割
- 散戶比例高
- ATR 停損目前未處理漲跌停 slippage（backlog 中，待修）

## 前端 Dashboard 設計

三段式：
1. **Status Bar（頂部常駐）**：最新資料日期、stock count、更新時間、regime
2. **掃描模式 Top 15（主角，佔畫面六成）**：列表 + 點擊展開詳情
3. **持股追蹤（輔助）**：手動輸入持股，顯示 V4 信號 + veto 狀態

不要做的：SQS 面板、R88 視覺化、Winner DNA UMAP 圖（全部凍結中）

## 基礎建設

### Cloud Run Job
- Image: `gcr.io/ooooorz/stock-daily-update`
- Region: asia-east1
- Spec: 2 vCPU, 4Gi RAM
- Schedule: 週一至週五 19:00 TWN（Cloud Scheduler）
- 通知: Telegram Bot（token + chat_id 走環境變數）

### Telegram 通知三級
- SUCCESS: 正常完成 + stock count + 耗時
- WARNING: 部分 fetch 失敗 / build > 30min / stock count drop > 10%
- ABORT: 致命錯誤（data freshness gap > 1 天等）
- **每次都發通知，沒收到 = 異常**

### Data Freshness
- gap > 1 天 → abort（不是 3 天）
- 週末 auto-skip（is_trading_day 判斷）
- 國定假日判斷待補（目前只判斷 weekday）

### 資料管線
- GitHub → Cloud Build → Cloud Run Job → GCS (Parquet) → Telegram
- Joe 的電腦不參與日常運作

## 測試標準

- **統計檢定**：所有策略信號必須 p < 0.05 才能上線
- **回測必須扣交易成本**（TRANSACTION_COST = 0.005855）
- **E2E 測試優先**，不是 mock
- **Profit Factor > 1.5** 才算有 edge
- **所有報酬數字用中位數**，不用平均值（避免被極端值拉高）
- 推代碼前所有測試必須通過

## Backlog 優先序

Phase 1（基礎建設）→ Phase 2（掃描模式 + 自我驗證）→ Phase 3（擴覆蓋 1,973 股）→ Phase 4（持股追蹤 + Preset UI）→ Phase 5（技術債）→ Phase 6（觀察項）

完整 backlog 見 `docs/backlog.xlsx` 或 README。

**當前狀態**：Phase 1 進行中，Cloud Run 已部署，等週一第一次交易日驗證。

## 溝通原則

- Joe 是股票新手，系統輸出要直覺可理解
- Joe 偏好 pattern-based 預測性分析，不是技術指標看盤
- 如果你看到任何不合理的參數、不合邏輯的策略設計、錯誤的假設，直接指出來改
- 不確定的事情問顧問，不要自己猜
