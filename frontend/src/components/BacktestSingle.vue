<script setup lang="ts">
import { reactive, computed } from 'vue'
import {
  NCard, NButton, NGrid, NGi, NTabs, NTabPane, NDataTable, NSpace,
} from 'naive-ui'
import { use } from 'echarts/core'
import { LineChart, PieChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useAppStore } from '../stores/app'
import { useBacktestStore } from '../stores/backtest'
import { fmtPct, fmtNum, priceColor, downloadCsv } from '../utils/format'
import { useChartTheme } from '../composables/useChartTheme'
import { useResponsive } from '../composables/useResponsive'
import MetricCard from './MetricCard.vue'
import ChartContainer from './ChartContainer.vue'

use([LineChart, PieChart, GridComponent, TooltipComponent, CanvasRenderer])

const props = defineProps<{ periodDays: number; capital: number }>()

const app = useAppStore()
const bt = useBacktestStore()
const { colors: chartColors, tooltipStyle } = useChartTheme()
const { cols } = useResponsive()
const metricCols = cols(2, 3, 4)

async function runBacktest() {
  await bt.runSingle(app.currentStockCode, { period_days: props.periodDays, initial_capital: props.capital })
}

const equityOption = computed(() => {
  const r = bt.singleResult
  if (!r?.equity_curve?.dates?.length) return {}
  const cc = chartColors.value
  return {
    tooltip: { trigger: 'axis', ...tooltipStyle.value },
    grid: { left: 80, right: 20, top: 20, bottom: 30 },
    xAxis: { type: 'category', data: r.equity_curve.dates, axisLabel: { color: cc.axisLabel } },
    yAxis: { type: 'value', axisLabel: { formatter: (v: number) => fmtNum(v), color: cc.axisLabel }, splitLine: { lineStyle: { color: cc.splitLine } } },
    series: [{ type: 'line', data: r.equity_curve.values, symbol: 'none', areaStyle: { opacity: 0.15 }, lineStyle: { width: 1.5, color: '#2196f3' } }],
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

const tradePagination = reactive({ page: 1, pageSize: 15, showSizePicker: true, pageSizes: [10, 15, 25, 50] })

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
    <NButton type="primary" @click="runBacktest" :loading="bt.isLoading" style="margin-bottom: 16px">執行回測</NButton>

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
      </NGrid>

      <NTabs type="line">
        <NTabPane name="equity" tab="權益曲線">
          <NCard size="small"><ChartContainer :option="equityOption" height="350px" /></NCard>
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
