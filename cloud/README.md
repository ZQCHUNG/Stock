# Cloud Run Job: 每日股票數據更新

## 架構

```
Cloud Scheduler (weekday 18:00 TST)
  └─> Cloud Run Job (stock-daily-update)
        ├─ Step 1: daily_update.py  (~14 min)
        │   ├─ 延伸收盤價矩陣 (pit_close_matrix)
        │   ├─ 自動修復異常數據
        │   ├─ 重算 RS 矩陣
        │   ├─ 更新 Screener DB
        │   ├─ 回填 forward returns
        │   ├─ 實現訊號 + 移動停損
        │   ├─ Auto-Sim 掃描
        │   └─ 每日複盤 LINE 推播
        ├─ Step 2: build_features.py (~30 min)
        │   └─ 65 features × 1096 stocks → Parquet
        ├─ Step 3: 上傳結果至 GCS
        │   ├─ gs://bucket/daily/YYYY-MM-DD/  (每日快照)
        │   └─ gs://bucket/latest/             (最新版本)
        └─ Step 4: LINE 通知完成狀態
```

## 費用估算 (NT$)

| 資源 | 規格 | 月費用 |
|------|------|--------|
| Cloud Run Job | 2 vCPU, 4Gi RAM, ~44min/day | ~NT$60 |
| Cloud Build | 每日一次 build (快取後 <5min) | ~NT$10 |
| GCS Storage | ~500MB × 30 days | ~NT$5 |
| Cloud Scheduler | 1 排程 | 免費 |
| **合計** | | **~NT$75/月** |

## 部署步驟

### 前置準備

```bash
# 1. 確認 gcloud 已認證
gcloud auth list

# 2. 設定專案
gcloud config set project ooooorz
```

### 首次部署

```bash
bash cloud/deploy.sh create
```

這會執行:
1. 啟用必要 API (Cloud Run, Build, Scheduler, Storage)
2. 建立 GCS bucket (30 天自動清理)
3. 建置 Docker image 並推送至 GCR
4. 建立 Cloud Run Job
5. 建立 Cloud Scheduler (週一至五 18:00)

### 常用操作

```bash
# 更新程式碼後重新部署
bash cloud/deploy.sh update

# 手動執行一次
bash cloud/deploy.sh run

# 查看 logs
bash cloud/deploy.sh logs

# 查看狀態
bash cloud/deploy.sh status

# 刪除所有資源 (保留 bucket)
bash cloud/deploy.sh delete
```

## 環境變數

| 變數 | 說明 | 預設 |
|------|------|------|
| `GCS_BUCKET` | GCS bucket 名稱 | deploy.sh 自動設定 |
| `LINE_TOKEN` | LINE Notify token | (選填) |
| `SKIP_FEATURES` | 設為 "1" 跳過 build_features | "0" |
| `DRY_RUN` | 設為 "1" 跳過 GCS 上傳 | "0" |

### 設定 LINE 通知

```bash
gcloud run jobs update stock-daily-update \
  --region asia-east1 \
  --set-env-vars "LINE_TOKEN=your_token_here" \
  --project ooooorz
```

## 本機測試

```bash
# 不上傳 GCS，只跑 pipeline
DRY_RUN=1 python cloud/daily_job.py

# 只跑 daily_update，跳過 features
DRY_RUN=1 SKIP_FEATURES=1 python cloud/daily_job.py
```

## 注意事項

- Job 設計為 **idempotent** — 同一天重複執行不會造成問題
- GCS `daily/` 目錄設有 30 天 lifecycle — 超過 30 天自動刪除
- `latest/` 目錄永遠保留最新版本
- 失敗自動重試 2 次 (max-retries=2)
- Task timeout 60 分鐘 (正常 ~44 分鐘)
- 數據源: yfinance (主) → FinMind (備援)，切換時會 LINE 通知
