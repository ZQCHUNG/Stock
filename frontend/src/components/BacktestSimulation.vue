<script setup lang="ts">
import { h, ref, reactive, computed } from 'vue'
import {
  NCard, NButton, NGrid, NGi, NTabs, NTabPane, NDataTable, NInputNumber, NSpace, NTag,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { use } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useAppStore } from '../stores/app'
import { useBacktestStore } from '../stores/backtest'
import { fmtPct, fmtNum, priceColor } from '../utils/format'
import { useChartTheme } from '../composables/useChartTheme'
import { useResponsive } from '../composables/useResponsive'
import MetricCard from './MetricCard.vue'
import ChartContainer from './ChartContainer.vue'

use([LineChart, GridComponent, TooltipComponent, CanvasRenderer])

const props = defineProps<{ periodDays: number; capital: number }>()

const app = useAppStore()
const bt = useBacktestStore()
const { colors: chartColors, tooltipStyle } = useChartTheme()
const { cols } = useResponsive()
const metricCols = cols(2, 3, 4)

const simDays = ref(30)

async function runSimulation() {
  await bt.runSimulation(app.currentStockCode, simDays.value, {
    period_days: props.periodDays,
    initial_capital: props.capital,
  })
}

const simEquityOption = computed(() => {
  const r = bt.simulationResult
  if (!r?.daily_records?.length) return {}
  const dates = r.daily_records.map((d: any) => d.date?.slice(0, 10))
  const equity = r.daily_records.map((d: any) => d.total_equity)
  const cc = chartColors.value
  return {
    tooltip: { trigger: 'axis', ...tooltipStyle.value },
    grid: { left: 80, right: 20, top: 20, bottom: 30 },
    xAxis: { type: 'category', data: dates, axisLabel: { color: cc.axisLabel } },
    yAxis: { type: 'value', axisLabel: { formatter: (v: number) => fmtNum(v), color: cc.axisLabel }, splitLine: { lineStyle: { color: cc.splitLine } } },
    series: [{ type: 'line', data: equity, symbol: 'none', areaStyle: { opacity: 0.15 }, lineStyle: { width: 1.5, color: '#e53e3e' } }],
  }
})

const simRecordPagination = reactive({ page: 1, pageSize: 15, showSizePicker: true, pageSizes: [10, 15, 30] })

const simRecordColumns: DataTableColumns = [
  { title: '日期', key: 'date', width: 100, render: (r: any) => r.date?.slice(0, 10) },
  { title: '收盤', key: 'close', width: 80, render: (r: any) => r.close?.toFixed(2) },
  { title: '訊號', key: 'signal', width: 70,
    render: (r: any) => r.signal ? h(NTag, { type: r.signal === 'BUY' ? 'error' : r.signal === 'SELL' ? 'success' : 'default', size: 'small' }, () => r.signal) : '-' },
  { title: '動作', key: 'action', width: 70 },
  { title: '持股', key: 'shares', width: 70 },
  { title: '現金', key: 'cash', width: 100, render: (r: any) => fmtNum(r.cash, 0) },
  { title: '持倉市值', key: 'position_value', width: 100, render: (r: any) => fmtNum(r.position_value, 0) },
  { title: '總資產', key: 'total_equity', width: 110, render: (r: any) => fmtNum(r.total_equity, 0) },
  { title: '日損益', key: 'daily_pnl', width: 80,
    render: (r: any) => h('span', { style: { color: priceColor(r.daily_pnl) } }, fmtNum(r.daily_pnl, 0)) },
]
</script>

<template>
  <div>
    <NSpace style="margin-bottom: 16px">
      <NInputNumber v-model:value="simDays" :min="5" :max="120" size="small" placeholder="模擬天數" style="width: 120px" />
      <NButton type="primary" @click="runSimulation" :loading="bt.isLoading">開始模擬</NButton>
    </NSpace>

    <template v-if="bt.simulationResult">
      <NGrid :cols="metricCols" :x-gap="12" :y-gap="12" style="margin-bottom: 16px">
        <NGi><MetricCard title="總報酬率" :value="fmtPct(bt.simulationResult.total_return)" :color="priceColor(bt.simulationResult.total_return)" /></NGi>
        <NGi><MetricCard title="最終資產" :value="fmtNum(bt.simulationResult.final_equity, 0)" /></NGi>
        <NGi><MetricCard title="最大回撤" :value="fmtPct(bt.simulationResult.max_drawdown)" color="#e53e3e" /></NGi>
        <NGi><MetricCard title="交易次數" :value="bt.simulationResult.total_trades" /></NGi>
        <NGi>
          <MetricCard title="勝/敗交易">
            <template #default>
              <span style="color: #e53e3e">{{ bt.simulationResult.winning_trades }}</span>
              /
              <span style="color: #38a169">{{ bt.simulationResult.losing_trades }}</span>
            </template>
          </MetricCard>
        </NGi>
        <NGi><MetricCard title="手續費" :value="fmtNum(bt.simulationResult.total_commission, 0)" /></NGi>
        <NGi><MetricCard title="交易稅" :value="fmtNum(bt.simulationResult.total_tax, 0)" /></NGi>
        <NGi><MetricCard title="初始資金" :value="fmtNum(bt.simulationResult.initial_capital, 0)" /></NGi>
      </NGrid>

      <NTabs type="line">
        <NTabPane name="equity" tab="資產曲線">
          <NCard size="small"><ChartContainer :option="simEquityOption" height="350px" /></NCard>
        </NTabPane>
        <NTabPane name="records" tab="每日紀錄">
          <NDataTable
            :columns="simRecordColumns"
            :data="bt.simulationResult.daily_records"
            :pagination="simRecordPagination"
            size="small"
            :scroll-x="680"
          />
        </NTabPane>
        <NTabPane v-if="bt.simulationResult.trade_log?.length" name="log" tab="交易日誌">
          <div style="font-size: 13px; line-height: 1.8">
            <div v-for="(log, i) in bt.simulationResult.trade_log" :key="i" style="border-bottom: 1px solid var(--border-light); padding: 4px 0">
              {{ log }}
            </div>
          </div>
        </NTabPane>
      </NTabs>
    </template>
  </div>
</template>
