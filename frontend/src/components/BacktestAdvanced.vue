<script setup lang="ts">
import { h, ref, computed } from 'vue'
import {
  NCard, NButton, NGrid, NGi, NTabs, NTabPane, NDataTable, NAlert, NInputNumber, NSpace,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { use } from 'echarts/core'
import { LineChart, BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, ToolboxComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useAppStore } from '../stores/app'
import { useBacktestStore } from '../stores/backtest'
import { fmtPct, priceColor } from '../utils/format'
import { useChartTheme } from '../composables/useChartTheme'
import { useResponsive } from '../composables/useResponsive'
import MetricCard from './MetricCard.vue'
import ChartContainer from './ChartContainer.vue'

use([LineChart, BarChart, GridComponent, TooltipComponent, LegendComponent, ToolboxComponent, CanvasRenderer])

const props = defineProps<{ periodDays: number; capital: number }>()

const app = useAppStore()
const bt = useBacktestStore()
const { colors: chartColors, tooltipStyle, toolboxConfig } = useChartTheme()
const { cols } = useResponsive()
const metricCols = cols(2, 3, 4)

const windowMonths = ref(6)

async function runRolling() {
  await bt.runRolling(app.currentStockCode, windowMonths.value, { period_days: props.periodDays, initial_capital: props.capital })
}
async function runSensitivity() {
  await bt.runSensitivity(app.currentStockCode, { period_days: props.periodDays, initial_capital: props.capital })
}
async function runAlphaBeta() {
  await bt.runAlphaBeta(app.currentStockCode, { period_days: props.periodDays, initial_capital: props.capital })
}

const rollingBarOption = computed(() => {
  const r = bt.rollingResult
  if (!r?.windows?.length) return {}
  const cc = chartColors.value
  const names = r.windows.map((w: any) => w.window_name)
  const returns = r.windows.map((w: any) => w.total_return)
  return {
    tooltip: { trigger: 'axis', ...tooltipStyle.value, formatter: (params: any[]) => {
      if (!params?.length) return ''
      const p = params[0]
      return `${p.name}<br/>報酬率: ${fmtPct(p.value)}`
    }},
    toolbox: { ...toolboxConfig.value, feature: { saveAsImage: toolboxConfig.value.feature.saveAsImage } },
    grid: { left: 60, right: 20, top: 30, bottom: 40 },
    xAxis: { type: 'category', data: names, axisLabel: { color: cc.axisLabel, rotate: 45, fontSize: 10 } },
    yAxis: { type: 'value', axisLabel: { formatter: (v: number) => fmtPct(v), color: cc.axisLabel }, splitLine: { lineStyle: { color: cc.splitLine } } },
    series: [{
      type: 'bar', data: returns.map((v: number) => ({
        value: v,
        itemStyle: { color: v >= 0 ? '#2196f3' : '#e53e3e' },
      })),
    }],
  }
})

const rollingWindowColumns: DataTableColumns = [
  { title: '區間', key: 'window_name', width: 120 },
  { title: '報酬率', key: 'total_return', width: 90, sorter: (a: any, b: any) => (a.total_return || 0) - (b.total_return || 0),
    render: (r: any) => h('span', { style: { color: priceColor(r.total_return), fontWeight: 600 } }, fmtPct(r.total_return)) },
  { title: '年化', key: 'annual_return', width: 80,
    render: (r: any) => h('span', { style: { color: priceColor(r.annual_return) } }, fmtPct(r.annual_return)) },
  { title: '最大回撤', key: 'max_drawdown', width: 90,
    render: (r: any) => h('span', { style: { color: '#e53e3e' } }, fmtPct(r.max_drawdown)) },
  { title: '勝率', key: 'win_rate', width: 70, render: (r: any) => fmtPct(r.win_rate) },
  { title: 'Sharpe', key: 'sharpe_ratio', width: 80, render: (r: any) => r.sharpe_ratio?.toFixed(2) || '-' },
  { title: '交易數', key: 'total_trades', width: 70 },
]

const sensitivityColumns: DataTableColumns = [
  { title: '參數', key: 'param', width: 80 },
  { title: '值', key: 'value', width: 80 },
  { title: '報酬率', key: 'return', width: 90, sorter: (a: any, b: any) => (a.return || 0) - (b.return || 0),
    render: (r: any) => h('span', { style: { color: priceColor(r.return), fontWeight: 600 } }, fmtPct(r.return)) },
  { title: '勝率', key: 'win_rate', width: 70, render: (r: any) => fmtPct(r.win_rate) },
  { title: '最大回撤', key: 'max_dd', width: 90,
    render: (r: any) => h('span', { style: { color: '#e53e3e' } }, fmtPct(r.max_dd)) },
  { title: 'Sharpe', key: 'sharpe', width: 80, render: (r: any) => r.sharpe?.toFixed(2) || '-' },
  { title: '交易數', key: 'trades', width: 70 },
]

const alphaBetaChartOption = computed(() => {
  const r = bt.alphaBetaResult
  if (!r?.rolling_alpha?.dates?.length) return {}
  const cc = chartColors.value
  return {
    tooltip: { trigger: 'axis', ...tooltipStyle.value },
    toolbox: { ...toolboxConfig.value, feature: { restore: toolboxConfig.value.feature.restore, saveAsImage: toolboxConfig.value.feature.saveAsImage } },
    legend: { data: ['Rolling Alpha', 'EMA20'], left: 0, textStyle: { color: cc.legendText } },
    grid: { left: 80, right: 20, top: 30, bottom: 30 },
    xAxis: { type: 'category', data: r.rolling_alpha.dates, axisLabel: { color: cc.axisLabel } },
    yAxis: { type: 'value', axisLabel: { formatter: (v: number) => fmtPct(v), color: cc.axisLabel }, splitLine: { lineStyle: { color: cc.splitLine } } },
    series: [
      { name: 'Rolling Alpha', type: 'line', data: r.rolling_alpha.values, symbol: 'none', lineStyle: { width: 1, color: '#2196f3' } },
      { name: 'EMA20', type: 'line', data: r.rolling_alpha_ema?.values || [], symbol: 'none', lineStyle: { width: 1.5, color: '#ff9800' } },
    ],
  }
})
</script>

<template>
  <div>
    <NSpace style="margin-bottom: 16px">
      <NInputNumber v-model:value="windowMonths" :min="3" :max="24" size="small" placeholder="窗口(月)" style="width: 120px" />
      <NButton @click="runRolling" :loading="bt.isLoading">滾動回測</NButton>
      <NButton @click="runSensitivity" :loading="bt.isLoading">敏感度</NButton>
      <NButton @click="runAlphaBeta" :loading="bt.isLoading">Alpha/Beta</NButton>
    </NSpace>

    <NTabs type="line">
      <!-- Rolling Backtest -->
      <NTabPane name="rolling" tab="滾動回測">
        <template v-if="bt.rollingResult">
          <NGrid :cols="metricCols" :x-gap="12" :y-gap="12" style="margin-bottom: 16px">
            <NGi><MetricCard title="一致性分數" :value="bt.rollingResult.consistency_score?.toFixed(1) || '-'" :color="(bt.rollingResult.consistency_score || 0) >= 70 ? '#38a169' : '#e53e3e'" /></NGi>
            <NGi><MetricCard title="平均報酬" :value="fmtPct(bt.rollingResult.avg_return)" :color="priceColor(bt.rollingResult.avg_return)" /></NGi>
            <NGi><MetricCard title="報酬標準差" :value="fmtPct(bt.rollingResult.return_std)" /></NGi>
            <NGi>
              <MetricCard title="正/負窗口">
                <template #default>
                  <span style="color: #e53e3e">{{ bt.rollingResult.positive_windows }}</span>
                  /
                  <span style="color: #38a169">{{ bt.rollingResult.total_windows - bt.rollingResult.positive_windows }}</span>
                </template>
              </MetricCard>
            </NGi>
            <NGi><MetricCard title="平均勝率" :value="fmtPct(bt.rollingResult.avg_win_rate)" /></NGi>
            <NGi><MetricCard title="平均最大回撤" :value="fmtPct(bt.rollingResult.avg_max_drawdown)" color="#e53e3e" /></NGi>
          </NGrid>
          <NCard size="small" style="margin-bottom: 12px">
            <ChartContainer :option="rollingBarOption" height="300px" />
          </NCard>
          <NDataTable :columns="rollingWindowColumns" :data="bt.rollingResult.windows" size="small" :pagination="{ pageSize: 10 }" :scroll-x="600" />
        </template>
        <NAlert v-else type="info">點擊「滾動回測」開始分析</NAlert>
      </NTabPane>

      <!-- Parameter Sensitivity -->
      <NTabPane name="sensitivity" tab="參數敏感度">
        <template v-if="bt.sensitivityResult?.length">
          <NDataTable :columns="sensitivityColumns" :data="bt.sensitivityResult" size="small" :pagination="{ pageSize: 20 }" :scroll-x="560" />
        </template>
        <NAlert v-else type="info">點擊「敏感度」開始分析</NAlert>
      </NTabPane>

      <!-- Alpha/Beta -->
      <NTabPane name="alphabeta" tab="Alpha / Beta">
        <template v-if="bt.alphaBetaResult">
          <NGrid :cols="metricCols" :x-gap="12" :y-gap="12" style="margin-bottom: 16px">
            <NGi><MetricCard title="Jensen's Alpha" :value="fmtPct(bt.alphaBetaResult.jensen_alpha)" :color="priceColor(bt.alphaBetaResult.jensen_alpha)" /></NGi>
            <NGi><MetricCard title="Beta" :value="bt.alphaBetaResult.beta?.toFixed(3) || '-'" /></NGi>
            <NGi><MetricCard title="Up Beta" :value="bt.alphaBetaResult.up_beta?.toFixed(3) || '-'" /></NGi>
            <NGi><MetricCard title="Down Beta" :value="bt.alphaBetaResult.down_beta?.toFixed(3) || '-'" /></NGi>
            <NGi><MetricCard title="Capture Ratio" :value="bt.alphaBetaResult.capture_ratio?.toFixed(2) || '-'" /></NGi>
            <NGi><MetricCard title="R-squared" :value="bt.alphaBetaResult.r_squared?.toFixed(3) || '-'" /></NGi>
          </NGrid>
          <NCard title="Rolling Alpha (60日)" size="small">
            <ChartContainer :option="alphaBetaChartOption" height="350px" />
          </NCard>
          <NAlert v-if="bt.alphaBetaResult.benchmark_warning" type="warning" style="margin-top: 8px">
            {{ bt.alphaBetaResult.benchmark_warning }}
          </NAlert>
        </template>
        <NAlert v-else type="info">點擊「Alpha/Beta」開始分析</NAlert>
      </NTabPane>
    </NTabs>
  </div>
</template>
