<script setup lang="ts">
import { h, ref, computed, watch } from 'vue'
import {
  NCard, NButton, NSpace, NDataTable, NSpin, NStatistic, NTag,
  NGrid, NGi, NAlert, NSelect, NText, useMessage,
} from 'naive-ui'
import type { DataTableColumns, SelectOption } from 'naive-ui'
import { backtestApi } from '../api/backtest'
import ChartContainer from './ChartContainer.vue'

const msg = useMessage()
const loading = ref(false)
const attrResult = ref<any>(null)
const selectedWindow = ref<string>('W1')

async function runAttribution() {
  loading.value = true
  try {
    const resp = await backtestApi.attributionAnalysis(3, 0.28, true)
    attrResult.value = resp
    msg.success(`Attribution Analysis complete: ${resp.windows?.length || 0} windows`)
  } catch (e: any) {
    msg.error(`Attribution Analysis failed: ${e?.message || e}`)
  }
  loading.value = false
}

// Window selector options
const windowOptions = computed<SelectOption[]>(() => {
  if (!attrResult.value?.windows?.length) return []
  return attrResult.value.windows.map((w: any) => ({
    label: `${w.window} (${w.start} ~ ${w.end}) — ${w.summary.net_return >= 0 ? '+' : ''}${w.summary.net_return.toFixed(2)}%`,
    value: w.window,
  }))
})

const currentWindow = computed(() => {
  if (!attrResult.value?.windows?.length) return null
  return attrResult.value.windows.find((w: any) => w.window === selectedWindow.value) || attrResult.value.windows[0]
})

// Formatting helpers
function fmtPct(v: number | null | undefined) {
  if (v == null) return '-'
  return `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`
}

function retColor(v: number) {
  if (v > 0) return '#18a058'
  if (v < -5) return '#d03050'
  return '#f0a020'
}

// Trade detail table columns
const tradeColumns: DataTableColumns = [
  { title: 'Code', key: 'code', width: 60 },
  {
    title: 'Sector', key: 'sector', width: 90,
    render: (row: any) => h(NTag, { size: 'tiny', bordered: false }, { default: () => row.sector }),
  },
  {
    title: 'Entry', key: 'entry_type', width: 100,
    render: (row: any) => {
      const label = row.entry_type === 'momentum_breakout' ? 'Breakout' : row.entry_type === 'oversold_bounce' ? 'Bounce' : row.entry_type
      return h(NTag, { size: 'tiny', type: row.entry_type === 'momentum_breakout' ? 'info' : 'warning' }, { default: () => label })
    },
  },
  { title: 'Open', key: 'date_open', width: 95 },
  { title: 'Close', key: 'date_close', width: 95 },
  { title: 'Days', key: 'held_days', width: 50, sorter: (a: any, b: any) => a.held_days - b.held_days },
  {
    title: 'Return', key: 'return_pct', width: 75,
    sorter: (a: any, b: any) => a.return_pct - b.return_pct,
    render: (row: any) => h('span', { style: `font-weight: 700; color: ${retColor(row.return_pct)}` }, fmtPct(row.return_pct)),
  },
  {
    title: 'Exit Reason', key: 'exit_reason', width: 150,
    render: (row: any) => {
      const r = row.exit_reason
      const color = r.includes('disaster') ? '#d03050' : r.includes('trail') || r.includes('parabolic') ? '#18a058' : r.startsWith('pts_') ? '#f0a020' : '#999'
      return h('span', { style: `font-size: 11px; color: ${color}` }, r)
    },
  },
  {
    title: 'RS', key: 'rs_rating', width: 55,
    render: (row: any) => h('span', { style: `color: ${row.rs_rating >= 80 ? '#18a058' : row.rs_rating >= 60 ? '#f0a020' : '#d03050'}` }, row.rs_rating.toFixed(0)),
  },
  {
    title: 'SQS', key: 'sqs_score', width: 55,
    render: (row: any) => h('span', {}, row.sqs_score.toFixed(2)),
  },
  {
    title: 'P&L', key: 'pnl', width: 80,
    sorter: (a: any, b: any) => a.pnl - b.pnl,
    render: (row: any) => h('span', { style: `color: ${row.pnl >= 0 ? '#18a058' : '#d03050'}` }, `${row.pnl >= 0 ? '+' : ''}${Math.round(row.pnl).toLocaleString()}`),
  },
]

// Exit reason breakdown chart
const exitBreakdownOption = computed(() => {
  const w = currentWindow.value
  if (!w?.exit_breakdown) return {}
  const entries = Object.entries(w.exit_breakdown).sort((a: any, b: any) => b[1] - a[1])
  return {
    tooltip: { trigger: 'item' },
    legend: { orient: 'vertical', right: 10, top: 'center', textStyle: { fontSize: 11 } },
    series: [{
      type: 'pie',
      radius: ['35%', '65%'],
      center: ['35%', '50%'],
      data: entries.map(([k, v]) => ({
        name: k,
        value: v,
        itemStyle: {
          color: k.includes('disaster') ? '#d03050'
            : k.includes('trail') || k.includes('parabolic') ? '#18a058'
            : k.startsWith('pts_') ? '#f0a020'
            : k === 'end_of_period' ? '#999'
            : '#2080f0',
        },
      })),
      label: { show: true, formatter: '{b}: {c}', fontSize: 10 },
    }],
  }
})

// Sector distribution bar chart
const sectorBarOption = computed(() => {
  const w = currentWindow.value
  if (!w?.sector_distribution) return {}
  const entries = Object.entries(w.sector_distribution).sort((a: any, b: any) => b[1] - a[1])
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 100, right: 20, top: 10, bottom: 30 },
    xAxis: { type: 'value' },
    yAxis: { type: 'category', data: entries.map(([k]) => k), axisLabel: { fontSize: 11 } },
    series: [{
      type: 'bar',
      data: entries.map(([, v]) => v),
      itemStyle: { color: '#2080f0' },
      label: { show: true, position: 'right', fontSize: 11 },
    }],
  }
})

// Cross-window advantage ratio trend
const advantageTrendOption = computed(() => {
  if (!attrResult.value?.windows?.length) return {}
  const wins = attrResult.value.windows
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['Advantage Ratio', 'Win Rate %', 'Net Return %'], top: 0 },
    grid: { left: 50, right: 50, top: 40, bottom: 30 },
    xAxis: { type: 'category', data: wins.map((w: any) => w.window) },
    yAxis: [
      { type: 'value', name: 'Ratio / Return', position: 'left' },
      { type: 'value', name: 'Win Rate %', position: 'right', min: 0, max: 100 },
    ],
    series: [
      {
        name: 'Advantage Ratio',
        type: 'bar',
        data: wins.map((w: any) => w.summary.advantage_ratio),
        itemStyle: { color: '#e88080' },
      },
      {
        name: 'Net Return %',
        type: 'line',
        data: wins.map((w: any) => w.summary.net_return),
        symbol: 'circle',
        symbolSize: 8,
        lineStyle: { width: 2.5, color: '#18a058' },
        itemStyle: { color: '#18a058' },
      },
      {
        name: 'Win Rate %',
        type: 'line',
        yAxisIndex: 1,
        data: wins.map((w: any) => w.summary.win_rate),
        symbol: 'diamond',
        symbolSize: 8,
        lineStyle: { width: 2, color: '#2080f0', type: 'dashed' },
        itemStyle: { color: '#2080f0' },
      },
    ],
  }
})

// TAIEX regime comparison
const taiexRegimeOption = computed(() => {
  if (!attrResult.value?.windows?.length) return {}
  const wins = attrResult.value.windows
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['TAIEX Return %', 'Days Above MA200 %', 'Portfolio Return %'], top: 0 },
    grid: { left: 50, right: 50, top: 40, bottom: 30 },
    xAxis: { type: 'category', data: wins.map((w: any) => w.window) },
    yAxis: { type: 'value', name: '%' },
    series: [
      {
        name: 'TAIEX Return %',
        type: 'bar',
        data: wins.map((w: any) => w.taiex_regime?.return_pct ?? 0),
        itemStyle: {
          color: (params: any) => params.data >= 0 ? '#69b1ff' : '#ff7875',
        },
      },
      {
        name: 'Days Above MA200 %',
        type: 'line',
        data: wins.map((w: any) => w.taiex_regime?.above_ma200_pct ?? 0),
        symbol: 'circle',
        symbolSize: 8,
        lineStyle: { width: 2.5, color: '#722ed1' },
        itemStyle: { color: '#722ed1' },
      },
      {
        name: 'Portfolio Return %',
        type: 'line',
        data: wins.map((w: any) => w.summary.net_return),
        symbol: 'diamond',
        symbolSize: 8,
        lineStyle: { width: 2.5, color: '#18a058' },
        itemStyle: { color: '#18a058' },
      },
    ],
  }
})

// Exit type evolution stacked bar
const exitEvolutionOption = computed(() => {
  if (!attrResult.value?.windows?.length) return {}
  const wins = attrResult.value.windows

  // Group exit reasons into categories
  const categories = ['PTS Filter', 'Trail Stop', 'Parabolic', 'Disaster', 'End of Period', 'Other']
  const colors = ['#f0a020', '#18a058', '#36cfc9', '#d03050', '#999', '#2080f0']

  function categorize(exits: Record<string, number>) {
    const result: Record<string, number> = {}
    for (const cat of categories) result[cat] = 0
    for (const [k, v] of Object.entries(exits)) {
      if (k.startsWith('pts_')) result['PTS Filter'] += v
      else if (k.includes('trail')) result['Trail Stop'] += v
      else if (k.includes('parabolic')) result['Parabolic'] += v
      else if (k.includes('disaster')) result['Disaster'] += v
      else if (k === 'end_of_period') result['End of Period'] += v
      else result['Other'] += v
    }
    return result
  }

  const categorized = wins.map((w: any) => categorize(w.exit_breakdown))

  return {
    tooltip: { trigger: 'axis' },
    legend: { data: categories, top: 0 },
    grid: { left: 50, right: 20, top: 40, bottom: 30 },
    xAxis: { type: 'category', data: wins.map((w: any) => w.window) },
    yAxis: { type: 'value', name: 'Trades' },
    series: categories.map((cat, i) => ({
      name: cat,
      type: 'bar',
      stack: 'total',
      data: categorized.map((c: any) => c[cat]),
      itemStyle: { color: colors[i] },
    })),
  }
})

// SQS distribution comparison (winners vs losers per window)
const sqsComparisonOption = computed(() => {
  if (!attrResult.value?.windows?.length) return {}
  const wins = attrResult.value.windows
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['Winners SQS', 'Losers SQS', 'Overall SQS'], top: 0 },
    grid: { left: 50, right: 20, top: 40, bottom: 30 },
    xAxis: { type: 'category', data: wins.map((w: any) => w.window) },
    yAxis: { type: 'value', name: 'SQS Score', min: 0, max: 0.6 },
    series: [
      {
        name: 'Winners SQS',
        type: 'bar',
        data: wins.map((w: any) => w.sqs_stats.winners_mean),
        itemStyle: { color: '#18a058' },
      },
      {
        name: 'Losers SQS',
        type: 'bar',
        data: wins.map((w: any) => w.sqs_stats.losers_mean),
        itemStyle: { color: '#d03050' },
      },
      {
        name: 'Overall SQS',
        type: 'line',
        data: wins.map((w: any) => w.sqs_stats.mean),
        symbol: 'circle',
        symbolSize: 8,
        lineStyle: { width: 2, color: '#2080f0' },
        itemStyle: { color: '#2080f0' },
      },
    ],
  }
})
</script>

<template>
  <div>
    <NCard size="small" style="margin-bottom: 12px">
      <NSpace align="center">
        <NButton type="primary" :loading="loading" @click="runAttribution">
          Run Attribution Analysis
        </NButton>
        <span style="font-size: 12px; color: #999">
          Phase 10C: Forensic breakdown per WFA window (CTO directive)
        </span>
      </NSpace>
    </NCard>

    <NSpin :show="loading">
      <template v-if="attrResult">
        <!-- Cross-window charts -->
        <NGrid :cols="2" :x-gap="12" style="margin-bottom: 12px">
          <NGi>
            <NCard size="small" title="TAIEX Regime vs Portfolio Return">
              <ChartContainer :option="taiexRegimeOption" height="250px" />
            </NCard>
          </NGi>
          <NGi>
            <NCard size="small" title="Advantage Ratio & Win Rate Trend">
              <ChartContainer :option="advantageTrendOption" height="250px" />
            </NCard>
          </NGi>
        </NGrid>

        <NGrid :cols="2" :x-gap="12" style="margin-bottom: 12px">
          <NGi>
            <NCard size="small" title="Exit Type Evolution (Stacked)">
              <ChartContainer :option="exitEvolutionOption" height="250px" />
            </NCard>
          </NGi>
          <NGi>
            <NCard size="small" title="SQS: Winners vs Losers per Window">
              <ChartContainer :option="sqsComparisonOption" height="250px" />
            </NCard>
          </NGi>
        </NGrid>

        <!-- Window selector -->
        <NCard size="small" style="margin-bottom: 12px">
          <NSpace align="center">
            <NText strong>Window Detail:</NText>
            <NSelect
              v-model:value="selectedWindow"
              :options="windowOptions"
              style="width: 400px"
              size="small"
            />
          </NSpace>
        </NCard>

        <!-- Selected window stats -->
        <template v-if="currentWindow">
          <NGrid :cols="6" :x-gap="8" style="margin-bottom: 12px">
            <NGi>
              <NCard size="small">
                <NStatistic label="Net Return">
                  <span :style="{ color: retColor(currentWindow.summary.net_return) }">
                    {{ fmtPct(currentWindow.summary.net_return) }}
                  </span>
                </NStatistic>
              </NCard>
            </NGi>
            <NGi>
              <NCard size="small">
                <NStatistic label="Win Rate">
                  <span>{{ currentWindow.summary.win_rate.toFixed(1) }}%</span>
                </NStatistic>
              </NCard>
            </NGi>
            <NGi>
              <NCard size="small">
                <NStatistic label="Advantage Ratio">
                  <span :style="{ color: currentWindow.summary.advantage_ratio >= 2 ? '#18a058' : '#f0a020' }">
                    {{ currentWindow.summary.advantage_ratio.toFixed(2) }}
                  </span>
                </NStatistic>
              </NCard>
            </NGi>
            <NGi>
              <NCard size="small">
                <NStatistic label="TAIEX">
                  <span :style="{ color: retColor(currentWindow.taiex_regime?.return_pct || 0) }">
                    {{ fmtPct(currentWindow.taiex_regime?.return_pct) }}
                  </span>
                </NStatistic>
              </NCard>
            </NGi>
            <NGi>
              <NCard size="small">
                <NStatistic label="MA200 Above %">
                  <span>{{ currentWindow.taiex_regime?.above_ma200_pct?.toFixed(0) || '?' }}%</span>
                </NStatistic>
              </NCard>
            </NGi>
            <NGi>
              <NCard size="small">
                <NStatistic label="Avg Held Days">
                  <span>{{ currentWindow.summary.avg_held_days.toFixed(0) }}d</span>
                </NStatistic>
              </NCard>
            </NGi>
          </NGrid>

          <!-- Held Days comparison -->
          <NAlert type="info" style="margin-bottom: 12px; font-size: 12px">
            <b>Held Days:</b> Winners avg {{ currentWindow.summary.avg_held_days_win.toFixed(0) }}d
            vs Losers avg {{ currentWindow.summary.avg_held_days_loss.toFixed(0) }}d |
            <b>SQS:</b> Winners {{ currentWindow.sqs_stats.winners_mean.toFixed(3) }}
            vs Losers {{ currentWindow.sqs_stats.losers_mean.toFixed(3) }} |
            <b>Avg RS:</b> {{ currentWindow.rs_stats.mean.toFixed(0) }} ± {{ currentWindow.rs_stats.std.toFixed(0) }}
          </NAlert>

          <!-- Exit breakdown + Sector distribution side by side -->
          <NGrid :cols="2" :x-gap="12" style="margin-bottom: 12px">
            <NGi>
              <NCard size="small" title="Exit Breakdown">
                <ChartContainer :option="exitBreakdownOption" height="200px" />
              </NCard>
            </NGi>
            <NGi>
              <NCard size="small" title="Sector Distribution">
                <ChartContainer :option="sectorBarOption" height="200px" />
              </NCard>
            </NGi>
          </NGrid>

          <!-- Trade detail table -->
          <NCard size="small" :title="`${currentWindow.window} — All ${currentWindow.trades.length} Trades`">
            <NDataTable
              :columns="tradeColumns"
              :data="currentWindow.trades || []"
              size="small"
              :bordered="true"
              :single-line="false"
              :scroll-x="1100"
              :pagination="{ pageSize: 20 }"
            />
          </NCard>
        </template>

        <div style="font-size: 11px; color: #999; margin-top: 8px">
          Cost: {{ attrResult.cost_settings }} | Stocks: {{ attrResult.stocks_loaded }}
        </div>
      </template>
    </NSpin>
  </div>
</template>
