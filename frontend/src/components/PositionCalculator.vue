<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { NCard, NGrid, NGi, NInputNumber, NSlider, NSelect, NAlert, NTag, NSpin } from 'naive-ui'
import { analysisApi } from '../api/analysis'
import MetricCard from './MetricCard.vue'
import { fmtNum } from '../utils/format'

const props = defineProps<{ code: string; currentPrice: number }>()

const capital = ref(1_000_000)
const riskPct = ref(2)
const confidence = ref(1.0)

const riskFactors = ref<any>(null)
const rfLoading = ref(false)
const rfError = ref('')

const confidenceOptions = [
  { label: '1.0 — 純技術', value: 1.0 },
  { label: '1.5 — 法人買入', value: 1.5 },
  { label: '1.7 — 投信連買', value: 1.7 },
  { label: '2.0 — 全法人連3買', value: 2.0 },
]

async function loadRiskFactors() {
  if (!props.code) return
  rfLoading.value = true
  rfError.value = ''
  try {
    riskFactors.value = await analysisApi.riskFactors(props.code)
  } catch (e: any) {
    rfError.value = e.message || '載入風險因子失敗'
    riskFactors.value = null
  }
  rfLoading.value = false
}

watch(() => props.code, loadRiskFactors, { immediate: true })

const liquidityFactor = computed(() => riskFactors.value?.liquidity_factor ?? 1)
const warnings = computed(() => riskFactors.value?.warnings ?? [])
const isGhostTown = computed(() => riskFactors.value?.institutional?.visibility === 'ghost_town')

const stopLossPct = 0.07
const slPrice = computed(() => props.currentPrice * (1 - stopLossPct))
const lossPerShare = computed(() => props.currentPrice - slPrice.value)

const effectiveRisk = computed(() =>
  capital.value * (riskPct.value / 100) * confidence.value * liquidityFactor.value
)
const shares = computed(() =>
  lossPerShare.value > 0 ? Math.floor(effectiveRisk.value / lossPerShare.value) : 0
)
const lots = computed(() => Math.floor(shares.value / 1000))
const cost = computed(() => lots.value * 1000 * props.currentPrice)
const maxLoss = computed(() => lots.value * 1000 * lossPerShare.value)
const costPct = computed(() => capital.value > 0 ? cost.value / capital.value * 100 : 0)
</script>

<template>
  <NCard title="下單計算機" size="small" style="margin-bottom: 16px" :segmented="{ content: true }">
    <NSpin :show="rfLoading" size="small">
      <!-- Risk warnings -->
      <NAlert v-if="isGhostTown" type="error" style="margin-bottom: 12px">
        零法人交易（Ghost Town）— 流動性極差，建議不持有此股票
      </NAlert>
      <NAlert v-else-if="warnings.length" type="warning" style="margin-bottom: 12px">
        <div v-for="(w, i) in warnings" :key="i">{{ w }}</div>
      </NAlert>

      <!-- Inputs -->
      <NGrid :cols="3" :x-gap="12" :y-gap="8" style="margin-bottom: 12px">
        <NGi>
          <div style="font-size: 12px; color: var(--n-text-color-3); margin-bottom: 4px">總資金 (TWD)</div>
          <NInputNumber v-model:value="capital" :min="100000" :max="100000000" :step="100000" size="small" />
        </NGi>
        <NGi>
          <div style="font-size: 12px; color: var(--n-text-color-3); margin-bottom: 4px">單筆風險 (%)</div>
          <NSlider v-model:value="riskPct" :min="1" :max="10" :step="0.5" :tooltip="true" />
        </NGi>
        <NGi>
          <div style="font-size: 12px; color: var(--n-text-color-3); margin-bottom: 4px">信心分數</div>
          <NSelect v-model:value="confidence" :options="confidenceOptions" size="small" />
        </NGi>
      </NGrid>

      <!-- Liquidity Factor display -->
      <div v-if="riskFactors" style="margin-bottom: 12px; font-size: 12px">
        <span style="color: var(--n-text-color-3)">流動性因子：</span>
        <NTag :type="liquidityFactor >= 0.8 ? 'success' : liquidityFactor >= 0.3 ? 'warning' : 'error'" size="small">
          {{ liquidityFactor.toFixed(2) }}
        </NTag>
        <NTag v-if="riskFactors.is_biotech" type="info" size="small" style="margin-left: 4px">生技股</NTag>
        <NTag v-if="riskFactors.cash_runway?.runway_label === '極高風險'" type="error" size="small" style="margin-left: 4px">
          現金跑道 {{ Math.min(riskFactors.cash_runway.runway_quarters, riskFactors.cash_runway.total_runway_quarters).toFixed(1) }}季
        </NTag>
      </div>

      <!-- Results -->
      <NGrid :cols="4" :x-gap="8" :y-gap="8">
        <NGi>
          <MetricCard
            title="建議張數"
            :value="isGhostTown ? '不建議' : lots > 0 ? `${lots} 張` : '不建議'"
            :color="isGhostTown || lots === 0 ? '#e53e3e' : undefined"
          />
        </NGi>
        <NGi>
          <MetricCard title="買入成本" :value="`$${fmtNum(cost, 0)}`" />
        </NGi>
        <NGi>
          <MetricCard title="停損價" :value="`$${slPrice.toFixed(2)}`" />
        </NGi>
        <NGi>
          <MetricCard title="最大虧損" :value="`$${fmtNum(maxLoss, 0)}`" color="#e53e3e" />
        </NGi>
      </NGrid>

      <!-- Status line -->
      <div v-if="lots > 0 && !isGhostTown" style="margin-top: 8px; font-size: 12px; color: var(--n-text-color-3)">
        佔總資金 {{ costPct.toFixed(1) }}% |
        停損 -{{ (stopLossPct * 100).toFixed(0) }}% = ${{ slPrice.toFixed(2) }} |
        最大虧損佔總資金 {{ (capital > 0 ? maxLoss / capital * 100 : 0).toFixed(1) }}%
      </div>
      <div v-if="cost > capital" style="margin-top: 4px; font-size: 12px; color: #e53e3e; font-weight: 600">
        買入成本超過總資金，無法執行
      </div>
    </NSpin>
  </NCard>
</template>
