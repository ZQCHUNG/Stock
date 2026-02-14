<script setup lang="ts">
import { h, ref, onMounted, computed } from 'vue'
import {
  NCard, NButton, NSpace, NGrid, NGi, NTag, NInput, NInputNumber,
  NDataTable, NSpin, NDivider, NStatistic, NAlert, NModal, NForm,
  NFormItem, NSelect, useMessage,
} from 'naive-ui'
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

onMounted(async () => {
  await Promise.all([loadStrategies(), loadRegime()])
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

    <!-- Backtest Result Modal -->
    <NModal v-model:show="showBacktest" preset="card" style="width: 700px"
            :title="`回測結果 — ${selectedStrategy?.name || ''} × ${app.currentStockCode || ''}`">
      <NSpin :show="btLoading">
        <template v-if="btResult?.result">
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
              <NStatistic label="最終資產" :value="`$${(btResult.result.final_capital || 0).toLocaleString()}`" />
            </NGi>
          </NGrid>
        </template>
        <div v-else-if="!btLoading" style="padding: 20px; text-align: center; color: #999">
          無回測結果
        </div>
      </NSpin>
    </NModal>
  </div>
</template>
