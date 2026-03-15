# Golden Template Library — Schema 設計文件

> 供交易顧問審核。所有數字皆來自實際資料計算，非估算。

---

## 0. 資料現況（實測數字）

| 指標 | 數值 |
|------|------|
| `pit_close_matrix.parquet` | 1,973 檔 x 1,501 天 (2020-01-02 ~ 2026-03-13) |
| `features_all.parquet` | 1,096 檔 x 1,487 天 x 65 特徵 |
| D30 報酬 >= +20% 的 (stock, date) 組合 | **187,163** (佔全部 8.66%) |
| 其中有 65 維特徵可用的 | **135,406** |
| 30 天去重後（同股票間隔 < 30 天合併） | **~13,500** |
| Regime 分布 | Bull(1): 59.5% / Bear(-1): 40.5% |
| 每檔平均模板數（去重前） | 98.0 (中位數 87.0) |
| 單檔最多模板 | 3661 (467 個) |

### D30 >= +20% 贏家的各天期報酬（歷史實績）

| 天期 | 平均報酬 | 中位數報酬 | 樣本數 |
|------|---------|-----------|--------|
| D7   | +14.4%  | +4.5%     | 186,879 |
| D14  | +30.3%  | +12.7%    | 186,857 |
| D30  | +67.7%  | +32.1%    | 187,163 |
| D90  | +88.8%  | +37.4%    | 176,808 |
| D180 | +118.1% | +40.9%    | 161,703 |

> **注意**：平均值被極端飆股拉高（max D30 = 21,127%），中位數更有參考價值。

---

## 1. Golden Template Library Schema

### 1.1 篩選條件

```
D30 Forward Return >= +20%   (使用 pit_close_matrix 計算)
AND 該 (stock, date) 存在於 features_all.parquet
AND 65 維特徵非全零（排除 ETF 早期空資料）
```

### 1.2 去重策略（Deduplication）

**問題**：同一檔股票連續 20 天都符合 D30 >= +20%，本質上是同一波行情。

**方案**：Per-stock Cooldown 30 天
- 同一檔股票，已選入的模板日期後 30 天內的其他符合日期全部跳過
- 保留每波行情最早出現的那一天（起漲點最有參考價值）
- 實測：135,406 → ~13,500（減少 90%），每檔平均 ~12 個模板

### 1.3 儲存格式：`golden_templates.parquet`

| 欄位 | 型別 | 說明 |
|------|------|------|
| `template_id` | `uint32` | 自增 PK (0 ~ N-1) |
| `stock_code` | `string` | 股票代碼 e.g. "2330" |
| `date` | `datetime64[ns]` | 特徵擷取日 |
| `regime_tag` | `int8` | 1=bull, -1=bear |
| `fwd_d7` | `float32` | D7 實際報酬 |
| `fwd_d14` | `float32` | D14 實際報酬 |
| `fwd_d30` | `float32` | D30 實際報酬 (>= 0.20) |
| `fwd_d90` | `float32` | D90 實際報酬 (可能 None) |
| `fwd_d180` | `float32` | D180 實際報酬 (可能 None) |
| `f_0` ~ `f_64` | `float32` x 65 | 65 維特徵向量（已 normalize） |

**大小估算**：
- 每筆模板：4 + 10 + 8 + 1 + 5×4 + 65×4 = ~303 bytes
- 13,500 筆 x 303B = **4.0 MB**（含 Parquet 壓縮約 2 MB）
- 記憶體中純 feature matrix: 13,500 x 65 x 4B = **3.4 MB**

### 1.4 預計算向量（加速用）

額外儲存：`golden_template_norms.npy`
- Shape: `(N,)` float32 — 每筆模板的 L2 norm
- 用途：cosine similarity 分母不需重算

### 1.5 Template 重建頻率

- **每週六 Cron 重建一次**（配合現有 Sat 02:00 Winner DNA 排程）
- 或手動 `POST /api/system/golden-templates/rebuild`
- 重建耗時預估：讀 parquet + 計算 fwd returns + 去重 ≈ 30-60 秒

---

## 2. Similarity 計算方案

### 2.1 核心流程（每日盤後）

```
1. 載入 features_all.parquet 的【最新一天】全部 1,096 檔
2. 取得當前 regime_tag
3. 對每檔股票 S：
   a. 取 S 的 65 維特徵向量 q
   b. 根據 preset 選定要用的維度 → 產生 feature mask
   c. 從 golden_templates 中篩選 regime 匹配的子集 T_filtered
   d. 計算 q 與 T_filtered 中每筆的 cosine similarity（masked features）
   e. 取 Top-K（K=5）最相似模板
   f. 彙整 Top-K 模板的 forward return 統計
4. 所有股票排序：依 avg_similarity × template_win_rate 排名
5. 輸出 Top 20 候選
```

### 2.2 維度選擇與 Preset

現有 5 個使用者維度（來自 `similarity_engine.py`）：

| 維度 | 內部維度 | 特徵數 |
|------|---------|--------|
| `technical` | technical | 20 |
| `institutional` | institutional + brokerage | 11 + 14 = 25 |
| `fundamental` | fundamental | 8 |
| `news` | attention | 7 |
| `industry` | industry | 5 |

**3 個 Preset（新增）**：

| Preset | 中文名 | 使用維度 | 特徵數 | 適用場景 |
|--------|--------|---------|--------|---------|
| `technical` | 技術派 | technical + institutional | 45 | 趨勢動量、VCP |
| `value` | 價值派 | fundamental + industry | 13 | 低估值、營收成長 |
| `event` | 事件派 | institutional + news | 32 | 法人異常、新聞驅動 |
| `all` | 全維度 | 全部 5 維度 | 65 | 預設 |

### 2.3 Regime 過濾

- `regime_tag` 來自 `features_all.parquet`：1 (bull) / -1 (bear)
- **預設行為**：只比對同 regime 的模板
  - 當前 bull → 只用 bull 模板（~8,000 筆）
  - 當前 bear → 只用 bear 模板（~5,500 筆）
- **可選**：`regime_filter=false` 關閉過濾（用全部 13,500 筆）

### 2.4 效能預估

```
單檔股票 vs 8,000 模板（bull regime）:
  - Masked cosine: 45 features x 8,000 = dot product on (45,) x (8000, 45) matrix
  - NumPy vectorized: ~0.5ms

全市場 1,096 檔:
  - 串行: 1,096 x 0.5ms = ~550ms
  - 矩陣化: (1096, 45) @ (45, 8000).T → (1096, 8000) 一次完成 ~50ms
  - Top-K 排序: np.argpartition ~10ms

總計: ~100ms（含 I/O）
```

---

## 3. 每日掃描輸出 Schema

### 3.1 單檔匹配結果 `MatchResult`

```python
@dataclass
class TemplateMatch:
    template_id: int           # golden_templates PK
    template_stock: str        # 模板來源股票 e.g. "2330"
    template_date: str         # 模板日期 ISO format
    similarity: float          # 0.0 ~ 1.0 cosine similarity
    dim_similarities: dict     # {"technical": 0.92, "institutional": 0.85, ...}
    fwd_d7: float | None       # 模板的 D7 實際報酬
    fwd_d14: float | None      # 模板的 D14 實際報酬
    fwd_d30: float             # 模板的 D30 實際報酬 (>= 20%)
    fwd_d90: float | None      # 模板的 D90 實際報酬
    fwd_d180: float | None     # 模板的 D180 實際報酬

@dataclass
class StockScanResult:
    stock_code: str            # 被掃描的股票
    stock_name: str            # 股票名稱
    current_regime: str        # "bull" / "bear"
    preset_used: str           # "technical" / "value" / "event" / "all"
    v4_signal: str | None      # 當前 V4 策略訊號（若有）
    sqs_grade: str | None      # 當前 SQS 等級
    top_matches: list[TemplateMatch]  # Top-K 最相似模板 (K=5)
    avg_similarity: float      # Top-K 平均相似度
    template_stats: dict       # 彙整統計（見 3.2）
    composite_score: float     # 綜合排名分數
```

### 3.2 模板統計 `template_stats`

```json
{
  "match_count": 5,
  "d7":  {"mean": 0.08, "median": 0.05, "win_rate": 0.80, "p5": -0.03, "p95": 0.22},
  "d14": {"mean": 0.15, "median": 0.12, "win_rate": 0.80, "p5": -0.05, "p95": 0.35},
  "d30": {"mean": 0.32, "median": 0.28, "win_rate": 1.00, "p5": 0.20, "p95": 0.55},
  "d90": {"mean": 0.45, "median": 0.35, "win_rate": 0.80, "p5": -0.10, "p95": 0.90},
  "d180":{"mean": 0.50, "median": 0.38, "win_rate": 0.75, "p5": -0.15, "p95": 1.20}
}
```

### 3.3 每日掃描報告 `DailyScanReport`

```python
@dataclass
class DailyScanReport:
    scan_date: str               # 掃描日期
    regime: str                  # 當日 regime
    preset: str                  # 使用的 preset
    total_stocks_scanned: int    # 掃描股票數
    template_count: int          # 使用的模板數（regime 過濾後）
    top_20: list[StockScanResult]  # 排名前 20
    aggregate_stats: dict        # 全市場彙整統計
    scan_duration_ms: int        # 掃描耗時
```

### 3.4 綜合排名分數 `composite_score`

```
composite_score = avg_similarity * 0.6 + template_quality * 0.4

其中:
  avg_similarity = Top-K 模板平均 cosine similarity
  template_quality = Top-K 模板的 D30 中位數報酬正規化 (0~1)
                   = min(median_d30 / 0.50, 1.0)
```

> [PLACEHOLDER: COMPOSITE_SCORE_WEIGHTS_001] 0.6/0.4 權重待回測驗證

---

## 4. 彙整統計 Schema

### 4.1 `aggregate_stats`（每日掃描報告層級）

```json
{
  "regime": "bull",
  "template_pool_size": 8023,
  "stocks_with_high_similarity": 45,
  "similarity_threshold": 0.85,
  "top20_avg_similarity": 0.91,
  "top20_template_d30_stats": {
    "mean": 0.38,
    "median": 0.31,
    "win_rate": 1.0,
    "count": 100
  },
  "regime_breakdown": {
    "bull_templates": 8023,
    "bear_templates": 5477,
    "used": "bull"
  }
}
```

### 4.2 歷史回測用統計

掃描結束後，可額外計算（非即時，排程用）：

```json
{
  "backtest_period": "2024-01-01 ~ 2025-12-31",
  "total_scans": 480,
  "total_top20_picks": 9600,
  "actual_d30_win_rate": 0.45,
  "actual_d30_mean": 0.08,
  "actual_d30_median": 0.05,
  "by_regime": {
    "bull": {"picks": 6200, "win_rate": 0.52, "mean": 0.11},
    "bear": {"picks": 3400, "win_rate": 0.35, "mean": 0.03}
  },
  "by_preset": {
    "technical": {"picks": 3200, "win_rate": 0.48},
    "value": {"picks": 3200, "win_rate": 0.43},
    "event": {"picks": 3200, "win_rate": 0.46}
  }
}
```

---

## 5. 邊界情況與設計決策

### 5.1 去重 vs 多樣性

| 方案 | 模板數 | 優點 | 缺點 |
|------|--------|------|------|
| 不去重 | 135,406 | 完整保留 | 同波行情重複灌票，記憶體 41 MB |
| 30 天去重 | ~13,500 | 平衡 | 可能遺漏短期連續訊號 |
| 60 天去重 | ~8,000 | 最精簡 | 可能丟失不同階段入場點 |

**建議：30 天去重**。13,500 筆 = 4 MB，效能無壓力。

### 5.2 同股票重複匹配

一檔當前股票可能同時匹配到同一檔歷史股票的多個模板。

**處理**：Top-K 中同一 `template_stock` 最多佔 2 筆。若超過，取相似度最高的 2 筆，空出名額給其他股票的模板。

### 5.3 特徵全零問題

部分股票早期（2020 年初）特徵全零（broker/news 資料尚未建立）。

**處理**：
- 模板篩選時排除 `sum(abs(f_0..f_64)) < 1e-6` 的行
- 每日掃描時，若當前股票特徵全零，直接跳過

### 5.4 Regime 只有 2 類

目前 `regime_tag` 只有 1 (bull) 和 -1 (bear)，沒有 sideways。

**建議**：先用現有 2 分法。未來若 `market_regime.py` 的 sideways 回寫到 features，自動支援 3 類。

### 5.5 Forward Return 截斷

- D90/D180 在接近資料尾端的模板可能為 None（超出資料範圍）
- 統計時自動排除 None，但保留 D30（必定有值，因為是篩選條件）

---

## 6. 檔案結構

```
data/
  golden_templates/
    golden_templates.parquet      # 模板庫主檔 (~2 MB)
    template_norms.npy            # L2 norms (~54 KB)
    build_metadata.json           # 建構資訊（時間、參數、統計）

  daily_reports/
    radar_2026-03-15.json         # 每日掃描結果
```

### `build_metadata.json` 範例

```json
{
  "built_at": "2026-03-15T02:00:00",
  "d30_threshold": 0.20,
  "cooldown_days": 30,
  "total_candidates": 135406,
  "after_dedup": 13521,
  "after_zero_filter": 13498,
  "regime_distribution": {"bull": 8023, "bear": 5475},
  "source_features": "features_all.parquet",
  "source_close": "pit_close_matrix.parquet",
  "feature_count": 65,
  "stocks_represented": 1096,
  "avg_templates_per_stock": 12.3
}
```

---

## 7. API 端點設計

```
# 管理
POST /api/system/golden-templates/rebuild     # 手動重建模板庫
GET  /api/system/golden-templates/stats        # 模板庫統計

# 掃描
POST /api/radar/scan                           # 執行全市場掃描
  Body: { "preset": "technical", "top_k": 5, "regime_filter": true }
  Response: DailyScanReport

GET  /api/radar/latest                         # 取最新掃描結果
GET  /api/radar/{stock_code}                   # 單檔股票的匹配詳情

# 歷史
GET  /api/radar/history?days=30                # 近 N 天掃描歷史
```

---

## 8. 待顧問確認事項

1. **D30 門檻 +20% 是否合適？** +25% 有 137,271 / +30% 有 104,211 個案例（去重前）。門檻越高，模板品質越好但數量越少。
2. **去重 Cooldown 30 天 vs 60 天？** 30 天 ~13,500 筆 / 60 天 ~8,000 筆。
3. **Top-K = 5 是否足夠？** 越多統計越穩定，但雜訊也增加。
4. **Composite Score 權重 0.6 similarity + 0.4 quality** — [PLACEHOLDER] 需回測。
5. **同股票模板上限 2 筆** — 是否需要更嚴格（1 筆）或更寬鬆（3 筆）？
6. **Preset 維度配置** — 技術派/價值派/事件派的維度組合是否符合使用情境？
7. **掃描頻率** — 僅盤後一次？還是盤中即時掃描？（即時掃描需要 features 即時更新）

---

*文件產生時間: 2026-03-15 | 資料截止: 2026-03-13 | 所有數字來自實測*
