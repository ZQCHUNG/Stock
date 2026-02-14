<script setup lang="ts">
import { ref, onMounted } from 'vue'
import {
  NTabs, NTabPane, NInputNumber, NSpace, NSpin, NAlert,
} from 'naive-ui'
import { useAppStore } from '../stores/app'
import { useBacktestStore } from '../stores/backtest'
import BacktestSingle from '../components/BacktestSingle.vue'
import BacktestPortfolio from '../components/BacktestPortfolio.vue'
import BacktestSimulation from '../components/BacktestSimulation.vue'
import BacktestAdvanced from '../components/BacktestAdvanced.vue'
import BacktestHistory from '../components/BacktestHistory.vue'
import ConfigManager from '../components/ConfigManager.vue'
import { parseUrlConfig } from '../utils/urlConfig'

const app = useAppStore()
const bt = useBacktestStore()

const mode = ref('single')
const periodDays = ref(1095)
const capital = ref(1_000_000)

function getBacktestConfig() {
  return {
    stockCode: app.currentStockCode,
    periodDays: periodDays.value,
    capital: capital.value,
    mode: mode.value,
  }
}

function loadBacktestConfig(config: Record<string, any>) {
  if (config.stockCode) app.selectStock(config.stockCode)
  if (config.periodDays) periodDays.value = config.periodDays
  if (config.capital) capital.value = config.capital
  if (config.mode) mode.value = config.mode
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
      <NTabPane name="single" tab="單一回測" />
      <NTabPane name="portfolio" tab="投資組合" />
      <NTabPane name="simulation" tab="模擬交易" />
      <NTabPane name="advanced" tab="進階分析" />
      <NTabPane name="history" tab="歷史結果" />
    </NTabs>

    <!-- Shared Params -->
    <NSpace align="center" style="margin-bottom: 16px">
      <span style="font-size: 12px; color: var(--text-muted)">回測天數</span>
      <NInputNumber v-model:value="periodDays" :min="180" :max="3650" :step="30" size="small" placeholder="180~3650" style="width: 130px" />
      <span style="font-size: 12px; color: var(--text-muted)">初始資金</span>
      <NInputNumber v-model:value="capital" :min="100000" :max="100000000" :step="100000" size="small" placeholder="10萬~1億" style="width: 160px" />
      <ConfigManager config-type="backtest" :get-current-config="getBacktestConfig" @load="loadBacktestConfig" />
    </NSpace>

    <NSpin :show="bt.isLoading">
      <NAlert v-if="bt.error" type="error" style="margin-bottom: 16px">{{ bt.error }}</NAlert>

      <BacktestSingle v-if="mode === 'single'" :period-days="periodDays" :capital="capital" />
      <BacktestPortfolio v-if="mode === 'portfolio'" :period-days="periodDays" :capital="capital" />
      <BacktestSimulation v-if="mode === 'simulation'" :period-days="periodDays" :capital="capital" />
      <BacktestAdvanced v-if="mode === 'advanced'" :period-days="periodDays" :capital="capital" />
      <BacktestHistory v-if="mode === 'history'" />
    </NSpin>
  </div>
</template>
