<script setup lang="ts">
import { h, computed, onMounted, ref as vRef } from 'vue'
import {
  NGrid, NGi, NCard, NAlert, NButton, NDatePicker,
  NStatistic, NDataTable, NSpace, NTag, NText, NDivider,
  NInputNumber, NCollapse, NCollapseItem, NProgress, NTooltip,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import VChart from 'vue-echarts'
import { useAppStore } from '../stores/app'
import { useClusterStore } from '../stores/cluster'
import { useResponsive } from '../composables/useResponsive'
import { useChartTheme } from '../composables/useChartTheme'
import { fmtPct, priceColor } from '../utils/format'
import type { BlockResult, ForwardPath, SimilarCase, SniperAssessment, MutationResult, DailySummary } from '../api/cluster'

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
  brokerage: '分點面',
  industry: '產業面',
  fundamental: '基本面',
  attention: '關注度',
}

// R88.7: Track warmup features for UI markers
const warmupDimensions = computed(() => {
  const set = new Set<string>()
  for (const dim of store.dimensions) {
    if (dim.has_warmup) set.add(dim.name)
  }
  return set
})

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
    store.loadDailySummary(),
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
        const allDims = ['technical', 'institutional', 'brokerage', 'industry', 'fundamental', 'attention']
        const selectedSet = new Set(store.selectedDimensions)

        return h('div', { style: { display: 'flex', flexDirection: 'column', gap: '2px', fontSize: '11px' } },
          allDims.map(dim => {
            const val = ds[dim] ?? 0
            const pct = Math.max(0, Math.min(100, Math.round(val * 100)))
            const isSelected = selectedSet.has(dim)
            const isWarning = !isSelected && val < 0.4
            const isWarmup = warmupDimensions.value.has(dim)
            const label = dimLabels[dim] || dim

            return h('div', {
              style: {
                display: 'flex',
                alignItems: 'center',
                gap: '4px',
                opacity: isSelected ? 1 : 0.5,
              },
              title: isWarmup ? '部分特徵數據累積中' : undefined,
            }, [
              h('span', { style: { width: '38px', textAlign: 'right', flexShrink: 0 } },
                isWarning ? `[!]${label}` : (isWarmup ? `\u23F3${label}` : label)),
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
                    background: isWarmup ? '#9ca3af' : simColor(val),
                    borderRadius: '2px',
                  },
                }),
              ]),
              h('span', {
                style: {
                  width: '32px',
                  textAlign: 'right',
                  flexShrink: 0,
                  color: isWarmup ? '#9ca3af' : simColor(val),
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

// --- Sniper Confidence Tiering [R88.5 CONVERGED] ---
const sniperTierConfig: Record<string, { color: string; type: 'warning' | 'info' | 'default'; label: string }> = {
  sniper: { color: '#d4a017', type: 'warning', label: 'Sniper' },
  tactical: { color: '#3b82f6', type: 'info', label: 'Tactical' },
  avoid: { color: '#9ca3af', type: 'default', label: 'Avoid' },
}

const sniperAssessment = computed(() => store.result?.sniper_assessment ?? null)

const sniperTierInfo = computed(() => {
  const tier = sniperAssessment.value?.tier ?? 'avoid'
  return sniperTierConfig[tier] ?? sniperTierConfig.avoid
})

const sniperTacticalNote = computed(() => {
  if (!sniperAssessment.value) return ''
  if (sniperAssessment.value.tier === 'tactical') {
    return '未達 50% 基本面門檻，但符合 40% 戰術門檻，建議輕倉參與。'
  }
  return ''
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

// ==================== Gene Mutation Scanner ====================
const showMutationPanel = vRef(false)

async function doMutationScan() {
  showMutationPanel.value = true
  await store.loadMutations(1.5, 20)
}

// Mutation table columns
const mutationColumns: DataTableColumns<MutationResult> = [
  {
    title: '股票',
    key: 'stock_code',
    width: 70,
    render: (row) => h(NText, { strong: true }, { default: () => row.stock_code }),
  },
  {
    title: '日期',
    key: 'date',
    width: 100,
  },
  {
    title: '類型',
    key: 'mutation_type',
    width: 100,
    render: (row) => h(
      NTooltip,
      { trigger: 'hover' },
      {
        trigger: () => h(
          NTag,
          {
            type: row.z_score > 0 ? 'success' : 'error',
            size: 'small',
            bordered: false,
          },
          { default: () => row.mutation_type },
        ),
        default: () => row.z_score > 0
          ? '分點積極買超、技術面平淡 — 主力正在低位建倉，市場尚未察覺'
          : '技術面火熱、分點已撤退 — 股價強勢但主力正在倒貨，小心高位套牢',
      },
    ),
  },
  {
    title: 'Z-Score',
    key: 'z_score',
    width: 80,
    sorter: (a, b) => Math.abs(a.z_score) - Math.abs(b.z_score),
    render: (row) => h(
      NText,
      { style: { color: row.z_score > 0 ? '#16a34a' : '#dc2626', fontWeight: 700 } },
      { default: () => row.z_score.toFixed(2) + 'σ' },
    ),
  },
  {
    title: '分點面',
    key: 'score_brokerage',
    width: 80,
    render: (row) => h(NText, {}, { default: () => row.score_brokerage.toFixed(3) }),
  },
  {
    title: '技術面',
    key: 'score_technical',
    width: 80,
    render: (row) => h(NText, {}, { default: () => row.score_technical.toFixed(3) }),
  },
  {
    title: 'Δ_div',
    key: 'delta_div',
    width: 80,
    sorter: (a, b) => a.delta_div - b.delta_div,
    render: (row) => h(
      NText,
      { strong: true, style: { color: row.delta_div > 0 ? '#16a34a' : '#dc2626' } },
      { default: () => (row.delta_div > 0 ? '+' : '') + row.delta_div.toFixed(3) },
    ),
  },
]

// Mutation histogram chart option
const mutationHistogramOption = computed(() => {
  const mr = store.mutationResult
  if (!mr) return null

  const { counts, edges, threshold_value_upper, threshold_value_lower } = mr.histogram
  const barData = counts.map((c, i) => {
    const midpoint = (edges[i] + edges[i + 1]) / 2
    const isExtreme = midpoint > threshold_value_upper || midpoint < threshold_value_lower
    return {
      value: c,
      itemStyle: { color: isExtreme ? '#dc2626' : colors.value.primary },
    }
  })

  const categories = counts.map((_, i) => ((edges[i] + edges[i + 1]) / 2).toFixed(2))

  return {
    ...baseOption.value,
    tooltip: {
      ...tooltipStyle.value,
      trigger: 'axis',
      formatter: (params: any) => {
        const p = params[0]
        return `Δ_div: ${p.name}<br/>個股數: ${p.value}`
      },
    },
    xAxis: {
      type: 'category',
      data: categories,
      name: 'Δ_div (Brokerage - Technical)',
      nameLocation: 'middle',
      nameGap: 28,
      axisLabel: { fontSize: 10 },
    },
    yAxis: {
      type: 'value',
      name: '個股數',
    },
    series: [
      {
        type: 'bar',
        data: barData,
        barWidth: '80%',
        markLine: {
          silent: true,
          lineStyle: { type: 'dashed', color: '#dc2626', width: 1.5 },
          data: [
            { xAxis: threshold_value_upper.toFixed(2), label: { formatter: `+${mr.config.threshold_sigma}σ`, fontSize: 10 } },
            { xAxis: threshold_value_lower.toFixed(2), label: { formatter: `-${mr.config.threshold_sigma}σ`, fontSize: 10 } },
          ],
        },
      },
    ],
  }
})

// Navigate to stock Gene Map on click
function goToStock(code: string) {
  app.setStockCode(code)
  doSearch()
}
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
            {{ dimLabels[dim.name] || dim.name }}
            ({{ dim.has_warmup ? `${dim.active_feature_count}/${dim.feature_count}` : dim.feature_count }})
            <span v-if="dim.has_warmup" title="部分特徵數據累積中" style="margin-left: 2px">&#9203;</span>
          </NTag>
        </NSpace>
      </NCard>
    </NGi>

    <!-- Error -->
    <NGi v-if="store.error">
      <NAlert type="error" :title="store.error" closable />
    </NGi>

    <!-- R88.5 Sniper Confidence Assessment -->
    <NGi v-if="sniperAssessment">
      <NCard size="small">
        <NSpace align="center" :size="8" wrap>
          <NTag
            :type="sniperTierInfo.type"
            :bordered="true"
            size="medium"
            round
          >
            <span style="font-weight: 700">{{ sniperTierInfo.label }}</span>
          </NTag>
          <NTag size="small" :bordered="false" type="default">
            {{ sniperAssessment.label }}
          </NTag>
          <NText depth="2" style="font-size: 13px">
            {{ sniperAssessment.confidence_label }}
          </NText>
          <NDivider vertical />
          <NText depth="3" style="font-size: 12px">
            平均相似度 {{ (sniperAssessment.mean_similarity * 100).toFixed(1) }}%
          </NText>
          <NText depth="3" style="font-size: 12px">
            基本面相似度 {{ (sniperAssessment.mean_fund_similarity * 100).toFixed(1) }}%
          </NText>
          <NDivider vertical />
          <NText depth="3" style="font-size: 11px">
            驗證: ρ={{ sniperAssessment.validation.rho }} PF={{ sniperAssessment.validation.pf }} n={{ sniperAssessment.validation.n }} ({{ sniperAssessment.validation.period }})
          </NText>
        </NSpace>
        <NAlert
          v-if="sniperTacticalNote"
          type="info"
          :show-icon="false"
          style="margin-top: 6px; font-size: 12px"
        >
          {{ sniperTacticalNote }}
        </NAlert>
      </NCard>
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

    <!-- ==================== Daily Summary (R88.7 Phase 10-11) ==================== -->
    <NGi v-if="store.dailySummary">
      <NCard size="small">
        <template #header>
          <NSpace align="center" :size="8">
            <NTag type="info" :bordered="false" size="small">每日摘要</NTag>
            <NText strong>Auto-Summary</NText>
            <NText depth="3" style="font-size: 11px">v{{ store.dailySummary.version }} · {{ store.dailySummary.date }}</NText>
          </NSpace>
        </template>
        <template #header-extra>
          <NSpace :size="4">
            <NTag
              :type="store.dailySummary.pipeline_health.status === 'OK' ? 'success' :
                     store.dailySummary.pipeline_health.status === 'NO_REPORT' ? 'default' : 'error'"
              size="small" :bordered="false"
            >
              Pipeline: {{ store.dailySummary.pipeline_health.status }}
            </NTag>
            <NTag
              v-if="store.dailySummary.pipeline_health.night_watchman"
              :type="store.dailySummary.pipeline_health.night_watchman.status === 'HEALTHY' ? 'success' : 'warning'"
              size="small" :bordered="false"
            >
              Watchman: {{ store.dailySummary.pipeline_health.night_watchman.status }}
            </NTag>
            <NTag
              v-if="store.dailySummary.pipeline_health.row_count_drift?.status === 'WARNING'"
              type="warning" size="small" :bordered="false"
            >
              RowDrift: {{ store.dailySummary.pipeline_health.row_count_drift.deviation_pct }}%
            </NTag>
            <NTag
              v-if="store.dailySummary.market_pulse?.activity_percentile?.label &&
                    store.dailySummary.market_pulse.activity_percentile.label !== 'insufficient_data'"
              :type="store.dailySummary.market_pulse.activity_percentile.percentile! >= 80 ? 'error' :
                     store.dailySummary.market_pulse.activity_percentile.percentile! >= 60 ? 'warning' : 'default'"
              size="small" :bordered="false"
            >
              活躍度: {{ store.dailySummary.market_pulse.activity_percentile.label }}
            </NTag>
            <NTag
              v-if="store.dailySummary.confidence_score"
              :type="store.dailySummary.confidence_score.color === 'green' ? 'success' :
                     store.dailySummary.confidence_score.color === 'yellow' ? 'warning' : 'error'"
              size="small" :bordered="false"
            >
              信心: {{ (store.dailySummary.confidence_score.score * 100).toFixed(0) }}%
              {{ store.dailySummary.confidence_score.label }}
            </NTag>
          </NSpace>
        </template>

        <!-- Narrative -->
        <NAlert
          :type="store.dailySummary.market_pulse?.circuit_breaker?.triggered ? 'error' : 'info'"
          :title="store.dailySummary.narrative"
          style="margin-bottom: 8px"
        />

        <!-- Pulse stats -->
        <NGrid :cols="cols(2, 3, 5).value" x-gap="8" y-gap="8" style="margin-bottom: 8px">
          <NGi>
            <NStatistic label="掃描股數" :value="store.dailySummary.market_pulse?.total_stocks_scanned ?? '-'" />
          </NGi>
          <NGi>
            <NStatistic label="突變數" :value="store.dailySummary.market_pulse?.total_mutations ?? '-'" />
          </NGi>
          <NGi>
            <NStatistic label="匿蹤吸貨" :value="store.dailySummary.market_pulse?.stealth_count ?? '-'" />
          </NGi>
          <NGi>
            <NStatistic label="誘多派發" :value="store.dailySummary.market_pulse?.distribution_count ?? '-'" />
          </NGi>
          <NGi>
            <NStatistic label="偏向" :value="
              store.dailySummary.market_pulse?.mutation_bias === 'distribution_heavy' ? '出貨' :
              store.dailySummary.market_pulse?.mutation_bias === 'accumulation_heavy' ? '吸貨' :
              store.dailySummary.market_pulse?.mutation_bias === 'balanced' ? '均衡' : '中性'
            " />
          </NGi>
        </NGrid>

        <!-- Hot Sectors (Phase 11 — Architect Critic) -->
        <div v-if="store.dailySummary.hot_sectors?.length" style="margin-bottom: 8px">
          <NText strong style="font-size: 12px; display: block; margin-bottom: 4px">
            族群熱點
          </NText>
          <NSpace :size="4" :wrap="true">
            <NTag
              v-for="sec in store.dailySummary.hot_sectors"
              :key="sec.sector"
              :type="sec.signal === 'stealth_heavy' ? 'success' :
                     sec.signal === 'distribution_heavy' ? 'error' : 'warning'"
              size="small"
            >
              {{ sec.sector }}
              <template #avatar>
                <span style="font-size: 10px">{{ sec.signal === 'stealth_heavy' ? '↗' : sec.signal === 'distribution_heavy' ? '↘' : '↔' }}</span>
              </template>
              ({{ sec.stealth_count }}↗ {{ sec.distribution_count }}↘)
            </NTag>
          </NSpace>
        </div>

        <!-- Top mutations side by side -->
        <NGrid v-if="store.dailySummary.top_mutations" :cols="cols(1, 2, 2).value" x-gap="8" y-gap="8">
          <NGi>
            <NText strong style="font-size: 12px; color: #18a058; display: block; margin-bottom: 4px">
              Top 匿蹤吸貨
            </NText>
            <div v-for="m in store.dailySummary.top_mutations.stealth" :key="m.stock_code"
              style="font-size: 12px; cursor: pointer; padding: 2px 0"
              @click="goToStock(m.stock_code)"
            >
              <NText strong>{{ m.stock_code }}</NText>
              <NText v-if="m.sector && m.sector !== '未分類'" depth="3" style="font-size: 10px"> [{{ m.sector }}]</NText>
              <NText depth="3"> z={{ m.z_score.toFixed(2) }}σ</NText>
            </div>
            <NText v-if="!store.dailySummary.top_mutations.stealth.length" depth="3" style="font-size: 11px">
              (none)
            </NText>
          </NGi>
          <NGi>
            <NText strong style="font-size: 12px; color: #d03050; display: block; margin-bottom: 4px">
              Top 誘多派發
            </NText>
            <div v-for="m in store.dailySummary.top_mutations.distribution" :key="m.stock_code"
              style="font-size: 12px; cursor: pointer; padding: 2px 0"
              @click="goToStock(m.stock_code)"
            >
              <NText strong>{{ m.stock_code }}</NText>
              <NText v-if="m.sector && m.sector !== '未分類'" depth="3" style="font-size: 10px"> [{{ m.sector }}]</NText>
              <NText depth="3"> z={{ m.z_score.toFixed(2) }}σ</NText>
            </div>
            <NText v-if="!store.dailySummary.top_mutations.distribution.length" depth="3" style="font-size: 11px">
              (none)
            </NText>
          </NGi>
        </NGrid>
      </NCard>
    </NGi>

    <!-- ==================== Gene Mutation Scanner ==================== -->
    <NGi>
      <NCard size="small">
        <template #header>
          <NSpace align="center" :size="8">
            <NTag type="warning" :bordered="false" size="small">突變掃描</NTag>
            <NText strong>基因突變偵測器</NText>
            <NText depth="3" style="font-size: 11px">分點面 vs 技術面 顯著背離</NText>
          </NSpace>
        </template>
        <template #header-extra>
          <NButton
            size="small"
            type="warning"
            :loading="store.isMutationLoading"
            @click="doMutationScan"
          >
            掃描全市場
          </NButton>
        </template>

        <!-- Circuit Breaker Alert -->
        <NAlert
          v-if="store.mutationResult?.circuit_breaker?.triggered"
          type="error"
          title="熔斷警告 — 全市場異常位移"
          style="margin-bottom: 8px"
        >
          {{ store.mutationResult.circuit_breaker.extreme_count }} /
          {{ store.mutationResult.total_stocks_scanned }} 檔
          ({{ (store.mutationResult.circuit_breaker.extreme_pct * 100).toFixed(1) }}%)
          超過 {{ store.mutationResult.circuit_breaker.threshold_sigma }}σ，
          疑似資料異常，非交易機會。Atomic Swap 應暫停。
        </NAlert>

        <NAlert
          v-if="store.mutationError"
          type="error"
          :title="store.mutationError"
          style="margin-bottom: 8px"
        />

        <!-- Summary stats -->
        <NGrid
          v-if="store.mutationResult"
          :cols="cols(2, 3, 5).value"
          x-gap="8" y-gap="8"
          style="margin-bottom: 12px"
        >
          <NGi>
            <NStatistic label="掃描股數">
              {{ store.mutationResult.total_stocks_scanned }}
            </NStatistic>
          </NGi>
          <NGi>
            <NStatistic label="突變個股">
              <span :style="{ color: store.mutationResult.total_mutations > 0 ? '#e53e3e' : '' }">
                {{ store.mutationResult.total_mutations }}
              </span>
            </NStatistic>
          </NGi>
          <NGi>
            <NStatistic label="Δ_div 均值">
              {{ store.mutationResult.distribution.mean.toFixed(4) }}
            </NStatistic>
          </NGi>
          <NGi>
            <NStatistic label="Δ_div σ">
              {{ store.mutationResult.distribution.std.toFixed(4) }}
            </NStatistic>
          </NGi>
          <NGi>
            <NStatistic label="閾值">
              ±{{ store.mutationResult.config.threshold_sigma }}σ
            </NStatistic>
          </NGi>
        </NGrid>

        <!-- Histogram -->
        <div v-if="mutationHistogramOption" style="margin-bottom: 12px">
          <NText depth="3" style="font-size: 11px">
            Δ_div 分佈 — 紅色區域為超過 ±{{ store.mutationResult?.config.threshold_sigma }}σ 的突變區
          </NText>
          <VChart :option="mutationHistogramOption" style="height: 220px; width: 100%" autoresize />
        </div>

        <!-- Mutation table -->
        <div v-if="store.mutationResult && store.mutationResult.mutations.length > 0">
          <NText depth="3" style="font-size: 11px; margin-bottom: 4px; display: block">
            Top {{ store.mutationResult.mutations.length }} 突變股（點擊查看基因譜）
          </NText>
          <NDataTable
            :columns="mutationColumns"
            :data="store.mutationResult.mutations"
            :pagination="false"
            :scroll-x="600"
            size="small"
            striped
            :row-props="(row: MutationResult) => ({
              style: 'cursor: pointer',
              onClick: () => goToStock(row.stock_code),
            })"
          />
        </div>

        <!-- No results -->
        <NText
          v-if="store.mutationResult && store.mutationResult.mutations.length === 0"
          depth="3"
          style="text-align: center; display: block; padding: 20px 0"
        >
          目前無突變個股（市場穩定期）
        </NText>

        <!-- Not yet loaded -->
        <NText
          v-if="!store.mutationResult && !store.isMutationLoading"
          depth="3"
          style="text-align: center; display: block; padding: 12px 0; font-size: 12px"
        >
          點擊「掃描全市場」偵測分點面 vs 技術面的顯著背離
        </NText>
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
