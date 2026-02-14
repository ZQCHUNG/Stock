<script setup lang="ts">
import { h, ref, computed } from 'vue'
import {
  NCard, NButton, NSpin, NGrid, NGi, NDataTable, NTag, NSpace, NAlert, NText,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import VChart from 'vue-echarts'
import { useAppStore } from '../stores/app'
import { useWatchlistStore } from '../stores/watchlist'
import { backtestApi } from '../api/backtest'
import { fmtPct, fmtNum, priceColor } from '../utils/format'
import { useResponsive } from '../composables/useResponsive'
import MetricCard from './MetricCard.vue'

const props = defineProps<{ periodDays: number; capital: number }>()

const app = useAppStore()
const wl = useWatchlistStore()
const { cols } = useResponsive()
const metricCols = cols(2, 4, 6)

const result = ref<any>(null)
const isLoading = ref(false)
const error = ref('')

async function runMetaBacktest() {
  isLoading.value = true
  error.value = ''
  try {
    // Use watchlist stocks if available, else fallback to first 20 stocks
    const codes = wl.watchlist.length > 0
      ? wl.watchlist.map(s => s.code)
      : app.allStocks.slice(0, 20).map(s => s.code)

    result.value = await backtestApi.metaStrategy(codes, props.periodDays, props.capital)
  } catch (e: any) {
    error.value = e.message || '回測失敗'
  }
  isLoading.value = false
}

// Strategy tag colors
type TagType = 'default' | 'error' | 'info' | 'success' | 'warning' | 'primary'
const tagColors: Record<string, TagType> = {
  V4: 'error',
  V5: 'info',
  Adaptive: 'success',
}

// Stock detail table
const stockColumns: DataTableColumns = [
  { title: '代號', key: 'code', width: 70 },
  { title: '名稱', key: 'name', width: 80 },
  {
    title: '適配標籤', key: 'fitness_tag', width: 140,
    render: (row: any) => h(NTag, { size: 'small', bordered: false }, () => row.fitness_tag),
  },
  {
    title: '選用策略', key: 'chosen_strategy', width: 90,
    render: (row: any) => h(NTag, {
      type: (tagColors[row.chosen_strategy] || 'default') as TagType,
      size: 'small',
    }, () => row.chosen_strategy),
  },
  {
    title: '報酬率', key: 'total_return', width: 90,
    sorter: (a: any, b: any) => a.total_return - b.total_return,
    render: (row: any) => h('span', { style: { color: priceColor(row.total_return) } }, fmtPct(row.total_return)),
  },
  {
    title: 'Sharpe', key: 'sharpe_ratio', width: 80,
    sorter: (a: any, b: any) => a.sharpe_ratio - b.sharpe_ratio,
    render: (row: any) => row.sharpe_ratio?.toFixed(2) || '-',
  },
  {
    title: '交易數', key: 'total_trades', width: 70,
    render: (row: any) => String(row.total_trades),
  },
  {
    title: '勝率', key: 'win_rate', width: 70,
    render: (row: any) => fmtPct(row.win_rate),
  },
]

const stockRows = computed(() => {
  if (!result.value?.stock_strategies) return []
  return Object.entries(result.value.stock_strategies).map(([code, info]: [string, any]) => ({
    code,
    ...info,
  }))
})

// Strategy distribution
const stratDist = computed(() => {
  if (!stockRows.value.length) return {}
  const dist: Record<string, number> = {}
  for (const row of stockRows.value) {
    const s = row.chosen_strategy || 'Unknown'
    dist[s] = (dist[s] || 0) + 1
  }
  return dist
})

// Equity curve chart
const equityChartOption = computed(() => {
  if (!result.value?.equity_curve) return {}
  const eq = result.value.equity_curve
  return {
    title: { text: 'Meta-Strategy 權益曲線', left: 'center', textStyle: { fontSize: 14 } },
    tooltip: {
      trigger: 'axis',
      formatter: (params: any[]) => {
        if (!params?.length) return ''
        const p = params[0]
        return `${p.name}<br/>組合淨值: ${fmtNum(p.value)}`
      },
    },
    grid: { left: 80, right: 20, top: 40, bottom: 30 },
    xAxis: { type: 'category', data: eq.dates, axisLabel: { show: false } },
    yAxis: {
      type: 'value',
      axisLabel: { formatter: (v: number) => fmtNum(v) },
    },
    series: [{
      type: 'line',
      data: eq.values,
      showSymbol: false,
      lineStyle: { width: 2, color: '#2080f0' },
      areaStyle: { color: 'rgba(32,128,240,0.1)' },
    }],
  }
})
</script>

<template>
  <div>
    <NCard size="small" style="margin-bottom: 16px">
      <template #header>
        <NSpace align="center" :size="8">
          <span style="font-weight: 700">Meta-Strategy 回測</span>
          <NTag size="small" :bordered="false" type="info">Gemini R41</NTag>
        </NSpace>
      </template>
      <template #header-extra>
        <NButton type="primary" size="small" @click="runMetaBacktest" :loading="isLoading">
          {{ result ? '重新回測' : '執行 Meta-Strategy' }}
        </NButton>
      </template>

      <NText depth="3" style="font-size: 12px; display: block; margin-bottom: 12px">
        根據每檔股票的 Fitness Tag 自動選擇最適合的策略（V4/V5/Adaptive），
        比較組合績效是否優於純 V4 基線。使用自選股清單或預設股池。
      </NText>

      <NAlert v-if="error" type="error" style="margin-bottom: 12px">{{ error }}</NAlert>

      <NSpin :show="isLoading">
        <template v-if="result">
          <!-- Summary Metrics -->
          <NGrid :cols="metricCols" :x-gap="8" :y-gap="8" style="margin-bottom: 16px">
            <NGi><MetricCard title="組合報酬" :value="fmtPct(result.total_return)" :color="priceColor(result.total_return)" /></NGi>
            <NGi><MetricCard title="年化報酬" :value="fmtPct(result.annual_return)" :color="priceColor(result.annual_return)" /></NGi>
            <NGi><MetricCard title="最大回撤" :value="fmtPct(result.max_drawdown)" color="#e53e3e" /></NGi>
            <NGi><MetricCard title="Sharpe" :value="result.sharpe_ratio?.toFixed(2) || '-'" /></NGi>
            <NGi><MetricCard title="交易數" :value="result.total_trades" /></NGi>
            <NGi>
              <MetricCard
                title="vs V4 基線"
                :value="result.alpha_vs_v4 != null ? (result.alpha_vs_v4 > 0 ? '+' : '') + fmtPct(result.alpha_vs_v4) : '-'"
                :color="result.alpha_vs_v4 > 0 ? '#18a058' : result.alpha_vs_v4 < 0 ? '#e53e3e' : undefined"
              />
            </NGi>
          </NGrid>

          <!-- Strategy Distribution -->
          <NSpace :size="8" style="margin-bottom: 16px">
            <NTag v-for="(count, strat) in stratDist" :key="strat" :type="(tagColors[strat as string] || 'default') as any" size="small">
              {{ strat }}: {{ count }}檔
            </NTag>
            <NTag size="small" :bordered="false">
              盈利 {{ result.winning_stocks }} / 虧損 {{ result.losing_stocks }}
            </NTag>
          </NSpace>

          <!-- Equity Curve -->
          <div v-if="equityChartOption?.series" style="margin-bottom: 16px">
            <VChart :option="equityChartOption" style="height: 300px" autoresize />
          </div>

          <!-- Stock Details Table -->
          <NDataTable
            :columns="stockColumns"
            :data="stockRows"
            :pagination="{ pageSize: 15 }"
            size="small"
            :bordered="true"
            :scroll-x="700"
          />
        </template>

        <div v-else-if="!isLoading" style="padding: 40px; text-align: center; color: var(--text-dimmed)">
          點擊「執行 Meta-Strategy」開始回測。系統會根據 Fitness Tag 為每檔股票選擇最適策略。
        </div>
      </NSpin>
    </NCard>
  </div>
</template>
