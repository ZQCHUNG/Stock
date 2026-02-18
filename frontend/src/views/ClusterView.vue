<script setup lang="ts">
import { h, computed, onMounted } from 'vue'
import {
  NGrid, NGi, NCard, NAlert, NButton, NDatePicker,
  NStatistic, NDataTable, NSpace, NTag, NText, NDivider,
  NInputNumber, NCollapse, NCollapseItem, NProgress,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import VChart from 'vue-echarts'
import { useAppStore } from '../stores/app'
import { useClusterStore } from '../stores/cluster'
import { useResponsive } from '../composables/useResponsive'
import { useChartTheme } from '../composables/useChartTheme'
import { fmtPct, priceColor } from '../utils/format'
import type { BlockResult, ForwardPath, SimilarCase } from '../api/cluster'

const app = useAppStore()
const store = useClusterStore()
const { isMobile, cols } = useResponsive()
const { colors, tooltipStyle, baseOption } = useChartTheme()

// --- Regime labels ---
const regimeLabels: Record<number, string> = {
  1: '多頭',
  0: '盤整',
  [-1]: '空頭',
}

// --- Dimension display labels ---
const dimLabels: Record<string, string> = {
  technical: '技術面',
  institutional: '籌碼面',
  industry: '產業面',
  fundamental: '基本面',
  attention: '關注度',
}

// --- Gene map color thresholds [ARCHITECT: >90 deep green, 70-90 light green, <50 red] ---
function simColor(v: number): string {
  if (v >= 0.9) return '#16a34a'   // deep green
  if (v >= 0.7) return '#65a30d'   // light green
  if (v >= 0.5) return '#d97706'   // amber
  return '#dc2626'                  // red
}

function simStatus(v: number): string {
  if (v >= 0.9) return '高度重合'
  if (v >= 0.7) return '結構相似'
  if (v >= 0.5) return '部分相似'
  if (v >= 0) return '低相似'
  return '嚴重背離'
}

// --- Init ---
onMounted(async () => {
  await Promise.all([
    store.loadFeatureStatus(),
    store.loadDimensions(),
  ])
})

// --- Dimension toggle ---
function toggleDimension(name: string) {
  const idx = store.selectedDimensions.indexOf(name)
  if (idx >= 0) {
    // Don't allow deselecting all
    if (store.selectedDimensions.length <= 1) return
    store.selectedDimensions.splice(idx, 1)
  } else {
    store.selectedDimensions.push(name)
  }
}

// --- Query ---
async function doSearch() {
  await store.loadSimilarDual(app.currentStockCode)
}

// --- Win rate horizons ---
const horizons = ['d3', 'd7', 'd21', 'd90', 'd180'] as const
const horizonLabels: Record<string, string> = {
  d3: '3日',
  d7: '7日',
  d21: '21日',
  d90: '90日',
  d180: '180日',
}

// --- Table columns with gene map expandable row ---
function makeTableColumns(showGeneMap: boolean): DataTableColumns<any> {
  const baseCols: DataTableColumns<any> = [
    { title: '股票', key: 'stock_code', width: 70, fixed: 'left' as const },
    { title: '日期', key: 'date', width: 100 },
    {
      title: '相似度',
      key: 'similarity',
      width: 80,
      sorter: (a: any, b: any) => a.similarity - b.similarity,
      render: (row: any) => {
        const pct = `${(row.similarity * 100).toFixed(0)}%`
        // Show overall rank in grey when dimensions are filtered
        const overallNote = row.dimension_similarities
          ? ` (全維度)`
          : ''
        return h('span', { style: { fontWeight: 600 } }, pct + overallNote)
      },
    },
    ...horizons.map((hz) => ({
      title: horizonLabels[hz],
      key: hz,
      width: 75,
      sorter: (a: any, b: any) => (a.forward_returns?.[hz] ?? 0) - (b.forward_returns?.[hz] ?? 0),
      render: (row: any) => {
        const v = row.forward_returns?.[hz]
        if (v == null) return '-'
        const pct = (v * 100).toFixed(2) + '%'
        const color = priceColor(v)
        return color ? h('span', { style: { color } }, pct) : pct
      },
    })),
  ]

  if (showGeneMap) {
    baseCols.push({
      title: '基因譜',
      key: 'gene_map',
      width: 220,
      render: (row: any) => {
        const ds = row.dimension_similarities
        if (!ds) return '-'
        const allDims = ['technical', 'institutional', 'industry', 'fundamental', 'attention']
        const selectedSet = new Set(store.selectedDimensions)

        return h('div', { style: { display: 'flex', flexDirection: 'column', gap: '2px', fontSize: '11px' } },
          allDims.map(dim => {
            const val = ds[dim] ?? 0
            const pct = Math.max(0, Math.min(100, Math.round(val * 100)))
            const isSelected = selectedSet.has(dim)
            const isWarning = !isSelected && val < 0.4
            const label = dimLabels[dim] || dim

            return h('div', {
              style: {
                display: 'flex',
                alignItems: 'center',
                gap: '4px',
                opacity: isSelected ? 1 : 0.5,
              },
            }, [
              h('span', { style: { width: '38px', textAlign: 'right', flexShrink: 0 } },
                isWarning ? `[!]${label}` : label),
              h('div', {
                style: {
                  flex: 1,
                  height: '10px',
                  background: 'var(--n-color-embedded)',
                  borderRadius: '2px',
                  overflow: 'hidden',
                },
              }, [
                h('div', {
                  style: {
                    width: `${Math.max(0, pct)}%`,
                    height: '100%',
                    background: simColor(val),
                    borderRadius: '2px',
                  },
                }),
              ]),
              h('span', {
                style: {
                  width: '32px',
                  textAlign: 'right',
                  flexShrink: 0,
                  color: simColor(val),
                  fontWeight: isWarning ? 700 : 400,
                },
              }, `${Math.round(val * 100)}%`),
            ])
          })
        )
      },
    })
  }

  return baseCols
}

const rawTableColumns = computed(() => makeTableColumns(true))
const augTableColumns = computed(() => makeTableColumns(true))

// --- Spaghetti Chart ---
function buildSpaghettiOption(paths: ForwardPath[], label: string) {
  if (!paths || paths.length === 0) return null

  const series: any[] = paths.map((p, i) => ({
    type: 'line',
    data: p.path.map(pt => [pt.day, pt.value]),
    lineStyle: { width: 1, color: 'rgba(150, 150, 150, 0.35)' },
    symbol: 'none',
    silent: true,
    z: 1,
  }))

  const maxDay = Math.max(...paths.flatMap(p => p.path.map(pt => pt.day)))
  const medianPath: [number, number][] = []
  const p25Path: [number, number][] = []
  const p75Path: [number, number][] = []

  for (let d = 0; d <= maxDay; d++) {
    const vals = paths
      .map(p => p.path.find(pt => pt.day === d)?.value)
      .filter((v): v is number => v != null)
    if (vals.length === 0) continue
    vals.sort((a, b) => a - b)
    const median = vals[Math.floor(vals.length / 2)]
    const p25 = vals[Math.floor(vals.length * 0.25)]
    const p75 = vals[Math.floor(vals.length * 0.75)]
    medianPath.push([d, median])
    p25Path.push([d, p25])
    p75Path.push([d, p75])
  }

  if (p25Path.length > 0) {
    series.push({
      type: 'line', data: p75Path,
      lineStyle: { width: 0 }, symbol: 'none',
      areaStyle: { color: 'rgba(84, 112, 198, 0.12)' },
      stack: 'band', silent: true, z: 2,
    })
    series.push({
      type: 'line', data: p25Path,
      lineStyle: { width: 0 }, symbol: 'none',
      areaStyle: { color: 'rgba(84, 112, 198, 0.12)' },
      stack: 'band', silent: true, z: 2,
    })
  }

  const lastMedian = medianPath.length > 0 ? medianPath[medianPath.length - 1][1] : 1
  const medianColor = lastMedian >= 1 ? '#e53e3e' : '#38a169'
  series.push({
    type: 'line', data: medianPath, name: '中位數路徑',
    lineStyle: { width: 3, color: medianColor }, symbol: 'none', z: 10,
  })
  series.push({
    type: 'line', data: [[0, 1], [maxDay, 1]],
    lineStyle: { width: 1, color: '#888', type: 'dashed' },
    symbol: 'none', silent: true, z: 5,
  })

  return {
    ...baseOption.value,
    tooltip: {
      ...tooltipStyle.value,
      trigger: 'axis',
      formatter: (params: any) => {
        const p = Array.isArray(params) ? params.find((x: any) => x.seriesName === '中位數路徑') : null
        if (!p) return ''
        const [day, val] = p.data
        return `T+${day}: ${((val - 1) * 100).toFixed(2)}%`
      },
    },
    grid: { left: 50, right: 20, top: 10, bottom: 35 },
    xAxis: {
      type: 'value', name: '交易日', nameLocation: 'end',
      axisLabel: { color: colors.value.axisLabel, formatter: (v: number) => `T+${v}` },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value',
      axisLabel: {
        color: colors.value.axisLabel,
        formatter: (v: number) => `${((v - 1) * 100).toFixed(0)}%`,
      },
      splitLine: { lineStyle: { color: colors.value.splitLine } },
    },
    series,
  }
}

const rawSpaghettiOption = computed(() => {
  if (!store.result?.raw.forward_paths) return null
  return buildSpaghettiOption(store.result.raw.forward_paths, '原始數據')
})

const augSpaghettiOption = computed(() => {
  if (!store.result?.augmented.forward_paths) return null
  return buildSpaghettiOption(store.result.augmented.forward_paths, '系統分析')
})

// --- Feature status ---
const dataReady = computed(() => store.featureStatus?.features_exists === true)

// --- Block 1 dynamic title ---
const rawBlockTitle = computed(() => {
  if (!store.result) return '原始數據'
  const dims = store.result.dimensions_used
  if (!dims || dims.length === 5) return '原始數據'
  return dims.map(d => dimLabels[d] || d).join('+') + ' 相似案例'
})

// --- Block 2 weight transparency text ---
const weightTransparencyText = computed(() => {
  const wt = store.result?.augmented?.opinion?.weight_transparency
  if (!wt) return ''
  const parts = Object.entries(wt)
    .filter(([, v]) => v !== 1.0)
    .map(([k, v]) => `${dimLabels[k] || k} ${v}x`)
  if (parts.length === 0) return '系統加權：均等'
  return `系統加權：${parts.join(', ')}`
})
</script>

<template>
  <NGrid :cols="1" x-gap="12" y-gap="8">
    <!-- Feature status warning -->
    <NGi v-if="!dataReady && store.featureStatus">
      <NAlert type="warning" title="特徵資料尚未建立">
        請先執行 <code>python data/build_features.py</code>
        產生 Parquet 檔案。
      </NAlert>
    </NGi>

    <!-- Controls: Stock + Date + TopK + Query -->
    <NGi>
      <NCard size="small">
        <NSpace align="center" :wrap="false" :size="12">
          <NText strong style="white-space: nowrap">{{ app.currentStockCode }}</NText>
          <NDatePicker
            v-model:formatted-value="store.queryDate"
            type="date"
            placeholder="日期（預設最新）"
            clearable
            size="small"
            style="width: 150px"
            value-format="yyyy-MM-dd"
          />
          <NInputNumber
            v-model:value="store.topK"
            :min="5" :max="100"
            size="small"
            style="width: 110px"
          >
            <template #prefix>Top</template>
          </NInputNumber>
          <NButton
            type="primary"
            :loading="store.isLoading"
            :disabled="!dataReady"
            @click="doSearch"
            size="small"
          >
            查詢
          </NButton>
          <NText v-if="store.result" depth="3" style="font-size: 11px; white-space: nowrap">
            {{ store.result.query.stock_code }} @ {{ store.result.query.date }}
            · {{ regimeLabels[store.result.query.regime] || '?' }}
          </NText>
        </NSpace>

        <!-- R88.3: Dimension tags (Lenses) -->
        <NSpace v-if="store.dimensions.length > 0" :size="6" style="margin-top: 8px">
          <NText depth="3" style="font-size: 11px; line-height: 24px">維度：</NText>
          <NTag
            v-for="dim in store.dimensions"
            :key="dim.name"
            :checked="store.selectedDimensions.includes(dim.name)"
            checkable
            size="small"
            @update:checked="toggleDimension(dim.name)"
          >
            {{ dimLabels[dim.name] || dim.name }} ({{ dim.feature_count }})
          </NTag>
        </NSpace>
      </NCard>
    </NGi>

    <!-- Error -->
    <NGi v-if="store.error">
      <NAlert type="error" :title="store.error" closable />
    </NGi>

    <!-- Divergence warning -->
    <NGi v-if="store.result?.divergence_warning">
      <NAlert type="warning" title="原始數據與系統分析顯著偏離">
        兩區塊的 D21 勝率差異超過 15%。請仔細比對兩者，判斷加工邏輯是否合理。
      </NAlert>
    </NGi>

    <!-- ==================== BLOCK 1: RAW DATA (The Facts) ==================== -->
    <NGi v-if="store.result">
      <NCard size="small">
        <template #header>
          <NSpace align="center" :size="8">
            <NTag type="default" :bordered="false" size="small">區塊 1</NTag>
            <NText strong>{{ rawBlockTitle }}</NText>
            <NText depth="3" style="font-size: 11px">{{ store.result.raw.description }}</NText>
          </NSpace>
        </template>
        <template #header-extra>
          <NTag size="small" :bordered="false">
            樣本 {{ store.result.raw.statistics.sample_count }}
          </NTag>
        </template>

        <NAlert
          v-if="store.result.raw.statistics.small_sample_warning"
          type="warning"
          style="margin-bottom: 8px"
          :show-icon="false"
        >
          樣本數不足 {{ store.result.raw.statistics.sample_count }} 筆，統計結果可能不穩定。
        </NAlert>

        <!-- Win rate cards -->
        <NGrid :cols="cols(2, 3, 5).value" x-gap="8" y-gap="8">
          <NGi v-for="hz in horizons" :key="hz">
            <NCard size="small" :bordered="false" style="background: var(--n-color-embedded)">
              <NStatistic :label="horizonLabels[hz]">
                <template #default>
                  <span
                    :style="{
                      color: store.result!.raw.statistics[hz].win_rate != null
                        ? store.result!.raw.statistics[hz].win_rate! > 0.5 ? '#e53e3e' : '#38a169'
                        : '',
                      fontSize: '20px',
                      fontWeight: 700,
                    }"
                  >
                    {{
                      store.result!.raw.statistics[hz].win_rate != null
                        ? (store.result!.raw.statistics[hz].win_rate! * 100).toFixed(1) + '%'
                        : '-'
                    }}
                  </span>
                </template>
                <template #suffix>
                  <span style="font-size: 11px; color: var(--n-text-color-3); margin-left: 4px">
                    EV {{ store.result!.raw.statistics[hz].expectancy != null
                      ? fmtPct(store.result!.raw.statistics[hz].expectancy!)
                      : '-' }}
                  </span>
                </template>
              </NStatistic>
              <div
                v-if="store.result!.raw.statistics[hz].p5 != null"
                style="font-size: 10px; margin-top: 2px; color: var(--n-text-color-3)"
              >
                P5 {{ fmtPct(store.result!.raw.statistics[hz].p5!) }}
                |
                P95 {{ fmtPct(store.result!.raw.statistics[hz].p95!) }}
              </div>
            </NCard>
          </NGi>
        </NGrid>

        <!-- Spaghetti Chart -->
        <div v-if="rawSpaghettiOption" style="margin-top: 8px">
          <NText depth="3" style="font-size: 11px">
            路徑圖 — 灰線: 歷史案例 · 粗線: 中位數 · 陰影: P25-P75
          </NText>
          <VChart :option="rawSpaghettiOption" style="height: 260px; width: 100%" autoresize />
        </div>

        <!-- Cases table with gene map -->
        <NCollapse style="margin-top: 8px">
          <NCollapseItem title="相似案例明細 + 基因譜" name="raw-cases">
            <NDataTable
              :columns="rawTableColumns"
              :data="store.result!.raw.similar_cases"
              :pagination="{ pageSize: 15 }"
              :scroll-x="850"
              size="small"
              striped
            />
          </NCollapseItem>
        </NCollapse>
      </NCard>
    </NGi>

    <!-- ==================== DIVIDER ==================== -->
    <NGi v-if="store.result">
      <NDivider style="margin: 4px 0">
        <NText depth="3" style="font-size: 12px">Facts ↑ — Opinion ↓</NText>
      </NDivider>
    </NGi>

    <!-- ==================== BLOCK 2: SYSTEM ANALYSIS (Our Opinion) ==================== -->
    <NGi v-if="store.result">
      <NCard size="small">
        <template #header>
          <NSpace align="center" :size="8">
            <NTag type="info" :bordered="false" size="small">區塊 2</NTag>
            <NText strong>{{ store.result.augmented.label }}</NText>
            <NText depth="3" style="font-size: 11px">{{ store.result.augmented.description }}</NText>
          </NSpace>
        </template>
        <template #header-extra>
          <NSpace :size="4">
            <NTag
              v-if="store.result.augmented.opinion"
              size="small"
              :bordered="false"
              :type="store.result.augmented.opinion.confidence === 'high' ? 'success'
                   : store.result.augmented.opinion.confidence === 'medium' ? 'warning'
                   : 'error'"
            >
              信心: {{ store.result.augmented.opinion.confidence }}
            </NTag>
            <NTag size="small" :bordered="false">
              樣本 {{ store.result.augmented.statistics.sample_count }}
            </NTag>
          </NSpace>
        </template>

        <!-- Opinion text -->
        <div
          v-if="store.result.augmented.opinion"
          style="
            padding: 8px 12px;
            margin-bottom: 8px;
            border-radius: 4px;
            background: var(--n-color-embedded);
            font-size: 13px;
            line-height: 1.6;
            white-space: pre-line;
          "
        >
          {{ store.result.augmented.opinion.advice_text }}
        </div>

        <!-- Filters + weight transparency [R88.3 ARCHITECT] -->
        <NSpace v-if="store.result.augmented.opinion" :size="4" style="margin-bottom: 8px" wrap>
          <NTag
            v-for="f in store.result.augmented.opinion.filters_applied"
            :key="f"
            size="tiny"
            :bordered="false"
            type="info"
          >
            {{ f }}
          </NTag>
          <NTag v-if="weightTransparencyText" size="tiny" :bordered="false" type="default">
            {{ weightTransparencyText }}
          </NTag>
        </NSpace>

        <!-- Win rate cards -->
        <NGrid :cols="cols(2, 3, 5).value" x-gap="8" y-gap="8">
          <NGi v-for="hz in horizons" :key="hz">
            <NCard size="small" :bordered="false" style="background: var(--n-color-embedded)">
              <NStatistic :label="horizonLabels[hz]">
                <template #default>
                  <span
                    :style="{
                      color: store.result!.augmented.statistics[hz].win_rate != null
                        ? store.result!.augmented.statistics[hz].win_rate! > 0.5 ? '#e53e3e' : '#38a169'
                        : '',
                      fontSize: '20px',
                      fontWeight: 700,
                    }"
                  >
                    {{
                      store.result!.augmented.statistics[hz].win_rate != null
                        ? (store.result!.augmented.statistics[hz].win_rate! * 100).toFixed(1) + '%'
                        : '-'
                    }}
                  </span>
                </template>
                <template #suffix>
                  <span style="font-size: 11px; color: var(--n-text-color-3); margin-left: 4px">
                    EV {{ store.result!.augmented.statistics[hz].expectancy != null
                      ? fmtPct(store.result!.augmented.statistics[hz].expectancy!)
                      : '-' }}
                  </span>
                </template>
              </NStatistic>
            </NCard>
          </NGi>
        </NGrid>

        <!-- Spaghetti Chart -->
        <div v-if="augSpaghettiOption" style="margin-top: 8px">
          <NText depth="3" style="font-size: 11px">
            路徑圖（環境過濾 + 特徵加權後）
          </NText>
          <VChart :option="augSpaghettiOption" style="height: 260px; width: 100%" autoresize />
        </div>

        <!-- Cases table with gene map -->
        <NCollapse style="margin-top: 8px">
          <NCollapseItem title="相似案例明細 + 基因譜" name="aug-cases">
            <NDataTable
              :columns="augTableColumns"
              :data="store.result!.augmented.similar_cases"
              :pagination="{ pageSize: 15 }"
              :scroll-x="850"
              size="small"
              striped
            />
          </NCollapseItem>
        </NCollapse>
      </NCard>
    </NGi>

    <!-- Transaction cost info -->
    <NGi v-if="store.result">
      <NText depth="3" style="font-size: 11px; text-align: center; display: block">
        已扣交易成本 {{ (store.result.transaction_cost_deducted * 100).toFixed(3) }}%
        · 歷史相似性不代表未來必然性 · 本系統為情境分析工具，非投資建議
      </NText>
    </NGi>
  </NGrid>
</template>
