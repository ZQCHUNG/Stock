<script setup lang="ts">
import { h, ref, computed, onMounted, reactive } from 'vue'
import { NButton, NCard, NCheckbox, NDataTable, NEmpty, NSpace, NTag } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { use } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, ToolboxComponent, DataZoomComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { btResultsApi, type SavedBtResult } from '../api/btResults'
import { fmtPct, priceColor } from '../utils/format'
import { message } from '../utils/discrete'
import { useAppStore } from '../stores/app'
import { useChartTheme } from '../composables/useChartTheme'
import ChartContainer from './ChartContainer.vue'

use([LineChart, GridComponent, TooltipComponent, LegendComponent, ToolboxComponent, DataZoomComponent, CanvasRenderer])

const app = useAppStore()
const { colors: chartColors, tooltipStyle } = useChartTheme()

const results = ref<SavedBtResult[]>([])
const isLoading = ref(false)
const pagination = reactive({ page: 1, pageSize: 15, showSizePicker: true, pageSizes: [10, 15, 30] })

// Comparison state
const selectedIndices = ref<Set<number>>(new Set())
const isComparing = ref(false)
const comparisonData = ref<SavedBtResult[]>([])
const isLoadingComparison = ref(false)

async function load() {
  isLoading.value = true
  try {
    results.value = await btResultsApi.list()
  } catch { /* handled */ }
  isLoading.value = false
}

async function remove(index: number) {
  try {
    await btResultsApi.remove(index)
    selectedIndices.value.delete(index)
    message.success('已刪除')
    await load()
  } catch { /* handled */ }
}

function toggleSelect(index: number) {
  const s = selectedIndices.value
  if (s.has(index)) {
    s.delete(index)
  } else {
    if (s.size >= 4) {
      message.warning('最多選擇 4 個結果比較')
      return
    }
    s.add(index)
  }
}

async function startCompare() {
  if (selectedIndices.value.size < 2) {
    message.warning('請至少選擇 2 個結果')
    return
  }
  isLoadingComparison.value = true
  try {
    const all = await btResultsApi.listWithEquity()
    comparisonData.value = [...selectedIndices.value].sort().map(i => all[i]).filter((x): x is SavedBtResult => !!x)
    isComparing.value = true
  } catch { /* handled */ }
  isLoadingComparison.value = false
}

function exitCompare() {
  isComparing.value = false
  comparisonData.value = []
}

onMounted(load)

const COMPARE_COLORS = ['#2196f3', '#ff9800', '#4caf50', '#e91e63']

// Comparison metrics table
const comparisonMetrics = computed(() => {
  if (!comparisonData.value.length) return []
  const metricKeys = [
    { key: 'total_return', label: '總報酬', fmt: fmtPct, color: true },
    { key: 'annual_return', label: '年化報酬', fmt: fmtPct, color: true },
    { key: 'max_drawdown', label: '最大回撤', fmt: fmtPct, color: false },
    { key: 'sharpe_ratio', label: 'Sharpe', fmt: (v: any) => v?.toFixed(2) || '-', color: false },
    { key: 'sortino_ratio', label: 'Sortino', fmt: (v: any) => v?.toFixed(2) || '-', color: false },
    { key: 'calmar_ratio', label: 'Calmar', fmt: (v: any) => v?.toFixed(2) || '-', color: false },
    { key: 'win_rate', label: '勝率', fmt: fmtPct, color: false },
    { key: 'profit_factor', label: '盈虧比', fmt: (v: any) => v?.toFixed(2) || '-', color: false },
    { key: 'total_trades', label: '交易次數', fmt: (v: any) => v ?? '-', color: false },
  ]
  return metricKeys.map(mk => {
    const row: any = { metric: mk.label }
    comparisonData.value.forEach((r, i) => {
      const val = r.metrics?.[mk.key]
      row[`val_${i}`] = mk.fmt(val)
      if (mk.color) row[`color_${i}`] = priceColor(val)
    })
    return row
  })
})

const comparisonTableColumns = computed<DataTableColumns>(() => {
  const cols: DataTableColumns = [
    { title: '指標', key: 'metric', width: 100, fixed: 'left' },
  ]
  comparisonData.value.forEach((r, i) => {
    cols.push({
      title: () => h('span', { style: { color: COMPARE_COLORS[i], fontWeight: 600 } }, `${r.name} (${r.stockCode})`),
      key: `val_${i}`,
      width: 130,
      render: (row: any) => h('span', {
        style: { fontWeight: 600, ...(row[`color_${i}`] ? { color: row[`color_${i}`] } : {}) },
      }, row[`val_${i}`]),
    })
  })
  return cols
})

// Equity curve comparison chart
const equityCompareOption = computed(() => {
  if (!comparisonData.value.length) return {}
  const cc = chartColors.value

  // Normalize equity curves to percentage returns for fair comparison
  const series = comparisonData.value
    .filter(r => r.equityCurve?.dates?.length)
    .map((r, i) => {
      const vals = r.equityCurve!.values
      const base = vals[0] || 1
      return {
        name: `${r.name} (${r.stockCode})`,
        type: 'line' as const,
        data: vals.map(v => +((v / base - 1) * 100).toFixed(2)),
        symbol: 'none',
        lineStyle: { width: 2, color: COMPARE_COLORS[i] },
        itemStyle: { color: COMPARE_COLORS[i] },
      }
    })

  if (!series.length) return {}

  // Use the longest date array
  const longestResult = comparisonData.value
    .filter(r => r.equityCurve?.dates?.length)
    .sort((a, b) => (b.equityCurve!.dates.length) - (a.equityCurve!.dates.length))[0]

  return {
    tooltip: {
      trigger: 'axis',
      ...tooltipStyle.value,
      formatter: (params: any[]) => {
        if (!params?.length) return ''
        let html = `<div style="font-size:12px"><b>${params[0].name}</b>`
        params.forEach((p: any) => {
          html += `<br/><span style="color:${p.color}">●</span> ${p.seriesName}: ${p.value >= 0 ? '+' : ''}${p.value}%`
        })
        return html + '</div>'
      },
    },
    legend: {
      data: series.map(s => s.name),
      textStyle: { color: cc.legendText, fontSize: 11 },
      bottom: 0,
    },
    grid: { left: 60, right: 20, top: 20, bottom: 60 },
    dataZoom: [
      { type: 'inside', start: 0, end: 100 },
      { type: 'slider', start: 0, end: 100, height: 18, bottom: 4, borderColor: 'transparent' },
    ],
    xAxis: {
      type: 'category',
      data: longestResult!.equityCurve!.dates,
      axisLabel: { color: cc.axisLabel, fontSize: 10 },
    },
    yAxis: {
      type: 'value',
      axisLabel: { formatter: (v: number) => `${v}%`, color: cc.axisLabel },
      splitLine: { lineStyle: { color: cc.splitLine } },
    },
    series,
  }
})

const hasEquityData = computed(() =>
  comparisonData.value.some(r => r.equityCurve?.dates?.length),
)

const columns: DataTableColumns = [
  {
    title: '選', key: 'select', width: 40,
    render: (_r: any, index: number) =>
      h(NCheckbox, {
        checked: selectedIndices.value.has(index),
        onUpdateChecked: () => toggleSelect(index),
      }),
  },
  { title: '名稱', key: 'name', width: 120, sorter: 'default' },
  {
    title: '股票', key: 'stockCode', width: 80,
    render: (r: any) => h('span', { style: { fontWeight: 600, cursor: 'pointer' }, onClick: () => app.selectStock(r.stockCode) },
      `${r.stockCode}`),
  },
  {
    title: '總報酬', key: 'total_return', width: 90,
    sorter: (a: any, b: any) => (a.metrics?.total_return || 0) - (b.metrics?.total_return || 0),
    render: (r: any) => h('span', { style: { color: priceColor(r.metrics?.total_return), fontWeight: 600 } }, fmtPct(r.metrics?.total_return)),
  },
  {
    title: '年化報酬', key: 'annual_return', width: 90,
    sorter: (a: any, b: any) => (a.metrics?.annual_return || 0) - (b.metrics?.annual_return || 0),
    render: (r: any) => h('span', { style: { color: priceColor(r.metrics?.annual_return) } }, fmtPct(r.metrics?.annual_return)),
  },
  {
    title: '最大回撤', key: 'max_drawdown', width: 90,
    render: (r: any) => h('span', { style: { color: '#e53e3e' } }, fmtPct(r.metrics?.max_drawdown)),
  },
  {
    title: 'Sharpe', key: 'sharpe_ratio', width: 80,
    sorter: (a: any, b: any) => (a.metrics?.sharpe_ratio || 0) - (b.metrics?.sharpe_ratio || 0),
    render: (r: any) => r.metrics?.sharpe_ratio?.toFixed(2) || '-',
  },
  {
    title: '勝率', key: 'win_rate', width: 70,
    render: (r: any) => fmtPct(r.metrics?.win_rate),
  },
  {
    title: '交易次數', key: 'total_trades', width: 80,
    render: (r: any) => r.metrics?.total_trades ?? '-',
  },
  {
    title: '日期', key: 'savedAt', width: 100,
    render: (r: any) => r.savedAt?.slice(0, 10),
  },
  {
    title: '操作', key: 'actions', width: 70,
    render: (_r: any, index: number) =>
      h(NButton, { size: 'tiny', quaternary: true, type: 'error', onClick: () => remove(index) }, () => '刪除'),
  },
]
</script>

<template>
  <div>
    <!-- Comparison View -->
    <template v-if="isComparing">
      <NSpace style="margin-bottom: 12px" align="center">
        <NButton size="small" @click="exitCompare">返回列表</NButton>
        <NTag type="info" size="small">比較 {{ comparisonData.length }} 個結果</NTag>
      </NSpace>

      <!-- Metrics Comparison Table -->
      <NCard size="small" title="指標比較" style="margin-bottom: 16px">
        <NDataTable
          :columns="comparisonTableColumns"
          :data="comparisonMetrics"
          :bordered="false"
          size="small"
          :scroll-x="100 + comparisonData.length * 130"
        />
      </NCard>

      <!-- Equity Curve Overlay Chart -->
      <NCard v-if="hasEquityData" size="small" title="權益曲線比較（歸一化 %）">
        <ChartContainer :option="equityCompareOption" height="400px" aria-label="回測結果比較圖表" />
      </NCard>
      <NCard v-else size="small">
        <NEmpty description="所選結果無權益曲線數據（請重新保存含權益曲線的結果）" />
      </NCard>
    </template>

    <!-- List View -->
    <template v-else>
      <NSpace style="margin-bottom: 12px" align="center">
        <NButton size="small" @click="load" :loading="isLoading">重新載入</NButton>
        <NButton
          v-if="results.length >= 2"
          size="small"
          type="primary"
          :disabled="selectedIndices.size < 2"
          :loading="isLoadingComparison"
          @click="startCompare"
        >
          比較選中 ({{ selectedIndices.size }})
        </NButton>
        <NTag v-if="results.length" size="small">共 {{ results.length }} 筆</NTag>
        <span v-if="results.length >= 2" style="font-size: 11px; color: var(--text-muted)">
          勾選 2-4 個結果進行比較
        </span>
      </NSpace>

      <NEmpty v-if="!results.length && !isLoading" description="尚無保存的回測結果" style="margin: 40px 0" />

      <NDataTable
        v-if="results.length"
        :columns="columns"
        :data="results"
        :pagination="pagination"
        size="small"
        :bordered="false"
        :single-line="false"
        :scroll-x="920"
      />
    </template>
  </div>
</template>
