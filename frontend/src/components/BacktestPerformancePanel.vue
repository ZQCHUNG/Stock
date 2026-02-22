<script setup lang="ts">
import { ref, computed } from 'vue'
import { h } from 'vue'
import {
  NCard, NButton, NSpace, NSpin, NStatistic, NGrid, NGi, NSwitch, NTag,
  NDataTable, useMessage,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { use } from 'echarts/core'
import { LineChart, HeatmapChart } from 'echarts/charts'
import {
  GridComponent, TooltipComponent, ToolboxComponent,
  DataZoomComponent, LegendComponent, VisualMapComponent, MarkLineComponent,
  MarkPointComponent, MarkAreaComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'
import { backtestApi } from '../api/backtest'
import { useChartTheme } from '../composables/useChartTheme'

use([
  LineChart, HeatmapChart, GridComponent, TooltipComponent, ToolboxComponent,
  DataZoomComponent, LegendComponent, VisualMapComponent, MarkLineComponent,
  MarkPointComponent, MarkAreaComponent, CanvasRenderer,
])

const props = defineProps<{
  periodDays: number
  capital: number
}>()

const msg = useMessage()
const { colors: chartColors, tooltipStyle } = useChartTheme()

const loading = ref(false)
const data = ref<any>(null)
const logScale = ref(false)

async function runBacktest() {
  loading.value = true
  data.value = null
  try {
    data.value = await backtestApi.portfolioBold(props.periodDays, props.capital)
    msg.success(`Portfolio backtest complete: ${data.value.total_trades} trades`)
  } catch (e: any) {
    msg.error(`Backtest failed: ${e?.message || e}`)
  }
  loading.value = false
}

function fmtNum(v: number) {
  if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(1)}M`
  if (Math.abs(v) >= 1e3) return `${(v / 1e3).toFixed(0)}K`
  return v.toFixed(0)
}

// === Equity Curve + Drawdown (Synced) ===
const equityOption = computed(() => {
  if (!data.value?.dates?.length) return {}
  const cc = chartColors.value
  const { dates, equity, benchmark, drawdown, holdings_count, mdd_info } = data.value

  // Build benchmark aligned to strategy dates
  const benchMap: Record<string, number> = {}
  if (benchmark?.length) {
    benchmark.forEach((b: any) => { benchMap[b.date] = b.value })
  }
  const benchSeries = dates.map((d: string) => benchMap[d] ?? null)

  // MDD annotation area
  const markArea: any[] = []
  if (mdd_info?.peak_date && mdd_info?.trough_date) {
    markArea.push([
      { xAxis: mdd_info.peak_date, itemStyle: { color: 'rgba(229,62,62,0.08)' } },
      { xAxis: mdd_info.recovery_date || mdd_info.trough_date },
    ])
  }

  return {
    tooltip: {
      trigger: 'axis',
      ...tooltipStyle.value,
      formatter: (params: any[]) => {
        const dateStr = params[0]?.axisValue || ''
        const dateIdx = dates.indexOf(dateStr)
        let html = `<b>${dateStr}</b><br/>`
        params.forEach((p: any) => {
          if (p.value != null) {
            html += `${p.marker} ${p.seriesName}: ${fmtNum(p.value)}<br/>`
          }
        })
        if (holdings_count && dateIdx >= 0) {
          html += `<span style="color:#999">Holdings: ${holdings_count[dateIdx]}</span>`
        }
        return html
      },
    },
    legend: {
      data: ['Strategy', 'TAIEX Benchmark'],
      textStyle: { color: cc.legendText, fontSize: 11 },
      top: 0,
    },
    grid: [
      { left: 80, right: 20, top: 35, bottom: '35%' },  // Equity
      { left: 80, right: 20, top: '72%', bottom: 40 },   // Drawdown
    ],
    xAxis: [
      {
        type: 'category', data: dates, gridIndex: 0,
        axisLabel: { show: false },
        axisTick: { show: false },
      },
      {
        type: 'category', data: dates, gridIndex: 1,
        axisLabel: { color: cc.axisLabel, fontSize: 10 },
      },
    ],
    yAxis: [
      {
        type: logScale.value ? 'log' : 'value',
        gridIndex: 0,
        axisLabel: { formatter: (v: number) => fmtNum(v), color: cc.axisLabel },
        splitLine: { lineStyle: { color: cc.splitLine } },
      },
      {
        type: 'value', gridIndex: 1, max: 0,
        axisLabel: { formatter: (v: number) => `${(v * 100).toFixed(0)}%`, color: cc.axisLabel },
        splitLine: { lineStyle: { color: cc.splitLine } },
      },
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1], start: 0, end: 100 },
      { type: 'slider', xAxisIndex: [0, 1], start: 0, end: 100, height: 18, bottom: 4 },
    ],
    series: [
      // Equity curve
      {
        name: 'Strategy',
        type: 'line',
        data: equity,
        xAxisIndex: 0,
        yAxisIndex: 0,
        symbol: 'none',
        lineStyle: { width: 2, color: '#18a058' },
        areaStyle: { opacity: 0.08, color: '#18a058' },
        markArea: markArea.length ? { silent: true, data: markArea } : undefined,
        markLine: mdd_info?.peak_date ? {
          silent: true,
          symbol: 'none',
          data: [
            {
              name: `MDD ${mdd_info.mdd_pct}%`,
              yAxis: equity[dates.indexOf(mdd_info.peak_date)] || 0,
              lineStyle: { type: 'dashed', color: '#e53e3e', width: 1 },
              label: {
                formatter: `MDD: ${mdd_info.mdd_pct}% (${mdd_info.drawdown_days}d)`,
                fontSize: 10,
                color: '#e53e3e',
              },
            },
          ],
        } : undefined,
      },
      // TAIEX benchmark
      {
        name: 'TAIEX Benchmark',
        type: 'line',
        data: benchSeries,
        xAxisIndex: 0,
        yAxisIndex: 0,
        symbol: 'none',
        lineStyle: { width: 1, color: '#999', type: 'dashed' },
        connectNulls: true,
      },
      // Drawdown underwater chart
      {
        name: 'Drawdown',
        type: 'line',
        data: drawdown,
        xAxisIndex: 1,
        yAxisIndex: 1,
        symbol: 'none',
        areaStyle: { color: 'rgba(229,62,62,0.3)' },
        lineStyle: { width: 1, color: '#e53e3e' },
        markPoint: mdd_info?.trough_date ? {
          data: [{
            coord: [mdd_info.trough_date, drawdown[dates.indexOf(mdd_info.trough_date)]],
            symbol: 'pin',
            symbolSize: 30,
            itemStyle: { color: '#e53e3e' },
            label: { formatter: `${mdd_info.mdd_pct}%`, fontSize: 9, color: '#fff' },
          }],
        } : undefined,
      },
    ],
  }
})

// === Monthly Returns Heatmap ===
const heatmapOption = computed(() => {
  if (!data.value?.monthly_returns?.length) return {}
  const cc = chartColors.value
  const mr = data.value.monthly_returns as { year: number; month: number; return_pct: number }[]

  const years = [...new Set(mr.map(r => r.year))].sort()
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

  const heatData: [number, number, number | null][] = []
  const yearTotals: Record<number, number> = {}

  for (const r of mr) {
    const yi = years.indexOf(r.year)
    heatData.push([r.month - 1, yi, r.return_pct])
    yearTotals[r.year] = (yearTotals[r.year] || 0) + r.return_pct
  }

  // Add yearly total column
  const extMonths = [...months, 'Year']
  for (const y of years) {
    const yi = years.indexOf(y)
    heatData.push([12, yi, yearTotals[y] != null ? Math.round(yearTotals[y] * 10) / 10 : null])
  }

  return {
    tooltip: {
      ...tooltipStyle.value,
      formatter: (p: any) => {
        const val = p.value?.[2]
        if (val == null) return ''
        const monthLabel = extMonths[p.value[0]]
        const yearLabel = years[p.value[1]]
        return `${yearLabel} ${monthLabel}: <b>${val > 0 ? '+' : ''}${val}%</b>`
      },
    },
    grid: { left: 60, right: 60, top: 10, bottom: 10 },
    xAxis: {
      type: 'category',
      data: extMonths,
      axisLabel: { color: cc.axisLabel, fontSize: 10 },
      splitArea: { show: true },
    },
    yAxis: {
      type: 'category',
      data: years.map(String),
      axisLabel: { color: cc.axisLabel, fontSize: 10 },
      splitArea: { show: true },
    },
    visualMap: {
      min: -10,
      max: 10,
      calculable: true,
      orient: 'vertical',
      right: 0,
      top: 'center',
      inRange: {
        color: ['#d73027', '#f46d43', '#fdae61', '#fee08b', '#ffffbf', '#d9ef8b', '#a6d96a', '#66bd63', '#1a9850'],
      },
      textStyle: { color: cc.axisLabel, fontSize: 10 },
    },
    series: [{
      type: 'heatmap',
      data: heatData.filter(d => d[2] != null),
      label: {
        show: true,
        formatter: (p: any) => {
          const v = p.value?.[2]
          if (v == null) return ''
          return `${v > 0 ? '+' : ''}${v.toFixed(1)}`
        },
        fontSize: 10,
      },
      emphasis: {
        itemStyle: { shadowBlur: 6, shadowColor: 'rgba(0,0,0,0.3)' },
      },
    }],
  }
})

// Trade table columns
const tradeColumns: DataTableColumns = [
  { title: 'Code', key: 'code', width: 70 },
  { title: 'Entry', key: 'date_open', width: 95 },
  { title: 'Exit', key: 'date_close', width: 95 },
  {
    title: 'Return',
    key: 'return_pct',
    width: 75,
    sorter: (a: any, b: any) => a.return_pct - b.return_pct,
    render: (row: any) => h(
      'span',
      { style: `color: ${row.return_pct >= 0 ? '#18a058' : '#d03050'}; font-weight: 600` },
      `${row.return_pct >= 0 ? '+' : ''}${(row.return_pct * 100).toFixed(1)}%`,
    ),
  },
  {
    title: 'Exit Reason',
    key: 'exit_reason',
    width: 110,
    render: (row: any) => h(NTag, { size: 'small', type: 'default' }, () => row.exit_reason || '-'),
  },
  { title: 'Entry Type', key: 'entry_type', width: 80 },
]
</script>

<template>
  <div>
    <!-- Controls -->
    <NCard size="small" style="margin-bottom: 12px">
      <NSpace align="center" :wrap="false" :size="16">
        <NButton type="primary" :loading="loading" @click="runBacktest">
          Run Portfolio Bold Backtest
        </NButton>
        <NSpace align="center" :size="8">
          <span style="font-size: 13px; color: #999">Log Scale:</span>
          <NSwitch v-model:value="logScale" size="small" />
        </NSpace>
        <span v-if="data" style="font-size: 12px; color: #999; margin-left: auto">
          {{ data.total_trades }} trades | {{ data.dates?.length || 0 }} days
        </span>
      </NSpace>
    </NCard>

    <NSpin :show="loading">
      <template v-if="data">
        <!-- Summary Stats -->
        <NGrid :cols="6" :x-gap="12" style="margin-bottom: 12px">
          <NGi>
            <NCard size="small">
              <NStatistic label="Total Return">
                <span :style="{ color: data.total_return >= 0 ? '#18a058' : '#d03050' }">
                  {{ data.total_return >= 0 ? '+' : '' }}{{ data.total_return.toFixed(1) }}%
                </span>
              </NStatistic>
            </NCard>
          </NGi>
          <NGi>
            <NCard size="small">
              <NStatistic label="Annual Return">
                <span :style="{ color: data.annual_return >= 0 ? '#18a058' : '#d03050' }">
                  {{ data.annual_return >= 0 ? '+' : '' }}{{ data.annual_return.toFixed(1) }}%
                </span>
              </NStatistic>
            </NCard>
          </NGi>
          <NGi>
            <NCard size="small">
              <NStatistic label="Max Drawdown">
                <span style="color: #d03050">{{ data.max_drawdown.toFixed(1) }}%</span>
              </NStatistic>
            </NCard>
          </NGi>
          <NGi>
            <NCard size="small">
              <NStatistic label="Calmar" :value="data.calmar_ratio.toFixed(2)" />
            </NCard>
          </NGi>
          <NGi>
            <NCard size="small">
              <NStatistic label="Sharpe" :value="data.sharpe_ratio.toFixed(2)" />
            </NCard>
          </NGi>
          <NGi>
            <NCard size="small">
              <NStatistic label="Win Rate">
                {{ data.win_rate.toFixed(1) }}%
              </NStatistic>
            </NCard>
          </NGi>
        </NGrid>

        <!-- MDD Info Banner -->
        <NCard v-if="data.mdd_info" size="small" style="margin-bottom: 12px; background: rgba(229,62,62,0.05)">
          <NSpace :size="24">
            <span style="font-size: 12px; color: #d03050; font-weight: 600">
              Max Drawdown: {{ data.mdd_info.mdd_pct }}%
            </span>
            <span style="font-size: 12px; color: #999">
              Peak: {{ data.mdd_info.peak_date }} | Trough: {{ data.mdd_info.trough_date }}
            </span>
            <span style="font-size: 12px; color: #999">
              Drawdown: {{ data.mdd_info.drawdown_days }}d
              <template v-if="data.mdd_info.recovery_days != null">
                | Recovery: {{ data.mdd_info.recovery_days }}d
                | Total Underwater: {{ data.mdd_info.total_underwater_days }}d
              </template>
              <template v-else>
                | Not yet recovered
              </template>
            </span>
          </NSpace>
        </NCard>

        <!-- Equity Curve + Drawdown -->
        <NCard size="small" title="Equity Curve & Drawdown" style="margin-bottom: 12px">
          <VChart
            :option="equityOption"
            :autoresize="true"
            style="height: 450px"
          />
        </NCard>

        <!-- Monthly Returns Heatmap -->
        <NCard size="small" title="Monthly Returns Heatmap" style="margin-bottom: 12px">
          <VChart
            :option="heatmapOption"
            :autoresize="true"
            :style="{ height: `${Math.max(180, (data.monthly_returns ? [...new Set(data.monthly_returns.map((r: any) => r.year))].length : 3) * 40 + 60)}px` }"
          />
        </NCard>

        <!-- Trade Log -->
        <NCard size="small" title="Trade Log" style="margin-bottom: 12px">
          <NDataTable
            :columns="tradeColumns"
            :data="data.trade_markers || []"
            :bordered="true"
            :single-line="false"
            :pagination="{ pageSize: 20 }"
            size="small"
            max-height="400"
            virtual-scroll
            style="font-size: 12px"
          />
        </NCard>
      </template>
    </NSpin>
  </div>
</template>
