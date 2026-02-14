<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { NCard, NGrid, NGi, NInputNumber, NInput, NSlider, NAlert, NTag, NSpin, NSpace, NTooltip, NButton } from 'naive-ui'
import { analysisApi } from '../api/analysis'
import { usePortfolioStore } from '../stores/portfolio'
import { useAppStore } from '../stores/app'
import MetricCard from './MetricCard.vue'
import { fmtNum } from '../utils/format'

const props = defineProps<{ code: string; currentPrice: number }>()
const emit = defineEmits<{
  (e: 'risk-loaded', data: { trailingStop: number | null; stopLoss: number }): void
}>()

// User inputs
const capital = ref(1_000_000)
const riskPct = ref(2)
const stopLossPrice = ref(0)
const useCustomStopLoss = ref(false)

// API data
const riskFactors = ref<any>(null)
const rfLoading = ref(false)
const rfError = ref('')

async function loadRiskFactors() {
  if (!props.code) return
  rfLoading.value = true
  rfError.value = ''
  try {
    riskFactors.value = await analysisApi.riskFactors(props.code)
    // Set default stop loss from V4 signal
    if (!useCustomStopLoss.value && riskFactors.value?.stop_loss_price) {
      stopLossPrice.value = riskFactors.value.stop_loss_price
    }
    // Emit risk data for chart overlay
    emit('risk-loaded', {
      trailingStop: riskFactors.value?.trailing_stop_price ?? null,
      stopLoss: riskFactors.value?.stop_loss_price ?? props.currentPrice * 0.93,
    })
  } catch (e: any) {
    rfError.value = e.message || '載入風險因子失敗'
    riskFactors.value = null
  }
  rfLoading.value = false
}

watch(() => props.code, () => { useCustomStopLoss.value = false; loadRiskFactors() }, { immediate: true })

// Derived values
const liquidityFactor = computed(() => riskFactors.value?.liquidity_factor ?? 1)
const warnings = computed(() => riskFactors.value?.warnings ?? [])
const isGhostTown = computed(() => liquidityFactor.value === 0)
const confidenceMultiplier = computed(() => riskFactors.value?.confidence_multiplier ?? 0.7)
const confidenceBreakdown = computed(() => riskFactors.value?.confidence_breakdown ?? [])
const signalMaturity = computed(() => riskFactors.value?.signal_maturity ?? 'N/A')
const sectorMomentum = computed(() => riskFactors.value?.sector_momentum ?? 'stable')
const isLeader = computed(() => riskFactors.value?.is_leader ?? false)
const v4Signal = computed(() => riskFactors.value?.v4_signal ?? 'HOLD')
const sectorL1 = computed(() => riskFactors.value?.sector_l1 ?? '')

// Dynamic exit (Gemini R24)
const atr14 = computed(() => riskFactors.value?.atr_14 ?? null)
const highestClose20d = computed(() => riskFactors.value?.highest_close_20d ?? null)
const trailingStopPrice = computed(() => riskFactors.value?.trailing_stop_price ?? null)
const hasTrailingStop = computed(() => trailingStopPrice.value !== null && trailingStopPrice.value > effectiveStopLoss.value)
const trailingStopPct = computed(() => {
  if (!trailingStopPrice.value || props.currentPrice <= 0) return 0
  return (1 - trailingStopPrice.value / props.currentPrice) * 100
})

// Default stop loss from V4
const defaultStopLoss = computed(() => riskFactors.value?.stop_loss_price ?? props.currentPrice * 0.93)

// Effective stop loss (user override or V4 default)
const effectiveStopLoss = computed(() => useCustomStopLoss.value ? stopLossPrice.value : defaultStopLoss.value)
const stopLossPct = computed(() => props.currentPrice > 0 ? (1 - effectiveStopLoss.value / props.currentPrice) * 100 : 7)

// Position sizing: N = floor((Equity × Risk% × C) / ((Entry - StopLoss) × 1000))
const lossPerShare = computed(() => props.currentPrice - effectiveStopLoss.value)

const riskAmount = computed(() =>
  capital.value * (riskPct.value / 100) * confidenceMultiplier.value
)
const lots = computed(() => {
  if (isGhostTown.value || lossPerShare.value <= 0) return 0
  const shares = Math.floor(riskAmount.value / lossPerShare.value)
  return Math.floor(shares / 1000)
})
const cost = computed(() => lots.value * 1000 * props.currentPrice)
const maxLoss = computed(() => lots.value * 1000 * lossPerShare.value)
const costPct = computed(() => capital.value > 0 ? cost.value / capital.value * 100 : 0)

// Confidence visual helpers
const confidenceColor = computed(() => {
  const c = confidenceMultiplier.value
  if (c >= 1.2) return '#18a058'
  if (c >= 0.8) return '#2080f0'
  if (c >= 0.5) return '#f0a020'
  return '#e53e3e'
})

const confidenceLabel = computed(() => {
  const c = confidenceMultiplier.value
  if (c >= 1.2) return '高信心'
  if (c >= 0.8) return '中信心'
  if (c >= 0.5) return '低信心'
  if (c > 0) return '極低'
  return '不建議'
})

const maturityTagType = computed(() => {
  const m = signalMaturity.value
  if (m === 'Structural Shift') return 'success' as const
  if (m === 'Trend Formation') return 'warning' as const
  return 'error' as const
})

const momentumIcon = computed(() => {
  const m = sectorMomentum.value
  if (m === 'surge') return '🔥'
  if (m === 'heating') return '↑'
  if (m === 'cooling') return '↓'
  return ''
})

// Simulated buy (Gemini R25→R28: with journal note)
const pfStore = usePortfolioStore()
const isBuying = ref(false)
const buyNote = ref('')

async function simulateBuy() {
  if (lots.value <= 0) return
  isBuying.value = true
  try {
    await pfStore.openPosition({
      code: props.code,
      name: useAppStore().currentStockName || props.code,
      entry_price: props.currentPrice,
      lots: lots.value,
      stop_loss: effectiveStopLoss.value,
      trailing_stop: trailingStopPrice.value,
      confidence: confidenceMultiplier.value,
      sector: sectorL1.value,
      note: buyNote.value,
    })
    buyNote.value = ''
  } catch { /* handled by store */ }
  isBuying.value = false
}

function onStopLossChange(val: number | null) {
  if (val !== null) {
    stopLossPrice.value = val
    useCustomStopLoss.value = true
  }
}

function resetStopLoss() {
  useCustomStopLoss.value = false
  stopLossPrice.value = defaultStopLoss.value
}
</script>

<template>
  <NCard title="部位計算機" size="small" style="margin-bottom: 16px" :segmented="{ content: true }">
    <NSpin :show="rfLoading" size="small">
      <!-- Ghost Town hard block -->
      <NAlert v-if="isGhostTown" type="error" style="margin-bottom: 12px">
        零法人交易（Ghost Town）— 流動性極差，建議不持有此股票
      </NAlert>
      <!-- Risk warnings -->
      <NAlert v-else-if="warnings.length" type="warning" style="margin-bottom: 12px">
        <div v-for="(w, i) in warnings" :key="i">{{ w }}</div>
      </NAlert>

      <!-- Context tags: Signal + Maturity + Sector + Momentum + Leader -->
      <div v-if="riskFactors" style="margin-bottom: 12px">
        <NSpace :size="6" style="flex-wrap: wrap">
          <NTag :type="v4Signal === 'BUY' ? 'error' : v4Signal === 'SELL' ? 'success' : 'default'" size="small">
            {{ v4Signal }}
          </NTag>
          <NTag v-if="signalMaturity !== 'N/A'" :type="maturityTagType" size="small">
            {{ signalMaturity }}
          </NTag>
          <NTag v-if="sectorL1" size="small" :bordered="false">
            {{ sectorL1 }}{{ momentumIcon ? ' ' + momentumIcon : '' }}
          </NTag>
          <NTag v-if="isLeader" type="warning" size="small" :bordered="false" style="font-weight: 700">
            ★ Leader
          </NTag>
        </NSpace>
      </div>

      <!-- Confidence Multiplier display -->
      <div v-if="riskFactors" style="margin-bottom: 12px">
        <NSpace align="center" :size="8">
          <span style="font-size: 12px; color: var(--n-text-color-3)">信心乘數:</span>
          <NTooltip trigger="hover">
            <template #trigger>
              <NTag :color="{ textColor: '#fff', color: confidenceColor, borderColor: confidenceColor }" size="small" style="font-weight: 700; cursor: help">
                {{ confidenceMultiplier.toFixed(2) }} ({{ confidenceLabel }})
              </NTag>
            </template>
            <div>
              <div style="font-weight: 600; margin-bottom: 4px">信心乘數計算</div>
              <div v-for="(line, i) in confidenceBreakdown" :key="i" style="font-size: 12px">{{ line }}</div>
            </div>
          </NTooltip>
          <span style="font-size: 12px; color: var(--n-text-color-3)">流動性:</span>
          <NTag :type="liquidityFactor >= 0.8 ? 'success' : liquidityFactor >= 0.3 ? 'warning' : 'error'" size="small">
            {{ liquidityFactor.toFixed(2) }}
          </NTag>
          <NTag v-if="riskFactors.is_biotech" type="info" size="small">生技股</NTag>
        </NSpace>
      </div>

      <!-- Inputs -->
      <NGrid :cols="3" :x-gap="12" :y-gap="8" style="margin-bottom: 12px">
        <NGi>
          <div style="font-size: 12px; color: var(--n-text-color-3); margin-bottom: 4px">總資金 (TWD)</div>
          <NInputNumber v-model:value="capital" :min="100000" :max="100000000" :step="100000" size="small" />
        </NGi>
        <NGi>
          <div style="font-size: 12px; color: var(--n-text-color-3); margin-bottom: 4px">
            單筆風險 {{ riskPct.toFixed(1) }}%
          </div>
          <NSlider v-model:value="riskPct" :min="0.5" :max="5" :step="0.5" :tooltip="true" />
        </NGi>
        <NGi>
          <div style="font-size: 12px; color: var(--n-text-color-3); margin-bottom: 4px">
            停損價
            <span v-if="useCustomStopLoss" style="color: #f0a020; cursor: pointer" @click="resetStopLoss">
              (自訂, 按此重設)
            </span>
            <span v-else style="color: #999">(V4: -{{ stopLossPct.toFixed(1) }}%)</span>
          </div>
          <NInputNumber
            :value="effectiveStopLoss"
            @update:value="onStopLossChange"
            :min="props.currentPrice * 0.7"
            :max="props.currentPrice * 0.99"
            :step="0.5"
            size="small"
          />
        </NGi>
      </NGrid>

      <!-- Results -->
      <NGrid :cols="5" :x-gap="8" :y-gap="8">
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
          <MetricCard title="靜態停損" :value="`$${effectiveStopLoss.toFixed(2)}`" />
        </NGi>
        <NGi>
          <NTooltip v-if="hasTrailingStop" trigger="hover">
            <template #trigger>
              <MetricCard
                title="移動停利"
                :value="`$${trailingStopPrice!.toFixed(2)}`"
                color="#2080f0"
              />
            </template>
            <div>
              <div style="font-weight: 600; margin-bottom: 4px">ATR 移動停利</div>
              <div>公式: max(靜態SL, 最高收盤 − 2×ATR)</div>
              <div>ATR(14): ${{ atr14?.toFixed(2) }}</div>
              <div>近20日最高收盤: ${{ highestClose20d?.toFixed(2) }}</div>
              <div>移動停利: ${{ trailingStopPrice!.toFixed(2) }} (−{{ trailingStopPct.toFixed(1) }}%)</div>
              <div style="font-size: 11px; color: #aaa; margin-top: 4px">持有中應以較高者為準</div>
            </div>
          </NTooltip>
          <MetricCard v-else title="移動停利" value="同靜態" />
        </NGi>
        <NGi>
          <MetricCard title="最大虧損" :value="`$${fmtNum(maxLoss, 0)}`" color="#e53e3e" />
        </NGi>
      </NGrid>

      <!-- Status line -->
      <div v-if="lots > 0 && !isGhostTown" style="margin-top: 8px; font-size: 12px; color: var(--n-text-color-3)">
        佔總資金 {{ costPct.toFixed(1) }}% |
        停損 -{{ stopLossPct.toFixed(1) }}% = ${{ effectiveStopLoss.toFixed(2) }}
        <template v-if="hasTrailingStop"> | 移動停利 ${{ trailingStopPrice!.toFixed(2) }} (ATR×2)</template> |
        風險金額 ${{ fmtNum(riskAmount, 0) }} (資金×{{ riskPct }}%×C{{ confidenceMultiplier.toFixed(2) }}) |
        最大虧損佔總資金 {{ (capital > 0 ? maxLoss / capital * 100 : 0).toFixed(2) }}%
      </div>
      <div v-if="cost > capital" style="margin-top: 4px; font-size: 12px; color: #e53e3e; font-weight: 600">
        買入成本超過總資金，無法執行
      </div>

      <!-- Simulated Buy Button + Journal (Gemini R25→R28) -->
      <div v-if="lots > 0 && !isGhostTown && v4Signal === 'BUY'" style="margin-top: 10px">
        <NInput
          v-model:value="buyNote"
          placeholder="買入理由（選填）：趨勢確認 / 突破支撐 / 板塊輪動..."
          size="small"
          style="margin-bottom: 6px; max-width: 400px"
        />
        <NButton
          type="error"
          size="small"
          :loading="isBuying"
          @click="simulateBuy"
        >
          模擬買入 {{ lots }} 張 @ ${{ props.currentPrice.toFixed(2) }}
        </NButton>
        <span style="font-size: 11px; color: #999; margin-left: 8px">建立模擬倉位，可在「模擬倉位」頁追蹤</span>
      </div>
    </NSpin>
  </NCard>
</template>
