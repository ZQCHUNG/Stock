<script setup lang="ts">
import { ref } from 'vue'
import { NCard, NButton, NSpin, NDataTable, NSpace, NTag, NAlert, NGrid, NGi, NInputNumber } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import VChart from 'vue-echarts'
import { backtestApi } from '../api/backtest'
import { fmtPct } from '../utils/format'

const loading = ref(false)
const result = ref<any>(null)
const error = ref('')
const periodDays = ref(730)

async function runBacktest() {
  loading.value = true
  error.value = ''
  result.value = null
  try {
    result.value = await backtestApi.sqsBacktest(undefined, periodDays.value)
  } catch (e: any) {
    error.value = e?.message || 'SQS backtest failed'
  } finally {
    loading.value = false
  }
}

// Comparison table columns
const compColumns: DataTableColumns = [
  { title: '篩選條件', key: 'label', width: 120 },
  { title: '信號數', key: 'count', width: 80 },
  { title: '通過率', key: 'pass_rate', width: 80, render: (r: any) => r.pass_rate != null ? `${(r.pass_rate * 100).toFixed(0)}%` : '-' },
  { title: '勝率 (5d)', key: 'win_rate_5d', width: 90, render: (r: any) => fmtPct(r.win_rate_5d) },
  { title: '勝率 (20d)', key: 'win_rate_20d', width: 90, render: (r: any) => fmtPct(r.win_rate_20d) },
  { title: '平均報酬 (5d)', key: 'avg_return_5d', width: 110, render: (r: any) => fmtPct(r.avg_return_5d) },
  { title: '平均報酬 (20d)', key: 'avg_return_20d', width: 110, render: (r: any) => fmtPct(r.avg_return_20d) },
  { title: 'Net 報酬 (5d)', key: 'net_return_5d', width: 110, render: (r: any) => fmtPct(r.net_return_5d) },
  { title: 'Net 報酬 (20d)', key: 'net_return_20d', width: 110, render: (r: any) => fmtPct(r.net_return_20d) },
  { title: '損益比 (5d)', key: 'profit_factor_5d', width: 90, render: (r: any) => r.profit_factor_5d != null ? r.profit_factor_5d.toFixed(2) : '-' },
  { title: '提升勝率', key: 'lift_win_rate_5d', width: 90,
    render: (r: any) => {
      if (r.lift_win_rate_5d == null) return '-'
      const v = r.lift_win_rate_5d
      return `${v > 0 ? '+' : ''}${(v * 100).toFixed(1)}%`
    }
  },
]

function compTableData() {
  if (!result.value) return []
  const rows: any[] = [{ label: '全部信號 (Baseline)', ...result.value.baseline, pass_rate: 1.0 }]
  for (const [, val] of Object.entries(result.value.thresholds || {})) {
    const v = val as any
    rows.push({ label: `SQS ≥ ${v.threshold}`, ...v })
  }
  return rows
}

// Histogram chart
function histogramOption() {
  if (!result.value?.distribution?.histogram) return {}
  const hist = result.value.distribution.histogram
  return {
    title: { text: 'SQS 分數分佈', left: 'center', textStyle: { fontSize: 14 } },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: hist.map((h: any) => h.range), name: 'SQS' },
    yAxis: { type: 'value', name: '信號數' },
    series: [{
      type: 'bar',
      data: hist.map((h: any) => h.count),
      itemStyle: {
        color: (params: any) => {
          const idx = params.dataIndex
          if (idx >= 8) return '#18a058'  // 80-100
          if (idx >= 6) return '#2080f0'  // 60-80
          if (idx >= 4) return '#f0a020'  // 40-60
          return '#999'  // <40
        },
      },
    }],
    grid: { left: 50, right: 20, bottom: 30, top: 40 },
  }
}

// Win rate comparison bar chart
function winRateCompOption() {
  if (!result.value) return {}
  const labels = ['全部']
  const wr5: number[] = [result.value.baseline?.win_rate_5d ?? 0]
  const wr20: number[] = [result.value.baseline?.win_rate_20d ?? 0]
  for (const [_key, val] of Object.entries(result.value.thresholds || {})) {
    const v = val as any
    labels.push(`SQS≥${v.threshold}`)
    wr5.push(v.win_rate_5d ?? 0)
    wr20.push(v.win_rate_20d ?? 0)
  }
  return {
    title: { text: '勝率比較', left: 'center', textStyle: { fontSize: 14 } },
    tooltip: { trigger: 'axis', valueFormatter: (v: number) => `${(v * 100).toFixed(1)}%` },
    legend: { bottom: 0, data: ['5日勝率', '20日勝率'] },
    xAxis: { type: 'category', data: labels },
    yAxis: { type: 'value', axisLabel: { formatter: (v: number) => `${(v * 100).toFixed(0)}%` }, max: 1 },
    series: [
      { name: '5日勝率', type: 'bar', data: wr5, itemStyle: { color: '#2080f0' } },
      { name: '20日勝率', type: 'bar', data: wr20, itemStyle: { color: '#18a058' } },
    ],
    grid: { left: 60, right: 20, bottom: 40, top: 40 },
  }
}

// Net return comparison bar chart
function netReturnCompOption() {
  if (!result.value) return {}
  const labels = ['全部']
  const nr5: number[] = [result.value.baseline?.net_return_5d ?? 0]
  const nr20: number[] = [result.value.baseline?.net_return_20d ?? 0]
  for (const [_key, val] of Object.entries(result.value.thresholds || {})) {
    const v = val as any
    labels.push(`SQS≥${v.threshold}`)
    nr5.push(v.net_return_5d ?? 0)
    nr20.push(v.net_return_20d ?? 0)
  }
  return {
    title: { text: 'Net 平均報酬比較', left: 'center', textStyle: { fontSize: 14 } },
    tooltip: { trigger: 'axis', valueFormatter: (v: number) => `${(v * 100).toFixed(2)}%` },
    legend: { bottom: 0, data: ['Net 5日', 'Net 20日'] },
    xAxis: { type: 'category', data: labels },
    yAxis: { type: 'value', axisLabel: { formatter: (v: number) => `${(v * 100).toFixed(1)}%` } },
    series: [
      { name: 'Net 5日', type: 'bar', data: nr5, itemStyle: { color: '#2080f0' } },
      { name: 'Net 20日', type: 'bar', data: nr20, itemStyle: { color: '#18a058' } },
    ],
    grid: { left: 60, right: 20, bottom: 40, top: 40 },
  }
}
</script>

<template>
  <div>
    <NSpace style="margin-bottom: 16px" align="center">
      <NInputNumber v-model:value="periodDays" :min="365" :max="1825" :step="365" size="small" style="width: 120px">
        <template #prefix>期間</template>
        <template #suffix>天</template>
      </NInputNumber>
      <NButton type="primary" @click="runBacktest" :loading="loading">
        執行 SQS 有效性驗證
      </NButton>
      <span style="font-size: 12px; color: #999">掃描 108 檔股票歷史 V4 信號，比較不同 SQS 閾值績效</span>
    </NSpace>

    <NAlert v-if="error" type="error" style="margin-bottom: 16px">{{ error }}</NAlert>

    <NSpin :show="loading">
      <template v-if="result">
        <!-- Summary -->
        <NSpace style="margin-bottom: 12px" :size="12">
          <NTag type="info" size="small">信號總數: {{ result.total_signals }}</NTag>
          <NTag type="info" size="small">股票數: {{ result.stock_count }}</NTag>
          <NTag size="small">{{ result.date_range?.start }} ~ {{ result.date_range?.end }}</NTag>
          <NTag size="small">交易成本: {{ (result.transaction_cost * 100).toFixed(2) }}%</NTag>
        </NSpace>

        <!-- Distribution stats -->
        <NCard size="small" style="margin-bottom: 12px">
          <template #header>SQS 分數統計</template>
          <NSpace :size="16">
            <span>最小: <b>{{ result.distribution?.min }}</b></span>
            <span>P25: <b>{{ result.distribution?.p25 }}</b></span>
            <span>中位數: <b>{{ result.distribution?.median }}</b></span>
            <span>平均: <b>{{ result.distribution?.mean }}</b></span>
            <span>P75: <b>{{ result.distribution?.p75 }}</b></span>
            <span>最大: <b>{{ result.distribution?.max }}</b></span>
          </NSpace>
          <NSpace style="margin-top: 8px" :size="12">
            <NTag v-for="(count, grade) in result.grade_counts" :key="grade" size="small"
              :type="grade === 'diamond' ? 'success' : grade === 'gold' ? 'warning' : grade === 'silver' ? 'info' : 'default'">
              {{ grade === 'diamond' ? '💎' : grade === 'gold' ? '🥇' : grade === 'silver' ? '🥈' : '⚪' }}
              {{ grade }}: {{ count }}
            </NTag>
          </NSpace>
        </NCard>

        <!-- Comparison Table (main result) -->
        <NCard size="small" style="margin-bottom: 12px">
          <template #header>SQS 閾值績效比較</template>
          <NDataTable
            :columns="compColumns"
            :data="compTableData()"
            size="small"
            :bordered="false"
            :single-line="false"
            :scroll-x="1100"
          />
        </NCard>

        <!-- Charts -->
        <NGrid :cols="2" :x-gap="12" style="margin-bottom: 12px">
          <NGi>
            <NCard size="small">
              <VChart :option="histogramOption()" style="height: 280px" autoresize />
            </NCard>
          </NGi>
          <NGi>
            <NCard size="small">
              <VChart :option="winRateCompOption()" style="height: 280px" autoresize />
            </NCard>
          </NGi>
        </NGrid>
        <NCard size="small" style="margin-bottom: 12px">
          <VChart :option="netReturnCompOption()" style="height: 280px" autoresize />
        </NCard>

        <!-- Regime breakdown -->
        <NCard v-if="result.regime_breakdown && Object.keys(result.regime_breakdown).length" size="small" style="margin-bottom: 12px">
          <template #header>市場環境分解</template>
          <NGrid :cols="3" :x-gap="12">
            <NGi v-for="(metrics, regime) in result.regime_breakdown" :key="regime">
              <NCard size="small" :title="regime === 'bull' ? '🐂 多頭' : regime === 'bear' ? '🐻 空頭' : '↔ 盤整'">
                <div style="font-size: 12px">
                  <div>信號數: <b>{{ metrics.count }}</b></div>
                  <div>5日勝率: <b>{{ fmtPct(metrics.win_rate_5d) }}</b></div>
                  <div>20日勝率: <b>{{ fmtPct(metrics.win_rate_20d) }}</b></div>
                  <div>Avg 5d: <b>{{ fmtPct(metrics.avg_return_5d) }}</b></div>
                  <div>Net 20d: <b>{{ fmtPct(metrics.net_return_20d) }}</b></div>
                </div>
              </NCard>
            </NGi>
          </NGrid>
        </NCard>

        <NAlert type="info">
          <template #header>驗證方法說明</template>
          使用簡化 SQS（Fitness 30% + Regime 25% + Maturity 10%，EV 和 Heat 維度使用中性值），
          對歷史 V4 信號計算 SQS 分數，比較不同閾值下的 5 日 / 20 日實際報酬。
          「Net 報酬」已扣除來回交易成本 {{ (result.transaction_cost * 100).toFixed(2) }}%。
        </NAlert>
      </template>
    </NSpin>
  </div>
</template>
