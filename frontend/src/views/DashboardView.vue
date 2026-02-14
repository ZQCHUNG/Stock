<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import {
  NCard, NGrid, NGi, NStatistic, NSpin, NTag, NSpace, NAlert,
  NDivider, NButton,
} from 'naive-ui'
import VChart from 'vue-echarts'
import { useRouter } from 'vue-router'
import { systemApi } from '../api/system'

const router = useRouter()
const loading = ref(true)
const data = ref<any>(null)

async function loadDashboard() {
  loading.value = true
  try {
    data.value = await systemApi.dashboard()
  } catch {
    data.value = null
  }
  loading.value = false
}

onMounted(loadDashboard)

const pos = computed(() => data.value?.positions || {})
const pnl = computed(() => data.value?.pnl || {})
const regime = computed(() => data.value?.regime || {})
const oms = computed(() => data.value?.oms || {})
const alerts = computed(() => data.value?.alerts || [])

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

function nav(route: string) {
  router.push({ name: route })
}
</script>

<template>
  <div>
    <NSpace align="center" justify="space-between" style="margin-bottom: 16px">
      <h2 style="margin: 0">Dashboard</h2>
      <NButton size="small" @click="loadDashboard" :loading="loading">Refresh</NButton>
    </NSpace>

    <NSpin :show="loading">
      <!-- Row 1: Key Metrics -->
      <NGrid :cols="5" :x-gap="12" :y-gap="12" style="margin-bottom: 16px">
        <NGi>
          <NCard size="small" :bordered="true">
            <NStatistic label="Open Positions" :value="pos.count || 0" />
          </NCard>
        </NGi>
        <NGi>
          <NCard size="small" :bordered="true">
            <NStatistic label="Total Market Value">
              <template #default>
                <span>${{ ((pos.total_value || 0) / 10000).toFixed(1) }}萬</span>
              </template>
            </NStatistic>
          </NCard>
        </NGi>
        <NGi>
          <NCard size="small" :bordered="true">
            <NStatistic label="Unrealized P&L">
              <template #default>
                <span :style="{ color: (pos.total_pnl || 0) >= 0 ? '#18a058' : '#e53e3e' }">
                  ${{ (pos.total_pnl || 0).toLocaleString() }}
                  ({{ ((pos.total_pnl_pct || 0) * 100).toFixed(2) }}%)
                </span>
              </template>
            </NStatistic>
          </NCard>
        </NGi>
        <NGi>
          <NCard size="small" :bordered="true">
            <NStatistic label="Cumulative P&L (Closed)">
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
            <NStatistic label="Total Closed Trades" :value="pnl.total_closed || 0" />
          </NCard>
        </NGi>
      </NGrid>

      <!-- Row 2: Market Regime + OMS -->
      <NGrid :cols="2" :x-gap="12" style="margin-bottom: 16px">
        <NGi>
          <NCard size="small" title="Market Regime (ML)" :bordered="true">
            <template #header-extra>
              <NButton size="tiny" text @click="nav('strategies')">Strategy Workbench</NButton>
            </template>
            <NGrid :cols="4" :x-gap="8">
              <NGi>
                <NStatistic label="Regime">
                  <template #default>
                    <NTag :bordered="false" size="large"
                          :style="{ color: regimeColor(regime.v4_suitability) }">
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
                <NStatistic label="V4 Suitability">
                  <template #default>
                    <NTag size="small" :style="{ color: regimeColor(regime.v4_suitability) }">
                      {{ regime.v4_suitability || '-' }}
                    </NTag>
                  </template>
                </NStatistic>
              </NGi>
            </NGrid>
            <NAlert v-if="regime.advice" type="info" :bordered="false" style="margin-top: 8px; font-size: 12px">
              {{ regime.advice }}
            </NAlert>
          </NCard>
        </NGi>
        <NGi>
          <NCard size="small" title="OMS Efficiency" :bordered="true">
            <template #header-extra>
              <NButton size="tiny" text @click="nav('alerts')">Details</NButton>
            </template>
            <NGrid :cols="3" :x-gap="8">
              <NGi>
                <NStatistic label="Auto Coverage" :value="`${((oms.auto_coverage || 0) * 100).toFixed(0)}%`" />
              </NGi>
              <NGi>
                <NStatistic label="Max Consec. Losses" :value="oms.max_consecutive_losses || 0" />
              </NGi>
              <NGi>
                <NStatistic label="Auto Exits" :value="oms.total_auto_exits || 0" />
              </NGi>
            </NGrid>
          </NCard>
        </NGi>
      </NGrid>

      <!-- Row 3: Monthly P&L Chart + Top Positions + Alerts -->
      <NGrid :cols="3" :x-gap="12">
        <NGi :span="1">
          <NCard size="small" title="Monthly P&L" :bordered="true" style="height: 240px">
            <template v-if="pnl.monthly?.length">
              <VChart :option="monthlyPnlChart" style="height: 180px" autoresize />
            </template>
            <div v-else style="text-align: center; color: #999; padding-top: 60px">No closed trades</div>
          </NCard>
        </NGi>
        <NGi :span="1">
          <NCard size="small" title="Top Positions" :bordered="true" style="height: 240px">
            <template #header-extra>
              <NButton size="tiny" text @click="nav('portfolio')">All</NButton>
            </template>
            <template v-if="pos.top_positions?.length">
              <div v-for="(p, idx) in pos.top_positions" :key="idx"
                   style="display: flex; justify-content: space-between; padding: 4px 0; font-size: 13px; border-bottom: 1px solid #f0f0f0">
                <span>{{ p.code }} {{ p.name }}</span>
                <span :style="{ color: (p.pnl || 0) >= 0 ? '#18a058' : '#e53e3e' }">
                  ${{ (p.pnl || 0).toLocaleString() }}
                  ({{ ((p.pnl_pct || 0) * 100).toFixed(1) }}%)
                </span>
              </div>
            </template>
            <div v-else style="text-align: center; color: #999; padding-top: 60px">No open positions</div>
          </NCard>
        </NGi>
        <NGi :span="1">
          <NCard size="small" title="Recent Alerts" :bordered="true" style="height: 240px">
            <template #header-extra>
              <NButton size="tiny" text @click="nav('alerts')">All</NButton>
            </template>
            <template v-if="alerts.length">
              <div v-for="(a, idx) in alerts" :key="idx"
                   style="padding: 4px 0; font-size: 12px; border-bottom: 1px solid #f0f0f0">
                <NTag :type="a.severity === 'high' ? 'error' : a.severity === 'medium' ? 'warning' : 'info'"
                      size="tiny" style="margin-right: 4px">
                  {{ a.type || 'alert' }}
                </NTag>
                {{ a.message || a.detail || JSON.stringify(a).substring(0, 60) }}
              </div>
            </template>
            <div v-else style="text-align: center; color: #999; padding-top: 60px">No recent alerts</div>
          </NCard>
        </NGi>
      </NGrid>

      <!-- Row 4: Quick Navigation -->
      <NDivider style="margin: 16px 0 8px" />
      <NSpace :size="8" :wrap="true">
        <NButton size="small" @click="nav('technical')">Technical Analysis</NButton>
        <NButton size="small" @click="nav('recommend')">Recommend</NButton>
        <NButton size="small" @click="nav('backtest')">Backtest</NButton>
        <NButton size="small" @click="nav('screener')">Screener</NButton>
        <NButton size="small" @click="nav('portfolio')">Portfolio</NButton>
        <NButton size="small" @click="nav('risk')">Risk Dashboard</NButton>
        <NButton size="small" @click="nav('strategies')">Strategy Workbench</NButton>
        <NButton size="small" @click="nav('watchlist')">Watchlist</NButton>
      </NSpace>
    </NSpin>
  </div>
</template>
