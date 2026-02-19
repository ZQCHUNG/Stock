<script setup lang="ts">
import { ref, onMounted } from 'vue'
import {
  NTabs, NTabPane, NInputNumber, NButton, NSpace, NSpin, NAlert, NCollapse, NCollapseItem, NGrid, NGi, NText,
} from 'naive-ui'
import { useAppStore } from '../stores/app'
import { useBacktestStore } from '../stores/backtest'
import BacktestSingle from '../components/BacktestSingle.vue'
import BacktestPortfolio from '../components/BacktestPortfolio.vue'
import BacktestSimulation from '../components/BacktestSimulation.vue'
import BacktestAdvanced from '../components/BacktestAdvanced.vue'
import BacktestHistory from '../components/BacktestHistory.vue'
import StrategyComparison from '../components/StrategyComparison.vue'
import BacktestMetaStrategy from '../components/BacktestMetaStrategy.vue'
import BacktestBold from '../components/BacktestBold.vue'
import BacktestAggressive from '../components/BacktestAggressive.vue'
import BacktestSqsValidation from '../components/BacktestSqsValidation.vue'
import ConfigManager from '../components/ConfigManager.vue'
import { parseUrlConfig } from '../utils/urlConfig'
import { systemApi, downloadBlob } from '../api/system'
import { useResponsive } from '../composables/useResponsive'

const app = useAppStore()
const { isMobile } = useResponsive()
const bt = useBacktestStore()

const mode = ref('single')
const periodDays = ref(1095)
const capital = ref(1_000_000)
const commissionRate = ref(0.1425)  // % display
const taxRate = ref(0.3)            // % display
const slippageRate = ref(0.1)       // % display

function getBacktestConfig() {
  return {
    stockCode: app.currentStockCode,
    periodDays: periodDays.value,
    capital: capital.value,
    mode: mode.value,
    commissionRate: commissionRate.value,
    taxRate: taxRate.value,
    slippageRate: slippageRate.value,
  }
}

function loadBacktestConfig(config: Record<string, any>) {
  if (config.stockCode) app.selectStock(config.stockCode)
  if (config.periodDays) periodDays.value = config.periodDays
  if (config.capital) capital.value = config.capital
  if (config.mode) mode.value = config.mode
  if (config.commissionRate != null) commissionRate.value = config.commissionRate
  if (config.taxRate != null) taxRate.value = config.taxRate
  if (config.slippageRate != null) slippageRate.value = config.slippageRate
}

// Convert % display values to decimal rates for API
function costParams() {
  return {
    commission_rate: commissionRate.value / 100,
    tax_rate: taxRate.value / 100,
    slippage: slippageRate.value / 100,
  }
}

// R57: PDF export
const pdfLoading = ref(false)
async function exportPdf() {
  pdfLoading.value = true
  try {
    const data = await systemApi.exportBacktestPdf(app.currentStockCode, periodDays.value)
    downloadBlob(data, `backtest_${app.currentStockCode}.pdf`)
  } catch (e: any) {
    console.error('PDF export failed:', e)
  } finally {
    pdfLoading.value = false
  }
}

onMounted(() => {
  const urlCfg = parseUrlConfig()
  if (urlCfg?.type === 'backtest') {
    loadBacktestConfig(urlCfg.config)
    // Clean URL
    window.history.replaceState({}, '', window.location.pathname)
  }
})
</script>

<template>
  <div>
    <h2 style="margin: 0 0 16px">{{ app.currentStockCode }} {{ app.currentStockName }} - 回測報告</h2>

    <!-- Mode Selector -->
    <NTabs v-model:value="mode" type="segment" style="margin-bottom: 16px">
      <NTabPane name="single" tab="策略回測" />
      <NTabPane name="bold" tab="Bold策略" />
      <NTabPane name="aggressive" tab="Aggressive" />
      <NTabPane name="portfolio" tab="投資組合" />
      <NTabPane name="simulation" tab="模擬交易" />
      <NTabPane name="comparison" tab="策略比較" />
      <NTabPane name="meta" tab="Meta策略" />
      <NTabPane name="sqs" tab="SQS驗證" />
      <NTabPane name="advanced" tab="進階分析" />
      <NTabPane name="history" tab="歷史結果" />
    </NTabs>

    <!-- Shared Params -->
    <NSpace align="center" style="margin-bottom: 8px">
      <span style="font-size: 12px; color: var(--text-muted)">回測天數</span>
      <NInputNumber v-model:value="periodDays" :min="180" :max="3650" :step="30" size="small" placeholder="180~3650" style="width: 130px" />
      <span style="font-size: 12px; color: var(--text-muted)">初始資金</span>
      <NInputNumber v-model:value="capital" :min="100000" :max="100000000" :step="100000" size="small" placeholder="10萬~1億" style="width: 160px" />
      <ConfigManager config-type="backtest" :get-current-config="getBacktestConfig" @load="loadBacktestConfig" />
      <NButton size="small" type="warning" :loading="pdfLoading" @click="exportPdf">匯出 PDF</NButton>
    </NSpace>

    <!-- Transaction Cost Settings -->
    <NCollapse style="margin-bottom: 16px">
      <NCollapseItem title="交易成本設定" name="costs">
        <NGrid :cols="isMobile ? 1 : 3" :x-gap="12" :y-gap="8">
          <NGi>
            <NText depth="3" style="font-size: 11px; display: block; margin-bottom: 4px">手續費 (%)</NText>
            <NInputNumber v-model:value="commissionRate" :min="0" :max="1" :step="0.01" size="small" style="width: 100%">
              <template #suffix>%</template>
            </NInputNumber>
          </NGi>
          <NGi>
            <NText depth="3" style="font-size: 11px; display: block; margin-bottom: 4px">交易稅 (%)</NText>
            <NInputNumber v-model:value="taxRate" :min="0" :max="1" :step="0.1" size="small" style="width: 100%">
              <template #suffix>%</template>
            </NInputNumber>
          </NGi>
          <NGi>
            <NText depth="3" style="font-size: 11px; display: block; margin-bottom: 4px">滑價 (%)</NText>
            <NInputNumber v-model:value="slippageRate" :min="0" :max="1" :step="0.05" size="small" style="width: 100%">
              <template #suffix>%</template>
            </NInputNumber>
          </NGi>
        </NGrid>
        <NText depth="3" style="font-size: 11px; margin-top: 8px; display: block">
          來回交易成本 ≈ {{ ((commissionRate * 2 + taxRate + slippageRate * 2) || 0).toFixed(3) }}%
          （手續費×2 + 稅 + 滑價×2）
        </NText>
      </NCollapseItem>
    </NCollapse>

    <NSpin :show="bt.isLoading">
      <NAlert v-if="bt.error" type="error" style="margin-bottom: 16px">{{ bt.error }}</NAlert>

      <BacktestSingle v-if="mode === 'single'" :period-days="periodDays" :capital="capital" :cost-params="costParams()" />
      <BacktestBold v-if="mode === 'bold'" :period-days="periodDays" :capital="capital" :cost-params="costParams()" />
      <BacktestAggressive v-if="mode === 'aggressive'" :period-days="periodDays" :capital="capital" :cost-params="costParams()" />
      <BacktestPortfolio v-if="mode === 'portfolio'" :period-days="periodDays" :capital="capital" />
      <BacktestSimulation v-if="mode === 'simulation'" :period-days="periodDays" :capital="capital" />
      <StrategyComparison v-if="mode === 'comparison'" :period-days="periodDays" :capital="capital" />
      <BacktestMetaStrategy v-if="mode === 'meta'" :period-days="periodDays" :capital="capital" />
      <BacktestSqsValidation v-if="mode === 'sqs'" />
      <BacktestAdvanced v-if="mode === 'advanced'" :period-days="periodDays" :capital="capital" />
      <BacktestHistory v-if="mode === 'history'" />
    </NSpin>
  </div>
</template>
