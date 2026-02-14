<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import {
  NCard, NButton, NDataTable, NTag, NSpace, NAlert, NSpin, NTabs, NTabPane, NSelect,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import VChart from 'vue-echarts'
import { analysisApi } from '../api/analysis'
import { fmtPct } from '../utils/format'

// State
const fitnessData = ref<any>(null)
const accuracyData = ref<any>(null)
const decayData = ref<any>(null)
const isLoading = ref(false)
const isScanRunning = ref(false)
const error = ref('')
const mode = ref('fitness')
const tagFilter = ref<string | null>(null)
const sqsDistData = ref<any>(null)
const isSqsLoading = ref(false)

// Load fitness data
async function loadFitness() {
  isLoading.value = true
  error.value = ''
  try {
    const [fitness, accuracy, decay] = await Promise.all([
      analysisApi.strategyFitness(),
      analysisApi.signalAccuracy(60).catch(() => null),
      analysisApi.signalDecay(90).catch(() => null),
    ])
    fitnessData.value = fitness
    accuracyData.value = accuracy
    decayData.value = decay
  } catch (e: any) {
    error.value = e.message || '載入失敗'
  }
  isLoading.value = false
}

async function runScan() {
  isScanRunning.value = true
  try {
    await analysisApi.runFitnessScan()
    await loadFitness()
  } catch (e: any) {
    error.value = e.message || '掃描失敗'
  }
  isScanRunning.value = false
}

async function recordSignals() {
  try {
    await analysisApi.recordSignals()
    await analysisApi.fillForwardReturns()
    await loadFitness()
  } catch { /* ignore */ }
}

async function loadSqsDistribution() {
  isSqsLoading.value = true
  try {
    sqsDistData.value = await analysisApi.sqsDistribution()
  } catch { sqsDistData.value = null }
  isSqsLoading.value = false
}

onMounted(loadFitness)

// Computed
const stocks = computed(() => {
  if (!fitnessData.value?.stocks) return []
  let list = fitnessData.value.stocks
  if (tagFilter.value) {
    list = list.filter((s: any) => s.fitness_tag === tagFilter.value)
  }
  return list
})

const summary = computed(() => fitnessData.value?.summary ?? {})

const tagOptions = computed(() => {
  const dist = summary.value.tag_distribution ?? {}
  return Object.entries(dist).map(([tag, count]) => ({
    label: `${tag} (${count})`,
    value: tag,
  }))
})

// Scatter chart: V4 PF vs V5 PF
const scatterOption = computed(() => {
  if (!stocks.value.length) return {}

  const tagColors: Record<string, string> = {
    'Trend Preferred (V4)': '#e53e3e',
    'Volatility Preferred (V5)': '#2080f0',
    'Balanced': '#18a058',
    'Trend Only (V4)': '#f0a020',
    'Reversion Only (V5)': '#9b59b6',
    'Insufficient Data': '#999',
    'No Signal': '#ccc',
  }

  const seriesMap = new Map<string, any[]>()
  for (const s of stocks.value) {
    const tag = s.fitness_tag || 'Unknown'
    if (!seriesMap.has(tag)) seriesMap.set(tag, [])
    seriesMap.get(tag)!.push({
      value: [s.v4_fitness_score || 0, s.v5_fitness_score || 0],
      name: s.code,
      tag,
    })
  }

  const series = Array.from(seriesMap.entries()).map(([tag, data]) => ({
    name: tag,
    type: 'scatter',
    data: data.map(d => d.value),
    symbolSize: 10,
    itemStyle: { color: tagColors[tag] || '#666' },
    emphasis: { focus: 'series' },
    tooltip: {
      formatter: (params: any) => {
        const idx = params.dataIndex
        const item = data[idx]
        return `${item.name}<br/>V4 Score: ${params.value[0].toFixed(2)}<br/>V5 Score: ${params.value[1].toFixed(2)}`
      },
    },
  }))

  return {
    title: { text: '策略適配度分佈', left: 'center', textStyle: { fontSize: 14 } },
    tooltip: { trigger: 'item' },
    legend: { bottom: 0, textStyle: { fontSize: 11 } },
    xAxis: {
      name: 'V4 Fitness Score',
      nameLocation: 'center',
      nameGap: 30,
      type: 'value',
    },
    yAxis: {
      name: 'V5 Fitness Score',
      nameLocation: 'center',
      nameGap: 40,
      type: 'value',
    },
    grid: { left: 60, right: 20, top: 40, bottom: 60 },
    series,
  }
})

// Table columns
const tableColumns: DataTableColumns = [
  { title: '代號', key: 'code', width: 80, sorter: 'default' },
  {
    title: '適配標籤', key: 'fitness_tag', width: 160,
    render: (row: any) => {
      const colors: Record<string, string> = {
        'Trend Preferred (V4)': 'error',
        'Volatility Preferred (V5)': 'info',
        'Balanced': 'success',
        'Trend Only (V4)': 'warning',
        'Reversion Only (V5)': 'info',
        'Insufficient Data': 'default',
        'No Signal': 'default',
      }
      return h(NTag, { type: (colors[row.fitness_tag] || 'default') as any, size: 'small' }, () => row.fitness_tag)
    },
  },
  {
    title: 'V4 Score', key: 'v4_fitness_score', width: 90,
    sorter: (a: any, b: any) => (a.v4_fitness_score || 0) - (b.v4_fitness_score || 0),
    render: (row: any) => row.v4_fitness_score?.toFixed(2) || '-',
  },
  {
    title: 'V5 Score', key: 'v5_fitness_score', width: 90,
    sorter: (a: any, b: any) => (a.v5_fitness_score || 0) - (b.v5_fitness_score || 0),
    render: (row: any) => row.v5_fitness_score?.toFixed(2) || '-',
  },
  {
    title: 'V4 PF', key: 'v4_profit_factor', width: 80,
    render: (row: any) => row.v4_profit_factor?.toFixed(2) || '-',
  },
  {
    title: 'V5 PF', key: 'v5_profit_factor', width: 80,
    render: (row: any) => row.v5_profit_factor?.toFixed(2) || '-',
  },
  {
    title: 'V4 Sharpe', key: 'v4_sharpe', width: 90,
    sorter: (a: any, b: any) => (a.v4_sharpe || 0) - (b.v4_sharpe || 0),
    render: (row: any) => row.v4_sharpe?.toFixed(2) || '-',
  },
  {
    title: 'V5 Sharpe', key: 'v5_sharpe', width: 90,
    render: (row: any) => row.v5_sharpe?.toFixed(2) || '-',
  },
  {
    title: 'V4 交易', key: 'v4_trades', width: 70,
    render: (row: any) => String(row.v4_trades || 0),
  },
  {
    title: 'V5 交易', key: 'v5_trades', width: 70,
    render: (row: any) => String(row.v5_trades || 0),
  },
  {
    title: 'Regime', key: 'regime', width: 120,
    render: (row: any) => {
      const labels: Record<string, string> = {
        trend_explosive: '趨勢噴發',
        trend_mild: '溫和趨勢',
        range_volatile: '震盪劇烈',
        range_quiet: '低波盤整',
      }
      return labels[row.regime] || row.regime || '-'
    },
  },
]

// Accuracy table
const accuracyRows = computed(() => {
  if (!accuracyData.value?.strategies) return []
  return Object.entries(accuracyData.value.strategies).map(([strat, data]: [string, any]) => ({
    strategy: strat,
    ...data,
  }))
})

const accuracyColumns: DataTableColumns = [
  { title: '策略', key: 'strategy', width: 100 },
  { title: '信號數', key: 'total_signals', width: 80 },
  { title: '已追蹤', key: 'filled', width: 80 },
  {
    title: '5日勝率', key: 'win_rate_5d', width: 100,
    render: (row: any) => row.win_rate_5d != null ? fmtPct(row.win_rate_5d) : '-',
  },
  {
    title: '平均5日報酬', key: 'avg_return_5d', width: 110,
    render: (row: any) => row.avg_return_5d != null ? fmtPct(row.avg_return_5d) : '-',
  },
  {
    title: '平均最大漲幅', key: 'avg_max_gain', width: 110,
    render: (row: any) => row.avg_max_gain != null ? fmtPct(row.avg_max_gain) : '-',
  },
  {
    title: '平均最大回撤', key: 'avg_max_dd', width: 110,
    render: (row: any) => row.avg_max_dd != null ? fmtPct(row.avg_max_dd) : '-',
  },
]

// Signal Decay chart (Gemini R40)
const decayChartOption = computed(() => {
  const d = decayData.value?.strategies
  if (!d) return {}

  const stratColors: Record<string, string> = {
    V4: '#e53e3e',
    V5: '#2080f0',
    Adaptive: '#18a058',
  }

  const series: any[] = []
  for (const [strat, info] of Object.entries(d) as [string, any][]) {
    if (!info.decay_curve?.length) continue
    series.push({
      name: `${strat} (n=${info.sample_count})`,
      type: 'line',
      data: info.decay_curve.map((p: any) => [p.day, +(p.avg_return * 100).toFixed(3)]),
      lineStyle: { width: 2, color: stratColors[strat] || '#666' },
      symbol: 'circle',
      symbolSize: 8,
      itemStyle: { color: stratColors[strat] || '#666' },
    })
    // BIAS-confirmed subset for V5
    if (strat === 'V5' && info.bias_decay_curve?.length) {
      series.push({
        name: `V5+BIAS (n=${info.bias_decay_curve[0]?.n || 0})`,
        type: 'line',
        data: info.bias_decay_curve.map((p: any) => [p.day, +(p.avg_return * 100).toFixed(3)]),
        lineStyle: { width: 2, color: '#9b59b6', type: 'dashed' },
        symbol: 'diamond',
        symbolSize: 8,
        itemStyle: { color: '#9b59b6' },
      })
    }
  }

  if (!series.length) return {}

  return {
    title: { text: '信號衰減曲線（平均報酬 %）', left: 'center', textStyle: { fontSize: 14 } },
    tooltip: {
      trigger: 'axis',
      formatter: (params: any[]) => {
        if (!params?.length) return ''
        let html = `<b>Day ${params[0].value[0]}</b><br/>`
        for (const p of params) {
          html += `<span style="color:${p.color}">${p.seriesName}: ${p.value[1].toFixed(3)}%</span><br/>`
        }
        return html
      },
    },
    legend: { bottom: 0, textStyle: { fontSize: 11 } },
    grid: { left: 60, right: 20, top: 40, bottom: 60 },
    xAxis: {
      type: 'value',
      name: '信號後天數',
      nameLocation: 'center',
      nameGap: 30,
      min: 0,
      max: 21,
      interval: 5,
    },
    yAxis: {
      type: 'value',
      name: '平均報酬 (%)',
      nameLocation: 'center',
      nameGap: 40,
      axisLabel: { formatter: '{value}%' },
      splitLine: { lineStyle: { type: 'dashed' } },
    },
    series,
  }
})

// Import h for render functions
import { h } from 'vue'
</script>

<template>
  <div>
    <h2 style="margin: 0 0 16px">策略適配度分析</h2>

    <NTabs v-model:value="mode" type="segment" style="margin-bottom: 16px">
      <NTabPane name="fitness" tab="適配度矩陣" />
      <NTabPane name="accuracy" tab="信號準確率" />
      <NTabPane name="decay" tab="信號衰減" />
      <NTabPane name="sqs-dist" tab="SQS 分佈" />
    </NTabs>

    <NSpin :show="isLoading">
      <NAlert v-if="error" type="error" style="margin-bottom: 16px">{{ error }}</NAlert>

      <!-- Fitness Matrix Tab -->
      <template v-if="mode === 'fitness'">
        <NCard size="small" style="margin-bottom: 16px">
          <template #header>
            <NSpace align="center" :size="8">
              <span>策略性格分佈</span>
              <NTag v-if="summary.total" size="small" :bordered="false">
                {{ summary.total }} 檔已分析
              </NTag>
              <NTag v-if="summary.last_computed" size="small" type="info" :bordered="false">
                {{ summary.last_computed?.split('T')[0] }}
              </NTag>
            </NSpace>
          </template>
          <template #header-extra>
            <NSpace :size="8">
              <NButton size="small" @click="recordSignals">記錄今日信號</NButton>
              <NButton size="small" type="primary" @click="runScan" :loading="isScanRunning">
                {{ summary.total ? '重新掃描' : '啟動適配度掃描' }}
              </NButton>
            </NSpace>
          </template>

          <!-- Scatter Plot -->
          <div v-if="stocks.length > 0" style="margin-bottom: 16px">
            <VChart :option="scatterOption" style="height: 360px" autoresize />
          </div>

          <div v-else-if="!isLoading" style="padding: 40px; text-align: center; color: var(--text-dimmed)">
            尚無適配度數據。點擊「啟動適配度掃描」批次計算 108 檔股票的 V4/V5/Adaptive 績效。
          </div>
        </NCard>

        <!-- Fitness Table -->
        <NCard v-if="stocks.length > 0" size="small">
          <template #header>
            <NSpace align="center" :size="8">
              <span>適配度明細</span>
              <NSelect
                v-model:value="tagFilter"
                :options="tagOptions"
                placeholder="篩選標籤"
                size="small"
                clearable
                style="min-width: 200px"
              />
            </NSpace>
          </template>
          <NDataTable
            :columns="tableColumns"
            :data="stocks"
            :pagination="{ pageSize: 20 }"
            size="small"
            :bordered="true"
            :scroll-x="1000"
          />
        </NCard>
      </template>

      <!-- Accuracy Tab -->
      <template v-if="mode === 'accuracy'">
        <NCard title="信號前瞻績效（過去 60 天）" size="small">
          <template #header-extra>
            <NTag v-if="accuracyData?.pending_fill" type="warning" size="small">
              {{ accuracyData.pending_fill }} 筆待追蹤
            </NTag>
          </template>

          <NDataTable
            v-if="accuracyRows.length"
            :columns="accuracyColumns"
            :data="accuracyRows"
            :pagination="false"
            size="small"
            :bordered="true"
          />

          <div v-else style="padding: 40px; text-align: center; color: var(--text-dimmed)">
            尚無信號追蹤數據。先「記錄今日信號」，5 個交易日後系統會自動計算前瞻報酬率。
          </div>
        </NCard>
      </template>

      <!-- Signal Decay Tab (Gemini R40) -->
      <template v-if="mode === 'decay'">
        <NCard title="信號衰減分析（過去 90 天）" size="small">
          <template #header-extra>
            <NSpace :size="8">
              <NButton size="small" @click="recordSignals">記錄今日信號</NButton>
            </NSpace>
          </template>

          <div v-if="decayChartOption?.series" style="margin-bottom: 16px">
            <VChart :option="decayChartOption" style="height: 360px" autoresize />
          </div>

          <!-- Per-strategy summary cards -->
          <NSpace v-if="decayData?.strategies" :size="12" style="margin-top: 8px">
            <NCard v-for="(info, strat) in decayData.strategies" :key="strat" size="small" style="min-width: 200px">
              <template #header>
                <NTag :type="strat === 'V4' ? 'error' : strat === 'V5' ? 'info' : 'success'" size="small">
                  {{ strat }}
                </NTag>
                <span style="margin-left: 8px; font-size: 12px">{{ info.sample_count }} 筆信號</span>
              </template>
              <div style="font-size: 13px; line-height: 1.8">
                <div><b>5日</b>: 漲幅 {{ info.avg_max_gain_5d != null ? fmtPct(info.avg_max_gain_5d) : '-' }} / 回撤 {{ info.avg_max_dd_5d != null ? fmtPct(info.avg_max_dd_5d) : '-' }}</div>
                <div><b>20日</b>: 漲幅 {{ info.avg_max_gain_20d != null ? fmtPct(info.avg_max_gain_20d) : '-' }} / 回撤 {{ info.avg_max_dd_20d != null ? fmtPct(info.avg_max_dd_20d) : '-' }}</div>
                <template v-if="info.ev?.d5">
                  <div style="margin-top: 4px; border-top: 1px solid var(--border-color); padding-top: 4px">
                    <b>EV(5d)</b>: <span :style="{ color: info.ev.d5.ev > 0 ? '#18a058' : '#e53e3e' }">{{ (info.ev.d5.ev * 100).toFixed(2) }}%</span>
                    <span v-if="info.ev.d5.net_ev != null" style="margin-left: 4px; font-size: 11px" :style="{ color: info.ev.d5.net_ev > 0 ? '#18a058' : '#e53e3e' }">
                      (Net {{ (info.ev.d5.net_ev * 100).toFixed(2) }}%)
                    </span>
                    <span style="margin-left: 6px; color: var(--text-dimmed); font-size: 12px">勝率 {{ (info.ev.d5.win_pct * 100).toFixed(1) }}%</span>
                    <span v-if="info.ev.d5.cost_trap" style="margin-left: 4px; font-size: 11px; color: #f0a020">成本陷阱</span>
                  </div>
                </template>
                <template v-if="info.ev?.d20">
                  <div>
                    <b>EV(20d)</b>: <span :style="{ color: info.ev.d20.ev > 0 ? '#18a058' : '#e53e3e' }">{{ (info.ev.d20.ev * 100).toFixed(2) }}%</span>
                    <span v-if="info.ev.d20.net_ev != null" style="margin-left: 4px; font-size: 11px" :style="{ color: info.ev.d20.net_ev > 0 ? '#18a058' : '#e53e3e' }">
                      (Net {{ (info.ev.d20.net_ev * 100).toFixed(2) }}%)
                    </span>
                    <span style="margin-left: 6px; color: var(--text-dimmed); font-size: 12px">勝率 {{ (info.ev.d20.win_pct * 100).toFixed(1) }}% (n={{ info.ev.d20.n }})</span>
                    <span v-if="info.ev.d20.cost_trap" style="margin-left: 4px; font-size: 11px; color: #f0a020">成本陷阱</span>
                  </div>
                </template>
              </div>
            </NCard>
          </NSpace>

          <div v-if="!decayData?.strategies" style="padding: 40px; text-align: center; color: var(--text-dimmed)">
            尚無衰減數據。先「記錄今日信號」，待信號累積後系統會計算衰減曲線。
          </div>
        </NCard>
      </template>

      <!-- SQS Distribution Tab -->
      <template v-if="mode === 'sqs-dist'">
        <NSpace style="margin-bottom: 12px">
          <NButton type="primary" @click="loadSqsDistribution" :loading="isSqsLoading" size="small">
            載入 SQS 分佈
          </NButton>
          <span style="font-size: 12px; color: #999">分析當前所有 BUY 信號的 SQS 分數分佈 + 自適應等級</span>
        </NSpace>

        <NSpin :show="isSqsLoading">
          <template v-if="sqsDistData && sqsDistData.count > 0">
            <!-- Percentile stats -->
            <NCard size="small" style="margin-bottom: 12px">
              <template #header>分佈統計 ({{ sqsDistData.count }} 筆信號)</template>
              <NSpace :size="16">
                <span>Min: <b>{{ sqsDistData.percentiles?.min }}</b></span>
                <span>P25: <b>{{ sqsDistData.percentiles?.p25 }}</b></span>
                <span>Median: <b>{{ sqsDistData.percentiles?.p50 }}</b></span>
                <span>Mean: <b>{{ sqsDistData.percentiles?.mean }}</b></span>
                <span>P75: <b>{{ sqsDistData.percentiles?.p75 }}</b></span>
                <span>Max: <b>{{ sqsDistData.percentiles?.max }}</b></span>
                <span>Std: <b>{{ sqsDistData.percentiles?.std }}</b></span>
              </NSpace>
            </NCard>

            <!-- Histogram chart -->
            <NCard size="small" style="margin-bottom: 12px">
              <VChart :option="{
                title: { text: 'SQS 分數直方圖', left: 'center', textStyle: { fontSize: 14 } },
                tooltip: { trigger: 'axis' },
                xAxis: { type: 'category', data: sqsDistData.histogram?.map((h: any) => h.range) || [], name: 'SQS 區間' },
                yAxis: { type: 'value', name: '信號數' },
                series: [{ type: 'bar', data: sqsDistData.histogram?.map((h: any) => h.count) || [],
                  itemStyle: { color: (p: any) => p.dataIndex >= 8 ? '#18a058' : p.dataIndex >= 6 ? '#2080f0' : p.dataIndex >= 4 ? '#f0a020' : '#999' }
                }],
                grid: { left: 50, right: 20, bottom: 30, top: 40 },
              }" style="height: 260px" autoresize />
            </NCard>

            <!-- Adaptive grades table -->
            <NCard size="small" style="margin-bottom: 12px">
              <template #header>
                <NSpace align="center" :size="8">
                  <span>自適應等級排名</span>
                  <NTag size="small" type="success">Top 20% = Diamond</NTag>
                  <NTag size="small" type="warning">20-50% = Gold</NTag>
                  <NTag size="small" type="info">50-80% = Silver</NTag>
                  <NTag size="small">Bottom 20% = Noise</NTag>
                </NSpace>
              </template>
              <NDataTable
                :columns="[
                  { title: '排名', key: 'rank', width: 60, sorter: (a: any, b: any) => a.rank - b.rank },
                  { title: '代碼', key: 'code', width: 80 },
                  { title: 'SQS', key: 'sqs', width: 70, sorter: (a: any, b: any) => a.sqs - b.sqs },
                  { title: '百分位', key: 'percentile_rank', width: 80 },
                  { title: '自適應等級', key: 'adaptive_grade', width: 100 },
                  { title: '固定等級', key: 'fixed_grade', width: 100 },
                ]"
                :data="Object.entries(sqsDistData.adaptive_grades || {}).map(([code, v]: [string, any]) => ({ code, ...v }))"
                :pagination="{ pageSize: 20 }"
                size="small"
                :bordered="false"
                :single-line="false"
              />
            </NCard>
          </template>
          <div v-else-if="sqsDistData && sqsDistData.count === 0" style="padding: 40px; text-align: center; color: #999">
            {{ sqsDistData.error || '尚無 BUY 信號數據。請先執行 Worker 產生 Alpha Hunter 數據。' }}
          </div>
        </NSpin>
      </template>
    </NSpin>
  </div>
</template>
