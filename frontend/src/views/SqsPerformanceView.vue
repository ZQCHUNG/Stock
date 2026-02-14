<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import {
  NCard, NButton, NSpace, NTag, NDataTable, NGrid, NGi, NSpin,
  NStatistic, NAlert, NDatePicker, NDivider, NEmpty,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import VChart from 'vue-echarts'
import { sqsPerformanceApi } from '../api/sqs-performance'

const isLoading = ref(false)
const isUpdating = ref(false)
const isBackfilling = ref(false)
const summary = ref<any>(null)
const signals = ref<any[]>([])
const error = ref('')
const dateRange = ref<[number, number] | null>(null)
const sourceFilter = ref<string | null>(null)  // null=all, 'live', 'backtest'

async function loadSummary() {
  isLoading.value = true
  error.value = ''
  try {
    const params: any = {}
    if (dateRange.value) {
      params.date_from = new Date(dateRange.value[0]).toISOString().slice(0, 10)
      params.date_to = new Date(dateRange.value[1]).toISOString().slice(0, 10)
    }
    if (sourceFilter.value) params.source = sourceFilter.value
    summary.value = await sqsPerformanceApi.getSummary(params)
  } catch (e: any) {
    error.value = e?.message || 'Failed to load'
  }
  isLoading.value = false
}

async function loadSignals() {
  try {
    const params: any = { limit: 200 }
    if (sourceFilter.value) params.source = sourceFilter.value
    const result = await sqsPerformanceApi.getSignals(params)
    signals.value = result.signals || []
  } catch { /* ignore */ }
}

async function updateReturns() {
  isUpdating.value = true
  try {
    await sqsPerformanceApi.updateReturns(50)
    await loadSummary()
    await loadSignals()
  } catch (e: any) {
    error.value = e?.message || 'Update failed'
  }
  isUpdating.value = false
}

async function runBackfill() {
  isBackfilling.value = true
  error.value = ''
  try {
    const result = await sqsPerformanceApi.backfill(730)
    await Promise.all([loadSummary(), loadSignals()])
    error.value = ''
  } catch (e: any) {
    error.value = e?.message || 'Backfill failed'
  }
  isBackfilling.value = false
}

function setSource(s: string | null) {
  sourceFilter.value = s
  loadSummary()
  loadSignals()
}

onMounted(async () => {
  await Promise.all([loadSummary(), loadSignals()])
})

// ---- Charts ----

const gradeColors: Record<string, string> = {
  diamond: '#b388ff',
  gold: '#ffd54f',
  silver: '#bdbdbd',
  noise: '#ef5350',
}

const winRateChartOption = computed(() => {
  const bg = summary.value?.by_grade
  if (!bg) return null
  const grades = ['diamond', 'gold', 'silver', 'noise']
  const labels = ['Diamond', 'Gold', 'Silver', 'Noise']

  const periods = ['d1', 'd3', 'd5', 'd10', 'd20']
  const series = periods.map(p => ({
    name: p,
    type: 'bar' as const,
    data: grades.map(g => {
      const val = bg[g]?.[p]?.win_rate
      return val != null ? +(val * 100).toFixed(1) : 0
    }),
  }))

  return {
    tooltip: { trigger: 'axis' },
    legend: { data: periods },
    xAxis: { type: 'category', data: labels },
    yAxis: { type: 'value', name: '勝率 (%)', max: 100 },
    series,
  }
})

const avgReturnChartOption = computed(() => {
  const bg = summary.value?.by_grade
  if (!bg) return null
  const grades = ['diamond', 'gold', 'silver', 'noise']
  const labels = ['Diamond', 'Gold', 'Silver', 'Noise']

  const periods = ['d1', 'd3', 'd5', 'd10', 'd20']
  const series = periods.map(p => ({
    name: p,
    type: 'bar' as const,
    data: grades.map(g => {
      const val = bg[g]?.[p]?.net_return
      return val != null ? +(val * 100).toFixed(2) : 0
    }),
  }))

  return {
    tooltip: { trigger: 'axis', valueFormatter: (v: number) => v.toFixed(2) + '%' },
    legend: { data: periods },
    xAxis: { type: 'category', data: labels },
    yAxis: { type: 'value', name: '淨報酬 (%)', axisLabel: { formatter: '{value}%' } },
    series,
  }
})

const cumulativeChartOption = computed(() => {
  const curve = summary.value?.cumulative_d5
  if (!curve?.length) return null

  return {
    tooltip: {
      trigger: 'axis',
      formatter: (params: any) => {
        const p = params[0]
        const d = curve[p.dataIndex]
        return `${d.date}<br/>${d.code} SQS:${d.sqs}<br/>本次: ${(d.net_return * 100).toFixed(2)}%<br/>累積: ${(d.cumulative * 100).toFixed(2)}%`
      },
    },
    xAxis: {
      type: 'category',
      data: curve.map((d: any) => d.date),
      axisLabel: { rotate: 45 },
    },
    yAxis: {
      type: 'value',
      name: '累積淨報酬 (%)',
      axisLabel: { formatter: (v: number) => (v * 100).toFixed(1) + '%' },
    },
    series: [{
      type: 'line',
      data: curve.map((d: any) => d.cumulative),
      areaStyle: { opacity: 0.15 },
      lineStyle: { width: 2 },
      itemStyle: {
        color: (p: any) => gradeColors[curve[p.dataIndex]?.grade] || '#999',
      },
    }],
  }
})

// ---- Signal Table ----
const signalColumns: DataTableColumns = [
  { title: '日期', key: 'trigger_date', width: 100 },
  { title: '代碼', key: 'code', width: 70 },
  { title: '名稱', key: 'name', width: 90 },
  { title: 'SQS', key: 'sqs', width: 60, sorter: (a: any, b: any) => a.sqs - b.sqs },
  { title: '等級', key: 'grade', width: 80 },
  { title: '來源', key: 'source', width: 60, render: (r: any) => r.source === 'backtest' ? 'BT' : 'Live' },
  {
    title: 'd1', key: 'r_d1', width: 70,
    render: (r: any) => fmtReturn(r.returns?.d1),
  },
  {
    title: 'd3', key: 'r_d3', width: 70,
    render: (r: any) => fmtReturn(r.returns?.d3),
  },
  {
    title: 'd5', key: 'r_d5', width: 70,
    render: (r: any) => fmtReturn(r.returns?.d5),
  },
  {
    title: 'd10', key: 'r_d10', width: 70,
    render: (r: any) => fmtReturn(r.returns?.d10),
  },
  {
    title: 'd20', key: 'r_d20', width: 70,
    render: (r: any) => fmtReturn(r.returns?.d20),
  },
]

function fmtReturn(val: number | undefined): string {
  if (val == null) return '-'
  const pct = (val * 100).toFixed(2)
  return val >= 0 ? `+${pct}%` : `${pct}%`
}
</script>

<template>
  <div>
    <h2 style="margin: 0 0 16px">SQS 績效追蹤</h2>

    <NAlert v-if="error" type="error" style="margin-bottom: 12px" closable @close="error = ''">
      {{ error }}
    </NAlert>

    <!-- Controls -->
    <NCard size="small" style="margin-bottom: 12px">
      <NSpace align="center" :wrap="true">
        <NDatePicker v-model:value="dateRange" type="daterange" clearable size="small" />
        <NButton type="primary" size="small" @click="loadSummary" :loading="isLoading">查詢</NButton>
        <NButton size="small" @click="updateReturns" :loading="isUpdating">更新前向報酬</NButton>
        <NDivider vertical />
        <NButton size="tiny" :type="!sourceFilter ? 'primary' : 'default'" @click="setSource(null)">全部</NButton>
        <NButton size="tiny" :type="sourceFilter === 'live' ? 'primary' : 'default'" @click="setSource('live')">實盤</NButton>
        <NButton size="tiny" :type="sourceFilter === 'backtest' ? 'primary' : 'default'" @click="setSource('backtest')">回測</NButton>
        <NDivider vertical />
        <NButton size="small" @click="runBackfill" :loading="isBackfilling" type="warning">歷史回測預填</NButton>
        <NButton size="small" tag="a" :href="'/api/system/export/signals/csv' + (sourceFilter ? '?source=' + sourceFilter : '')" target="_blank">匯出 CSV</NButton>
        <NTag v-if="summary?.total" size="small">{{ summary.total }} 筆信號</NTag>
      </NSpace>
    </NCard>

    <NSpin :show="isLoading">
      <template v-if="summary && summary.total > 0">
        <!-- Overall Stats -->
        <NGrid :cols="5" :x-gap="12" :y-gap="12" style="margin-bottom: 16px">
          <NGi>
            <NCard size="small">
              <NStatistic label="總信號數" :value="summary.total" />
            </NCard>
          </NGi>
          <NGi>
            <NCard size="small">
              <NStatistic label="SQS 均值" :value="summary.sqs_stats?.mean?.toFixed(1) || '-'" />
            </NCard>
          </NGi>
          <NGi>
            <NCard size="small">
              <NStatistic
                label="d5 勝率"
                :value="summary.overall?.d5?.win_rate != null ? (summary.overall.d5.win_rate * 100).toFixed(1) + '%' : '-'"
              />
            </NCard>
          </NGi>
          <NGi>
            <NCard size="small">
              <NStatistic
                label="d5 淨報酬"
                :value="summary.overall?.d5?.net_return != null ? (summary.overall.d5.net_return * 100).toFixed(2) + '%' : '-'"
              />
            </NCard>
          </NGi>
          <NGi>
            <NCard size="small">
              <NStatistic
                label="d20 淨報酬"
                :value="summary.overall?.d20?.net_return != null ? (summary.overall.d20.net_return * 100).toFixed(2) + '%' : '-'"
              />
            </NCard>
          </NGi>
        </NGrid>

        <!-- Charts -->
        <NGrid :cols="2" :x-gap="16" :y-gap="16">
          <NGi>
            <NCard title="各等級勝率" size="small">
              <VChart v-if="winRateChartOption" :option="winRateChartOption" style="height: 300px" autoresize />
              <NEmpty v-else description="資料不足" />
            </NCard>
          </NGi>
          <NGi>
            <NCard title="各等級淨報酬" size="small">
              <VChart v-if="avgReturnChartOption" :option="avgReturnChartOption" style="height: 300px" autoresize />
              <NEmpty v-else description="資料不足" />
            </NCard>
          </NGi>
        </NGrid>

        <!-- Cumulative Curve -->
        <NCard title="累積淨報酬曲線 (d5)" size="small" style="margin-top: 16px">
          <VChart v-if="cumulativeChartOption" :option="cumulativeChartOption" style="height: 300px" autoresize />
          <NEmpty v-else description="尚無前向報酬資料" />
        </NCard>

        <NDivider />

        <!-- Grade Breakdown Table -->
        <NCard title="等級績效明細" size="small">
          <table style="width: 100%; border-collapse: collapse; font-size: 13px">
            <thead>
              <tr style="border-bottom: 2px solid #e0e0e0; text-align: right">
                <th style="text-align: left; padding: 6px">等級</th>
                <th style="padding: 6px">信號數</th>
                <th style="padding: 6px">d5 勝率</th>
                <th style="padding: 6px">d5 淨報酬</th>
                <th style="padding: 6px">d10 勝率</th>
                <th style="padding: 6px">d10 淨報酬</th>
                <th style="padding: 6px">d20 勝率</th>
                <th style="padding: 6px">d20 淨報酬</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="grade in ['diamond', 'gold', 'silver', 'noise']" :key="grade"
                  style="border-bottom: 1px solid #eee; text-align: right"
                  v-if="summary.by_grade?.[grade]">
                <td style="text-align: left; padding: 6px">
                  <NTag :type="grade === 'diamond' ? 'success' : grade === 'gold' ? 'warning' : grade === 'noise' ? 'error' : 'default'" size="small">
                    {{ grade }}
                  </NTag>
                  <span style="margin-left: 4px; font-size: 12px; color: #999">
                    ({{ summary.by_grade[grade].count }})
                  </span>
                </td>
                <td style="padding: 6px">{{ summary.by_grade[grade].count }}</td>
                <td style="padding: 6px">{{ summary.by_grade[grade].d5?.win_rate != null ? (summary.by_grade[grade].d5.win_rate * 100).toFixed(1) + '%' : '-' }}</td>
                <td style="padding: 6px" :style="{ color: (summary.by_grade[grade].d5?.net_return ?? 0) >= 0 ? '#4caf50' : '#f44336' }">
                  {{ summary.by_grade[grade].d5?.net_return != null ? (summary.by_grade[grade].d5.net_return * 100).toFixed(2) + '%' : '-' }}
                </td>
                <td style="padding: 6px">{{ summary.by_grade[grade].d10?.win_rate != null ? (summary.by_grade[grade].d10.win_rate * 100).toFixed(1) + '%' : '-' }}</td>
                <td style="padding: 6px" :style="{ color: (summary.by_grade[grade].d10?.net_return ?? 0) >= 0 ? '#4caf50' : '#f44336' }">
                  {{ summary.by_grade[grade].d10?.net_return != null ? (summary.by_grade[grade].d10.net_return * 100).toFixed(2) + '%' : '-' }}
                </td>
                <td style="padding: 6px">{{ summary.by_grade[grade].d20?.win_rate != null ? (summary.by_grade[grade].d20.win_rate * 100).toFixed(1) + '%' : '-' }}</td>
                <td style="padding: 6px" :style="{ color: (summary.by_grade[grade].d20?.net_return ?? 0) >= 0 ? '#4caf50' : '#f44336' }">
                  {{ summary.by_grade[grade].d20?.net_return != null ? (summary.by_grade[grade].d20.net_return * 100).toFixed(2) + '%' : '-' }}
                </td>
              </tr>
            </tbody>
          </table>
        </NCard>
      </template>
      <NEmpty v-else-if="!isLoading" description="尚無績效數據。系統會在警報觸發時自動記錄信號。" />
    </NSpin>

    <!-- Signal List -->
    <NCard title="追蹤信號列表" size="small" style="margin-top: 16px">
      <NDataTable
        v-if="signals.length"
        :columns="signalColumns"
        :data="signals"
        :pagination="{ pageSize: 20 }"
        size="small"
        :bordered="false"
        :single-line="false"
        :scroll-x="800"
      />
      <NEmpty v-else description="尚無追蹤信號" />
    </NCard>
  </div>
</template>
