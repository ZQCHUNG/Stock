<script setup lang="ts">
import { h, ref, computed, onMounted } from 'vue'
import {
  NCard, NButton, NGrid, NGi, NTabs, NTabPane, NDataTable, NSelect, NSpace,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { use } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, ToolboxComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useAppStore } from '../stores/app'
import { useBacktestStore } from '../stores/backtest'
import { useWatchlistStore } from '../stores/watchlist'
import { fmtPct, fmtNum, priceColor } from '../utils/format'
import { useChartTheme } from '../composables/useChartTheme'
import { useResponsive } from '../composables/useResponsive'
import MetricCard from './MetricCard.vue'
import ChartContainer from './ChartContainer.vue'

use([LineChart, GridComponent, TooltipComponent, ToolboxComponent, CanvasRenderer])

const props = defineProps<{ periodDays: number; capital: number }>()

const app = useAppStore()
const bt = useBacktestStore()
const wl = useWatchlistStore()
const { colors: chartColors, tooltipStyle, toolboxConfig } = useChartTheme()
const { cols } = useResponsive()
const metricCols = cols(2, 3, 4)

onMounted(() => wl.load())

const portfolioCodes = ref<string[]>([])

const portfolioStockOptions = computed(() => {
  const opts = wl.watchlist.map((s) => ({ label: `${s.code} ${s.name}`, value: s.code }))
  if (opts.length === 0) {
    return ['2330', '2317', '2454', '2881', '2882', '3008', '2412', '1301'].map(
      (c) => ({ label: `${c} ${app.getStockName(c)}`, value: c }),
    )
  }
  return opts
})

async function runPortfolio() {
  if (portfolioCodes.value.length < 2) return
  await bt.runPortfolio(portfolioCodes.value, { period_days: props.periodDays, initial_capital: props.capital })
}

const portfolioEquityOption = computed(() => {
  const r = bt.portfolioResult
  if (!r?.equity_curve?.dates?.length) return {}
  const cc = chartColors.value
  return {
    tooltip: { trigger: 'axis', ...tooltipStyle.value },
    toolbox: { ...toolboxConfig.value, feature: { restore: toolboxConfig.value.feature.restore, saveAsImage: toolboxConfig.value.feature.saveAsImage } },
    grid: { left: 80, right: 20, top: 30, bottom: 30 },
    xAxis: { type: 'category', data: r.equity_curve.dates, axisLabel: { color: cc.axisLabel } },
    yAxis: { type: 'value', axisLabel: { formatter: (v: number) => fmtNum(v), color: cc.axisLabel }, splitLine: { lineStyle: { color: cc.splitLine } } },
    series: [{ type: 'line', data: r.equity_curve.values, symbol: 'none', areaStyle: { opacity: 0.15 }, lineStyle: { width: 1.5, color: '#7c3aed' } }],
  }
})

const stockResultColumns: DataTableColumns = [
  { title: '代碼', key: 'code', width: 70 },
  { title: '名稱', key: 'name', width: 80 },
  { title: '總報酬', key: 'total_return', width: 90, sorter: (a: any, b: any) => (a.total_return || 0) - (b.total_return || 0),
    render: (r: any) => h('span', { style: { color: priceColor(r.total_return), fontWeight: 600 } }, fmtPct(r.total_return)) },
  { title: '年化報酬', key: 'annual_return', width: 90,
    render: (r: any) => h('span', { style: { color: priceColor(r.annual_return) } }, fmtPct(r.annual_return)) },
  { title: '最大回撤', key: 'max_drawdown', width: 90,
    render: (r: any) => h('span', { style: { color: '#e53e3e' } }, fmtPct(r.max_drawdown)) },
  { title: 'Sharpe', key: 'sharpe_ratio', width: 80,
    render: (r: any) => r.sharpe_ratio?.toFixed(2) || '-' },
  { title: '勝率', key: 'win_rate', width: 70, render: (r: any) => fmtPct(r.win_rate) },
  { title: '交易數', key: 'total_trades', width: 70 },
]

const portfolioStockData = computed(() => {
  const r = bt.portfolioResult
  if (!r?.stock_results) return []
  return Object.entries(r.stock_results).map(([code, sr]: [string, any]) => ({
    code,
    name: r.stock_names?.[code] || code,
    ...sr,
  }))
})
</script>

<template>
  <div>
    <NSpace style="margin-bottom: 16px">
      <NSelect
        v-model:value="portfolioCodes"
        :options="portfolioStockOptions"
        multiple
        filterable
        tag
        placeholder="選擇股票 (至少 2 隻)"
        size="small"
        style="min-width: 300px"
      />
      <NButton type="primary" @click="runPortfolio" :loading="bt.isLoading" :disabled="portfolioCodes.length < 2">
        組合回測
      </NButton>
    </NSpace>

    <template v-if="bt.portfolioResult">
      <NGrid :cols="metricCols" :x-gap="12" :y-gap="12" style="margin-bottom: 16px">
        <NGi><MetricCard title="組合總報酬" :value="fmtPct(bt.portfolioResult.total_return)" :color="priceColor(bt.portfolioResult.total_return)" /></NGi>
        <NGi><MetricCard title="年化報酬" :value="fmtPct(bt.portfolioResult.annual_return)" :color="priceColor(bt.portfolioResult.annual_return)" /></NGi>
        <NGi><MetricCard title="最大回撤" :value="fmtPct(bt.portfolioResult.max_drawdown)" color="#e53e3e" /></NGi>
        <NGi><MetricCard title="Sharpe Ratio" :value="bt.portfolioResult.sharpe_ratio?.toFixed(2) || '-'" /></NGi>
        <NGi><MetricCard title="交易次數" :value="bt.portfolioResult.total_trades" /></NGi>
        <NGi><MetricCard title="初始資金" :value="fmtNum(bt.portfolioResult.initial_capital, 0)" /></NGi>
        <NGi><MetricCard title="每股資金" :value="fmtNum(bt.portfolioResult.per_stock_capital, 0)" /></NGi>
        <NGi>
          <MetricCard title="獲利/虧損股">
            <template #default>
              <span style="color: #e53e3e">{{ bt.portfolioResult.winning_stocks }}</span>
              /
              <span style="color: #38a169">{{ bt.portfolioResult.losing_stocks }}</span>
            </template>
          </MetricCard>
        </NGi>
      </NGrid>

      <NTabs type="line">
        <NTabPane name="equity" tab="組合權益曲線">
          <NCard size="small"><ChartContainer :option="portfolioEquityOption" height="350px" /></NCard>
        </NTabPane>
        <NTabPane name="stocks" tab="個股明細">
          <NDataTable
            :columns="stockResultColumns"
            :data="portfolioStockData"
            size="small"
            :pagination="{ pageSize: 20 }"
            :scroll-x="560"
          />
        </NTabPane>
      </NTabs>
    </template>
  </div>
</template>
