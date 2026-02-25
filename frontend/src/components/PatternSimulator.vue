<script setup lang="ts">
import { h, ref, computed } from 'vue'
import {
  NCard, NButton, NGrid, NGi, NInput, NDatePicker,
  NCheckbox, NCheckboxGroup, NTag, NText, NSpin,
  NDataTable, NSpace, NAlert, NProgress, NTooltip, NBadge
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import VChart from 'vue-echarts'
import { clusterApi, type PatternSimulateResult } from '../api/cluster'
import { useAppStore } from '../stores/app'
import { fmtPct, priceColor } from '../utils/format'

const app = useAppStore()

const props = defineProps<{
  stockCode?: string
}>()

// ─── State ───────────────────────────────────────────────────────

const code = ref(props.stockCode || '')
const queryDate = ref<number | null>(null) // timestamp
const selectedDims = ref<string[]>(['technical', 'institutional', 'fundamental'])
const topK = ref(30)
const isLoading = ref(false)
const result = ref<PatternSimulateResult | null>(null)
const error = ref('')

const allDimensions = [
  { value: 'technical', label: '技術面 (20)' },
  { value: 'institutional', label: '法人面 (11)' },
  { value: 'brokerage', label: '分點面 (14)' },
  { value: 'industry', label: '產業面 (5)' },
  { value: 'fundamental', label: '基本面 (8)' },
  { value: 'attention', label: '輿情面 (7)' },
]

const horizons = ['d3', 'd5', 'd7', 'd14', 'd21', 'd30', 'd90', 'd180']
const horizonLabels: Record<string, string> = {
  d3: '3天', d5: '5天', d7: '7天', d14: '14天',
  d21: '21天', d30: '30天', d90: '90天', d180: '180天',
}

// ─── Computed ────────────────────────────────────────────────────

const horizonStats = computed(() => {
  if (!result.value) return []
  return horizons.map(h => {
    const s = result.value!.statistics[h]
    return {
      horizon: h,
      label: horizonLabels[h],
      ...s,
    }
  })
})

const winRateBarData = computed(() => {
  return horizonStats.value.map(s => ({
    label: s.label,
    value: s.win_rate != null ? Math.round(s.win_rate * 100) : 0,
    count: s.count || 0,
  }))
})

// ─── Confidence ──────────────────────────────────────────────────

const confidence = computed(() => result.value?.statistics?.confidence)

const confidenceColor = computed(() => {
  const g = confidence.value?.grade
  return g === 'HIGH' ? '#d03050' : g === 'MEDIUM' ? '#f0a020' : '#999'
})

// ─── Spaghetti Chart ─────────────────────────────────────────────

const spaghettiOption = computed(() => {
  const sp = result.value?.spaghetti
  if (!sp?.paths?.length || !sp?.stats) return null

  const { paths, stats } = sp
  const series: any[] = []

  // Individual paths (thin, semi-transparent)
  for (const p of paths) {
    series.push({
      type: 'line',
      data: p.path.map((v: number, i: number) => [i, v]),
      lineStyle: { width: 1, opacity: 0.25, color: '#999' },
      symbol: 'none',
      silent: true,
    })
  }

  // P25-P75 confidence band (area)
  if (stats.p25_path && stats.p75_path) {
    series.push({
      type: 'line',
      data: stats.p25_path.map((v: number, i: number) => [i, v]),
      lineStyle: { width: 0 },
      areaStyle: { color: 'rgba(24, 160, 88, 0.1)' },
      symbol: 'none',
      silent: true,
      stack: 'band',
    })
    series.push({
      type: 'line',
      data: stats.p75_path.map((v: number, i: number) => [i, v - stats.p25_path[i]]),
      lineStyle: { width: 0 },
      areaStyle: { color: 'rgba(24, 160, 88, 0.15)' },
      symbol: 'none',
      silent: true,
      stack: 'band',
    })
  }

  // Mean path (bold blue)
  if (stats.mean_path) {
    series.push({
      name: '平均走勢',
      type: 'line',
      data: stats.mean_path.map((v: number, i: number) => [i, v]),
      lineStyle: { width: 2.5, color: '#2080f0' },
      symbol: 'none',
    })
  }

  // Median path (bold green)
  if (stats.median_path) {
    series.push({
      name: '中位數',
      type: 'line',
      data: stats.median_path.map((v: number, i: number) => [i, v]),
      lineStyle: { width: 2, color: '#18a058', type: 'dashed' },
      symbol: 'none',
    })
  }

  // Worst case (red)
  if (stats.worst_path) {
    series.push({
      name: `最差 (${stats.worst_case?.stock_code})`,
      type: 'line',
      data: stats.worst_path.map((v: number, i: number) => [i, v]),
      lineStyle: { width: 1.5, color: '#d03050', type: 'dotted' },
      symbol: 'none',
    })
  }

  // Best case (orange)
  if (stats.best_path) {
    series.push({
      name: `最佳 (${stats.best_case?.stock_code})`,
      type: 'line',
      data: stats.best_path.map((v: number, i: number) => [i, v]),
      lineStyle: { width: 1.5, color: '#f0a020', type: 'dotted' },
      symbol: 'none',
    })
  }

  // Breakeven line
  const maxDays = stats.days?.length || 91
  series.push({
    name: '損益平衡',
    type: 'line',
    data: [[0, 1.0], [maxDays - 1, 1.0]],
    lineStyle: { width: 1, color: '#666', type: 'dashed' },
    symbol: 'none',
    silent: true,
  })

  return {
    tooltip: {
      trigger: 'axis',
      formatter: (params: any[]) => {
        const named = params.filter((p: any) => p.seriesName && !p.seriesName.startsWith('series'))
        if (!named.length) return ''
        const day = named[0].data[0]
        let html = `<b>T+${day}天</b><br/>`
        for (const p of named) {
          const val = ((p.data[1] - 1) * 100).toFixed(2)
          html += `${p.marker} ${p.seriesName}: ${val}%<br/>`
        }
        return html
      },
    },
    legend: {
      data: ['平均走勢', '中位數', stats.worst_case ? `最差 (${stats.worst_case.stock_code})` : '', stats.best_case ? `最佳 (${stats.best_case.stock_code})` : '', '損益平衡'].filter(Boolean),
      bottom: 0,
      textStyle: { fontSize: 11 },
    },
    grid: { top: 20, right: 20, bottom: 50, left: 50 },
    xAxis: {
      type: 'value',
      name: '交易日',
      nameLocation: 'end',
      min: 0,
      max: maxDays - 1,
    },
    yAxis: {
      type: 'value',
      axisLabel: { formatter: (v: number) => `${((v - 1) * 100).toFixed(0)}%` },
      splitLine: { lineStyle: { type: 'dashed', opacity: 0.3 } },
    },
    series,
  }
})

// ─── Actions ─────────────────────────────────────────────────────

async function runSimulation() {
  if (!code.value) return
  isLoading.value = true
  error.value = ''
  try {
    const dateStr = queryDate.value
      ? new Date(queryDate.value).toISOString().split('T')[0]
      : undefined
    result.value = await clusterApi.patternSimulate({
      stock_code: code.value,
      query_date: dateStr,
      dimensions: selectedDims.value.length > 0 ? selectedDims.value : undefined,
      top_k: topK.value,
    })
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e.message || 'Simulation failed'
    result.value = null
  } finally {
    isLoading.value = false
  }
}

// Watch for prop changes
if (props.stockCode) code.value = props.stockCode

// ─── Horizon stats table ─────────────────────────────────────────

const horizonColumns: DataTableColumns = [
  { title: '期間', key: 'label', width: 60 },
  { title: '勝率', key: 'win_rate', width: 70,
    render: (r: any) => {
      if (r.win_rate == null) return '-'
      const pct = r.win_rate * 100
      const color = pct >= 55 ? '#d03050' : pct >= 45 ? '#f0a020' : '#18a058'
      return h('span', { style: { color, fontWeight: 600 } }, `${pct.toFixed(0)}%`)
    }},
  { title: '均報酬', key: 'mean', width: 80,
    render: (r: any) => r.mean != null
      ? h('span', { style: { color: priceColor(r.mean) } }, fmtPct(r.mean))
      : '-' },
  { title: '中位數', key: 'median', width: 80,
    render: (r: any) => r.median != null
      ? h('span', { style: { color: priceColor(r.median) } }, fmtPct(r.median))
      : '-' },
  { title: '期望值', key: 'expectancy', width: 80,
    render: (r: any) => r.expectancy != null
      ? h('span', { style: { color: priceColor(r.expectancy), fontWeight: 600 } }, fmtPct(r.expectancy))
      : '-' },
  { title: '均贏', key: 'avg_win', width: 70,
    render: (r: any) => r.avg_win != null ? `+${(r.avg_win * 100).toFixed(1)}%` : '-' },
  { title: '均虧', key: 'avg_loss', width: 70,
    render: (r: any) => r.avg_loss != null ? `-${(r.avg_loss * 100).toFixed(1)}%` : '-' },
  { title: 'n', key: 'count', width: 40 },
]

// ─── Cases table ─────────────────────────────────────────────────

const caseColumns = computed<DataTableColumns>(() => [
  { title: '代碼', key: 'stock_code', width: 60,
    render: (r: any) => h('span', { style: { cursor: 'pointer', fontWeight: 600, color: '#18a058' }, onClick: () => app.selectStock(r.stock_code) }, r.stock_code) },
  { title: '日期', key: 'date', width: 90 },
  { title: '相似度', key: 'similarity', width: 70,
    sorter: (a: any, b: any) => a.similarity - b.similarity,
    render: (r: any) => {
      const pct = (r.similarity * 100).toFixed(0)
      const type = r.similarity >= 0.88 ? 'error' : r.similarity >= 0.7 ? 'warning' : 'default'
      return h(NTag, { size: 'small', type, bordered: false }, () => `${pct}%`)
    }},
  ...horizons.map(horizon => ({
    title: horizonLabels[horizon],
    key: `ret_${horizon}`,
    width: 65,
    render: (r: any) => {
      const val = r.returns?.[horizon]
      if (val == null) return '-'
      return h('span', { style: { color: priceColor(val), fontSize: '12px' } }, `${(val * 100).toFixed(1)}%`)
    },
  })),
])
</script>

<template>
  <div>
    <!-- Input section -->
    <NCard size="small" style="margin-bottom: 12px">
      <NGrid :cols="4" :x-gap="12" :y-gap="8" responsive="screen" :item-responsive="true">
        <NGi :span="1">
          <NText depth="3" style="font-size: 12px; display: block">股票代碼</NText>
          <NInput v-model:value="code" size="small" placeholder="例: 2330" @keyup.enter="runSimulation" />
        </NGi>
        <NGi :span="1">
          <NText depth="3" style="font-size: 12px; display: block">查詢日期 (空=最新)</NText>
          <NDatePicker v-model:value="queryDate" type="date" size="small" clearable style="width: 100%" />
        </NGi>
        <NGi :span="2">
          <NText depth="3" style="font-size: 12px; display: block">比對維度</NText>
          <NCheckboxGroup v-model:value="selectedDims" style="flex-wrap: wrap">
            <NSpace :size="4">
              <NCheckbox v-for="d in allDimensions" :key="d.value" :value="d.value" :label="d.label" size="small" />
            </NSpace>
          </NCheckboxGroup>
        </NGi>
      </NGrid>
      <NSpace style="margin-top: 8px">
        <NButton type="primary" @click="runSimulation" :loading="isLoading" :disabled="!code">
          模擬
        </NButton>
      </NSpace>
    </NCard>

    <NAlert v-if="error" type="error" style="margin-bottom: 12px">{{ error }}</NAlert>

    <!-- Results -->
    <NSpin :show="isLoading">
      <template v-if="result">
        <!-- Query info + Confidence -->
        <NSpace style="margin-bottom: 8px" align="center">
          <NTag type="info" size="small">{{ result.query.stock_code }}</NTag>
          <NText depth="3">@ {{ result.query.date }}</NText>
          <NText depth="3">| {{ result.statistics.sample_count }} 個相似案例</NText>
          <NTag v-if="confidence" :type="confidence.grade === 'HIGH' ? 'error' : confidence.grade === 'MEDIUM' ? 'warning' : 'default'" size="small" round>
            信心 {{ confidence.score }}
          </NTag>
          <NTooltip v-if="confidence?.expected_return_range?.low != null">
            <template #trigger>
              <NTag size="small" :bordered="false">
                95% CI: {{ (confidence.expected_return_range.low * 100).toFixed(1) }}% ~ {{ (confidence.expected_return_range.high * 100).toFixed(1) }}%
              </NTag>
            </template>
            樣本{{ confidence.factors.sample_size.toFixed(0) }}分 / 一致性{{ confidence.factors.consistency.toFixed(0) }}分 / 方向{{ confidence.factors.direction.toFixed(0) }}分
          </NTooltip>
          <NTag v-if="result.sniper_assessment?.tier === 'sniper'" type="error" size="small" :bordered="false">Sniper</NTag>
          <NTag v-else-if="result.sniper_assessment?.tier === 'tactical'" type="warning" size="small" :bordered="false">Tactical</NTag>
          <NTag v-if="result.statistics.small_sample" type="warning" size="small">小樣本</NTag>
        </NSpace>

        <!-- Spaghetti Chart -->
        <NCard v-if="spaghettiOption" title="走勢分佈圖 (Spaghetti Chart)" size="small" style="margin-bottom: 12px">
          <VChart :option="spaghettiOption" style="height: 350px" autoresize />
          <NSpace v-if="result.spaghetti?.stats" size="small" style="margin-top: 4px">
            <NText depth="3" style="font-size: 11px">
              {{ result.spaghetti.stats.path_count }} 條走勢線 |
              最差: {{ result.spaghetti.stats.worst_case?.stock_code }} ({{ ((result.spaghetti.stats.worst_path?.[result.spaghetti.stats.worst_path.length-1] - 1) * 100).toFixed(1) }}%) |
              最佳: {{ result.spaghetti.stats.best_case?.stock_code }} ({{ ((result.spaghetti.stats.best_path?.[result.spaghetti.stats.best_path.length-1] - 1) * 100).toFixed(1) }}%)
            </NText>
          </NSpace>
        </NCard>

        <!-- Win Rate Visual Bar -->
        <NCard title="多期間勝率" size="small" style="margin-bottom: 12px">
          <div style="display: flex; gap: 8px; flex-wrap: wrap">
            <div v-for="bar in winRateBarData" :key="bar.label" style="flex: 1; min-width: 70px; text-align: center">
              <div style="font-size: 11px; color: #999; margin-bottom: 4px">{{ bar.label }}</div>
              <NProgress
                type="line"
                :percentage="bar.value"
                :color="bar.value >= 55 ? '#d03050' : bar.value >= 45 ? '#f0a020' : '#18a058'"
                :show-indicator="false"
                :height="20"
                :border-radius="4"
                style="margin-bottom: 2px"
              />
              <div :style="{ fontSize: '14px', fontWeight: 600, color: bar.value >= 55 ? '#d03050' : bar.value >= 45 ? '#f0a020' : '#18a058' }">
                {{ bar.value }}%
              </div>
              <div style="font-size: 10px; color: #bbb">n={{ bar.count }}</div>
            </div>
          </div>
        </NCard>

        <!-- Detailed horizon stats table -->
        <NCard title="期間統計明細" size="small" style="margin-bottom: 12px">
          <NDataTable
            :columns="horizonColumns"
            :data="horizonStats"
            size="small"
            :bordered="false"
            :pagination="false"
          />
        </NCard>

        <!-- Similar cases table -->
        <NCard :title="`相似案例 (${result.cases.length})`" size="small">
          <NDataTable
            :columns="caseColumns"
            :data="result.cases"
            :pagination="{ pageSize: 20, showSizePicker: true, pageSizes: [10, 20, 50] }"
            :row-props="(r: any) => ({ style: { cursor: 'pointer' }, onClick: () => app.selectStock(r.stock_code) })"
            size="small"
            :bordered="false"
            :single-line="false"
            :scroll-x="800"
          />
        </NCard>
      </template>
    </NSpin>
  </div>
</template>
