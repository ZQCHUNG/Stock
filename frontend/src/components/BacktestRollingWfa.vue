<script setup lang="ts">
import { h, ref, computed } from 'vue'
import {
  NCard, NButton, NSpace, NDataTable, NSpin, NStatistic,
  NGrid, NGi, NTag, NAlert, useMessage,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { backtestApi } from '../api/backtest'
import ChartContainer from './ChartContainer.vue'

const msg = useMessage()
const loading = ref(false)
const wfaResult = ref<any>(null)

async function runWfa() {
  loading.value = true
  try {
    const resp = await backtestApi.rollingWfa(3, 0.28, true)
    wfaResult.value = resp
    msg.success(`Rolling WFA complete: ${resp.windows?.length || 0} windows`)
  } catch (e: any) {
    msg.error(`Rolling WFA failed: ${e?.message || e}`)
  }
  loading.value = false
}

function fmtPct(v: number | null | undefined) {
  if (v == null) return '-'
  return `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`
}

function retColor(v: number) {
  if (v > 0) return '#18a058'
  if (v < -5) return '#d03050'
  return '#f0a020'
}

function calmarColor(v: number) {
  if (v >= 3) return '#18a058'
  if (v >= 1) return '#f0a020'
  return '#d03050'
}

function expColor(v: number) {
  if (v > 0.5) return '#18a058'
  if (v > 0) return '#f0a020'
  return '#d03050'
}

const windowColumns: DataTableColumns = [
  { title: 'Window', key: 'window', width: 70 },
  { title: 'Start', key: 'start', width: 90 },
  { title: 'End', key: 'end', width: 90 },
  {
    title: 'Net Return',
    key: 'net_return',
    width: 90,
    sorter: (a: any, b: any) => a.net_return - b.net_return,
    render: (row: any) => h('span', { style: `font-weight: 700; color: ${retColor(row.net_return)}` }, fmtPct(row.net_return)),
  },
  {
    title: 'MaxDD',
    key: 'max_drawdown',
    width: 80,
    render: (row: any) => h('span', { style: 'color: #d03050' }, fmtPct(row.max_drawdown)),
  },
  {
    title: 'Calmar',
    key: 'calmar',
    width: 70,
    sorter: (a: any, b: any) => a.calmar - b.calmar,
    render: (row: any) => h('span', { style: `font-weight: 700; color: ${calmarColor(row.calmar)}` }, row.calmar?.toFixed(2) || '-'),
  },
  {
    title: 'Sharpe',
    key: 'sharpe',
    width: 70,
    render: (row: any) => h('span', {}, row.sharpe?.toFixed(2) || '-'),
  },
  {
    title: 'WR%',
    key: 'win_rate',
    width: 60,
    render: (row: any) => h('span', {}, row.win_rate != null ? `${row.win_rate.toFixed(1)}%` : '-'),
  },
  {
    title: 'Trades',
    key: 'trades',
    width: 60,
  },
  {
    title: 'PF',
    key: 'profit_factor',
    width: 60,
    render: (row: any) => h('span', {}, row.profit_factor?.toFixed(2) || '-'),
  },
  {
    title: 'Expectancy',
    key: 'expectancy',
    width: 90,
    sorter: (a: any, b: any) => a.expectancy - b.expectancy,
    render: (row: any) => h('span', { style: `font-weight: 700; color: ${expColor(row.expectancy)}` }, row.expectancy?.toFixed(3) || '-'),
  },
]

// Chart: Return per window bar chart
const returnBarOption = computed(() => {
  if (!wfaResult.value?.windows?.length) return {}
  const wins = wfaResult.value.windows
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['Net Return', 'Expectancy'], top: 0 },
    grid: { left: 50, right: 20, top: 40, bottom: 30 },
    xAxis: { type: 'category', data: wins.map((w: any) => w.window) },
    yAxis: [
      { type: 'value', name: 'Return %', position: 'left' },
      { type: 'value', name: 'Expectancy', position: 'right' },
    ],
    series: [
      {
        name: 'Net Return',
        type: 'bar',
        data: wins.map((w: any) => w.net_return),
        itemStyle: {
          color: (params: any) => params.data >= 0 ? '#18a058' : '#d03050',
        },
      },
      {
        name: 'Expectancy',
        type: 'line',
        yAxisIndex: 1,
        data: wins.map((w: any) => w.expectancy),
        symbol: 'circle',
        symbolSize: 8,
        lineStyle: { width: 2, color: '#2080f0' },
        itemStyle: { color: '#2080f0' },
      },
    ],
  }
})

// Calmar trend chart
const calmarLineOption = computed(() => {
  if (!wfaResult.value?.windows?.length) return {}
  const wins = wfaResult.value.windows
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['Calmar', 'Sharpe'], top: 0 },
    grid: { left: 50, right: 50, top: 40, bottom: 30 },
    xAxis: { type: 'category', data: wins.map((w: any) => w.window) },
    yAxis: { type: 'value', name: 'Ratio' },
    series: [
      {
        name: 'Calmar',
        type: 'line',
        data: wins.map((w: any) => w.calmar),
        symbol: 'circle',
        symbolSize: 8,
        lineStyle: { width: 2.5, color: '#e88080' },
        itemStyle: { color: '#e88080' },
        areaStyle: { opacity: 0.1, color: '#e88080' },
      },
      {
        name: 'Sharpe',
        type: 'line',
        data: wins.map((w: any) => w.sharpe),
        symbol: 'diamond',
        symbolSize: 8,
        lineStyle: { width: 2, color: '#2080f0', type: 'dashed' },
        itemStyle: { color: '#2080f0' },
      },
    ],
  }
})

const efficiencyLabel = computed(() => {
  if (!wfaResult.value) return '-'
  const r = wfaResult.value.efficiency_ratio
  if (r == null) return '-'
  return r.toFixed(3)
})
const efficiencyColor = computed(() => {
  if (!wfaResult.value) return '#999'
  const r = wfaResult.value.efficiency_ratio
  if (r >= 0.8) return '#18a058'
  if (r >= 0.5) return '#f0a020'
  return '#d03050'
})
</script>

<template>
  <div>
    <NCard size="small" style="margin-bottom: 12px">
      <NSpace align="center">
        <NButton type="primary" :loading="loading" @click="runWfa">
          Run Rolling WFA (3-Month Windows)
        </NButton>
        <span style="font-size: 12px; color: #999">
          Phase 10A: 108 stocks, 2.8折 + Kyle Lambda, Jan 2025 onwards
        </span>
      </NSpace>
    </NCard>

    <NSpin :show="loading">
      <template v-if="wfaResult">
        <!-- Stats -->
        <NGrid :cols="5" :x-gap="12" style="margin-bottom: 12px">
          <NGi>
            <NCard size="small">
              <NStatistic label="Full Period Net Return">
                <span :style="{ color: retColor(wfaResult.full_period?.net_return || 0) }">
                  {{ fmtPct(wfaResult.full_period?.net_return) }}
                </span>
              </NStatistic>
            </NCard>
          </NGi>
          <NGi>
            <NCard size="small">
              <NStatistic label="Full Period Calmar">
                <span :style="{ color: calmarColor(wfaResult.full_period?.calmar || 0) }">
                  {{ wfaResult.full_period?.calmar?.toFixed(2) || '-' }}
                </span>
              </NStatistic>
            </NCard>
          </NGi>
          <NGi>
            <NCard size="small">
              <NStatistic label="Efficiency Ratio">
                <span :style="{ color: efficiencyColor }">
                  {{ efficiencyLabel }}
                </span>
              </NStatistic>
            </NCard>
          </NGi>
          <NGi>
            <NCard size="small">
              <NStatistic label="Windows" :value="wfaResult.windows?.length || 0" />
            </NCard>
          </NGi>
          <NGi>
            <NCard size="small">
              <NStatistic label="Total Trades" :value="wfaResult.full_period?.trades || 0" />
            </NCard>
          </NGi>
        </NGrid>

        <!-- Alert if efficiency is low -->
        <NAlert v-if="wfaResult.efficiency_ratio < 0.5" type="warning" style="margin-bottom: 12px">
          Efficiency Ratio {{ wfaResult.efficiency_ratio?.toFixed(3) }} &lt; 0.50 — later windows
          are significantly worse than earlier ones. Possible regime change or overfitting.
        </NAlert>

        <!-- Return Bar + Expectancy Line -->
        <NCard size="small" title="Net Return & Expectancy per Window" style="margin-bottom: 12px">
          <ChartContainer :option="returnBarOption" height="300px" />
        </NCard>

        <!-- Calmar Trend -->
        <NCard size="small" title="Calmar & Sharpe Trend" style="margin-bottom: 12px">
          <ChartContainer :option="calmarLineOption" height="250px" />
        </NCard>

        <!-- Window Detail Table -->
        <NCard size="small" title="Window Details">
          <NDataTable
            :columns="windowColumns"
            :data="wfaResult.windows || []"
            size="small"
            :bordered="true"
            :single-line="false"
            :scroll-x="900"
          />
        </NCard>

        <div style="font-size: 11px; color: #999; margin-top: 8px">
          Cost: {{ wfaResult.cost_settings }} | Stocks: {{ wfaResult.stocks_loaded }}
        </div>
      </template>
    </NSpin>
  </div>
</template>
