<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import {
  NCard, NGrid, NGi, NStatistic, NSpin, NTag, NSpace, NAlert,
  NDivider, NButton, NBadge,
} from 'naive-ui'
import VChart from 'vue-echarts'
import { useRouter } from 'vue-router'
import { useAppStore } from '../stores/app'
import { systemApi } from '../api/system'
import { useMarketData } from '../composables/useMarketData'
import { useResponsive } from '../composables/useResponsive'

const router = useRouter()
const app = useAppStore()
const { isMobile, isTablet } = useResponsive()

// R56: Responsive grid columns
const metricCols = computed(() => isMobile.value ? 2 : isTablet.value ? 3 : 6)
const row2Cols = computed(() => isMobile.value ? 1 : isTablet.value ? 2 : 3)
const row3Cols = computed(() => isMobile.value ? 1 : isTablet.value ? 2 : 4)
const loading = ref(true)
const data = ref<any>(null)

// R55-1: WebSocket live market data
const { isConnected, quotes, subscribe, requestStatus } = useMarketData()

async function loadDashboard() {
  loading.value = true
  try {
    data.value = await systemApi.dashboard()
    // Subscribe to position stocks for live prices
    const positionCodes = (data.value?.positions?.top_positions || []).map((p: any) => p.code).filter(Boolean)
    const signalCodes = (data.value?.today_signals || []).map((s: any) => s.code).filter(Boolean)
    const allCodes = [...new Set([...positionCodes, ...signalCodes])]
    if (allCodes.length > 0) {
      subscribe(allCodes)
    }
  } catch {
    data.value = null
  }
  loading.value = false
}

onMounted(() => {
  loadDashboard()
  // Request feed status after connection
  setTimeout(() => requestStatus(), 2000)
})

const pos = computed(() => data.value?.positions || {})
const pnl = computed(() => data.value?.pnl || {})
const regime = computed(() => data.value?.regime || {})
const oms = computed(() => data.value?.oms || {})
const alerts = computed(() => data.value?.alerts || [])
const risk = computed(() => data.value?.risk || {})
const signals = computed(() => data.value?.today_signals || [])
const equity = computed(() => data.value?.equity_curve || {})

function regimeColor(suitability: string): string {
  if (suitability === 'excellent') return '#18a058'
  if (suitability === 'good') return '#2080f0'
  if (suitability === 'fair') return '#f0a020'
  return '#e53e3e'
}

const monthlyPnlChart = computed(() => {
  const months = pnl.value?.monthly || []
  if (!months.length) return {}
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 50, right: 10, top: 8, bottom: 20 },
    xAxis: { type: 'category', data: months.map((m: any) => m.month), axisLabel: { fontSize: 10 } },
    yAxis: { type: 'value', axisLabel: { fontSize: 10, formatter: (v: number) => `$${(v / 1000).toFixed(0)}K` } },
    series: [{
      type: 'bar',
      data: months.map((m: any) => ({
        value: m.pnl,
        itemStyle: { color: m.pnl >= 0 ? '#18a058' : '#e53e3e' },
      })),
    }],
  }
})

const equityCurveChart = computed(() => {
  const dates = equity.value?.dates || []
  const values = equity.value?.values || []
  if (!dates.length) return {}
  return {
    tooltip: { trigger: 'axis', formatter: (p: any) => `${p[0]?.axisValue}<br/>$${(p[0]?.value || 0).toLocaleString()}` },
    grid: { left: 60, right: 10, top: 8, bottom: 20 },
    xAxis: { type: 'category', data: dates, axisLabel: { fontSize: 10, rotate: 30 } },
    yAxis: { type: 'value', axisLabel: { fontSize: 10, formatter: (v: number) => `$${(v / 1e6).toFixed(2)}M` } },
    series: [{
      type: 'line', data: values, symbol: 'none',
      lineStyle: { width: 2 },
      areaStyle: { opacity: 0.15 },
      itemStyle: { color: '#2080f0' },
    }],
  }
})

function nav(route: string) {
  router.push({ name: route })
}

function analyzeStock(code: string) {
  app.selectStock(code)
  router.push({ name: 'technical' })
}
</script>

<template>
  <div>
    <NSpace align="center" justify="space-between" style="margin-bottom: 16px">
      <NSpace align="center" :size="10">
        <h2 style="margin: 0">Dashboard</h2>
        <NBadge :dot="true" :type="isConnected ? 'success' : 'error'" :offset="[-2, 0]">
          <NTag size="tiny" :bordered="false" :type="isConnected ? 'success' : 'default'">
            {{ isConnected ? 'LIVE' : 'OFFLINE' }}
          </NTag>
        </NBadge>
      </NSpace>
      <NButton size="small" @click="loadDashboard" :loading="loading">Refresh</NButton>
    </NSpace>

    <!-- R55-1: Live Market Ticker -->
    <div v-if="quotes.size > 0" style="display: flex; gap: 10px; overflow-x: auto; margin-bottom: 10px; padding: 6px 0">
      <NTag v-for="[code, q] of quotes" :key="code" size="small" :bordered="true"
            style="cursor: pointer; min-width: fit-content" @click="analyzeStock(code)">
        <span style="font-weight: 600">{{ code }}</span>
        <span style="margin-left: 6px">{{ q.last_price ?? '-' }}</span>
        <span v-if="q.change_pct != null" style="margin-left: 4px"
              :style="{ color: q.change_pct >= 0 ? '#18a058' : '#e53e3e' }">
          {{ q.change_pct >= 0 ? '+' : '' }}{{ q.change_pct.toFixed(2) }}%
        </span>
      </NTag>
    </div>

    <NSpin :show="loading">
      <!-- Row 1: Key Metrics -->
      <NGrid :cols="metricCols" :x-gap="10" :y-gap="10" style="margin-bottom: 12px">
        <NGi>
          <NCard size="small" :bordered="true">
            <NStatistic label="Positions" :value="pos.count || 0" />
          </NCard>
        </NGi>
        <NGi>
          <NCard size="small" :bordered="true">
            <NStatistic label="Market Value">
              <template #default>${{ ((pos.total_value || 0) / 10000).toFixed(1) }}W</template>
            </NStatistic>
          </NCard>
        </NGi>
        <NGi>
          <NCard size="small" :bordered="true">
            <NStatistic label="Unrealized P&L">
              <template #default>
                <span :style="{ color: (pos.total_pnl || 0) >= 0 ? '#18a058' : '#e53e3e' }">
                  ${{ (pos.total_pnl || 0).toLocaleString() }}
                </span>
              </template>
            </NStatistic>
          </NCard>
        </NGi>
        <NGi>
          <NCard size="small" :bordered="true">
            <NStatistic label="Closed P&L">
              <template #default>
                <span :style="{ color: (pnl.cumulative_pnl || 0) >= 0 ? '#18a058' : '#e53e3e' }">
                  ${{ (pnl.cumulative_pnl || 0).toLocaleString() }}
                </span>
              </template>
            </NStatistic>
          </NCard>
        </NGi>
        <NGi>
          <NCard size="small" :bordered="true">
            <NStatistic label="VaR 1D (95%)">
              <template #default>
                <span v-if="risk.has_data" style="color: #e53e3e">
                  {{ ((risk.var_1d_pct || 0) * 100).toFixed(2) }}%
                </span>
                <span v-else style="color: #999">-</span>
              </template>
            </NStatistic>
          </NCard>
        </NGi>
        <NGi>
          <NCard size="small" :bordered="true">
            <NStatistic label="VaR 5D (95%)">
              <template #default>
                <span v-if="risk.has_data" style="color: #e53e3e">
                  ${{ (risk.var_1d_amt || 0).toLocaleString() }}
                </span>
                <span v-else style="color: #999">-</span>
              </template>
            </NStatistic>
          </NCard>
        </NGi>
      </NGrid>

      <!-- Row 2: Market Regime + OMS + Risk -->
      <NGrid :cols="row2Cols" :x-gap="12" :y-gap="12" style="margin-bottom: 12px">
        <NGi>
          <NCard size="small" title="Market Regime (ML)" :bordered="true">
            <template #header-extra>
              <NButton size="tiny" text @click="nav('strategies')">Workbench</NButton>
            </template>
            <NGrid :cols="2" :x-gap="8" :y-gap="4">
              <NGi>
                <NStatistic label="Regime">
                  <template #default>
                    <NTag :bordered="false" :style="{ color: regimeColor(regime.v4_suitability) }">
                      {{ regime.label || 'N/A' }}
                    </NTag>
                  </template>
                </NStatistic>
              </NGi>
              <NGi>
                <NStatistic label="Confidence" :value="`${((regime.confidence || 0) * 100).toFixed(0)}%`" />
              </NGi>
              <NGi>
                <NStatistic label="Kelly" :value="(regime.kelly || 0).toFixed(2)" />
              </NGi>
              <NGi>
                <NStatistic label="V4 Fit">
                  <template #default>
                    <NTag size="small" :style="{ color: regimeColor(regime.v4_suitability) }">
                      {{ regime.v4_suitability || '-' }}
                    </NTag>
                  </template>
                </NStatistic>
              </NGi>
            </NGrid>
            <NAlert v-if="regime.advice" type="info" :bordered="false" style="margin-top: 6px; font-size: 11px">
              {{ regime.advice }}
            </NAlert>
          </NCard>
        </NGi>
        <NGi>
          <NCard size="small" title="OMS Efficiency" :bordered="true">
            <template #header-extra>
              <NButton size="tiny" text @click="nav('risk')">Details</NButton>
            </template>
            <NGrid :cols="3" :x-gap="8">
              <NGi><NStatistic label="Auto Coverage" :value="`${((oms.auto_coverage || 0) * 100).toFixed(0)}%`" /></NGi>
              <NGi><NStatistic label="Consec. Loss" :value="oms.max_consecutive_losses || 0" /></NGi>
              <NGi><NStatistic label="Auto Exits" :value="oms.total_auto_exits || 0" /></NGi>
            </NGrid>
          </NCard>
        </NGi>
        <NGi>
          <NCard size="small" title="Today's Signals" :bordered="true">
            <template #header-extra>
              <NButton size="tiny" text @click="nav('recommend')">Scan</NButton>
            </template>
            <template v-if="signals.length">
              <div v-for="(s, idx) in signals.slice(0, 5)" :key="idx"
                   style="display: flex; justify-content: space-between; align-items: center; padding: 3px 0; font-size: 12px; border-bottom: 1px solid #f0f0f0; cursor: pointer"
                   @click="analyzeStock(s.code)">
                <NSpace :size="4" :wrap="false">
                  <NTag :type="s.signal === 'BUY' ? 'success' : 'error'" size="tiny">{{ s.signal }}</NTag>
                  <span>{{ s.code }}</span>
                </NSpace>
                <span style="color: #999">{{ s.entry_type || '' }}</span>
              </div>
              <div v-if="signals.length > 5" style="text-align: center; font-size: 11px; color: #999; padding-top: 4px">
                +{{ signals.length - 5 }} more
              </div>
            </template>
            <div v-else style="text-align: center; color: #999; padding-top: 30px; font-size: 12px">
              No signals (run scan)
            </div>
          </NCard>
        </NGi>
      </NGrid>

      <!-- Row 3: Equity Curve + Monthly P&L + Top Positions + Alerts -->
      <NGrid :cols="row3Cols" :x-gap="12" :y-gap="12" style="margin-bottom: 12px">
        <NGi :span="1">
          <NCard size="small" title="Equity Curve" :bordered="true" style="height: 220px">
            <template #header-extra>
              <NButton size="tiny" text @click="nav('portfolio')">Portfolio</NButton>
            </template>
            <template v-if="equity.dates?.length">
              <VChart :option="equityCurveChart" style="height: 160px" autoresize />
            </template>
            <div v-else style="text-align: center; color: #999; padding-top: 50px; font-size: 12px">No equity data</div>
          </NCard>
        </NGi>
        <NGi :span="1">
          <NCard size="small" title="Monthly P&L" :bordered="true" style="height: 220px">
            <template v-if="pnl.monthly?.length">
              <VChart :option="monthlyPnlChart" style="height: 160px" autoresize />
            </template>
            <div v-else style="text-align: center; color: #999; padding-top: 50px; font-size: 12px">No trades</div>
          </NCard>
        </NGi>
        <NGi :span="1">
          <NCard size="small" title="Top Positions" :bordered="true" style="height: 220px">
            <template v-if="pos.top_positions?.length">
              <div v-for="(p, idx) in pos.top_positions" :key="idx"
                   style="display: flex; justify-content: space-between; padding: 3px 0; font-size: 12px; border-bottom: 1px solid #f0f0f0; cursor: pointer"
                   @click="analyzeStock(p.code)">
                <span>{{ p.code }}</span>
                <span :style="{ color: (p.pnl || 0) >= 0 ? '#18a058' : '#e53e3e' }">
                  {{ ((p.pnl_pct || 0) * 100).toFixed(1) }}%
                </span>
              </div>
            </template>
            <div v-else style="text-align: center; color: #999; padding-top: 50px; font-size: 12px">No positions</div>
          </NCard>
        </NGi>
        <NGi :span="1">
          <NCard size="small" title="Alerts" :bordered="true" style="height: 220px">
            <template #header-extra>
              <NButton size="tiny" text @click="nav('risk')">All</NButton>
            </template>
            <template v-if="alerts.length">
              <div v-for="(a, idx) in alerts" :key="idx"
                   style="padding: 3px 0; font-size: 11px; border-bottom: 1px solid #f0f0f0">
                <NTag :type="a.severity === 'high' ? 'error' : a.severity === 'medium' ? 'warning' : 'info'"
                      size="tiny" style="margin-right: 4px">
                  {{ a.type || 'alert' }}
                </NTag>
                {{ (a.message || a.detail || '').substring(0, 40) }}
              </div>
            </template>
            <div v-else style="text-align: center; color: #999; padding-top: 50px; font-size: 12px">No alerts</div>
          </NCard>
        </NGi>
      </NGrid>

      <!-- Quick Navigation -->
      <NDivider style="margin: 8px 0" />
      <NSpace :size="6" :wrap="true">
        <NButton size="small" @click="nav('technical')">Technical</NButton>
        <NButton size="small" @click="nav('recommend')">Recommend</NButton>
        <NButton size="small" @click="nav('strategies')">Backtest</NButton>
        <NButton size="small" @click="nav('screener')">Screener</NButton>
        <NButton size="small" @click="nav('portfolio')">Portfolio</NButton>
        <NButton size="small" @click="nav('risk')">Risk</NButton>
        <NButton size="small" @click="nav('strategies')">Strategies</NButton>
        <NButton size="small" @click="nav('watchlist')">Watchlist</NButton>
      </NSpace>
    </NSpin>
  </div>
</template>
