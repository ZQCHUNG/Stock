<script setup lang="ts">
import { h, ref, computed } from 'vue'
import {
  NCard, NButton, NSpace, NDataTable, NSpin, NStatistic, NTag,
  NGrid, NGi, NAlert, NText, NProgress, useMessage,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { backtestApi } from '../api/backtest'
import ChartContainer from './ChartContainer.vue'

const msg = useMessage()
const loading = ref(false)
const data = ref<any>(null)

async function runBarometer() {
  loading.value = true
  try {
    const resp = await backtestApi.regimeBarometer(180, 20)
    data.value = resp
    if (resp.status === 'no_trades') {
      msg.warning('No recent trades found')
    } else {
      msg.success(`Regime Barometer: ${resp.regime_label} (Hunting Index: ${resp.hunting_index})`)
    }
  } catch (e: any) {
    msg.error(`Barometer failed: ${e?.message || e}`)
  }
  loading.value = false
}

// Hunting Index color
function huntingColor(v: number) {
  if (v >= 50) return '#18a058'
  if (v >= 20) return '#f0a020'
  return '#d03050'
}

// Regime badge
const regimeType = computed(() => {
  if (!data.value) return 'default'
  const r = data.value.regime
  if (r === 'hot_momentum') return 'success'
  if (r === 'chop') return 'warning'
  if (r === 'flash_crash') return 'error'
  return 'info'
})

// Exit type pie chart
const exitPieOption = computed(() => {
  if (!data.value?.exit_categories) return {}
  const cats = data.value.exit_categories
  const colorMap: Record<string, string> = {
    PTS: '#f0a020',
    Parabolic: '#18a058',
    Trail: '#36cfc9',
    Disaster: '#d03050',
    TrendBreak: '#722ed1',
    EndOfPeriod: '#999',
    Other: '#2080f0',
  }
  const entries = Object.entries(cats).sort((a: any, b: any) => b[1] - a[1])
  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    legend: { orient: 'vertical', right: 10, top: 'center', textStyle: { fontSize: 11 } },
    series: [{
      type: 'pie',
      radius: ['40%', '70%'],
      center: ['35%', '50%'],
      data: entries.map(([k, v]) => ({
        name: k,
        value: v,
        itemStyle: { color: colorMap[k] || '#2080f0' },
      })),
      label: { show: true, formatter: '{b}\n{d}%', fontSize: 11 },
      emphasis: { itemStyle: { shadowBlur: 10 } },
    }],
  }
})

// Sector Alpha Drift table
const sectorColumns: DataTableColumns = [
  { title: 'Sector', key: 'sector', width: 120 },
  { title: 'Trades', key: 'trades', width: 60 },
  {
    title: 'PTS %', key: 'pts_rate', width: 70,
    render: (row: any) => h('span', {
      style: `color: ${row.pts_rate > 70 ? '#d03050' : row.pts_rate > 40 ? '#f0a020' : '#999'}`,
    }, `${row.pts_rate}%`),
  },
  {
    title: 'Parabolic %', key: 'parabolic_rate', width: 90,
    render: (row: any) => h('span', {
      style: `color: ${row.parabolic_rate > 30 ? '#18a058' : '#999'}`,
    }, `${row.parabolic_rate}%`),
  },
  {
    title: 'Hunting Idx', key: 'hunting_index', width: 100,
    sorter: (a: any, b: any) => a.hunting_index - b.hunting_index,
    render: (row: any) => h('span', {
      style: `font-weight: 700; color: ${huntingColor(row.hunting_index)}`,
    }, row.hunting_index.toFixed(0)),
  },
]

// Hunting Index gauge
const gaugeOption = computed(() => {
  if (!data.value) return {}
  const v = data.value.hunting_index
  return {
    series: [{
      type: 'gauge',
      startAngle: 180,
      endAngle: 0,
      min: 0,
      max: 100,
      splitNumber: 5,
      itemStyle: { color: huntingColor(v) },
      progress: { show: true, width: 18 },
      pointer: { show: true, length: '60%', width: 6 },
      axisLine: {
        lineStyle: {
          width: 18,
          color: [[0.2, '#d03050'], [0.5, '#f0a020'], [1, '#18a058']],
        },
      },
      axisTick: { show: false },
      splitLine: { length: 10 },
      axisLabel: { distance: 25, fontSize: 11 },
      detail: {
        valueAnimation: true,
        formatter: '{value}',
        fontSize: 28,
        offsetCenter: [0, '20%'],
        color: huntingColor(v),
      },
      data: [{ value: v, name: 'Hunting Index' }],
      title: { offsetCenter: [0, '45%'], fontSize: 13 },
    }],
  }
})
</script>

<template>
  <div>
    <NCard size="small" style="margin-bottom: 12px">
      <NSpace align="center">
        <NButton type="primary" :loading="loading" @click="runBarometer">
          Run Regime Barometer
        </NButton>
        <span style="font-size: 12px; color: #999">
          Phase 11: Analyzes last 20 trades exit type distribution (180-day lookback)
        </span>
      </NSpace>
    </NCard>

    <NSpin :show="loading">
      <template v-if="data && data.status !== 'no_trades'">
        <!-- Top row: Regime badge + key metrics -->
        <NGrid :cols="5" :x-gap="8" style="margin-bottom: 12px">
          <NGi>
            <NCard size="small">
              <NStatistic label="Regime">
                <NTag :type="regimeType" size="large" style="font-size: 14px; font-weight: 700">
                  {{ data.regime_label }}
                </NTag>
              </NStatistic>
            </NCard>
          </NGi>
          <NGi>
            <NCard size="small">
              <NStatistic label="Hunting Index">
                <span :style="{ fontSize: '22px', fontWeight: '700', color: huntingColor(data.hunting_index) }">
                  {{ data.hunting_index.toFixed(0) }}
                </span>
              </NStatistic>
            </NCard>
          </NGi>
          <NGi>
            <NCard size="small">
              <NStatistic label="Win Rate">
                <span>{{ data.win_rate.toFixed(1) }}%</span>
              </NStatistic>
            </NCard>
          </NGi>
          <NGi>
            <NCard size="small">
              <NStatistic label="Avg Return">
                <span :style="{ color: data.avg_return_pct >= 0 ? '#18a058' : '#d03050' }">
                  {{ data.avg_return_pct >= 0 ? '+' : '' }}{{ data.avg_return_pct.toFixed(2) }}%
                </span>
              </NStatistic>
            </NCard>
          </NGi>
          <NGi>
            <NCard size="small">
              <NStatistic label="Avg Held Days" :value="data.avg_held_days.toFixed(0)" />
            </NCard>
          </NGi>
        </NGrid>

        <!-- Alert based on regime -->
        <NAlert
          v-if="data.regime === 'flash_crash'"
          type="error" style="margin-bottom: 12px"
        >
          <b>FLASH CRASH DETECTED</b> — Disaster exits > 10%. Check TAIEX Guard status immediately.
        </NAlert>
        <NAlert
          v-else-if="data.regime === 'chop'"
          type="warning" style="margin-bottom: 12px"
        >
          <b>CHOP MARKET</b> — PTS exits > 70%. Consider pausing new entries or switching to Sniper A.
          CTO says: "Go drink coffee."
        </NAlert>
        <NAlert
          v-else-if="data.regime === 'hot_momentum'"
          type="success" style="margin-bottom: 12px"
        >
          <b>HOT MOMENTUM</b> — Parabolic exits > 30%. Harvest season. Stay fully deployed in Sniper B.
        </NAlert>

        <!-- Rate bars -->
        <NCard size="small" title="Exit Type Rates" style="margin-bottom: 12px">
          <div style="margin-bottom: 8px">
            <NText depth="3" style="font-size: 11px">PTS Rate (Time-Stop Filter)</NText>
            <NProgress
              type="line"
              :percentage="data.pts_rate"
              :color="data.pts_rate > 70 ? '#d03050' : data.pts_rate > 40 ? '#f0a020' : '#999'"
              :height="16"
              :show-indicator="true"
            />
          </div>
          <div style="margin-bottom: 8px">
            <NText depth="3" style="font-size: 11px">Parabolic Rate (Profitable Momentum Exit)</NText>
            <NProgress
              type="line"
              :percentage="data.parabolic_rate"
              :color="data.parabolic_rate > 30 ? '#18a058' : '#999'"
              :height="16"
              :show-indicator="true"
            />
          </div>
          <div style="margin-bottom: 8px">
            <NText depth="3" style="font-size: 11px">Trail Rate (Trailing Stop)</NText>
            <NProgress
              type="line"
              :percentage="data.trail_rate"
              color="#36cfc9"
              :height="16"
              :show-indicator="true"
            />
          </div>
          <div style="margin-bottom: 8px">
            <NText depth="3" style="font-size: 11px">Disaster Rate (Hard Stop)</NText>
            <NProgress
              type="line"
              :percentage="data.disaster_rate"
              :color="data.disaster_rate > 10 ? '#d03050' : '#999'"
              :height="16"
              :show-indicator="true"
            />
          </div>
          <div>
            <NText depth="3" style="font-size: 11px">Trend Break Rate</NText>
            <NProgress
              type="line"
              :percentage="data.trend_break_rate"
              color="#722ed1"
              :height="16"
              :show-indicator="true"
            />
          </div>
        </NCard>

        <!-- Charts row: Pie + Gauge -->
        <NGrid :cols="2" :x-gap="12" style="margin-bottom: 12px">
          <NGi>
            <NCard size="small" title="Exit Type Distribution (Last 20 Trades)">
              <ChartContainer :option="exitPieOption" height="280px" />
            </NCard>
          </NGi>
          <NGi>
            <NCard size="small" title="Hunting Index Gauge">
              <ChartContainer :option="gaugeOption" height="280px" />
              <NText depth="3" style="font-size: 11px; display: block; text-align: center">
                Formula: Parabolic% / (PTS% + Disaster%) | >50 = Green, 20-50 = Yellow, <20 = Red
              </NText>
            </NCard>
          </NGi>
        </NGrid>

        <!-- Sector Alpha Drift -->
        <NCard size="small" title="Sector Alpha Drift" style="margin-bottom: 12px">
          <NDataTable
            :columns="sectorColumns"
            :data="data.sector_alpha || []"
            size="small"
            :bordered="true"
            :single-line="false"
          />
        </NCard>

        <div style="font-size: 11px; color: #999; margin-top: 8px">
          Period: {{ data.period_start }} ~ {{ data.period_end }} |
          Trades analyzed: {{ data.actual_trades }} of {{ data.all_trades_count }} |
          Cost: {{ data.cost_settings }} | Stocks: {{ data.stocks_loaded }}
        </div>
      </template>

      <NAlert v-else-if="data?.status === 'no_trades'" type="info">
        No completed trades in the lookback period.
      </NAlert>
    </NSpin>
  </div>
</template>
