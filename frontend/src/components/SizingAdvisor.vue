<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { NCard, NGrid, NGi, NTag, NSpace, NTooltip, NSpin, NInputNumber, NSlider, NCollapse, NCollapseItem } from 'naive-ui'
import { analysisApi } from '../api/analysis'
import MetricCard from './MetricCard.vue'
import { fmtNum } from '../utils/format'

const props = defineProps<{ code: string; currentPrice: number }>()

const capital = ref(1_000_000)
const riskPct = ref(3.0)
const data = ref<any>(null)
const loading = ref(false)

async function load() {
  if (!props.code) return
  loading.value = true
  try {
    data.value = await analysisApi.sizingAdvisor(props.code, capital.value, riskPct.value)
  } catch {
    data.value = null
  }
  loading.value = false
}

watch(() => props.code, load, { immediate: true })
watch([capital, riskPct], load)

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
            {{ data.suggested_lots }} 張
          </NTag>
        </NSpace>
      </template>

      <NSpin :show="loading" size="small">
        <!-- Inputs -->
        <NGrid :cols="2" :x-gap="12" :y-gap="8" style="margin-bottom: 12px">
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
        </NGrid>

        <template v-if="data">
          <!-- Mode + ATR% context -->
          <div style="margin-bottom: 10px">
            <NSpace :size="6" align="center">
              <NTag :type="modeType" size="small" round>
                {{ data.mode === 'Trender' ? '🎯' : '⚡' }} {{ modeLabel }}
              </NTag>
              <NTag size="small" :bordered="false">ATR% {{ data.atr_pct }}%</NTag>
              <NTag v-if="data.regime_multiplier < 1" size="small" type="warning" :bordered="false">
                Regime x{{ data.regime_multiplier }}
              </NTag>
            </NSpace>
          </div>

          <!-- Results: 5 metric cards -->
          <NGrid :cols="5" :x-gap="8" :y-gap="8" style="margin-bottom: 8px">
            <NGi>
              <MetricCard
                title="建議張數"
                :value="data.suggested_lots > 0 ? `${data.suggested_lots} 張` : '無法買入'"
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

          <!-- Status line -->
          <div style="font-size: 12px; color: var(--n-text-color-3)">
            <NSpace :size="8" :wrap="true" align="center">
              <span>Equal Risk: {{ data.max_risk_pct }}% / 7% SL = {{ data.position_pct }}% 倉位</span>
              <span v-if="data.suggested_lots > 0">
                | 剩餘 {{ cashRemainingPct.toFixed(0) }}% (Dry Powder)
              </span>
              <span v-if="data.over_risk" style="color: #f0a020; font-weight: 600">
                | 1-Lot Floor: 最低1張超出風險預算
              </span>
              <span v-if="data.capital_barrier" style="color: #e53e3e; font-weight: 600">
                | 資本門檻: 1張 = ${{ fmtNum(data.one_lot_cost, 0) }} > 總資金
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
            <div style="font-size: 12px; white-space: pre-wrap">{{ data.reasoning }}</div>
          </NTooltip>
        </template>
      </NSpin>
    </NCollapseItem>
  </NCollapse>
</template>
