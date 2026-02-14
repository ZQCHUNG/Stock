<script setup lang="ts">
import { ref, reactive, computed, watch } from 'vue'
import {
  NCard, NButton, NGrid, NGi, NTabs, NTabPane, NDataTable, NSpace, NPopover, NInput, NSpin,
} from 'naive-ui'
import { use } from 'echarts/core'
import { LineChart, PieChart, BarChart, ScatterChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, ToolboxComponent, DataZoomComponent, MarkPointComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useAppStore } from '../stores/app'
import { useBacktestStore } from '../stores/backtest'
import { fmtPct, fmtNum, priceColor, downloadCsv } from '../utils/format'
import { useChartTheme } from '../composables/useChartTheme'
import { useResponsive } from '../composables/useResponsive'
import MetricCard from './MetricCard.vue'
import ChartContainer from './ChartContainer.vue'
import CandlestickChart from './CandlestickChart.vue'
import { btResultsApi } from '../api/btResults'
import { analysisApi } from '../api/analysis'
import type { TimeSeriesData } from '../api/stocks'
import { message } from '../utils/discrete'

use([LineChart, PieChart, BarChart, ScatterChart, GridComponent, TooltipComponent, ToolboxComponent, DataZoomComponent, MarkPointComponent, LegendComponent, CanvasRenderer])

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

// K-line data for trade chart tab
const klineData = ref<TimeSeriesData | null>(null)
const klineLoading = ref(false)

async function runBacktest() {
  await bt.runSingle(app.currentStockCode, {
    period_days: props.periodDays,
    initial_capital: props.capital,
    ...props.costParams,
  })
}

// Auto-fetch K-line data when backtest result is available
watch(() => bt.singleResult, async (r) => {
  if (r?.trades?.length) {
    klineLoading.value = true
    try {
      klineData.value = await analysisApi.indicators(app.currentStockCode, props.periodDays, 0)
    } catch { /* silent */ }
    klineLoading.value = false
  }
})

const expectancy = computed(() => {
  const r = bt.singleResult
  if (!r || !r.total_trades) return '-'
  const wr = r.win_rate || 0
  const avgW = r.avg_win || 0
  const avgL = r.avg_loss || 0
  const exp = wr * avgW + (1 - wr) * avgL
  return fmtPct(exp)
})

const equityOption = computed(() => {
  const r = bt.singleResult
  if (!r?.equity_curve?.dates?.length) return {}
  const cc = chartColors.value
  const dates = r.equity_curve.dates
  const values = r.equity_curve.values as number[]
  const trades = r.trades || []

  // Build date→index map for fast lookup
  const dateIdx: Record<string, number> = {}
  dates.forEach((d: string, i: number) => { dateIdx[d.slice(0, 10)] = i })

  // Trade markers: buy (green up triangle) and sell (red down triangle)
  const buyMarks: any[] = []
  const sellMarks: any[] = []
  trades.forEach((t: any) => {
    const openDate = t.date_open?.slice(0, 10)
    const closeDate = t.date_close?.slice(0, 10)
    if (openDate && dateIdx[openDate] !== undefined) {
      buyMarks.push({
        coord: [dateIdx[openDate], values[dateIdx[openDate]]],
        symbol: 'triangle', symbolSize: 10,
        itemStyle: { color: '#38a169' },
      })
    }
    if (closeDate && dateIdx[closeDate] !== undefined) {
      sellMarks.push({
        coord: [dateIdx[closeDate], values[dateIdx[closeDate]]],
        symbol: 'pin', symbolSize: 10,
        symbolRotate: 180,
        itemStyle: { color: t.pnl >= 0 ? '#38a169' : '#e53e3e' },
      })
    }
  })

  return {
    tooltip: { trigger: 'axis', ...tooltipStyle.value, formatter: (params: any[]) => {
      if (!params?.length) return ''
      let html = `<div style="font-size:12px"><b>${params[0].name}</b>`
      params.forEach((p: any) => {
        if (p.seriesName === '權益') html += `<br/>權益: $${fmtNum(p.value, 0)}`
        else if (p.seriesName === '買入' && p.value) html += `<br/><span style="color:#38a169">▲</span> 買入`
        else if (p.seriesName === '賣出' && p.value) html += `<br/><span style="color:#e53e3e">◆</span> 賣出`
      })
      return html + '</div>'
    }},
    toolbox: { ...toolboxConfig.value, feature: { restore: toolboxConfig.value.feature.restore, saveAsImage: toolboxConfig.value.feature.saveAsImage } },
    legend: { data: ['權益', '買入', '賣出'], textStyle: { color: cc.legendText, fontSize: 11 }, top: 0 },
    grid: { left: 80, right: 20, top: 30, bottom: 50 },
    xAxis: { type: 'category', data: dates, axisLabel: { color: cc.axisLabel } },
    yAxis: { type: 'value', axisLabel: { formatter: (v: number) => fmtNum(v), color: cc.axisLabel }, splitLine: { lineStyle: { color: cc.splitLine } } },
    dataZoom: [
      { type: 'inside', start: 0, end: 100 },
      { type: 'slider', start: 0, end: 100, height: 20, bottom: 4, borderColor: 'transparent', backgroundColor: cc.splitLine, fillerColor: 'rgba(33,150,243,0.15)' },
    ],
    series: [
      { name: '權益', type: 'line', data: values, symbol: 'none', areaStyle: { opacity: 0.15 }, lineStyle: { width: 1.5, color: '#2196f3' } },
      { name: '買入', type: 'scatter', data: buyMarks.map(m => m.coord), symbol: 'triangle', symbolSize: 8, itemStyle: { color: '#38a169' }, z: 10 },
      { name: '賣出', type: 'scatter', data: sellMarks.map(m => m.coord), symbol: 'diamond', symbolSize: 8, itemStyle: { color: '#e53e3e' }, z: 10 },
    ],
  }
})

const exitPieOption = computed(() => {
  const trades = bt.singleResult?.trades || []
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
  const r = bt.singleResult
  if (!r?.equity_curve?.dates?.length) return {}
  const cc = chartColors.value
  const vals = r.equity_curve.values as number[]
  // Calculate drawdown series
  let peak = vals[0]
  const dd = vals.map((v: number) => {
    if (v > peak) peak = v
    return +((v / peak - 1) * 100).toFixed(2)
  })
  return {
    tooltip: { trigger: 'axis', ...tooltipStyle.value, formatter: (params: any[]) => {
      if (!params?.length) return ''
      const p = params[0]
      return `<div style="font-size:12px"><b>${p.name}</b><br/>回撤: ${p.value}%</div>`
    }},
    grid: { left: 60, right: 20, top: 20, bottom: 50 },
    xAxis: { type: 'category', data: r.equity_curve.dates, axisLabel: { color: cc.axisLabel } },
    yAxis: { type: 'value', max: 0, axisLabel: { formatter: (v: number) => `${v}%`, color: cc.axisLabel }, splitLine: { lineStyle: { color: cc.splitLine } } },
    dataZoom: [
      { type: 'inside', start: 0, end: 100 },
      { type: 'slider', start: 0, end: 100, height: 18, bottom: 4, borderColor: 'transparent' },
    ],
    series: [{
      type: 'line', data: dd, symbol: 'none',
      areaStyle: { color: 'rgba(229,62,62,0.3)' },
      lineStyle: { width: 1, color: '#e53e3e' },
    }],
  }
})

// Monthly returns
const monthlyReturnsOption = computed(() => {
  const trades = bt.singleResult?.trades || []
  if (!trades.length) return {}
  const cc = chartColors.value
  const monthly: Record<string, number> = {}
  trades.forEach((t: any) => {
    if (!t.date_close) return
    const month = t.date_close.slice(0, 7)
    monthly[month] = (monthly[month] || 0) + (t.pnl || 0)
  })
  const months = Object.keys(monthly).sort()
  const values = months.map(m => +(monthly[m]).toFixed(0))
  return {
    tooltip: { trigger: 'axis', ...tooltipStyle.value, formatter: (params: any[]) => {
      if (!params?.length) return ''
      const p = params[0]
      return `<div style="font-size:12px"><b>${p.name}</b><br/>損益: $${fmtNum(p.value, 0)}</div>`
    }},
    grid: { left: 80, right: 20, top: 20, bottom: 30 },
    xAxis: { type: 'category', data: months, axisLabel: { color: cc.axisLabel, fontSize: 10, rotate: 45 } },
    yAxis: { type: 'value', axisLabel: { formatter: (v: number) => fmtNum(v), color: cc.axisLabel }, splitLine: { lineStyle: { color: cc.splitLine } } },
    series: [{
      type: 'bar',
      data: values.map(v => ({
        value: v,
        itemStyle: { color: v >= 0 ? '#38a169' : '#e53e3e' },
      })),
    }],
  }
})

function exportTrades() {
  const trades = bt.singleResult?.trades || []
  downloadCsv(trades, [
    { key: 'date_open', label: '開倉日' },
    { key: 'date_close', label: '平倉日' },
    { key: 'price_open', label: '買入價' },
    { key: 'price_close', label: '賣出價' },
    { key: 'pnl', label: '損益' },
    { key: 'return_pct', label: '報酬率' },
    { key: 'exit_reason', label: '出場原因' },
  ], `backtest_${app.currentStockCode}_trades.csv`)
}

function exportEquityCurve() {
  const ec = bt.singleResult?.equity_curve
  if (!ec?.dates?.length) return
  const rows = ec.dates.map((d: string, i: number) => ({
    date: d,
    equity: ec.values[i],
  }))
  downloadCsv(rows, [
    { key: 'date', label: '日期' },
    { key: 'equity', label: '權益' },
  ], `backtest_${app.currentStockCode}_equity.csv`)
}

function exportMetrics() {
  const r = bt.singleResult
  if (!r) return
  const rows = [{
    stock: `${app.currentStockCode} ${app.currentStockName}`,
    total_return: r.total_return,
    annual_return: r.annual_return,
    max_drawdown: r.max_drawdown,
    sharpe: r.sharpe_ratio,
    sortino: r.sortino_ratio,
    calmar: r.calmar_ratio,
    win_rate: r.win_rate,
    profit_factor: r.profit_factor,
    total_trades: r.total_trades,
    avg_holding: r.avg_holding_days,
    max_wins: r.max_consecutive_wins,
    max_losses: r.max_consecutive_losses,
  }]
  downloadCsv(rows, [
    { key: 'stock', label: '股票' },
    { key: 'total_return', label: '總報酬率' },
    { key: 'annual_return', label: '年化報酬' },
    { key: 'max_drawdown', label: '最大回撤' },
    { key: 'sharpe', label: 'Sharpe' },
    { key: 'sortino', label: 'Sortino' },
    { key: 'calmar', label: 'Calmar' },
    { key: 'win_rate', label: '勝率' },
    { key: 'profit_factor', label: '盈虧比' },
    { key: 'total_trades', label: '交易次數' },
    { key: 'avg_holding', label: '平均持有天數' },
    { key: 'max_wins', label: '最大連勝' },
    { key: 'max_losses', label: '最大連敗' },
  ], `backtest_${app.currentStockCode}_metrics.csv`)
}

const tradePagination = reactive({ page: 1, pageSize: 15, showSizePicker: true, pageSizes: [10, 15, 25, 50] })

const saveResultName = ref('')
const showSaveResult = ref(false)

async function saveResult() {
  const name = saveResultName.value.trim()
  if (!name || !bt.singleResult) return
  const r = bt.singleResult
  try {
    await btResultsApi.save({
      name,
      stockCode: app.currentStockCode,
      stockName: app.currentStockName,
      config: { periodDays: props.periodDays, capital: props.capital },
      metrics: {
        total_return: r.total_return,
        annual_return: r.annual_return,
        max_drawdown: r.max_drawdown,
        sharpe_ratio: r.sharpe_ratio,
        win_rate: r.win_rate,
        profit_factor: r.profit_factor,
        total_trades: r.total_trades,
        sortino_ratio: r.sortino_ratio,
        calmar_ratio: r.calmar_ratio,
      },
      equityCurve: r.equity_curve?.dates?.length
        ? { dates: r.equity_curve.dates, values: r.equity_curve.values }
        : undefined,
    })
    message.success(`已保存「${name}」`)
    saveResultName.value = ''
    showSaveResult.value = false
  } catch { /* handled by interceptor */ }
}

const tradeColumns = [
  { title: '開倉日', key: 'date_open', width: 100, render: (r: any) => r.date_open?.slice(0, 10) },
  { title: '平倉日', key: 'date_close', width: 100, render: (r: any) => r.date_close?.slice(0, 10) },
  { title: '買入價', key: 'price_open', width: 80, render: (r: any) => r.price_open?.toFixed(2) },
  { title: '賣出價', key: 'price_close', width: 80, render: (r: any) => r.price_close?.toFixed(2) },
  { title: '損益', key: 'pnl', width: 100, render: (r: any) => fmtNum(r.pnl) },
  { title: '報酬%', key: 'return_pct', width: 80, render: (r: any) => fmtPct(r.return_pct) },
  { title: '出場原因', key: 'exit_reason', width: 100 },
]
</script>

<template>
  <div>
    <NSpace style="margin-bottom: 16px">
      <NButton type="primary" @click="runBacktest" :loading="bt.isLoading">執行回測</NButton>
      <NButton v-if="bt.singleResult" size="small" quaternary @click="exportMetrics">匯出指標</NButton>
      <NPopover v-if="bt.singleResult" v-model:show="showSaveResult" trigger="click" placement="bottom">
        <template #trigger>
          <NButton size="small" quaternary>保存結果</NButton>
        </template>
        <div style="width: 220px; padding: 4px">
          <NInput v-model:value="saveResultName" size="small" :placeholder="`${app.currentStockCode} 回測結果`" @keyup.enter="saveResult" />
          <NButton size="small" type="primary" style="margin-top: 8px; width: 100%" @click="saveResult" :disabled="!saveResultName.trim()">保存</NButton>
        </div>
      </NPopover>
    </NSpace>

    <template v-if="bt.singleResult">
      <NGrid :cols="metricCols" :x-gap="12" :y-gap="12" style="margin-bottom: 16px">
        <NGi><MetricCard title="總報酬率" :value="fmtPct(bt.singleResult.total_return)" :color="priceColor(bt.singleResult.total_return)" /></NGi>
        <NGi><MetricCard title="年化報酬" :value="fmtPct(bt.singleResult.annual_return)" :color="priceColor(bt.singleResult.annual_return)" /></NGi>
        <NGi><MetricCard title="最大回撤" :value="fmtPct(bt.singleResult.max_drawdown)" color="#e53e3e" /></NGi>
        <NGi><MetricCard title="Sharpe Ratio" :value="bt.singleResult.sharpe_ratio?.toFixed(2) || '-'" /></NGi>
        <NGi><MetricCard title="勝率" :value="fmtPct(bt.singleResult.win_rate)" /></NGi>
        <NGi><MetricCard title="盈虧比" :value="bt.singleResult.profit_factor?.toFixed(2) || '-'" /></NGi>
        <NGi><MetricCard title="交易次數" :value="bt.singleResult.total_trades" /></NGi>
        <NGi><MetricCard title="平均持有天數" :value="bt.singleResult.avg_holding_days?.toFixed(1) || '-'" /></NGi>
        <NGi><MetricCard title="Sortino" :value="bt.singleResult.sortino_ratio?.toFixed(2) || '-'" /></NGi>
        <NGi><MetricCard title="Calmar" :value="bt.singleResult.calmar_ratio?.toFixed(2) || '-'" /></NGi>
        <NGi><MetricCard title="最大連勝" :value="bt.singleResult.max_consecutive_wins" /></NGi>
        <NGi><MetricCard title="最大連敗" :value="bt.singleResult.max_consecutive_losses" /></NGi>
        <NGi>
          <MetricCard title="期望值" :value="expectancy" :color="priceColor(parseFloat(String(expectancy)) || 0)" subtitle="每筆交易期望報酬率" />
        </NGi>
        <NGi v-if="bt.singleResult.total_costs">
          <MetricCard title="總交易成本" :value="'$' + fmtNum(bt.singleResult.total_costs, 0)" color="#e53e3e" />
        </NGi>
      </NGrid>

      <NTabs type="line">
        <NTabPane name="equity" tab="權益曲線">
          <NCard size="small">
            <template #header-extra>
              <NButton size="tiny" quaternary @click="exportEquityCurve" :disabled="!bt.singleResult?.equity_curve?.dates?.length">匯出 CSV</NButton>
            </template>
            <ChartContainer :option="equityOption" height="350px" />
          </NCard>
        </NTabPane>
        <NTabPane name="kline-trades" tab="K線交易">
          <NCard size="small">
            <NSpin :show="klineLoading">
              <CandlestickChart
                v-if="klineData"
                :data="klineData"
                :trades="bt.singleResult?.trades"
              />
              <div v-else style="text-align: center; padding: 40px; color: var(--text-muted)">
                載入中...
              </div>
            </NSpin>
          </NCard>
        </NTabPane>
        <NTabPane name="drawdown" tab="回撤曲線">
          <NCard size="small"><ChartContainer :option="drawdownOption" height="300px" aria-label="回撤曲線" /></NCard>
        </NTabPane>
        <NTabPane name="monthly" tab="月度損益">
          <NCard size="small"><ChartContainer :option="monthlyReturnsOption" height="300px" aria-label="月度損益" /></NCard>
        </NTabPane>
        <NTabPane name="exit" tab="出場分布">
          <NCard size="small"><ChartContainer :option="exitPieOption" height="300px" /></NCard>
        </NTabPane>
        <NTabPane name="trades" tab="交易明細">
          <NSpace style="margin-bottom: 8px" justify="end">
            <NButton size="small" @click="exportTrades" :disabled="!bt.singleResult?.trades?.length">匯出 CSV</NButton>
          </NSpace>
          <NDataTable
            :columns="tradeColumns"
            :data="bt.singleResult.trades"
            :pagination="tradePagination"
            size="small"
            :row-class-name="(r: any) => r.pnl > 0 ? 'row-win' : 'row-loss'"
            :scroll-x="640"
          />
        </NTabPane>
      </NTabs>

      <div v-if="bt.singleResult.params_description" style="margin-top: 8px; font-size: 12px; color: var(--text-muted)">
        策略參數: {{ bt.singleResult.params_description }}
      </div>
    </template>
  </div>
</template>

<style>
.row-win td:nth-child(5) { color: #e53e3e; }
.row-loss td:nth-child(5) { color: #38a169; }
</style>
