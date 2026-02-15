<script setup lang="ts">
import { ref, watch, onMounted, computed } from 'vue'
import {
  NGrid, NGi, NCard, NSpin, NAlert, NButton, NInputNumber,
  NDataTable, NTag, NSpace, NSelect, NText, NStatistic, NEmpty,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import VChart from 'vue-echarts'
import { useAppStore } from '../stores/app'
import { useResponsive } from '../composables/useResponsive'
import { patternApi } from '../api/patterns'
import { fmtNum, fmtPct, priceColor } from '../utils/format'

const app = useAppStore()
const { cols, isMobile } = useResponsive()

// --- State ---
const windowSize = ref(20)
const lookbackDays = ref(365)
const loadingSimilar = ref(false)
const loadingHistory = ref(false)
const similarResults = ref<any[]>([])
const historyResults = ref<any[]>([])
const activeTab = ref<'cross' | 'history'>('history')

// --- Window options ---
const windowOptions = [
  { label: '10 天（短線）', value: 10 },
  { label: '20 天（月線）', value: 20 },
  { label: '40 天（雙月）', value: 40 },
  { label: '60 天（季線）', value: 60 },
]

// --- Load functions ---
async function loadSimilarStocks() {
  const code = app.currentStockCode
  if (!code) return
  loadingSimilar.value = true
  try {
    const res = await patternApi.similarStocks(code, windowSize.value, 15)
    similarResults.value = res.results || []
  } catch (e) {
    console.error('Similar stocks failed:', e)
    similarResults.value = []
  } finally {
    loadingSimilar.value = false
  }
}

async function loadHistoryPatterns() {
  const code = app.currentStockCode
  if (!code) return
  loadingHistory.value = true
  try {
    const res = await patternApi.similarHistory(code, windowSize.value, undefined, lookbackDays.value)
    historyResults.value = res.results || []
  } catch (e) {
    console.error('History patterns failed:', e)
    historyResults.value = []
  } finally {
    loadingHistory.value = false
  }
}

function loadData() {
  if (activeTab.value === 'cross') loadSimilarStocks()
  else loadHistoryPatterns()
}

onMounted(loadHistoryPatterns)
watch(() => app.currentStockCode, loadData)

// --- History table columns ---
const historyColumns: DataTableColumns<any> = [
  { title: '起始', key: 'start_date', width: 110, sorter: (a, b) => a.start_date.localeCompare(b.start_date) },
  { title: '結束', key: 'end_date', width: 110 },
  {
    title: '相似度',
    key: 'similarity_score',
    width: 90,
    sorter: (a: any, b: any) => a.similarity_score - b.similarity_score,
    render: (r: any) => {
      const s = r.similarity_score
      const color = s >= 90 ? '#18a058' : s >= 80 ? '#2080f0' : s >= 70 ? '#f0a020' : '#999'
      return h('span', { style: { color, fontWeight: 600 } }, `${s}%`)
    },
  },
  { title: 'DTW', key: 'dtw_distance', width: 80, render: (r: any) => r.dtw_distance.toFixed(3) },
  {
    title: 'D5 報酬',
    key: 'fwd_d5',
    width: 90,
    sorter: (a: any, b: any) => (a.forward_returns?.d5 ?? 0) - (b.forward_returns?.d5 ?? 0),
    render: (r: any) => {
      const v = r.forward_returns?.d5
      if (v == null) return '-'
      return h('span', { style: { color: priceColor(v) } }, `${v > 0 ? '+' : ''}${v.toFixed(1)}%`)
    },
  },
  {
    title: 'D10 報酬',
    key: 'fwd_d10',
    width: 90,
    render: (r: any) => {
      const v = r.forward_returns?.d10
      if (v == null) return '-'
      return h('span', { style: { color: priceColor(v) } }, `${v > 0 ? '+' : ''}${v.toFixed(1)}%`)
    },
  },
  {
    title: 'D20 報酬',
    key: 'fwd_d20',
    width: 90,
    render: (r: any) => {
      const v = r.forward_returns?.d20
      if (v == null) return '-'
      return h('span', { style: { color: priceColor(v) } }, `${v > 0 ? '+' : ''}${v.toFixed(1)}%`)
    },
  },
]

// --- Similar stocks table columns ---
const similarColumns: DataTableColumns<any> = [
  { title: '代碼', key: 'code', width: 70 },
  { title: '名稱', key: 'name', width: 100 },
  {
    title: '相似度',
    key: 'similarity_score',
    width: 90,
    sorter: (a: any, b: any) => a.similarity_score - b.similarity_score,
    render: (r: any) => {
      const s = r.similarity_score
      const color = s >= 90 ? '#18a058' : s >= 80 ? '#2080f0' : s >= 70 ? '#f0a020' : '#999'
      return h('span', { style: { color, fontWeight: 600 } }, `${s}%`)
    },
  },
  {
    title: '相關係數',
    key: 'correlation',
    width: 90,
    render: (r: any) => r.correlation.toFixed(3),
  },
  { title: 'DTW', key: 'dtw_distance', width: 80, render: (r: any) => r.dtw_distance.toFixed(3) },
  {
    title: '目標報酬',
    key: 'target_return_pct',
    width: 100,
    render: (r: any) => h('span', { style: { color: priceColor(r.target_return_pct) } },
      `${r.target_return_pct > 0 ? '+' : ''}${r.target_return_pct.toFixed(1)}%`),
  },
  {
    title: '候選報酬',
    key: 'candidate_return_pct',
    width: 100,
    render: (r: any) => h('span', { style: { color: priceColor(r.candidate_return_pct) } },
      `${r.candidate_return_pct > 0 ? '+' : ''}${r.candidate_return_pct.toFixed(1)}%`),
  },
]

// --- Probability Cloud Chart ---
const probabilityCloudOption = computed(() => {
  const data = historyResults.value
  if (!data || data.length === 0) return null

  // Extract forward returns for D5, D10, D20
  const d5 = data.filter((r: any) => r.forward_returns?.d5 != null).map((r: any) => r.forward_returns.d5)
  const d10 = data.filter((r: any) => r.forward_returns?.d10 != null).map((r: any) => r.forward_returns.d10)
  const d20 = data.filter((r: any) => r.forward_returns?.d20 != null).map((r: any) => r.forward_returns.d20)

  const avg = (arr: number[]) => arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : 0
  const winRate = (arr: number[]) => arr.length ? arr.filter(v => v > 0).length / arr.length * 100 : 0

  return {
    tooltip: {
      trigger: 'axis',
      formatter: (params: any) => {
        if (!Array.isArray(params)) return ''
        return params.map((p: any) => `${p.seriesName}: ${p.value.toFixed(1)}%`).join('<br>')
      },
    },
    legend: { data: ['D5 報酬', 'D10 報酬', 'D20 報酬'], top: 5 },
    grid: { left: 50, right: 20, bottom: 40, top: 40 },
    xAxis: {
      type: 'category',
      data: data.map((_: any, i: number) => `#${i + 1}`),
      axisLabel: { fontSize: 10 },
    },
    yAxis: {
      type: 'value',
      name: '報酬率 (%)',
      axisLine: { show: true },
      splitLine: { lineStyle: { type: 'dashed' } },
    },
    series: [
      {
        name: 'D5 報酬',
        type: 'scatter',
        data: d5,
        symbolSize: 8,
        itemStyle: { color: '#2080f0' },
        markLine: {
          silent: true,
          data: [
            { yAxis: 0, lineStyle: { color: '#999', type: 'dashed' } },
            { yAxis: avg(d5), name: `D5 avg: ${avg(d5).toFixed(1)}%`, lineStyle: { color: '#2080f0' } },
          ],
        },
      },
      {
        name: 'D10 報酬',
        type: 'scatter',
        data: d10,
        symbolSize: 8,
        itemStyle: { color: '#f0a020' },
      },
      {
        name: 'D20 報酬',
        type: 'scatter',
        data: d20,
        symbolSize: 8,
        itemStyle: { color: '#18a058' },
      },
    ],
  }
})

// --- Win Rate Stats ---
const winRateStats = computed(() => {
  const data = historyResults.value
  if (!data || data.length === 0) return null

  const calc = (key: string) => {
    const vals = data.filter((r: any) => r.forward_returns?.[key] != null).map((r: any) => r.forward_returns[key])
    if (!vals.length) return { avg: 0, winRate: 0, count: 0 }
    return {
      avg: vals.reduce((a: number, b: number) => a + b, 0) / vals.length,
      winRate: vals.filter((v: number) => v > 0).length / vals.length * 100,
      count: vals.length,
    }
  }

  return { d5: calc('d5'), d10: calc('d10'), d20: calc('d20') }
})

import { h } from 'vue'
</script>

<template>
  <div>
    <h2 style="margin: 0 0 16px">
      {{ app.currentStockCode }} {{ app.currentStockName }} - 相似線型分析
    </h2>

    <!-- Controls -->
    <NCard size="small" style="margin-bottom: 16px">
      <NSpace align="center" :wrap="true">
        <NSpace align="center" :size="4">
          <NText>比對天數:</NText>
          <NSelect
            v-model:value="windowSize"
            :options="windowOptions"
            style="width: 160px"
            size="small"
          />
        </NSpace>
        <NSpace align="center" :size="4">
          <NText>回溯:</NText>
          <NInputNumber v-model:value="lookbackDays" :min="60" :max="1825" :step="30" size="small" style="width: 100px" />
          <NText>天</NText>
        </NSpace>
        <NButton
          type="primary"
          size="small"
          :loading="loadingHistory"
          @click="loadHistoryPatterns"
        >
          歷史自比對
        </NButton>
        <NButton
          size="small"
          :loading="loadingSimilar"
          @click="loadSimilarStocks"
        >
          跨股比對
        </NButton>
      </NSpace>
    </NCard>

    <!-- Win Rate Summary -->
    <NGrid :cols="cols(2, 3, 6)" :x-gap="12" :y-gap="12" v-if="winRateStats" style="margin-bottom: 16px">
      <NGi>
        <NCard size="small">
          <NStatistic label="D5 平均報酬" :value="`${winRateStats.d5.avg > 0 ? '+' : ''}${winRateStats.d5.avg.toFixed(1)}%`" />
        </NCard>
      </NGi>
      <NGi>
        <NCard size="small">
          <NStatistic label="D5 勝率">
            <template #default>
              <span :style="{ color: winRateStats.d5.winRate >= 60 ? '#18a058' : winRateStats.d5.winRate >= 50 ? '#2080f0' : '#d03050' }">
                {{ winRateStats.d5.winRate.toFixed(0) }}%
              </span>
            </template>
          </NStatistic>
        </NCard>
      </NGi>
      <NGi>
        <NCard size="small">
          <NStatistic label="D10 平均報酬" :value="`${winRateStats.d10.avg > 0 ? '+' : ''}${winRateStats.d10.avg.toFixed(1)}%`" />
        </NCard>
      </NGi>
      <NGi>
        <NCard size="small">
          <NStatistic label="D10 勝率">
            <template #default>
              <span :style="{ color: winRateStats.d10.winRate >= 60 ? '#18a058' : winRateStats.d10.winRate >= 50 ? '#2080f0' : '#d03050' }">
                {{ winRateStats.d10.winRate.toFixed(0) }}%
              </span>
            </template>
          </NStatistic>
        </NCard>
      </NGi>
      <NGi>
        <NCard size="small">
          <NStatistic label="D20 平均報酬" :value="`${winRateStats.d20.avg > 0 ? '+' : ''}${winRateStats.d20.avg.toFixed(1)}%`" />
        </NCard>
      </NGi>
      <NGi>
        <NCard size="small">
          <NStatistic label="樣本數" :value="winRateStats.d5.count" />
        </NCard>
      </NGi>
    </NGrid>

    <!-- Probability Cloud Chart -->
    <NCard title="機率雲 — 歷史相似區段後的報酬分佈" size="small" style="margin-bottom: 16px" v-if="probabilityCloudOption">
      <VChart :option="probabilityCloudOption" style="height: 300px" autoresize />
    </NCard>

    <!-- History Results Table -->
    <NCard title="歷史相似區段" size="small" style="margin-bottom: 16px" v-if="historyResults.length > 0">
      <NSpin :show="loadingHistory">
        <NDataTable
          :columns="historyColumns"
          :data="historyResults"
          :bordered="false"
          :single-line="false"
          :pagination="{ pageSize: 20 }"
          size="small"
          max-height="400"
        />
      </NSpin>
    </NCard>

    <!-- Similar Stocks Results -->
    <NCard title="跨股相似度 (DTW)" size="small" style="margin-bottom: 16px" v-if="similarResults.length > 0">
      <NSpin :show="loadingSimilar">
        <NDataTable
          :columns="similarColumns"
          :data="similarResults"
          :bordered="false"
          :single-line="false"
          :pagination="{ pageSize: 15 }"
          size="small"
          max-height="400"
        />
      </NSpin>
    </NCard>

    <!-- Empty state -->
    <NCard v-if="!loadingHistory && !loadingSimilar && historyResults.length === 0 && similarResults.length === 0">
      <NEmpty description="點擊上方按鈕開始分析" />
    </NCard>
  </div>
</template>
