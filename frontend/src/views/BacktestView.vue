<script setup lang="ts">
import { ref } from 'vue'
import {
  NTabs, NTabPane, NInputNumber, NSpace, NSpin, NAlert,
} from 'naive-ui'
import { useAppStore } from '../stores/app'
import { useBacktestStore } from '../stores/backtest'
import BacktestSingle from '../components/BacktestSingle.vue'
import BacktestPortfolio from '../components/BacktestPortfolio.vue'
import BacktestSimulation from '../components/BacktestSimulation.vue'
import BacktestAdvanced from '../components/BacktestAdvanced.vue'

const app = useAppStore()
const bt = useBacktestStore()

const mode = ref('single')
const periodDays = ref(1095)
const capital = ref(1_000_000)
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
    </NTabs>

    <!-- Shared Params -->
    <NSpace style="margin-bottom: 16px">
      <NInputNumber v-model:value="periodDays" :min="180" :max="3650" size="small" placeholder="天數" style="width: 120px" />
      <NInputNumber v-model:value="capital" :min="100000" :step="100000" size="small" placeholder="資金" style="width: 160px" />
    </NSpace>

    <NSpin :show="bt.isLoading">
      <NAlert v-if="bt.error" type="error" style="margin-bottom: 16px">{{ bt.error }}</NAlert>

      <BacktestSingle v-if="mode === 'single'" :period-days="periodDays" :capital="capital" />
      <BacktestPortfolio v-if="mode === 'portfolio'" :period-days="periodDays" :capital="capital" />
      <BacktestSimulation v-if="mode === 'simulation'" :period-days="periodDays" :capital="capital" />
      <BacktestAdvanced v-if="mode === 'advanced'" :period-days="periodDays" :capital="capital" />
    </NSpin>
  </div>
</template>
