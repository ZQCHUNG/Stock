<script setup lang="ts">
import { h, ref, onMounted, computed } from 'vue'
import {
  NCard, NButton, NSpace, NGrid, NGi, NTag, NInput, NInputNumber,
  NDataTable, NSpin, NDivider, NStatistic, NAlert, NModal, NForm,
  NFormItem, NSelect, useMessage,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import VChart from 'vue-echarts'
import { strategiesApi, type Strategy, type StrategyParams } from '../api/strategies'
import { analysisApi } from '../api/analysis'
import { useAppStore } from '../stores/app'

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

onMounted(async () => {
  await Promise.all([loadStrategies(), loadRegime(), loadAdaptive()])
})
</script>

<template>
  <div>
    <h2 style="margin: 0 0 16px">策略工作台</h2>

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
      </NForm>
      <template #action>
        <NSpace>
          <NButton @click="showCreate = false">取消</NButton>
          <NButton type="primary" @click="createStrategy" :disabled="!createForm.name">建立</NButton>
        </NSpace>
      </template>
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
  </div>
</template>
