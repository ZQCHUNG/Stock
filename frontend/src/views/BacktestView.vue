<script setup lang="ts">
import { h, ref, reactive, computed, onMounted } from 'vue'
import {
  NCard, NButton, NGrid, NGi, NSpin, NAlert, NTabs, NTabPane,
  NInputNumber, NSpace, NDataTable, NTag, NSelect,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart, BarChart, PieChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useAppStore } from '../stores/app'
import { useBacktestStore } from '../stores/backtest'
import { useWatchlistStore } from '../stores/watchlist'
import { fmtPct, fmtNum, priceColor, downloadCsv } from '../utils/format'
import { useResponsive } from '../composables/useResponsive'
import MetricCard from '../components/MetricCard.vue'

use([LineChart, BarChart, PieChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const app = useAppStore()
const bt = useBacktestStore()
const wl = useWatchlistStore()

onMounted(() => wl.load())

const { cols } = useResponsive()
const metricCols = cols(2, 3, 4)

// Shared params
const periodDays = ref(1095)
const capital = ref(1_000_000)

// Mode: single / portfolio / simulation
const mode = ref('single')

// --- Single Backtest ---
async function runBacktest() {
  await bt.runSingle(app.currentStockCode, { period_days: periodDays.value, initial_capital: capital.value })
}

const equityOption = computed(() => {
  const r = bt.singleResult
  if (!r?.equity_curve?.dates?.length) return {}
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 80, right: 20, top: 20, bottom: 30 },
    xAxis: { type: 'category', data: r.equity_curve.dates },
    yAxis: { type: 'value', axisLabel: { formatter: (v: number) => fmtNum(v) } },
    series: [{ type: 'line', data: r.equity_curve.values, symbol: 'none', areaStyle: { opacity: 0.15 }, lineStyle: { width: 1.5, color: '#2196f3' } }],
  }
})

const exitPieOption = computed(() => {
  const trades = bt.singleResult?.trades || []
  const counts: Record<string, number> = {}
  trades.forEach((t: any) => { counts[t.exit_reason] = (counts[t.exit_reason] || 0) + 1 })
  const data = Object.entries(counts).map(([name, value]) => ({ name, value }))
  return {
    tooltip: { trigger: 'item' },
    series: [{ type: 'pie', radius: ['40%', '70%'], data, label: { fontSize: 11 } }],
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

// --- Portfolio Backtest ---
const portfolioCodes = ref<string[]>([])

const portfolioStockOptions = computed(() => {
  // Use watchlist stocks as quick options
  const opts = wl.watchlist.map((s) => ({ label: `${s.code} ${s.name}`, value: s.code }))
  // Also add some popular defaults
  if (opts.length === 0) {
    return ['2330', '2317', '2454', '2881', '2882', '3008', '2412', '1301'].map(
      (c) => ({ label: `${c} ${app.getStockName(c)}`, value: c }),
    )
  }
  return opts
})

async function runPortfolio() {
  if (portfolioCodes.value.length < 2) return
  await bt.runPortfolio(portfolioCodes.value, { period_days: periodDays.value, initial_capital: capital.value })
}

const portfolioEquityOption = computed(() => {
  const r = bt.portfolioResult
  if (!r?.equity_curve?.dates?.length) return {}
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 80, right: 20, top: 20, bottom: 30 },
    xAxis: { type: 'category', data: r.equity_curve.dates },
    yAxis: { type: 'value', axisLabel: { formatter: (v: number) => fmtNum(v) } },
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

// --- Simulation ---
const simDays = ref(30)

async function runSimulation() {
  await bt.runSimulation(app.currentStockCode, simDays.value, {
    period_days: periodDays.value,
    initial_capital: capital.value,
  })
}

const simEquityOption = computed(() => {
  const r = bt.simulationResult
  if (!r?.daily_records?.length) return {}
  const dates = r.daily_records.map((d: any) => d.date?.slice(0, 10))
  const equity = r.daily_records.map((d: any) => d.total_equity)
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 80, right: 20, top: 20, bottom: 30 },
    xAxis: { type: 'category', data: dates },
    yAxis: { type: 'value', axisLabel: { formatter: (v: number) => fmtNum(v) } },
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
    <h2 style="margin: 0 0 16px">{{ app.currentStockCode }} {{ app.currentStockName }} - 回測報告</h2>

    <!-- Mode Selector -->
    <NTabs v-model:value="mode" type="segment" style="margin-bottom: 16px">
      <NTabPane name="single" tab="單一回測" />
      <NTabPane name="portfolio" tab="投資組合" />
      <NTabPane name="simulation" tab="模擬交易" />
    </NTabs>

    <!-- Shared Params -->
    <NSpace style="margin-bottom: 16px">
      <NInputNumber v-model:value="periodDays" :min="180" :max="3650" size="small" placeholder="天數" style="width: 120px" />
      <NInputNumber v-model:value="capital" :min="100000" :step="100000" size="small" placeholder="資金" style="width: 160px" />

      <!-- Single mode button -->
      <NButton v-if="mode === 'single'" type="primary" @click="runBacktest" :loading="bt.isLoading">執行回測</NButton>

      <!-- Portfolio mode controls -->
      <template v-if="mode === 'portfolio'">
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
      </template>

      <!-- Simulation mode controls -->
      <template v-if="mode === 'simulation'">
        <NInputNumber v-model:value="simDays" :min="5" :max="120" size="small" placeholder="模擬天數" style="width: 120px" />
        <NButton type="primary" @click="runSimulation" :loading="bt.isLoading">開始模擬</NButton>
      </template>
    </NSpace>

    <NSpin :show="bt.isLoading">
      <NAlert v-if="bt.error" type="error" style="margin-bottom: 16px">{{ bt.error }}</NAlert>

      <!-- ====== SINGLE BACKTEST ====== -->
      <template v-if="mode === 'single' && bt.singleResult">
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
            <NCard size="small"><VChart :option="equityOption" autoresize style="height: 350px" /></NCard>
          </NTabPane>
          <NTabPane name="exit" tab="出場分布">
            <NCard size="small"><VChart :option="exitPieOption" autoresize style="height: 300px" /></NCard>
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
            />
          </NTabPane>
        </NTabs>

        <div v-if="bt.singleResult.params_description" style="margin-top: 8px; font-size: 12px; color: #718096">
          策略參數: {{ bt.singleResult.params_description }}
        </div>
      </template>

      <!-- ====== PORTFOLIO BACKTEST ====== -->
      <template v-if="mode === 'portfolio' && bt.portfolioResult">
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
            <NCard size="small"><VChart :option="portfolioEquityOption" autoresize style="height: 350px" /></NCard>
          </NTabPane>
          <NTabPane name="stocks" tab="個股明細">
            <NDataTable
              :columns="stockResultColumns"
              :data="portfolioStockData"
              size="small"
              :pagination="{ pageSize: 20 }"
            />
          </NTabPane>
        </NTabs>
      </template>

      <!-- ====== SIMULATION ====== -->
      <template v-if="mode === 'simulation' && bt.simulationResult">
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
            <NCard size="small"><VChart :option="simEquityOption" autoresize style="height: 350px" /></NCard>
          </NTabPane>
          <NTabPane name="records" tab="每日紀錄">
            <NDataTable
              :columns="simRecordColumns"
              :data="bt.simulationResult.daily_records"
              :pagination="simRecordPagination"
              size="small"
            />
          </NTabPane>
          <NTabPane v-if="bt.simulationResult.trade_log?.length" name="log" tab="交易日誌">
            <div style="font-size: 13px; line-height: 1.8">
              <div v-for="(log, i) in bt.simulationResult.trade_log" :key="i" style="border-bottom: 1px solid #f0f0f0; padding: 4px 0">
                {{ log }}
              </div>
            </div>
          </NTabPane>
        </NTabs>
      </template>
    </NSpin>
  </div>
</template>

<style>
.row-win td:nth-child(5) { color: #e53e3e; }
.row-loss td:nth-child(5) { color: #38a169; }
</style>
