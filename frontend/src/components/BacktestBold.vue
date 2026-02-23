<script setup lang="ts">
import { h, ref, reactive, computed, watch } from 'vue'
import {
  NCard, NButton, NGrid, NGi, NTabs, NTabPane, NDataTable, NSpace, NSwitch, NText, NSpin, NTag, NSelect,
} from 'naive-ui'
import { use } from 'echarts/core'
import { LineChart, PieChart, BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, ToolboxComponent, DataZoomComponent, LegendComponent } from 'echarts/components'
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

use([LineChart, PieChart, BarChart, GridComponent, TooltipComponent, ToolboxComponent, DataZoomComponent, LegendComponent, CanvasRenderer])

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

const ultraWide = ref(true)
const brokerDiscount = ref(1.0)  // Phase 9A: 1.0=full, 0.28=2.8折
const dynamicSlippage = ref(false)  // Phase 9A: Kyle Lambda
const klineData = ref<TimeSeriesData | null>(null)
const klineLoading = ref(false)
const liquidityData = ref<any>(null)

// Phase 8C: Trade Replay
const candlestickRef = ref<InstanceType<typeof CandlestickChart> | null>(null)
const activeTradeIdx = ref<number | undefined>(undefined)
const activeTab = ref('equity')

function replayTrade(trade: any, index: number) {
  activeTradeIdx.value = index
  activeTab.value = 'kline-trades'
  // Wait for tab switch, then zoom
  setTimeout(() => {
    candlestickRef.value?.zoomToTrade(trade)
  }, 100)
}

function clearReplay() {
  activeTradeIdx.value = undefined
}

const r = computed(() => bt.boldResult)

async function runBacktest() {
  await bt.runBold(app.currentStockCode, {
    period_days: props.periodDays,
    initial_capital: props.capital,
    ultra_wide: ultraWide.value,
    broker_discount: brokerDiscount.value,
    use_dynamic_slippage: dynamicSlippage.value,
    ...props.costParams,
  })
  // Load liquidity score alongside backtest
  analysisApi.liquidity(app.currentStockCode, props.capital)
    .then(d => { liquidityData.value = d })
    .catch(() => { liquidityData.value = null })
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

const expectancy = computed(() => {
  if (!r.value?.total_trades) return '-'
  const wr = r.value.win_rate || 0
  const avgW = r.value.avg_win || 0
  const avgL = r.value.avg_loss || 0
  return fmtPct(wr * avgW + (1 - wr) * avgL)
})

// Phase 9A: CAR (Cost-to-Alpha Ratio) — CTO mandate
const carLabel = computed(() => {
  const car = r.value?.cost_to_alpha_ratio
  if (car == null) return '-'
  return `${car.toFixed(1)}%`
})
const carColor = computed(() => {
  const car = r.value?.cost_to_alpha_ratio
  if (car == null) return undefined
  if (car > 30) return '#e53e3e'  // bloated
  if (car < 15) return '#38a169'  // high quality
  return '#dd6b20'  // warning
})

const equityOption = computed(() => {
  if (!r.value?.equity_curve?.dates?.length) return {}
  const cc = chartColors.value
  const dates = r.value.equity_curve.dates
  const values = r.value.equity_curve.values as number[]
  const grossValues = r.value?.gross_equity_curve?.values as number[] | undefined
  const trades = r.value.trades || []
  const dateIdx: Record<string, number> = {}
  dates.forEach((d: string, i: number) => { dateIdx[d.slice(0, 10)] = i })
  const buyMarks: number[][] = []
  const sellMarks: number[][] = []
  trades.forEach((t: any) => {
    const od = t.date_open?.slice(0, 10)
    const cd = t.date_close?.slice(0, 10)
    const oi = od ? dateIdx[od] : undefined
    const ci = cd ? dateIdx[cd] : undefined
    if (oi !== undefined) buyMarks.push([oi, values[oi] as number])
    if (ci !== undefined) sellMarks.push([ci, values[ci] as number])
  })
  const hasGross = grossValues && grossValues.length > 0
  const legendData = hasGross ? ['Gross', 'Net', '買入', '賣出'] : ['權益', '買入', '賣出']
  const series: any[] = []
  if (hasGross) {
    series.push({ name: 'Gross', type: 'line', data: grossValues, symbol: 'none', lineStyle: { width: 1.5, color: '#38a169', type: 'dashed' } })
    series.push({ name: 'Net', type: 'line', data: values, symbol: 'none', areaStyle: { opacity: 0.1, color: '#e53e3e' }, lineStyle: { width: 1.5, color: '#ff6b35' } })
  } else {
    series.push({ name: '權益', type: 'line', data: values, symbol: 'none', areaStyle: { opacity: 0.15 }, lineStyle: { width: 1.5, color: '#ff6b35' } })
  }
  return {
    tooltip: { trigger: 'axis', ...tooltipStyle.value },
    toolbox: { ...toolboxConfig.value, feature: { restore: toolboxConfig.value.feature.restore, saveAsImage: toolboxConfig.value.feature.saveAsImage } },
    legend: { data: legendData, textStyle: { color: cc.legendText, fontSize: 11 }, top: 0 },
    grid: { left: 80, right: 20, top: 30, bottom: 50 },
    xAxis: { type: 'category', data: dates, axisLabel: { color: cc.axisLabel } },
    yAxis: { type: 'value', axisLabel: { formatter: (v: number) => fmtNum(v), color: cc.axisLabel }, splitLine: { lineStyle: { color: cc.splitLine } } },
    dataZoom: [
      { type: 'inside', start: 0, end: 100 },
      { type: 'slider', start: 0, end: 100, height: 20, bottom: 4, borderColor: 'transparent', backgroundColor: cc.splitLine },
    ],
    series: [
      ...series,
      { name: '買入', type: 'scatter', data: buyMarks, symbol: 'triangle', symbolSize: 8, itemStyle: { color: '#38a169' }, z: 10 },
      { name: '賣出', type: 'scatter', data: sellMarks, symbol: 'diamond', symbolSize: 8, itemStyle: { color: '#e53e3e' }, z: 10 },
    ],
  }
})

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

function exportTrades() {
  downloadCsv(r.value?.trades || [], [
    { key: 'date_open', label: '開倉日' },
    { key: 'date_close', label: '平倉日' },
    { key: 'price_open', label: '買入價' },
    { key: 'price_close', label: '賣出價' },
    { key: 'pnl', label: '損益' },
    { key: 'return_pct', label: '報酬率' },
    { key: 'exit_reason', label: '出場原因' },
  ], `bold_${app.currentStockCode}_trades.csv`)
}

const tradePagination = reactive({ page: 1, pageSize: 15, showSizePicker: true, pageSizes: [10, 15, 25, 50] })

const tradeColumns = [
  {
    title: '',
    key: 'replay',
    width: 45,
    render: (row: any, index: number) => h(
      NButton,
      { size: 'tiny', type: 'primary', ghost: true, onClick: () => replayTrade(row, index) },
      () => '>>',
    ),
  },
  { title: '開倉日', key: 'date_open', width: 100, render: (row: any) => row.date_open?.slice(0, 10) },
  { title: '平倉日', key: 'date_close', width: 100, render: (row: any) => row.date_close?.slice(0, 10) },
  { title: '買入價', key: 'price_open', width: 80, render: (row: any) => row.price_open?.toFixed(2) },
  { title: '賣出價', key: 'price_close', width: 80, render: (row: any) => row.price_close?.toFixed(2) },
  { title: '損益', key: 'pnl', width: 100, render: (row: any) => fmtNum(row.pnl) },
  {
    title: '報酬%',
    key: 'return_pct',
    width: 80,
    render: (row: any) => h(
      'span',
      { style: `color: ${(row.return_pct ?? 0) >= 0 ? '#e53e3e' : '#38a169'}; font-weight: 600` },
      fmtPct(row.return_pct),
    ),
  },
  { title: '出場原因', key: 'exit_reason', width: 120 },
  {
    title: '天數',
    key: 'hold_days',
    width: 55,
    render: (row: any) => {
      if (!row.date_open || !row.date_close) return '-'
      const days = Math.round((new Date(row.date_close).getTime() - new Date(row.date_open).getTime()) / 86400000)
      return `${days}d`
    },
  },
]
</script>

<template>
  <div>
    <NSpace align="center" style="margin-bottom: 16px" :wrap="true">
      <NButton type="warning" @click="runBacktest" :loading="bt.isLoading">執行 Bold 回測</NButton>
      <NSpace align="center" :size="4">
        <NSwitch v-model:value="ultraWide" size="small" />
        <NText depth="3" style="font-size: 12px">Ultra-Wide</NText>
      </NSpace>
      <NSpace align="center" :size="4">
        <NText depth="3" style="font-size: 11px">券商折讓</NText>
        <NSelect v-model:value="brokerDiscount" :options="[
          { label: '原價 (0.1425%)', value: 1.0 },
          { label: '5折 (0.071%)', value: 0.5 },
          { label: '3.5折 (0.050%)', value: 0.35 },
          { label: '2.8折 (0.040%)', value: 0.28 },
        ]" size="small" style="width: 140px" />
      </NSpace>
      <NSpace align="center" :size="4">
        <NSwitch v-model:value="dynamicSlippage" size="small" />
        <NText depth="3" style="font-size: 11px">動態滑價 (Kyle Lambda)</NText>
      </NSpace>
    </NSpace>

    <NText depth="3" style="font-size: 11px; display: block; margin-bottom: 12px">
      Bold 策略：能量擠壓突破 + 量能爬坡 + 階梯式停利。適合爆發性波段。
      {{ ultraWide ? 'Ultra-Wide: MA200 多頭放寬 trail (0.15→0.20)，max_hold 365d。' : '標準: trail 15%，max_hold 120d。' }}
    </NText>

    <!-- Liquidity Risk Badge (R69) -->
    <NCard v-if="liquidityData" size="small" style="margin-bottom: 12px">
      <NSpace align="center" :size="12">
        <NTag
          :type="liquidityData.grade === 'green' ? 'success' : liquidityData.grade === 'yellow' ? 'warning' : 'error'"
          size="small"
        >
          流動性 {{ liquidityData.score }} 分
        </NTag>
        <NText depth="3" style="font-size: 11px">
          出清 {{ liquidityData.dtl?.toFixed(1) }}天 |
          日均 {{ liquidityData.adv_20_lots?.toFixed(0) }}張 |
          衝擊 {{ liquidityData.market_impact_pct?.toFixed(2) }}% |
          {{ liquidityData.grade === 'green' ? '可順利出清' : liquidityData.grade === 'yellow' ? '需拆單出場' : '停損可能失敗' }}
        </NText>
      </NSpace>
    </NCard>

    <template v-if="r">
      <NGrid :cols="metricCols" :x-gap="12" :y-gap="12" style="margin-bottom: 16px">
        <NGi><MetricCard title="總報酬率" :value="fmtPct(r.total_return)" :color="priceColor(r.total_return)" /></NGi>
        <NGi><MetricCard title="年化報酬" :value="fmtPct(r.annual_return)" :color="priceColor(r.annual_return)" /></NGi>
        <NGi><MetricCard title="最大回撤" :value="fmtPct(r.max_drawdown)" color="#e53e3e" /></NGi>
        <NGi><MetricCard title="Sharpe" :value="r.sharpe_ratio?.toFixed(2) || '-'" /></NGi>
        <NGi><MetricCard title="勝率" :value="fmtPct(r.win_rate)" /></NGi>
        <NGi><MetricCard title="盈虧比" :value="r.profit_factor?.toFixed(2) || '-'" /></NGi>
        <NGi><MetricCard title="交易次數" :value="r.total_trades" /></NGi>
        <NGi><MetricCard title="平均持有天數" :value="r.avg_holding_days?.toFixed(1) || '-'" /></NGi>
        <NGi><MetricCard title="Sortino" :value="r.sortino_ratio?.toFixed(2) || '-'" /></NGi>
        <NGi><MetricCard title="Calmar" :value="r.calmar_ratio?.toFixed(2) || '-'" /></NGi>
        <NGi><MetricCard title="期望值" :value="expectancy" :color="priceColor(parseFloat(String(expectancy)) || 0)" /></NGi>
        <NGi v-if="r.total_costs"><MetricCard title="總交易成本" :value="'$' + fmtNum(r.total_costs, 0)" color="#e53e3e" /></NGi>
        <NGi v-if="r.gross_total_return != null"><MetricCard title="Gross Return" :value="fmtPct(r.gross_total_return)" :color="priceColor(r.gross_total_return)" /></NGi>
        <NGi v-if="r.cost_to_alpha_ratio != null"><MetricCard title="CAR (Cost/Alpha)" :value="carLabel" :color="carColor" /></NGi>
        <NGi v-if="r.total_slippage"><MetricCard title="滑價成本" :value="'$' + fmtNum(r.total_slippage, 0)" color="#dd6b20" /></NGi>
      </NGrid>

      <!-- Phase 9A: Cost breakdown banner -->
      <NCard v-if="r.total_costs" size="small" style="margin-bottom: 12px">
        <NSpace align="center" :size="16" :wrap="true">
          <NText depth="3" style="font-size: 11px">
            手續費 ${{ fmtNum(r.total_commission, 0) }} |
            交易稅 ${{ fmtNum(r.total_tax, 0) }} |
            滑價 ${{ fmtNum(r.total_slippage || 0, 0) }} |
            合計 ${{ fmtNum(r.total_costs, 0) }}
          </NText>
          <NTag v-if="r.cost_to_alpha_ratio != null" :type="r.cost_to_alpha_ratio > 30 ? 'error' : r.cost_to_alpha_ratio < 15 ? 'success' : 'warning'" size="small">
            CAR {{ r.cost_to_alpha_ratio?.toFixed(1) }}%
            {{ r.cost_to_alpha_ratio > 30 ? '(high drag)' : r.cost_to_alpha_ratio < 15 ? '(efficient)' : '' }}
          </NTag>
        </NSpace>
      </NCard>

      <NTabs v-model:value="activeTab" type="line">
        <NTabPane name="equity" tab="權益曲線">
          <NCard size="small"><ChartContainer :option="equityOption" height="350px" /></NCard>
        </NTabPane>
        <NTabPane name="kline-trades" tab="K線交易">
          <NCard size="small">
            <NSpin :show="klineLoading">
              <CandlestickChart
                v-if="klineData"
                ref="candlestickRef"
                :data="klineData"
                :trades="r?.trades"
                :active-trade-idx="activeTradeIdx"
                :show-trade-areas="true"
              />
              <div v-else style="text-align: center; padding: 40px; color: var(--text-muted)">載入中...</div>
            </NSpin>
          </NCard>
        </NTabPane>
        <NTabPane name="drawdown" tab="回撤曲線">
          <NCard size="small"><ChartContainer :option="drawdownOption" height="300px" /></NCard>
        </NTabPane>
        <NTabPane name="exit" tab="出場分布">
          <NCard size="small"><ChartContainer :option="exitPieOption" height="300px" /></NCard>
        </NTabPane>
        <NTabPane name="trades" tab="交易明細">
          <NSpace style="margin-bottom: 8px" justify="space-between">
            <NSpace :size="8" align="center">
              <NText depth="3" style="font-size: 11px">Click >> to replay trade on K-line chart</NText>
              <NButton v-if="activeTradeIdx != null" size="tiny" @click="clearReplay">Clear Selection</NButton>
            </NSpace>
            <NButton size="small" @click="exportTrades" :disabled="!r?.trades?.length">匯出 CSV</NButton>
          </NSpace>
          <NDataTable :columns="tradeColumns" :data="r.trades" :pagination="tradePagination" size="small" :scroll-x="640" />
        </NTabPane>
      </NTabs>
    </template>
  </div>
</template>
