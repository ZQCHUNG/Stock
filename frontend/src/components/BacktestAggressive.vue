<script setup lang="ts">
import { ref, reactive, computed, watch } from 'vue'
import {
  NCard, NButton, NGrid, NGi, NTabs, NTabPane, NDataTable, NSpace, NText, NSpin, NTag, NProgress,
} from 'naive-ui'
import { use } from 'echarts/core'
import { LineChart, PieChart, BarChart, RadarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, ToolboxComponent, DataZoomComponent, LegendComponent, RadarComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useAppStore } from '../stores/app'
import { useBacktestStore } from '../stores/backtest'
import { fmtPct, fmtNum, priceColor, downloadCsv } from '../utils/format'
import { useChartTheme } from '../composables/useChartTheme'
import { useResponsive } from '../composables/useResponsive'
import MetricCard from './MetricCard.vue'
import ChartContainer from './ChartContainer.vue'
import CandlestickChart from './CandlestickChart.vue'
import { analysisApi } from '../api/analysis'
import type { TimeSeriesData } from '../api/stocks'

use([LineChart, PieChart, BarChart, RadarChart, GridComponent, TooltipComponent, ToolboxComponent, DataZoomComponent, LegendComponent, RadarComponent, CanvasRenderer])

const props = defineProps<{
  periodDays: number
  capital: number
  costParams?: { commission_rate: number; tax_rate: number; slippage: number }
}>()

const app = useAppStore()
const bt = useBacktestStore()
const { colors: chartColors, tooltipStyle, toolboxConfig } = useChartTheme()
const { cols } = useResponsive()
const metricCols = cols(2, 3, 4)

const klineData = ref<TimeSeriesData | null>(null)
const klineLoading = ref(false)

const r = computed(() => bt.aggressiveResult)
const am = computed(() => r.value?.aggressive_metrics || {})

async function runBacktest() {
  await bt.runAggressive(app.currentStockCode, {
    period_days: props.periodDays,
    initial_capital: props.capital,
    ...props.costParams,
  })
}

watch(r, async (val) => {
  if (val?.trades?.length) {
    klineLoading.value = true
    try {
      klineData.value = await analysisApi.indicators(app.currentStockCode, props.periodDays, 0)
    } catch { /* silent */ }
    klineLoading.value = false
  }
})

// Home Run badge color
function hrColor(count: number) {
  if (count >= 5) return '#ff6b35'
  if (count >= 3) return '#38a169'
  if (count >= 1) return '#3182ce'
  return '#718096'
}

// Equity curve chart
const equityOption = computed(() => {
  if (!r.value?.equity_curve?.dates?.length) return {}
  const cc = chartColors.value
  const dates = r.value.equity_curve.dates
  const values = r.value.equity_curve.values as number[]
  const trades = r.value.trades || []
  const dateIdx: Record<string, number> = {}
  dates.forEach((d: string, i: number) => { dateIdx[d.slice(0, 10)] = i })
  const buyMarks: number[][] = []
  const sellMarks: number[][] = []
  const hrMarks: number[][] = []
  trades.forEach((t: any) => {
    const od = t.date_open?.slice(0, 10)
    const cd = t.date_close?.slice(0, 10)
    const oi = od ? dateIdx[od] : undefined
    const ci = cd ? dateIdx[cd] : undefined
    if (oi !== undefined) buyMarks.push([oi, values[oi] as number])
    if (ci !== undefined) {
      sellMarks.push([ci, values[ci] as number])
      if ((t.return_pct || 0) >= 0.5) hrMarks.push([ci, values[ci] as number])
    }
  })
  return {
    tooltip: { trigger: 'axis', ...tooltipStyle.value },
    toolbox: { ...toolboxConfig.value, feature: { restore: toolboxConfig.value.feature.restore, saveAsImage: toolboxConfig.value.feature.saveAsImage } },
    legend: { data: ['权益', '买入', '卖出', 'Home Run'], textStyle: { color: cc.legendText, fontSize: 11 }, top: 0 },
    grid: { left: 80, right: 20, top: 30, bottom: 50 },
    xAxis: { type: 'category', data: dates, axisLabel: { color: cc.axisLabel } },
    yAxis: { type: 'value', axisLabel: { formatter: (v: number) => fmtNum(v), color: cc.axisLabel }, splitLine: { lineStyle: { color: cc.splitLine } } },
    dataZoom: [
      { type: 'inside', start: 0, end: 100 },
      { type: 'slider', start: 0, end: 100, height: 20, bottom: 4, borderColor: 'transparent', backgroundColor: cc.splitLine },
    ],
    series: [
      { name: '权益', type: 'line', data: values, symbol: 'none', areaStyle: { opacity: 0.15 }, lineStyle: { width: 1.5, color: '#ff6b35' } },
      { name: '买入', type: 'scatter', data: buyMarks, symbol: 'triangle', symbolSize: 8, itemStyle: { color: '#38a169' }, z: 10 },
      { name: '卖出', type: 'scatter', data: sellMarks, symbol: 'diamond', symbolSize: 8, itemStyle: { color: '#e53e3e' }, z: 10 },
      { name: 'Home Run', type: 'scatter', data: hrMarks, symbol: 'star', symbolSize: 14, itemStyle: { color: '#ff6b35' }, z: 20 },
    ],
  }
})

// Exit reason pie
const exitPieOption = computed(() => {
  const trades = r.value?.trades || []
  const counts: Record<string, number> = {}
  trades.forEach((t: any) => { counts[t.exit_reason] = (counts[t.exit_reason] || 0) + 1 })
  const data = Object.entries(counts).map(([name, value]) => ({ name, value }))
  const cc = chartColors.value
  return {
    tooltip: { trigger: 'item', ...tooltipStyle.value },
    series: [{ type: 'pie', radius: ['40%', '70%'], data, label: { fontSize: 11, color: cc.legendText } }],
  }
})

// Drawdown chart
const drawdownOption = computed(() => {
  if (!r.value?.equity_curve?.dates?.length) return {}
  const cc = chartColors.value
  const vals = r.value.equity_curve.values as number[]
  let peak = vals[0] ?? 0
  const dd = vals.map((v: number) => {
    if (v > peak!) peak = v
    return +((v / peak! - 1) * 100).toFixed(2)
  })
  return {
    tooltip: { trigger: 'axis', ...tooltipStyle.value },
    grid: { left: 60, right: 20, top: 20, bottom: 50 },
    xAxis: { type: 'category', data: r.value.equity_curve.dates, axisLabel: { color: cc.axisLabel } },
    yAxis: { type: 'value', max: 0, axisLabel: { formatter: (v: number) => `${v}%`, color: cc.axisLabel }, splitLine: { lineStyle: { color: cc.splitLine } } },
    dataZoom: [{ type: 'inside', start: 0, end: 100 }, { type: 'slider', start: 0, end: 100, height: 18, bottom: 4 }],
    series: [{ type: 'line', data: dd, symbol: 'none', areaStyle: { color: 'rgba(229,62,62,0.3)' }, lineStyle: { width: 1, color: '#e53e3e' } }],
  }
})

// Trade return distribution bar chart
const returnDistOption = computed(() => {
  const trades = r.value?.trades || []
  if (!trades.length) return {}
  const cc = chartColors.value
  const bins = ['-20%+', '-15%', '-10%', '-5%', '0%', '+5%', '+10%', '+15%', '+20%', '+30%', '+50%', '+100%+']
  const edges = [-Infinity, -0.15, -0.10, -0.05, 0, 0.05, 0.10, 0.15, 0.20, 0.30, 0.50, 1.00, Infinity]
  const counts = new Array(bins.length).fill(0)
  trades.forEach((t: any) => {
    const ret = t.return_pct || 0
    for (let i = 0; i < edges.length - 1; i++) {
      if (ret >= edges[i] && ret < edges[i + 1]) { counts[i]++; break }
    }
  })
  return {
    tooltip: { trigger: 'axis', ...tooltipStyle.value },
    grid: { left: 40, right: 20, top: 20, bottom: 40 },
    xAxis: { type: 'category', data: bins, axisLabel: { color: cc.axisLabel, fontSize: 10, rotate: 30 } },
    yAxis: { type: 'value', axisLabel: { color: cc.axisLabel }, splitLine: { lineStyle: { color: cc.splitLine } } },
    series: [{
      type: 'bar',
      data: counts.map((v: number, i: number) => ({
        value: v,
        itemStyle: { color: i < 4 ? '#e53e3e' : i === 4 ? '#718096' : i < 8 ? '#38a169' : '#ff6b35' },
      })),
    }],
  }
})

function exportTrades() {
  downloadCsv(r.value?.trades || [], [
    { key: 'date_open', label: '开仓日' },
    { key: 'date_close', label: '平仓日' },
    { key: 'price_open', label: '买入价' },
    { key: 'price_close', label: '卖出价' },
    { key: 'pnl', label: '损益' },
    { key: 'return_pct', label: '报酬率' },
    { key: 'hold_days', label: '持有天数' },
    { key: 'exit_reason', label: '出场原因' },
  ], `aggressive_${app.currentStockCode}_trades.csv`)
}

const tradePagination = reactive({ page: 1, pageSize: 15, showSizePicker: true, pageSizes: [10, 15, 25, 50] })

const tradeColumns = [
  { title: '开仓日', key: 'date_open', width: 100, render: (row: any) => row.date_open?.slice(0, 10) },
  { title: '平仓日', key: 'date_close', width: 100, render: (row: any) => row.date_close?.slice(0, 10) },
  { title: '买入价', key: 'price_open', width: 80, render: (row: any) => row.price_open?.toFixed(2) },
  { title: '卖出价', key: 'price_close', width: 80, render: (row: any) => row.price_close?.toFixed(2) },
  { title: '损益', key: 'pnl', width: 100, render: (row: any) => fmtNum(row.pnl) },
  { title: '报酬%', key: 'return_pct', width: 80, render: (row: any) => fmtPct(row.return_pct) },
  { title: '持有天', key: 'hold_days', width: 70 },
  { title: '出场原因', key: 'exit_reason', width: 120 },
]
</script>

<template>
  <div>
    <NSpace align="center" style="margin-bottom: 16px">
      <NButton type="error" @click="runBacktest" :loading="bt.isLoading">
        执行 Aggressive 回测
      </NButton>
    </NSpace>

    <NText depth="3" style="font-size: 11px; display: block; margin-bottom: 12px">
      Aggressive (WarriorExitEngine)：ATR 3x 宽幅追踪、MA20/MA50 结构出场、-20% 灾难停损、60天最长持有。
      专门捕捉 +50%~+200% 大波段。加码：MA20 回踩 + 量能确认。
    </NText>

    <template v-if="r">
      <!-- Core Metrics -->
      <NGrid :cols="metricCols" :x-gap="12" :y-gap="12" style="margin-bottom: 16px">
        <NGi><MetricCard title="总报酬率" :value="fmtPct(r.total_return)" :color="priceColor(r.total_return)" /></NGi>
        <NGi><MetricCard title="年化报酬" :value="fmtPct(r.annual_return)" :color="priceColor(r.annual_return)" /></NGi>
        <NGi><MetricCard title="最大回撤" :value="fmtPct(r.max_drawdown)" color="#e53e3e" /></NGi>
        <NGi><MetricCard title="Sharpe" :value="r.sharpe_ratio?.toFixed(2) || '-'" /></NGi>
        <NGi><MetricCard title="胜率" :value="fmtPct(r.win_rate)" /></NGi>
        <NGi><MetricCard title="盈亏比" :value="r.profit_factor?.toFixed(2) || '-'" /></NGi>
        <NGi><MetricCard title="交易次数" :value="r.total_trades" /></NGi>
        <NGi><MetricCard title="平均持有天数" :value="r.avg_holding_days?.toFixed(1) || '-'" /></NGi>
      </NGrid>

      <!-- Aggressive-Specific Metrics -->
      <NCard title="Aggressive 专属指标" size="small" style="margin-bottom: 16px">
        <NGrid :cols="cols(2, 3, 5)" :x-gap="12" :y-gap="12">
          <NGi>
            <div style="text-align: center">
              <NTag :color="{ color: hrColor(am.home_run_count || 0), textColor: '#fff' }" size="large" round>
                {{ am.home_run_count || 0 }} Home Runs
              </NTag>
              <NText depth="3" style="font-size: 10px; display: block; margin-top: 4px">
                单笔 +50% 以上
              </NText>
            </div>
          </NGi>
          <NGi>
            <div style="text-align: center">
              <div style="font-size: 20px; font-weight: bold; color: #ff6b35">
                {{ ((am.payload_ratio || 0) * 100).toFixed(1) }}%
              </div>
              <NText depth="3" style="font-size: 10px">Payload Ratio</NText>
              <NProgress
                type="line"
                :percentage="(am.payload_ratio || 0) * 100"
                :show-indicator="false"
                color="#ff6b35"
                rail-color="rgba(255,107,53,0.15)"
                style="margin-top: 4px"
              />
            </div>
          </NGi>
          <NGi>
            <div style="text-align: center">
              <div style="font-size: 20px; font-weight: bold">
                {{ (am.ulcer_index || 0).toFixed(2) }}
              </div>
              <NText depth="3" style="font-size: 10px">Ulcer Index</NText>
              <NText depth="3" style="font-size: 9px; display: block">
                {{ (am.ulcer_index || 0) < 5 ? '低痛苦' : (am.ulcer_index || 0) < 10 ? '中等' : '高痛苦' }}
              </NText>
            </div>
          </NGi>
          <NGi>
            <div style="text-align: center">
              <div style="font-size: 20px; font-weight: bold; color: #3182ce">
                {{ fmtPct(am.capture_rate_30 || 0) }}
              </div>
              <NText depth="3" style="font-size: 10px">Capture Rate 30%</NText>
            </div>
          </NGi>
          <NGi>
            <div style="text-align: center">
              <div style="font-size: 20px; font-weight: bold; color: #ff6b35">
                {{ fmtPct(am.capture_rate_50 || 0) }}
              </div>
              <NText depth="3" style="font-size: 10px">Capture Rate 50%</NText>
            </div>
          </NGi>
        </NGrid>
        <NSpace style="margin-top: 12px" :size="16">
          <NText depth="3" style="font-size: 11px">
            最大单笔赢 <span :style="{ color: '#38a169', fontWeight: 'bold' }">{{ fmtPct(am.largest_winner || 0) }}</span>
          </NText>
          <NText depth="3" style="font-size: 11px">
            最大单笔亏 <span :style="{ color: '#e53e3e', fontWeight: 'bold' }">{{ fmtPct(am.largest_loser || 0) }}</span>
          </NText>
          <NText depth="3" style="font-size: 11px">
            Home Run 占总获利 <span :style="{ color: '#ff6b35', fontWeight: 'bold' }">{{ fmtPct(am.home_run_pct || 0) }}</span>
          </NText>
        </NSpace>
      </NCard>

      <!-- Charts -->
      <NTabs type="line">
        <NTabPane name="equity" tab="权益曲线">
          <NCard size="small"><ChartContainer :option="equityOption" height="350px" /></NCard>
        </NTabPane>
        <NTabPane name="kline-trades" tab="K线交易">
          <NCard size="small">
            <NSpin :show="klineLoading">
              <CandlestickChart v-if="klineData" :data="klineData" :trades="r?.trades" />
              <div v-else style="text-align: center; padding: 40px; color: var(--text-muted)">载入中...</div>
            </NSpin>
          </NCard>
        </NTabPane>
        <NTabPane name="drawdown" tab="回撤曲线">
          <NCard size="small"><ChartContainer :option="drawdownOption" height="300px" /></NCard>
        </NTabPane>
        <NTabPane name="return-dist" tab="报酬分布">
          <NCard size="small"><ChartContainer :option="returnDistOption" height="300px" /></NCard>
        </NTabPane>
        <NTabPane name="exit" tab="出场分布">
          <NCard size="small"><ChartContainer :option="exitPieOption" height="300px" /></NCard>
        </NTabPane>
        <NTabPane name="trades" tab="交易明细">
          <NSpace style="margin-bottom: 8px" justify="end">
            <NButton size="small" @click="exportTrades" :disabled="!r?.trades?.length">汇出 CSV</NButton>
          </NSpace>
          <NDataTable :columns="tradeColumns" :data="r.trades" :pagination="tradePagination" size="small" :scroll-x="720" />
        </NTabPane>
      </NTabs>
    </template>
  </div>
</template>
