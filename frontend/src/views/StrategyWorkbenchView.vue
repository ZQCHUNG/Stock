<script setup lang="ts">
import { h, ref, onMounted, computed } from 'vue'
import {
  NCard, NButton, NSpace, NGrid, NGi, NTag, NInput, NInputNumber,
  NDataTable, NSpin, NDivider, NStatistic, NAlert, NModal, NForm,
  NFormItem, NTabs, NTabPane, useMessage,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import VChart from 'vue-echarts'
import { strategiesApi, type Strategy } from '../api/strategies'
import { analysisApi } from '../api/analysis'
import { useAppStore } from '../stores/app'
import FitnessView from './FitnessView.vue'
import BacktestView from './BacktestView.vue'

const msg = useMessage()
const app = useAppStore()

const strategies = ref<Strategy[]>([])
const loading = ref(false)
const regime = ref<any>(null)
const regimeLoading = ref(false)
const showCreate = ref(false)
const showBacktest = ref(false)
const btResult = ref<any>(null)
const btLoading = ref(false)
const selectedStrategy = ref<Strategy | null>(null)
const adaptive = ref<any>(null)
const adaptiveLoading = ref(false)
const showAdaptiveBt = ref(false)
const adaptiveBtResult = ref<any>(null)
const adaptiveBtLoading = ref(false)
const activeTab = ref('manage')
const batchResult = ref<any>(null)
const batchLoading = ref(false)
const showBatchModal = ref(false)

// Create form
const createForm = ref({
  name: '',
  description: '',
  adx_threshold: 18,
  ma_trend_days: 10,
  take_profit_pct: 0.10,
  stop_loss_pct: -0.07,
  trailing_stop_pct: 0.02,
  min_hold_days: 5,
  min_volume: 500,
  // R52 P1: Fundamental filters
  min_roe: null as number | null,
  max_pe: null as number | null,
  min_market_cap: null as number | null,
})

async function loadStrategies() {
  loading.value = true
  try {
    const data = await strategiesApi.list()
    strategies.value = data.strategies || []
  } catch { /* ignore */ }
  loading.value = false
}

async function loadRegime() {
  regimeLoading.value = true
  try {
    regime.value = await analysisApi.marketRegimeMl()
  } catch { regime.value = null }
  regimeLoading.value = false
}

async function loadAdaptive() {
  adaptiveLoading.value = true
  try {
    adaptive.value = await strategiesApi.adaptiveRecommendation()
  } catch { adaptive.value = null }
  adaptiveLoading.value = false
}

async function createStrategy() {
  try {
    const f = createForm.value
    await strategiesApi.create({
      name: f.name,
      description: f.description,
      params: {
        adx_threshold: f.adx_threshold,
        ma_short: 20,
        ma_long: 60,
        ma_trend_days: f.ma_trend_days,
        take_profit_pct: f.take_profit_pct,
        stop_loss_pct: f.stop_loss_pct,
        trailing_stop_pct: f.trailing_stop_pct,
        min_hold_days: f.min_hold_days,
        min_volume: f.min_volume,
        confidence_weight: 1.0,
        min_roe: f.min_roe,
        max_pe: f.max_pe,
        min_market_cap: f.min_market_cap ? f.min_market_cap * 1e8 : null,  // 億 → raw
      },
    })
    msg.success('策略已建立')
    showCreate.value = false
    await loadStrategies()
  } catch (e: any) {
    msg.error(e?.message || '建立失敗')
  }
}

async function cloneStrategy(id: string) {
  try {
    await strategiesApi.clone(id)
    msg.success('策略已複製')
    await loadStrategies()
  } catch (e: any) {
    msg.error(e?.message || '複製失敗')
  }
}

async function deleteStrategy(id: string) {
  try {
    await strategiesApi.delete(id)
    msg.success('策略已刪除')
    await loadStrategies()
  } catch (e: any) {
    msg.error(e?.message || '刪除失敗')
  }
}

async function runBacktest(strategy: Strategy) {
  const code = app.currentStockCode
  if (!code) {
    msg.warning('請先選擇股票')
    return
  }
  selectedStrategy.value = strategy
  btLoading.value = true
  showBacktest.value = true
  btResult.value = null
  try {
    btResult.value = await strategiesApi.backtest(strategy.id, code)
  } catch (e: any) {
    msg.error(e?.message || '回測失敗')
  }
  btLoading.value = false
}

async function runAdaptiveBacktest() {
  const code = app.currentStockCode
  if (!code) {
    msg.warning('請先選擇股票')
    return
  }
  showAdaptiveBt.value = true
  adaptiveBtLoading.value = true
  adaptiveBtResult.value = null
  try {
    adaptiveBtResult.value = await strategiesApi.adaptiveBacktest(code)
  } catch (e: any) {
    msg.error(e?.message || '自適應回測失敗')
  }
  adaptiveBtLoading.value = false
}

async function runBatchValidation() {
  batchLoading.value = true
  showBatchModal.value = true
  batchResult.value = null
  try {
    batchResult.value = await strategiesApi.batchAdaptiveBacktest(
      ['0050', '2330', '2317', '2454', '2882', '1301'],
    )
  } catch (e: any) {
    msg.error(e?.message || '批次驗證失敗')
  }
  batchLoading.value = false
}

// R54: Batch validation table columns
const batchColumns: DataTableColumns = [
  { title: '代號', key: 'code', width: 70 },
  { title: '數據天數', key: 'data_days', width: 80 },
  { title: 'Adaptive 報酬', key: 'a_ret', width: 110,
    render: (r: any) => h('span', { style: { color: (r.adaptive?.total_return || 0) >= 0 ? '#18a058' : '#e53e3e' } },
      `${((r.adaptive?.total_return || 0) * 100).toFixed(2)}%`),
    sorter: (a: any, b: any) => (a.adaptive?.total_return || 0) - (b.adaptive?.total_return || 0) },
  { title: 'V4 報酬', key: 'b_ret', width: 100,
    render: (r: any) => h('span', { style: { color: (r.baseline?.total_return || 0) >= 0 ? '#18a058' : '#e53e3e' } },
      `${((r.baseline?.total_return || 0) * 100).toFixed(2)}%`) },
  { title: 'Alpha', key: 'alpha', width: 90,
    render: (r: any) => h('span', { style: { color: (r.comparison?.alpha || 0) >= 0 ? '#18a058' : '#e53e3e', fontWeight: '600' } },
      `${(r.comparison?.alpha || 0) > 0 ? '+' : ''}${((r.comparison?.alpha || 0) * 100).toFixed(2)}%`),
    sorter: (a: any, b: any) => (a.comparison?.alpha || 0) - (b.comparison?.alpha || 0) },
  { title: 'Sharpe Δ', key: 'sharpe_d', width: 90,
    render: (r: any) => `${(r.comparison?.sharpe_delta || 0) > 0 ? '+' : ''}${(r.comparison?.sharpe_delta || 0).toFixed(3)}` },
  { title: 'Drawdown Δ', key: 'dd_d', width: 100,
    render: (r: any) => `${((r.comparison?.drawdown_delta || 0) * 100).toFixed(2)}%` },
  { title: '情境切換', key: 'regime_switches', width: 80 },
]

function regimeTagType(suit: string): 'success' | 'warning' | 'error' | 'info' | 'default' {
  if (suit === 'excellent') return 'success'
  if (suit === 'good') return 'info'
  if (suit === 'fair') return 'warning'
  if (suit === 'poor' || suit === 'avoid') return 'error'
  return 'default'
}

// R51-3: Monthly returns chart option
const monthlyChartOption = computed(() => {
  const data = btResult.value?.monthly_returns || []
  if (!data.length) return {}
  return {
    tooltip: { trigger: 'axis', formatter: (p: any) => `${p[0]?.axisValue}<br/>損益: $${(p[0]?.value || 0).toLocaleString()}` },
    grid: { left: 60, right: 16, top: 8, bottom: 24 },
    xAxis: { type: 'category', data: data.map((d: any) => d.month), axisLabel: { fontSize: 10, rotate: 30 } },
    yAxis: { type: 'value', axisLabel: { fontSize: 10, formatter: (v: number) => `$${(v / 1000).toFixed(0)}K` } },
    series: [{
      type: 'bar',
      data: data.map((d: any) => ({
        value: d.pnl,
        itemStyle: { color: d.pnl >= 0 ? '#18a058' : '#e53e3e' },
      })),
    }],
  }
})

// R51-3: Regime breakdown table columns
const regimeColumns: DataTableColumns = [
  { title: '市場情境', key: 'regime', width: 120 },
  { title: '交易數', key: 'count', width: 70, sorter: (a: any, b: any) => a.count - b.count },
  { title: '勝率', key: 'win_rate', width: 80,
    render: (r: any) => `${((r.win_rate || 0) * 100).toFixed(1)}%`,
    sorter: (a: any, b: any) => a.win_rate - b.win_rate },
  { title: '平均報酬', key: 'avg_return', width: 100,
    render: (r: any) => h('span', { style: { color: (r.avg_return || 0) >= 0 ? '#18a058' : '#e53e3e' } },
      `${((r.avg_return || 0) * 100).toFixed(2)}%`),
    sorter: (a: any, b: any) => a.avg_return - b.avg_return },
  { title: '累計損益', key: 'total_pnl', width: 110,
    render: (r: any) => h('span', { style: { color: (r.total_pnl || 0) >= 0 ? '#18a058' : '#e53e3e' } },
      `$${(r.total_pnl || 0).toLocaleString()}`),
    sorter: (a: any, b: any) => a.total_pnl - b.total_pnl },
]

// R52 P0: Adaptive vs Baseline equity curve comparison chart
const adaptiveEquityChartOption = computed(() => {
  const r = adaptiveBtResult.value
  if (!r?.adaptive?.equity_curve?.dates?.length) return {}
  const aDates = r.adaptive.equity_curve.dates
  const aVals = r.adaptive.equity_curve.values
  const bDates = r.baseline?.equity_curve?.dates || []
  const bVals = r.baseline?.equity_curve?.values || []
  return {
    tooltip: { trigger: 'axis', formatter: (p: any) => {
      let s = p[0]?.axisValue || ''
      for (const item of p) s += `<br/>${item.marker}${item.seriesName}: $${(item.value || 0).toLocaleString()}`
      return s
    }},
    legend: { data: ['自適應策略', 'V4 標準'], top: 0, textStyle: { fontSize: 11 } },
    grid: { left: 60, right: 16, top: 30, bottom: 24 },
    xAxis: { type: 'category', data: aDates, axisLabel: { fontSize: 10, rotate: 30 } },
    yAxis: { type: 'value', axisLabel: { fontSize: 10, formatter: (v: number) => `$${(v / 1e6).toFixed(2)}M` } },
    series: [
      { name: '自適應策略', type: 'line', data: aVals, lineStyle: { width: 2 }, symbol: 'none', itemStyle: { color: '#18a058' } },
      { name: 'V4 標準', type: 'line', data: bVals.length === aDates.length ? bVals : bDates.map((_: any, i: number) => bVals[i]), lineStyle: { width: 2, type: 'dashed' }, symbol: 'none', itemStyle: { color: '#666' } },
    ],
  }
})

// R52 P0: Regime performance table columns for adaptive backtest
const adaptiveRegimeColumns: DataTableColumns = [
  { title: '市場情境', key: 'regime', width: 120 },
  { title: '交易數', key: 'count', width: 70, sorter: (a: any, b: any) => a.count - b.count },
  { title: '勝率', key: 'win_rate', width: 80,
    render: (r: any) => `${((r.win_rate || 0) * 100).toFixed(1)}%`,
    sorter: (a: any, b: any) => a.win_rate - b.win_rate },
  { title: '平均報酬', key: 'avg_return', width: 100,
    render: (r: any) => h('span', { style: { color: (r.avg_return || 0) >= 0 ? '#18a058' : '#e53e3e' } },
      `${((r.avg_return || 0) * 100).toFixed(2)}%`),
    sorter: (a: any, b: any) => a.avg_return - b.avg_return },
  { title: '累計損益', key: 'total_pnl', width: 110,
    render: (r: any) => h('span', { style: { color: (r.total_pnl || 0) >= 0 ? '#18a058' : '#e53e3e' } },
      `$${(r.total_pnl || 0).toLocaleString()}`),
    sorter: (a: any, b: any) => a.total_pnl - b.total_pnl },
]

onMounted(async () => {
  await Promise.all([loadStrategies(), loadRegime(), loadAdaptive()])
})
</script>

<template>
  <div>
    <h2 style="margin: 0 0 16px">策略工作台</h2>

    <NTabs v-model:value="activeTab" type="line" style="margin-bottom: 16px">
      <NTabPane name="manage" tab="策略管理" display-directive="show:lazy">

    <!-- Market Regime ML -->
    <NCard size="small" style="margin-bottom: 16px">
      <template #header>
        <NSpace align="center" :size="8">
          <span>市場情境分析 (ML)</span>
          <NButton size="tiny" @click="loadRegime" :loading="regimeLoading">刷新</NButton>
        </NSpace>
      </template>
      <NSpin :show="regimeLoading">
        <template v-if="regime && regime.regime !== 'unknown'">
          <NGrid :cols="6" :x-gap="12">
            <NGi>
              <NStatistic label="市場情境">
                <template #default>
                  <NTag :type="regimeTagType(regime.v4_suitability)" size="large">
                    {{ regime.regime_label }}
                  </NTag>
                </template>
              </NStatistic>
            </NGi>
            <NGi>
              <NStatistic label="信心度" :value="`${(regime.confidence * 100).toFixed(0)}%`" />
            </NGi>
            <NGi>
              <NStatistic label="Kelly 乘數" :value="regime.kelly_multiplier?.toFixed(1)" />
            </NGi>
            <NGi>
              <NStatistic label="ADX" :value="regime.features?.adx?.toFixed(1)" />
            </NGi>
            <NGi>
              <NStatistic label="RSI" :value="regime.features?.rsi?.toFixed(1)" />
            </NGi>
            <NGi>
              <NStatistic label="V4 適配">
                <template #default>
                  <NTag :type="regimeTagType(regime.v4_suitability)" size="small">
                    {{ regime.v4_suitability }}
                  </NTag>
                </template>
              </NStatistic>
            </NGi>
          </NGrid>
          <NAlert type="info" :bordered="false" style="margin-top: 8px">
            {{ regime.strategy_advice }}
          </NAlert>
        </template>
        <div v-else-if="!regimeLoading" style="color: #999; padding: 8px">無法取得市場情境</div>
      </NSpin>
    </NCard>

    <!-- Adaptive Recommendation (R51-1) -->
    <NCard size="small" style="margin-bottom: 16px" v-if="adaptive && !adaptive.error">
      <template #header>
        <NSpace align="center" :size="8">
          <span>自適應策略推薦</span>
          <NButton size="tiny" @click="loadAdaptive" :loading="adaptiveLoading">刷新</NButton>
        </NSpace>
      </template>
      <NGrid :cols="12" :x-gap="12">
        <NGi :span="4">
          <NStatistic label="推薦策略">
            <template #default>
              <NTag type="primary" size="large">{{ adaptive.recommended_strategy?.name || '-' }}</NTag>
            </template>
          </NStatistic>
        </NGi>
        <NGi :span="2">
          <NStatistic label="倉位縮放" :value="`${((adaptive.param_adjustments?.position_scale || 0) * 100).toFixed(0)}%`" />
        </NGi>
        <NGi :span="2">
          <NStatistic label="Kelly" :value="adaptive.kelly_multiplier?.toFixed(1)" />
        </NGi>
        <NGi :span="4">
          <NStatistic label="參數調整">
            <template #default>
              <NSpace :size="4" :wrap="true">
                <NTag v-if="adaptive.param_adjustments?.stop_loss_pct" size="small" type="error">
                  SL {{ (adaptive.param_adjustments.stop_loss_pct * 100).toFixed(0) }}%
                </NTag>
                <NTag v-if="adaptive.param_adjustments?.trailing_stop_pct" size="small" type="warning">
                  TS {{ (adaptive.param_adjustments.trailing_stop_pct * 100).toFixed(1) }}%
                </NTag>
                <NTag v-if="adaptive.param_adjustments?.adx_threshold" size="small">
                  ADX ≥ {{ adaptive.param_adjustments.adx_threshold }}
                </NTag>
                <NTag v-if="adaptive.param_adjustments?.max_positions" size="small">
                  Max {{ adaptive.param_adjustments.max_positions }}
                </NTag>
                <NTag v-if="adaptive.param_adjustments?.pause_new_entries" size="small" type="error">
                  暫停開倉
                </NTag>
              </NSpace>
            </template>
          </NStatistic>
        </NGi>
      </NGrid>
      <NAlert v-for="(reason, idx) in (adaptive.reasoning || [])" :key="idx"
              type="info" :bordered="false" style="margin-top: 4px">
        {{ reason }}
      </NAlert>
    </NCard>

    <!-- Adaptive Backtest Buttons -->
    <NCard size="small" style="margin-bottom: 16px">
      <NSpace align="center" justify="space-between">
        <div>
          <strong>自適應策略驗證</strong>
          <span style="color: #999; margin-left: 8px; font-size: 12px">
            ML 情境動態切換策略 vs 固定 V4
          </span>
        </div>
        <NSpace :size="8">
          <NButton @click="runAdaptiveBacktest" :loading="adaptiveBtLoading">
            單股回測 {{ app.currentStockCode || '...' }}
          </NButton>
          <NButton type="primary" @click="runBatchValidation" :loading="batchLoading">
            批次驗證 (6 標的, 3年)
          </NButton>
        </NSpace>
      </NSpace>
    </NCard>

    <!-- Strategy List -->
    <NCard size="small">
      <template #header>
        <NSpace align="center" :size="8">
          <span>策略列表</span>
          <NTag size="small">{{ strategies.length }} 個策略</NTag>
        </NSpace>
      </template>
      <template #header-extra>
        <NButton size="small" type="primary" @click="showCreate = true">新增策略</NButton>
      </template>
      <NSpin :show="loading">
        <NGrid :cols="1" :y-gap="12">
          <NGi v-for="s in strategies" :key="s.id">
            <NCard size="small" :bordered="true" embedded>
              <NGrid :cols="12" :x-gap="8" style="align-items: center">
                <NGi :span="3">
                  <div>
                    <strong>{{ s.name }}</strong>
                    <NTag v-if="s.is_default" type="info" size="small" style="margin-left: 6px">預設</NTag>
                  </div>
                  <div style="font-size: 12px; color: #999; margin-top: 2px">{{ s.description || '-' }}</div>
                </NGi>
                <NGi :span="6">
                  <NSpace :size="8" :wrap="false">
                    <NTag size="small">ADX ≥ {{ s.params.adx_threshold }}</NTag>
                    <NTag size="small">TP {{ (s.params.take_profit_pct * 100).toFixed(0) }}%</NTag>
                    <NTag size="small" type="error">SL {{ (s.params.stop_loss_pct * 100).toFixed(0) }}%</NTag>
                    <NTag size="small" type="warning">TS {{ (s.params.trailing_stop_pct * 100).toFixed(1) }}%</NTag>
                    <NTag size="small">持有 ≥ {{ s.params.min_hold_days }}d</NTag>
                    <NTag size="small">量 ≥ {{ s.params.min_volume }}</NTag>
                    <NTag v-if="s.params.min_roe" size="small" type="success">ROE ≥ {{ (s.params.min_roe * 100).toFixed(0) }}%</NTag>
                    <NTag v-if="s.params.max_pe" size="small" type="info">PE ≤ {{ s.params.max_pe }}</NTag>
                    <NTag v-if="s.params.min_market_cap" size="small">市值 ≥ {{ (s.params.min_market_cap / 1e8).toFixed(0) }}億</NTag>
                  </NSpace>
                </NGi>
                <NGi :span="3" style="text-align: right">
                  <NSpace :size="4">
                    <NButton size="tiny" type="primary" @click="runBacktest(s)">
                      回測 {{ app.currentStockCode || '...' }}
                    </NButton>
                    <NButton size="tiny" @click="cloneStrategy(s.id)">複製</NButton>
                    <NButton size="tiny" type="error" :disabled="s.is_default" @click="deleteStrategy(s.id)">刪除</NButton>
                  </NSpace>
                </NGi>
              </NGrid>
            </NCard>
          </NGi>
        </NGrid>
        <div v-if="!loading && !strategies.length" style="padding: 20px; text-align: center; color: #999">
          尚無策略。點擊「新增策略」建立第一個。
        </div>
      </NSpin>
    </NCard>

      </NTabPane>

      <NTabPane name="backtest" tab="回測與分析" display-directive="if">
        <BacktestView />
      </NTabPane>

      <NTabPane name="fitness" tab="策略適配" display-directive="if">
        <FitnessView />
      </NTabPane>
    </NTabs>

    <!-- Create Strategy Modal -->
    <NModal v-model:show="showCreate" preset="card" title="新增策略" style="width: 520px">
      <NForm label-placement="left" label-width="120" :model="createForm">
        <NFormItem label="策略名稱">
          <NInput v-model:value="createForm.name" placeholder="e.g. V4 Conservative" />
        </NFormItem>
        <NFormItem label="說明">
          <NInput v-model:value="createForm.description" type="textarea" :rows="2" />
        </NFormItem>
        <NDivider style="margin: 12px 0">參數</NDivider>
        <NGrid :cols="2" :x-gap="12">
          <NGi>
            <NFormItem label="ADX 門檻">
              <NInputNumber v-model:value="createForm.adx_threshold" :min="10" :max="40" :step="1" size="small" />
            </NFormItem>
          </NGi>
          <NGi>
            <NFormItem label="MA 趨勢天數">
              <NInputNumber v-model:value="createForm.ma_trend_days" :min="3" :max="30" :step="1" size="small" />
            </NFormItem>
          </NGi>
          <NGi>
            <NFormItem label="停利 %">
              <NInputNumber v-model:value="createForm.take_profit_pct" :min="0.03" :max="0.50" :step="0.01" size="small" />
            </NFormItem>
          </NGi>
          <NGi>
            <NFormItem label="停損 %">
              <NInputNumber v-model:value="createForm.stop_loss_pct" :min="-0.20" :max="-0.03" :step="0.01" size="small" />
            </NFormItem>
          </NGi>
          <NGi>
            <NFormItem label="移動停利 %">
              <NInputNumber v-model:value="createForm.trailing_stop_pct" :min="0.01" :max="0.05" :step="0.005" size="small" />
            </NFormItem>
          </NGi>
          <NGi>
            <NFormItem label="最小持有日">
              <NInputNumber v-model:value="createForm.min_hold_days" :min="1" :max="20" :step="1" size="small" />
            </NFormItem>
          </NGi>
          <NGi>
            <NFormItem label="最小成交量">
              <NInputNumber v-model:value="createForm.min_volume" :min="100" :max="5000" :step="100" size="small" />
            </NFormItem>
          </NGi>
        </NGrid>
        <NDivider style="margin: 12px 0">基本面篩選 (R52)</NDivider>
        <NGrid :cols="3" :x-gap="12">
          <NGi>
            <NFormItem label="ROE ≥">
              <NInputNumber v-model:value="createForm.min_roe" :min="0" :max="1" :step="0.01" size="small"
                            placeholder="e.g. 0.15" clearable />
            </NFormItem>
          </NGi>
          <NGi>
            <NFormItem label="PE ≤">
              <NInputNumber v-model:value="createForm.max_pe" :min="1" :max="200" :step="1" size="small"
                            placeholder="e.g. 20" clearable />
            </NFormItem>
          </NGi>
          <NGi>
            <NFormItem label="市值 ≥ (億)">
              <NInputNumber v-model:value="createForm.min_market_cap" :min="0" :step="10" size="small"
                            placeholder="e.g. 100" clearable />
            </NFormItem>
          </NGi>
        </NGrid>
      </NForm>
      <template #action>
        <NSpace>
          <NButton @click="showCreate = false">取消</NButton>
          <NButton type="primary" @click="createStrategy" :disabled="!createForm.name">建立</NButton>
        </NSpace>
      </template>
    </NModal>

    <!-- Adaptive Backtest Result Modal (R52 P0) -->
    <NModal v-model:show="showAdaptiveBt" preset="card" style="width: 900px"
            :title="`自適應策略回測 — ${app.currentStockCode || ''}`">
      <NSpin :show="adaptiveBtLoading">
        <template v-if="adaptiveBtResult?.adaptive">
          <!-- Comparison Metrics -->
          <NGrid :cols="3" :x-gap="12" :y-gap="8" style="margin-bottom: 12px">
            <NGi>
              <NStatistic label="Alpha (自適應 - V4)">
                <template #default>
                  <span :style="{ color: (adaptiveBtResult.comparison?.alpha || 0) >= 0 ? '#18a058' : '#e53e3e', fontSize: '18px' }">
                    {{ ((adaptiveBtResult.comparison?.alpha || 0) * 100).toFixed(2) }}%
                  </span>
                </template>
              </NStatistic>
            </NGi>
            <NGi>
              <NStatistic label="Sharpe Delta">
                <template #default>
                  <span :style="{ color: (adaptiveBtResult.comparison?.sharpe_delta || 0) >= 0 ? '#18a058' : '#e53e3e' }">
                    {{ (adaptiveBtResult.comparison?.sharpe_delta || 0) > 0 ? '+' : '' }}{{ (adaptiveBtResult.comparison?.sharpe_delta || 0).toFixed(3) }}
                  </span>
                </template>
              </NStatistic>
            </NGi>
            <NGi>
              <NStatistic label="Drawdown Delta">
                <template #default>
                  <span :style="{ color: (adaptiveBtResult.comparison?.drawdown_delta || 0) >= 0 ? '#18a058' : '#e53e3e' }">
                    {{ ((adaptiveBtResult.comparison?.drawdown_delta || 0) * 100).toFixed(2) }}%
                  </span>
                </template>
              </NStatistic>
            </NGi>
          </NGrid>

          <!-- Side-by-side metrics -->
          <NGrid :cols="2" :x-gap="12">
            <NGi>
              <NCard size="small" title="自適應策略" :bordered="true">
                <NGrid :cols="2" :x-gap="8" :y-gap="4">
                  <NGi><NStatistic label="總報酬" :value="`${((adaptiveBtResult.adaptive?.total_return || 0) * 100).toFixed(2)}%`" /></NGi>
                  <NGi><NStatistic label="年化" :value="`${((adaptiveBtResult.adaptive?.annual_return || 0) * 100).toFixed(2)}%`" /></NGi>
                  <NGi><NStatistic label="最大回撤" :value="`${((adaptiveBtResult.adaptive?.max_drawdown || 0) * 100).toFixed(2)}%`" /></NGi>
                  <NGi><NStatistic label="Sharpe" :value="(adaptiveBtResult.adaptive?.sharpe_ratio || 0).toFixed(2)" /></NGi>
                  <NGi><NStatistic label="勝率" :value="`${((adaptiveBtResult.adaptive?.win_rate || 0) * 100).toFixed(1)}%`" /></NGi>
                  <NGi><NStatistic label="交易數" :value="adaptiveBtResult.adaptive?.total_trades || 0" /></NGi>
                </NGrid>
              </NCard>
            </NGi>
            <NGi>
              <NCard size="small" title="V4 標準 (Baseline)" :bordered="true">
                <NGrid :cols="2" :x-gap="8" :y-gap="4">
                  <NGi><NStatistic label="總報酬" :value="`${((adaptiveBtResult.baseline?.total_return || 0) * 100).toFixed(2)}%`" /></NGi>
                  <NGi><NStatistic label="年化" :value="`${((adaptiveBtResult.baseline?.annual_return || 0) * 100).toFixed(2)}%`" /></NGi>
                  <NGi><NStatistic label="最大回撤" :value="`${((adaptiveBtResult.baseline?.max_drawdown || 0) * 100).toFixed(2)}%`" /></NGi>
                  <NGi><NStatistic label="Sharpe" :value="(adaptiveBtResult.baseline?.sharpe_ratio || 0).toFixed(2)" /></NGi>
                  <NGi><NStatistic label="勝率" :value="`${((adaptiveBtResult.baseline?.win_rate || 0) * 100).toFixed(1)}%`" /></NGi>
                  <NGi><NStatistic label="交易數" :value="adaptiveBtResult.baseline?.total_trades || 0" /></NGi>
                </NGrid>
              </NCard>
            </NGi>
          </NGrid>

          <!-- Equity Curve Comparison -->
          <NDivider style="margin: 12px 0">資金曲線對比</NDivider>
          <VChart :option="adaptiveEquityChartOption" style="height: 250px" autoresize />

          <!-- Regime Performance Breakdown -->
          <template v-if="adaptiveBtResult.regime_performance?.length">
            <NDivider style="margin: 12px 0">各情境表現分解</NDivider>
            <NDataTable
              :columns="adaptiveRegimeColumns"
              :data="adaptiveBtResult.regime_performance"
              size="small"
              :bordered="false"
              :pagination="false"
            />
          </template>

          <!-- Regime Log Summary -->
          <template v-if="adaptiveBtResult.regime_log?.length">
            <NDivider style="margin: 12px 0">情境切換日誌 (最近 {{ adaptiveBtResult.regime_log.length }} 次)</NDivider>
            <div style="max-height: 150px; overflow-y: auto; font-size: 12px; color: #666">
              <div v-for="(rt, idx) in adaptiveBtResult.regime_log" :key="idx" style="padding: 2px 0">
                <NTag size="tiny" style="margin-right: 4px">{{ rt.date?.substring(0, 10) || '' }}</NTag>
                {{ rt.label || rt.regime }}
                <span style="margin-left: 8px; color: #999">信心 {{ ((rt.confidence || 0) * 100).toFixed(0) }}% / Kelly {{ (rt.kelly || 0).toFixed(2) }}</span>
              </div>
            </div>
          </template>
        </template>
        <div v-else-if="!adaptiveBtLoading" style="padding: 20px; text-align: center; color: #999">
          無回測結果
        </div>
      </NSpin>
    </NModal>

    <!-- Backtest Result Modal (R51-3 Enhanced) -->
    <NModal v-model:show="showBacktest" preset="card" style="width: 800px"
            :title="`回測結果 — ${selectedStrategy?.name || ''} × ${app.currentStockCode || ''}`">
      <NSpin :show="btLoading">
        <template v-if="btResult?.result">
          <!-- Key Metrics -->
          <NGrid :cols="4" :x-gap="12" :y-gap="8">
            <NGi>
              <NStatistic label="總報酬">
                <template #default>
                  <span :style="{ color: (btResult.result.total_return || 0) >= 0 ? '#18a058' : '#e53e3e' }">
                    {{ ((btResult.result.total_return || 0) * 100).toFixed(2) }}%
                  </span>
                </template>
              </NStatistic>
            </NGi>
            <NGi>
              <NStatistic label="年化報酬" :value="`${((btResult.result.annual_return || 0) * 100).toFixed(2)}%`" />
            </NGi>
            <NGi>
              <NStatistic label="最大回撤">
                <template #default>
                  <span style="color: #e53e3e">{{ ((btResult.result.max_drawdown || 0) * 100).toFixed(2) }}%</span>
                </template>
              </NStatistic>
            </NGi>
            <NGi>
              <NStatistic label="Sharpe" :value="(btResult.result.sharpe_ratio || 0).toFixed(2)" />
            </NGi>
            <NGi>
              <NStatistic label="交易次數" :value="btResult.result.total_trades || 0" />
            </NGi>
            <NGi>
              <NStatistic label="勝率" :value="`${((btResult.result.win_rate || 0) * 100).toFixed(1)}%`" />
            </NGi>
            <NGi>
              <NStatistic label="獲利因子" :value="(btResult.result.profit_factor || 0).toFixed(2)" />
            </NGi>
            <NGi>
              <NStatistic label="連續虧損" :value="btResult.result.max_consecutive_losses || 0" />
            </NGi>
          </NGrid>

          <!-- Monthly Returns Bar Chart (R51-3) -->
          <template v-if="btResult.monthly_returns?.length">
            <NDivider style="margin: 12px 0">月度損益分佈</NDivider>
            <VChart :option="monthlyChartOption" style="height: 180px" autoresize />
          </template>

          <!-- Regime Breakdown (R51-3) -->
          <template v-if="btResult.regime_breakdown?.length">
            <NDivider style="margin: 12px 0">市場情境表現分解</NDivider>
            <NDataTable
              :columns="regimeColumns"
              :data="btResult.regime_breakdown"
              size="small"
              :bordered="false"
              :pagination="false"
            />
          </template>
        </template>
        <div v-else-if="!btLoading" style="padding: 20px; text-align: center; color: #999">
          無回測結果
        </div>
      </NSpin>
    </NModal>

    <!-- Batch Validation Modal (R54) -->
    <NModal v-model:show="showBatchModal" preset="card" style="width: 1000px"
            title="自適應策略批次驗證報告">
      <NSpin :show="batchLoading">
        <template v-if="batchResult?.aggregate">
          <!-- Aggregate Summary -->
          <NGrid :cols="5" :x-gap="12" :y-gap="8" style="margin-bottom: 16px">
            <NGi>
              <NStatistic label="測試標的" :value="batchResult.aggregate.stocks_tested" />
            </NGi>
            <NGi>
              <NStatistic label="自適應勝出">
                <template #default>
                  <span :style="{ color: batchResult.aggregate.adaptive_win_rate >= 0.5 ? '#18a058' : '#e53e3e' }">
                    {{ batchResult.aggregate.adaptive_wins }}/{{ batchResult.aggregate.stocks_tested }}
                    ({{ (batchResult.aggregate.adaptive_win_rate * 100).toFixed(0) }}%)
                  </span>
                </template>
              </NStatistic>
            </NGi>
            <NGi>
              <NStatistic label="平均 Alpha">
                <template #default>
                  <span :style="{ color: batchResult.aggregate.avg_alpha >= 0 ? '#18a058' : '#e53e3e', fontSize: '18px', fontWeight: '600' }">
                    {{ batchResult.aggregate.avg_alpha > 0 ? '+' : '' }}{{ (batchResult.aggregate.avg_alpha * 100).toFixed(2) }}%
                  </span>
                </template>
              </NStatistic>
            </NGi>
            <NGi>
              <NStatistic label="平均 Sharpe Δ">
                <template #default>
                  <span :style="{ color: batchResult.aggregate.avg_sharpe_delta >= 0 ? '#18a058' : '#e53e3e' }">
                    {{ batchResult.aggregate.avg_sharpe_delta > 0 ? '+' : '' }}{{ batchResult.aggregate.avg_sharpe_delta.toFixed(3) }}
                  </span>
                </template>
              </NStatistic>
            </NGi>
            <NGi>
              <NStatistic label="平均 Drawdown Δ">
                <template #default>
                  {{ (batchResult.aggregate.avg_drawdown_delta * 100).toFixed(2) }}%
                </template>
              </NStatistic>
            </NGi>
          </NGrid>

          <NAlert v-if="batchResult.aggregate.best_alpha" type="info" style="margin-bottom: 8px">
            最佳: {{ batchResult.aggregate.best_alpha.code }} (Alpha +{{ (batchResult.aggregate.best_alpha.alpha * 100).toFixed(2) }}%)
            &nbsp;|&nbsp;
            最差: {{ batchResult.aggregate.worst_alpha.code }} (Alpha {{ (batchResult.aggregate.worst_alpha.alpha * 100).toFixed(2) }}%)
          </NAlert>

          <!-- Per-stock results table -->
          <NDataTable
            :columns="batchColumns"
            :data="batchResult.results"
            size="small"
            :bordered="false"
            :single-line="false"
          />

          <!-- Errors -->
          <NAlert v-for="(err, idx) in (batchResult.errors || [])" :key="idx"
                  type="warning" style="margin-top: 8px">
            {{ err.code }}: {{ err.error }}
          </NAlert>
        </template>
        <div v-else-if="!batchLoading" style="padding: 20px; text-align: center; color: #999">
          無批次驗證結果
        </div>
      </NSpin>
    </NModal>
  </div>
</template>
