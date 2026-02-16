<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { NGrid, NGi, NTag, NSpace, NTooltip, NSpin, NInputNumber, NSlider, NCollapse, NCollapseItem, NCheckbox } from 'naive-ui'
import { analysisApi } from '../api/analysis'
import MetricCard from './MetricCard.vue'
import { fmtNum } from '../utils/format'

const props = defineProps<{ code: string; currentPrice: number }>()

const capital = ref(1_000_000)
const riskPct = ref(3.0)
const oddLot = ref(false)
const data = ref<any>(null)
const loading = ref(false)

async function load() {
  if (!props.code) return
  loading.value = true
  try {
    data.value = await analysisApi.sizingAdvisor(props.code, capital.value, riskPct.value, oddLot.value)
  } catch {
    data.value = null
  }
  loading.value = false
}

watch(() => props.code, load, { immediate: true })
watch([capital, riskPct, oddLot], load)

const lightColor = computed(() => {
  if (!data.value) return '#999'
  if (data.value.light === 'green') return '#18a058'
  if (data.value.light === 'yellow') return '#f0a020'
  return '#e53e3e'
})

const modeLabel = computed(() => {
  if (!data.value) return ''
  return data.value.mode === 'Trender' ? 'Precision Trender' : 'Momentum Scalper'
})

const modeType = computed(() => {
  if (!data.value) return 'default' as const
  return data.value.mode === 'Trender' ? 'info' as const : 'warning' as const
})

const cashRemaining = computed(() => {
  if (!data.value) return 0
  return data.value.capital - data.value.cost
})

const cashRemainingPct = computed(() => {
  if (!data.value || data.value.capital <= 0) return 0
  return cashRemaining.value / data.value.capital * 100
})

const lotUnit = computed(() => oddLot.value ? '股' : '張')
const hasSectorPenalty = computed(() => data.value?.sector_penalty_applied === true)
const hasSizingDiff = computed(() => data.value && data.value.base_lots !== data.value.suggested_lots)
</script>

<template>
  <NCollapse style="margin-bottom: 16px" :default-expanded-names="['sizing']">
    <NCollapseItem name="sizing">
      <template #header>
        <span style="font-weight: 600">風險倉位顧問</span>
      </template>
      <template #header-extra>
        <NSpace :size="6" align="center" @click.stop>
          <NTag v-if="data" :color="{ textColor: '#fff', color: lightColor, borderColor: lightColor }" size="small" round style="font-weight: 700">
            {{ data.light_label }}
          </NTag>
          <NTag v-if="data && data.suggested_lots > 0" size="small" :bordered="false">
            {{ data.suggested_lots }} {{ lotUnit }}
          </NTag>
          <NTag v-if="hasSectorPenalty" size="small" type="warning" :bordered="false">
            板塊重疊
          </NTag>
        </NSpace>
      </template>

      <NSpin :show="loading" size="small">
        <!-- Inputs -->
        <NGrid :cols="3" :x-gap="12" :y-gap="8" style="margin-bottom: 12px">
          <NGi>
            <div style="font-size: 12px; color: var(--n-text-color-3); margin-bottom: 4px">總資金 (TWD)</div>
            <NInputNumber v-model:value="capital" :min="100000" :max="100000000" :step="100000" size="small" />
          </NGi>
          <NGi>
            <div style="font-size: 12px; color: var(--n-text-color-3); margin-bottom: 4px">
              最大單筆風險 {{ riskPct.toFixed(1) }}%
            </div>
            <NSlider v-model:value="riskPct" :min="0.5" :max="10" :step="0.5" />
          </NGi>
          <NGi>
            <div style="font-size: 12px; color: var(--n-text-color-3); margin-bottom: 4px">&nbsp;</div>
            <NTooltip trigger="hover">
              <template #trigger>
                <NCheckbox v-model:checked="oddLot" size="small">零股模式</NCheckbox>
              </template>
              <div style="max-width: 250px">
                以 1 股為單位計算倉位，適用高價股（如台積電）。注意：零股交易流動性較差，可能有較大滑價。
              </div>
            </NTooltip>
          </NGi>
        </NGrid>

        <template v-if="data">
          <!-- Mode + ATR% + Sector context -->
          <div style="margin-bottom: 10px">
            <NSpace :size="6" align="center">
              <NTag :type="modeType" size="small" round>
                {{ data.mode === 'Trender' ? '🎯' : '⚡' }} {{ modeLabel }}
              </NTag>
              <NTag size="small" :bordered="false">ATR% {{ data.atr_pct }}%</NTag>
              <NTag v-if="data.regime_multiplier < 1" size="small" type="warning" :bordered="false">
                Regime x{{ data.regime_multiplier }}
              </NTag>
              <NTag v-if="data.sector && data.sector !== '未分類'" size="small" :bordered="false">
                {{ data.sector }}
              </NTag>
              <NTag v-if="hasSectorPenalty" size="small" type="warning">
                板塊 x{{ data.sector_multiplier }}
              </NTag>
              <NTag v-if="data.odd_lot" size="small" type="info">零股</NTag>
            </NSpace>
          </div>

          <!-- Results: 5 metric cards -->
          <NGrid :cols="5" :x-gap="8" :y-gap="8" style="margin-bottom: 8px">
            <NGi>
              <MetricCard
                title="建議張數"
                :value="data.suggested_lots > 0 ? `${data.suggested_lots} ${lotUnit}` : '無法買入'"
                :color="data.light === 'red' ? '#e53e3e' : data.light === 'yellow' ? '#f0a020' : undefined"
              />
            </NGi>
            <NGi>
              <MetricCard
                title="倉位比重"
                :value="`${data.position_pct}%`"
              />
            </NGi>
            <NGi>
              <MetricCard
                title="風險暴露"
                :value="`${data.risk_per_trade_pct}%`"
                :color="data.over_risk ? '#f0a020' : undefined"
              />
            </NGi>
            <NGi>
              <MetricCard
                title="買入成本"
                :value="`$${fmtNum(data.cost, 0)}`"
              />
            </NGi>
            <NGi>
              <MetricCard
                title="剩餘資金"
                :value="data.suggested_lots > 0 ? `$${fmtNum(cashRemaining, 0)}` : '-'"
                :color="cashRemainingPct < 20 ? '#f0a020' : undefined"
              />
            </NGi>
          </NGrid>

          <!-- R82: Sector Penalty Comparison -->
          <div v-if="hasSizingDiff" style="margin-bottom: 8px; padding: 6px 10px; background: var(--n-color-embedded); border-radius: 6px; font-size: 12px">
            <NSpace :size="12" align="center">
              <span style="color: var(--n-text-color-3)">倉位比較:</span>
              <span>標準 {{ data.base_lots }} {{ lotUnit }} (${{ fmtNum(data.base_cost, 0) }})</span>
              <span style="color: var(--n-text-color-3)">→</span>
              <span :style="{ fontWeight: 600, color: hasSectorPenalty ? '#f0a020' : undefined }">
                調整後 {{ data.suggested_lots }} {{ lotUnit }} (${{ fmtNum(data.cost, 0) }})
              </span>
              <NTag v-if="hasSectorPenalty" size="small" type="warning">
                {{ data.sector_reason }}
              </NTag>
            </NSpace>
          </div>

          <!-- Status line -->
          <div style="font-size: 12px; color: var(--n-text-color-3)">
            <NSpace :size="8" :wrap="true" align="center">
              <span>Equal Risk: {{ data.max_risk_pct }}% / 7% SL = {{ data.position_pct }}% 倉位</span>
              <span v-if="data.suggested_lots > 0">
                | 剩餘 {{ cashRemainingPct.toFixed(0) }}% (Dry Powder)
              </span>
              <span v-if="data.over_risk" style="color: #f0a020; font-weight: 600">
                | 1-Lot Floor: 超出風險預算
              </span>
              <span v-if="data.capital_barrier" style="color: #e53e3e; font-weight: 600">
                | 資本門檻: 1{{ lotUnit }} = ${{ fmtNum(data.one_lot_cost, 0) }} > 總資金
              </span>
              <span v-if="data.odd_lot" style="color: #2080f0">
                | 零股模式 (流動性較差)
              </span>
            </NSpace>
          </div>

          <!-- Reasoning tooltip -->
          <NTooltip trigger="hover" placement="bottom" style="max-width: 500px">
            <template #trigger>
              <span style="font-size: 11px; color: #999; cursor: help; text-decoration: underline dotted">
                計算邏輯
              </span>
            </template>
            <div style="font-size: 12px; white-space: pre-wrap">{{ data.reasoning }}{{ hasSectorPenalty ? '\n\n' + data.sector_reason : '' }}</div>
          </NTooltip>
        </template>
      </NSpin>
    </NCollapseItem>
  </NCollapse>
</template>
