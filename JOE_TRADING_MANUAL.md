# Joe 交易系統操作手冊 (V1.0.0)

## 每日開盤前檢核清單 (Pre-Market Checklist)
Quick 15-min checklist format:
- [ ] Check Control Tower → Global Risk Flag (紅/綠燈)
- [ ] Check Aggressive Index (score + regime)
- [ ] Check Live Positions status (trailing stops, +1R targets)
- [ ] Review any overnight Signal Log alerts
- [ ] Check Pipeline Monitor for data freshness

## 1. Emergency Kill Switch 操作指南
- What it does: POST /system/emergency-stop
- When to use: System anomaly, flash crash, data corruption
- How: Control Tower → click "Emergency Stop" button
- What happens: Suppresses all new signals, sends LINE alert
- Recovery: Manual restart via Control Tower after investigation
- 心理提醒: Kill Switch 不是恐慌按鈕。只在系統異常時使用，市場正常下跌不需要按。

## 2. Aggressive Index 解讀
- Score 0-40: Defensive (藍色/🧊) → 建議觀望，減少新進場
  - 情緒對照: 此時應保持耐心，不要因為「錯過機會」而焦慮
- Score 40-70: Normal (綠色/☘️) → 正常操作
  - 情緒對照: 維持紀律，按系統建議執行
- Score 70-100: Aggressive (紅色/🔥) → 市場過熱，注意風險
  - 情緒對照: 市場貪婪時要冷靜，不要追高
- Components: Market Context (30) + Sector RS (25) + In-Bounds Rate (25) + Signal Quality (20)

## 3. Monthly Parameter Recommendation 調整流程
- 系統每月 1 日 10:00 自動產生建議
- 查看: Control Tower → Signal Log tab → Parameter Recommendations card
- 嚴重等級: info (參考) / warning (建議調整) / critical (必須處理)
- 調整流程:
  1. 閱讀建議內容與 evidence
  2. 如果是 critical: 立即暫停新進場，評估風險
  3. 如果是 warning: 考慮下調 risk_per_trade 或收緊 entry threshold
  4. 如果是 info: 記錄但不急著改
- 重要: 系統只建議，不自動修改。所有參數修改需手動操作。
- 心理提醒: 不要在連續虧損的情緒低谷中大幅修改參數。等心情冷靜後再決定。

## 4. Signal Log 使用指南
- Auto-Sim: 每日 20:30 自動執行，篩選 RS>=80 的高信心標的
- AI Comment: 每個信號旁有 "Ask AI" 按鈕，獲取一句話點評
- Confirm Live: 實際下單後，點擊 "Confirm Live" 輸入實際成交價
- 追蹤: 系統自動追蹤 T+5, T+10, T+21 報酬率
- In-Bounds: 實際報酬是否在預測 CI 區間內（健康指標）

## 5. Risk Management 操作
- Trailing Stop: 4 階段自動追蹤 (Initial → Breakeven → ATR → Tight)
- +1R Scale-out: 達到 +1R 目標後建議部分獲利了結
- Stress Test: War Room 可隨時執行壓力測試
- Sector Concentration: L1 產業上限 30%，相關性熱度 0.7 觸發降倉

## 6. 封存實驗清單 (Archived Experiments)
List of experiments that were tested and deliberately NOT adopted:

### ML 機器學習系列 (v5-v8) — 已關閉
- v5 Binary: P=0.521, EV 微薄
- v6 Global: P=0.555, EV 下降
- v7 Per-stock: P=0.279, EV<0
- v8 Meta-Labeling: AUC=0.5012, Kill Switch 觸發 (< 0.55)
- 根本原因: Cohen's d=0.223, Win/Loss 特徵分布高度重疊
- 教訓: 台股的 alpha 信號太微弱，ML 模型無法有效區分贏家與輸家
- 心理提醒: 不要在虧損期想「要是用 ML 就好了」——數據已經證明 ML 在此領域無效

### Adaptive Sniper (Phase 14) — 已封存
- 測試結果: OOS Calmar Delta = 0% (門檻: +5%)
- 判決: BASELINE_WINS
- 原因: Omega weighting 在正常交易量下無法累積足夠樣本進行 regime detection
- 教訓: 複雜的自適應機制不一定比簡單的固定規則更好
- 心理提醒: 系統的強大在於紀律，不在於複雜度

### Pyramid 加碼 (R14.17.3) — 已刪除
- 測試結果: Calmar 退化
- 判決: KILLED
- 原因: 加碼在已有利潤的部位上，增加了集中度風險
- 教訓: 分散比集中安全

## 7. API 配額管理表

| 數據源 | 用途 | 速率限制 | 延遲策略 | 憑證 | 配額重置 |
|--------|------|---------|---------|------|---------|
| **TWSE** | 日線/法人/除權息 (主要) | IP 封鎖風險 | 3-8s random | 無 (公開) | — |
| **TPEX** | 上櫃股日線/法人 | 同 TWSE | 3-8s random | 無 (公開) | — |
| **yfinance** | 日線備援 | 隱性限制 (IP 阻斷) | 無 | 無 (公開) | — |
| **FinMind** | 日線/財報/法人備援 | 429→指數退避; 402→60min 窗口 | 1-3s random | FINMIND_TOKEN (.env) | 滾動 60 分鐘窗口 |
| **MOPS** | 月營收 | 同 TWSE | 3-8s random | 無 (公開) | — |
| **Google News** | 新聞 RSS | 429→等 60s | 2-5s random | 無 (公開) | — |
| **LINE Notify** | 通知推送 | 1000 則/小時 | 4hr 去重 | LINE_NOTIFY_TOKEN (.env) | 每小時重置 |
| **Telegram Bot** | 通知推送 (選用) | 30 則/秒 | 無 | telegram_bot_token (config) | — |

注意事項:
- FinMind 402 錯誤 = 配額耗盡，系統自動等待 60 分鐘後重試
- TWSE/TPEX 如遭 IP 封鎖，等待 1 小時或更換網路
- yfinance 偶爾對台股 IP 阻斷，系統會自動 fallback 至 FinMind
- 所有 token 存放在 `.env` 檔案中，絕不 commit 到 Git

## 8. Secrets 安全規則
- 所有 API token 從環境變數載入 (`os.environ.get`)
- `.env` 已在 `.gitignore` 中排除
- Frontend API 回傳時自動遮蔽 token (`token[:8] + "***"`)
- Log 中不會出現任何 token 內容
- 如需更換 token: 修改 `.env` 後重啟 backend

## 9. 系統維護注意事項
- 數據更新: 每日 20:00 自動重建 Parquet 特徵
- Scheduler: 啟動時自動運行所有排程任務
- Backup: Control Tower → Run Backup
- 不要做的事:
  - 不要在盤中修改 config.py 參數
  - 不要手動刪除 data/ 目錄下的檔案
  - 不要在虧損期衝動修改策略邏輯

## 版本資訊
- V1.0.0 (2026-02-25): 正式版發佈
- Phase 1-14 全部完成
- 系統已通過 Architect Gate + CTO 確認
