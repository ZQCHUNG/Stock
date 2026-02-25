<script setup lang="ts">
import { ref, computed, onMounted, h } from 'vue'
import {
  NCard, NButton, NTag, NGrid, NGi, NSpin, NStatistic, NSpace,
  NAlert, NEmpty, NDataTable, NTabs, NTabPane, NTooltip,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import VChart from 'vue-echarts'
import { systemApi } from '../api/system'
import type { DriftReport, RiskFlag, PipelineMonitor, TrailingStopResult, FailureAnalysis, FilteredSignal, SelfHealedEvents, SectorHeatmapData, WarRoomData, StressTestResult, AggressiveIndex } from '../api/system'

// --- State ---
const activeTab = ref('signals')
const isLoading = ref(false)
const error = ref('')

// Signal Log
const signals = ref<any[]>([])
const signalFilter = ref<'all' | 'active' | 'realized'>('all')

// Drift Report
const driftReport = ref<DriftReport | null>(null)

// Risk Flag
const riskFlag = ref<RiskFlag | null>(null)

// Pipeline Monitor
const pipeline = ref<PipelineMonitor | null>(null)

// Failure Analysis
const failures = ref<FailureAnalysis[]>([])

// Missed Opportunities (Phase 7 P2)
const missedOpps = ref<FilteredSignal[]>([])

// Self-Healed Events (Phase 8 P0)
const healedEvents = ref<SelfHealedEvents | null>(null)

// Sector Heatmap (Phase 8 P1)
const sectorData = ref<SectorHeatmapData | null>(null)

// War Room (Phase 9 P1)
const warRoom = ref<WarRoomData | null>(null)

// Stress Test (Phase 10 P0)
const stressTest = ref<StressTestResult | null>(null)
const stressMode = ref(false)

// Aggressive Index (Phase 10 P1)
const aggIndex = ref<AggressiveIndex | null>(null)

// --- Loaders ---
async function loadSignals() {
  isLoading.value = true
  error.value = ''
  try {
    signals.value = await systemApi.signalLog(signalFilter.value, 200)
  } catch (e: any) {
    error.value = e?.message || 'Failed to load signals'
  }
  isLoading.value = false
}

async function loadDrift() {
  isLoading.value = true
  error.value = ''
  try {
    driftReport.value = await systemApi.driftReport()
  } catch (e: any) {
    error.value = e?.message || 'Failed to load drift report'
  }
  isLoading.value = false
}

async function loadRiskFlag() {
  try {
    riskFlag.value = await systemApi.riskFlag()
  } catch {
    // silent
  }
}

async function loadPipeline() {
  try {
    pipeline.value = await systemApi.pipelineMonitor()
  } catch {
    // silent
  }
}

async function loadFailures() {
  try {
    const result = await systemApi.failureAnalysis(90)
    failures.value = result.failures || []
  } catch {
    // silent
  }
}

async function loadMissedOpps() {
  try {
    const result = await systemApi.missedOpportunities(30, 50)
    missedOpps.value = result.filtered || []
  } catch {
    // silent
  }
}

async function loadHealedEvents() {
  try {
    healedEvents.value = await systemApi.selfHealedEvents()
  } catch {
    // silent
  }
}

async function loadSectorHeatmap() {
  try {
    sectorData.value = await systemApi.sectorHeatmap()
  } catch {
    // silent
  }
}

async function loadWarRoom() {
  try {
    warRoom.value = await systemApi.warRoom()
  } catch {
    // silent
  }
}

async function loadStressTest() {
  try {
    stressTest.value = await systemApi.stressTest()
  } catch {
    // silent
  }
}

async function loadAggIndex() {
  try {
    aggIndex.value = await systemApi.aggressiveIndex()
  } catch {
    // silent
  }
}

async function loadAll() {
  await Promise.all([loadSignals(), loadDrift(), loadRiskFlag(), loadPipeline(), loadFailures(), loadMissedOpps(), loadHealedEvents(), loadSectorHeatmap(), loadWarRoom(), loadStressTest(), loadAggIndex()])
}

// --- Actions ---
async function triggerRealize() {
  try {
    const result = await systemApi.realizeSignals()
    await loadSignals()
    alert(`Realized: ${result.realized} signals, Updated: ${result.updated}`)
  } catch (e: any) {
    error.value = e?.message || 'Realize failed'
  }
}

async function triggerAudit() {
  isLoading.value = true
  try {
    const result = await systemApi.weeklyAudit()
    await loadAll()
    alert(`Audit complete. In-Bounds Rate: ${result.in_bounds?.in_bounds_rate != null ? (result.in_bounds.in_bounds_rate * 100).toFixed(0) + '%' : 'N/A'}`)
  } catch (e: any) {
    error.value = e?.message || 'Audit failed'
  }
  isLoading.value = false
}

async function triggerTrailingStops() {
  isLoading.value = true
  try {
    const result = await systemApi.updateTrailingStops()
    await loadSignals()
    alert(`Trailing stops updated: ${result.updated} signals, ${result.active_stops?.length || 0} active`)
  } catch (e: any) {
    error.value = e?.message || 'Trailing stops update failed'
  }
  isLoading.value = false
}

async function toggleRiskFlag() {
  if (!riskFlag.value) return
  const newState = !riskFlag.value.global_risk_on
  const reason = newState ? 'Manual re-enable' : 'Manual kill-switch'
  try {
    riskFlag.value = await systemApi.setRiskFlag(newState, reason)
  } catch (e: any) {
    error.value = e?.message || 'Failed to toggle risk flag'
  }
}

// Phase 11 P0: Emergency Kill Switch
async function triggerEmergencyStop() {
  const confirmed = confirm(
    'EMERGENCY STOP\n\n' +
    'This will:\n' +
    '- Stop all scheduled tasks\n' +
    '- Set Risk Flag to OFF (LOCKDOWN)\n' +
    '- Send emergency LINE notification\n\n' +
    'You must manually re-enable Risk Flag to resume.\n\n' +
    'Are you sure?'
  )
  if (!confirmed) return

  isLoading.value = true
  try {
    await systemApi.emergencyStop()
    // Refresh risk flag state
    await loadRiskFlag()
    alert('EMERGENCY STOP executed. System is now in LOCKDOWN mode.')
  } catch (e: any) {
    error.value = e?.message || 'Emergency stop failed'
  }
  isLoading.value = false
}

// Phase 11 P1: Confirm Live Trade
async function confirmLive(row: any) {
  const priceStr = prompt(`Confirm live trade for ${row.stock_code} ${row.stock_name}\nSystem entry: ${row.entry_price}\n\nEnter actual entry price:`)
  if (!priceStr) return
  const price = parseFloat(priceStr)
  if (isNaN(price) || price <= 0) {
    alert('Invalid price')
    return
  }
  try {
    await systemApi.confirmLiveTrade(row.id, price)
    await loadSignals()
  } catch (e: any) {
    error.value = e?.message || 'Confirm live failed'
  }
}

// --- Signal Table Columns ---
const signalColumns = computed<DataTableColumns>(() => [
  { title: 'Date', key: 'signal_date', width: 100, sorter: 'default' },
  { title: 'Code', key: 'stock_code', width: 70 },
  { title: 'Name', key: 'stock_name', width: 90 },
  {
    title: 'Tier',
    key: 'sniper_tier',
    width: 80,
    render: (row: any) => {
      const tier = row.sniper_tier || 'unknown'
      const color = tier === 'sniper' ? '#a855f7' : tier === 'tactical' ? '#f59e0b' : '#94a3b8'
      return h(NTag, { size: 'small', color: { color, textColor: '#fff' } }, () => tier)
    },
  },
  {
    title: 'Score',
    key: 'sim_score',
    width: 60,
    sorter: (a: any, b: any) => (a.sim_score || 0) - (b.sim_score || 0),
  },
  {
    title: 'Grade',
    key: 'confidence_grade',
    width: 70,
    render: (row: any) => {
      const g = row.confidence_grade || 'LOW'
      const type = g === 'HIGH' ? 'success' : g === 'MEDIUM' ? 'warning' : 'default'
      return h(NTag, { size: 'small', type }, () => g)
    },
  },
  {
    title: 'CI Low',
    key: 'ci_lower',
    width: 70,
    render: (row: any) => row.ci_lower != null ? (row.ci_lower * 100).toFixed(1) + '%' : '-',
  },
  {
    title: 'CI High',
    key: 'ci_upper',
    width: 70,
    render: (row: any) => row.ci_upper != null ? (row.ci_upper * 100).toFixed(1) + '%' : '-',
  },
  {
    title: 'T+21 Actual',
    key: 'actual_return_d21',
    width: 90,
    sorter: (a: any, b: any) => (a.actual_return_d21 || 0) - (b.actual_return_d21 || 0),
    render: (row: any) => {
      const val = row.actual_return_d21
      if (val == null) return h('span', { style: 'color: #999' }, '-')
      const pct = (val * 100).toFixed(1) + '%'
      const inBounds = row.in_bounds_d21
      let color = '#999'
      if (inBounds === 1) color = '#22c55e' // green — in CI
      else if (inBounds === 0) {
        color = val < (row.worst_case_pct || -999) / 100 ? '#ef4444' : '#f59e0b'
      }
      return h('span', { style: `color: ${color}; font-weight: 600` }, pct)
    },
  },
  {
    title: 'Status',
    key: 'status',
    width: 80,
    render: (row: any) => {
      const s = row.status || 'active'
      const type = s === 'realized' ? 'info' : 'default'
      return h(NTag, { size: 'small', type }, () => s)
    },
    filterOptions: [
      { label: 'Active', value: 'active' },
      { label: 'Realized', value: 'realized' },
    ],
    filter: (value: any, row: any) => row.status === value,
  },
  {
    title: 'Stop',
    key: 'current_stop_price',
    width: 80,
    render: (row: any) => {
      const stop = row.current_stop_price
      if (stop == null || row.status === 'realized') return h('span', { style: 'color: #999' }, '-')
      const phase = row.trailing_phase || 0
      const phaseNames: Record<number, string> = { 0: 'Init', 1: 'BE', 2: 'ATR', 3: 'Tight' }
      const phaseColors: Record<number, string> = { 0: '#94a3b8', 1: '#f59e0b', 2: '#22c55e', 3: '#3b82f6' }
      return h('span', { style: `color: ${phaseColors[phase] || '#999'}; font-weight: 600` },
        `${stop.toFixed(1)} (${phaseNames[phase] || '?'})`)
    },
  },
  {
    title: '+1R',
    key: 'target_1r_price',
    width: 70,
    render: (row: any) => {
      const target = row.target_1r_price
      if (target == null || row.status === 'realized') return h('span', { style: 'color: #999' }, '-')
      const triggered = row.scale_out_triggered
      const color = triggered ? '#a855f7' : '#999'
      const label = triggered ? `${target.toFixed(1)} ✓` : target.toFixed(1)
      return h('span', { style: `color: ${color}; font-weight: ${triggered ? '600' : '400'}` }, label)
    },
  },
  {
    title: 'Live',
    key: 'is_live',
    width: 55,
    render: (row: any) => {
      if (row.is_live) return h('span', { style: 'color: #22c55e; font-weight: 700' }, '✓ Live')
      return h('span', { style: 'color: #d1d5db' }, '-')
    },
  },
  {
    title: 'Slippage',
    key: 'slippage_pct',
    width: 80,
    render: (row: any) => {
      if (!row.is_live || row.actual_entry_price == null || row.entry_price == null) return h('span', { style: 'color: #999' }, '-')
      const slip = ((row.actual_entry_price - row.entry_price) / row.entry_price) * 100
      const color = slip > 0 ? '#ef4444' : slip < 0 ? '#22c55e' : '#999'
      return h('span', { style: `color: ${color}; font-weight: 600` }, slip > 0 ? `+${slip.toFixed(2)}%` : `${slip.toFixed(2)}%`)
    },
  },
  { title: 'Industry', key: 'industry', width: 80 },
  {
    title: '',
    key: 'actions',
    width: 90,
    render: (row: any) => {
      if (row.is_live || row.status === 'realized') return null
      return h(NButton, {
        size: 'tiny',
        type: 'primary',
        ghost: true,
        onClick: () => confirmLive(row),
      }, () => 'Confirm Live')
    },
  },
])

// --- Computed Stats ---
const signalStats = computed(() => {
  const all = signals.value
  const active = all.filter((s: any) => s.status === 'active').length
  const realized = all.filter((s: any) => s.status === 'realized').length
  const inBounds = all.filter((s: any) => s.in_bounds_d21 === 1).length
  const outBounds = all.filter((s: any) => s.in_bounds_d21 === 0).length
  return { total: all.length, active, realized, inBounds, outBounds }
})

const inBoundsRate = computed(() => {
  const r = driftReport.value?.in_bounds
  if (!r || r.in_bounds_rate == null) return null
  return r.in_bounds_rate
})

const inBoundsHealthy = computed(() => driftReport.value?.in_bounds?.healthy ?? true)
const zScoreAlarm = computed(() => driftReport.value?.z_score?.alarm ?? false)
const riskOn = computed(() => riskFlag.value?.global_risk_on ?? true)

// --- Stress Test Columns (Phase 10 P0) ---
const stressColumns = computed<DataTableColumns>(() => [
  { title: 'Code', key: 'stock_code', width: 70 },
  { title: 'Name', key: 'stock_name', width: 90 },
  {
    title: 'Position %',
    key: 'position_pct',
    width: 80,
    render: (row: any) => (row.position_pct * 100).toFixed(1) + '%',
  },
  {
    title: 'Position $',
    key: 'position_value',
    width: 100,
    render: (row: any) => '$' + Math.round(row.position_value).toLocaleString(),
  },
  {
    title: 'Stressed $',
    key: 'stressed_value',
    width: 100,
    render: (row: any) => h('span', { style: 'color: #ef4444; font-weight: 600' },
      '$' + Math.round(row.stressed_value).toLocaleString()),
  },
  {
    title: 'Loss %',
    key: 'loss_pct',
    width: 70,
    render: (row: any) => h('span', { style: 'color: #ef4444; font-weight: 600' },
      '-' + row.loss_pct.toFixed(1) + '%'),
  },
])

// --- War Room Charts (Phase 9 P1) ---
const equityCurveOption = computed(() => {
  if (!warRoom.value?.equity_curve?.length) return null
  const curve = warRoom.value.equity_curve.filter((p: any) => p.date)
  if (!curve.length) return null

  return {
    tooltip: {
      trigger: 'axis',
      formatter: (params: any) => {
        const p = params[0]
        const d = curve[p.dataIndex]
        let tip = `${d.date}<br/>Equity: $${(d.equity / 10000).toFixed(1)}W`
        if (d.stock_code) tip += `<br/>${d.stock_code}: ${d.return_pct > 0 ? '+' : ''}${d.return_pct}%`
        return tip
      },
    },
    grid: { top: 30, right: 20, bottom: 30, left: 60 },
    xAxis: { type: 'category', data: curve.map((p: any) => p.date), axisLabel: { rotate: 45, fontSize: 10 } },
    yAxis: { type: 'value', name: 'Equity (TWD)', axisLabel: { formatter: (v: number) => `${(v / 10000).toFixed(0)}W` } },
    series: [{
      name: 'Equity',
      type: 'line',
      data: curve.map((p: any) => p.equity),
      smooth: true,
      lineStyle: { color: '#3b82f6', width: 2 },
      areaStyle: { color: 'rgba(59,130,246,0.08)' },
      itemStyle: { color: '#3b82f6' },
    }],
  }
})

const drawdownOption = computed(() => {
  if (!warRoom.value?.equity_curve?.length) return null
  const curve = warRoom.value.equity_curve.filter((p: any) => p.date)
  if (!curve.length) return null

  return {
    tooltip: {
      trigger: 'axis',
      formatter: (params: any) => {
        const p = params[0]
        const d = curve[p.dataIndex]
        return `${d.date}<br/>Drawdown: ${d.drawdown_pct.toFixed(2)}%`
      },
    },
    grid: { top: 30, right: 20, bottom: 30, left: 60 },
    xAxis: { type: 'category', data: curve.map((p: any) => p.date), axisLabel: { rotate: 45, fontSize: 10 } },
    yAxis: { type: 'value', name: 'Drawdown %', max: 0 },
    series: [{
      name: 'Drawdown',
      type: 'line',
      data: curve.map((p: any) => p.drawdown_pct),
      smooth: true,
      lineStyle: { color: '#ef4444', width: 2 },
      areaStyle: { color: 'rgba(239,68,68,0.15)' },
      itemStyle: { color: '#ef4444' },
    }],
  }
})

// --- Init ---
onMounted(loadAll)
</script>

<template>
  <div>
    <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 16px">
      <h2 style="margin: 0">Strategy Control Tower</h2>

      <!-- Risk Flag Badge -->
      <NTag
        :type="riskOn ? 'success' : 'error'"
        size="medium"
        round
        style="cursor: pointer"
        @click="toggleRiskFlag"
      >
        {{ riskOn ? 'RISK ON' : 'RISK OFF' }}
      </NTag>

      <!-- Aggressive Index Badge (Phase 10 P1) -->
      <NTooltip v-if="aggIndex" trigger="hover">
        <template #trigger>
          <NTag
            size="medium"
            round
            :color="{ color: aggIndex.color, textColor: '#fff' }"
          >
            {{ aggIndex.score }} {{ aggIndex.regime === 'aggressive' ? 'HOT' : aggIndex.regime === 'defensive' ? 'COLD' : 'WARM' }}
          </NTag>
        </template>
        <div style="max-width: 240px">
          <div style="font-weight: 600; margin-bottom: 4px">Aggressive Index: {{ aggIndex.score }}/100</div>
          <div style="margin-bottom: 4px">{{ aggIndex.advice }}</div>
          <div v-for="(v, k) in aggIndex.breakdown" :key="k" style="font-size: 12px; color: #ccc">
            {{ k }}: {{ v.score }}/{{ v.max }} — {{ v.label }}
          </div>
        </div>
      </NTooltip>

      <!-- Z-Score Alarm -->
      <NTag v-if="zScoreAlarm" type="error" size="small">
        Z-Score ALARM
      </NTag>

      <div style="flex: 1" />

      <NButton size="small" @click="triggerRealize">
        Realize Signals
      </NButton>
      <NButton size="small" type="info" @click="triggerTrailingStops">
        Update Stops
      </NButton>
      <NButton size="small" type="warning" @click="triggerAudit">
        Run Audit
      </NButton>
      <NButton
        size="small"
        type="error"
        strong
        style="animation: pulse-red 2s infinite"
        @click="triggerEmergencyStop"
      >
        EMERGENCY STOP
      </NButton>
    </div>

    <NAlert v-if="error" type="error" style="margin-bottom: 12px" closable @close="error = ''">
      {{ error }}
    </NAlert>

    <!-- Risk Off Warning -->
    <NAlert v-if="!riskOn" type="error" style="margin-bottom: 12px">
      Risk Flag is OFF — Auto-Sim recommendations are suppressed.
      Reason: {{ riskFlag?.reason || 'N/A' }}
    </NAlert>

    <NSpin :show="isLoading">
      <NTabs v-model:value="activeTab" type="line">

        <!-- Tab 1: Signal History -->
        <NTabPane name="signals" tab="Signal Log" display-directive="show:lazy">
          <!-- Summary Cards -->
          <NGrid :cols="5" :x-gap="12" :y-gap="12" style="margin-bottom: 16px">
            <NGi>
              <NCard size="small">
                <NStatistic label="Total Signals" :value="signalStats.total" />
              </NCard>
            </NGi>
            <NGi>
              <NCard size="small">
                <NStatistic label="Active" :value="signalStats.active" />
              </NCard>
            </NGi>
            <NGi>
              <NCard size="small">
                <NStatistic label="Realized" :value="signalStats.realized" />
              </NCard>
            </NGi>
            <NGi>
              <NCard size="small">
                <NStatistic label="In-Bounds" :value="signalStats.inBounds">
                  <template #suffix>
                    <span style="color: #22c55e; font-size: 14px"> / {{ signalStats.inBounds + signalStats.outBounds }}</span>
                  </template>
                </NStatistic>
              </NCard>
            </NGi>
            <NGi>
              <NCard size="small">
                <NStatistic
                  label="In-Bounds Rate"
                  :value="inBoundsRate != null ? (inBoundsRate * 100).toFixed(0) + '%' : 'N/A'"
                >
                  <template #prefix>
                    <span :style="{ color: inBoundsHealthy ? '#22c55e' : '#ef4444' }">
                      {{ inBoundsHealthy ? '' : '' }}
                    </span>
                  </template>
                </NStatistic>
              </NCard>
            </NGi>
          </NGrid>

          <!-- Filter Buttons -->
          <NSpace style="margin-bottom: 12px">
            <NButton
              v-for="f in (['all', 'active', 'realized'] as const)"
              :key="f"
              size="small"
              :type="signalFilter === f ? 'primary' : 'default'"
              @click="signalFilter = f; loadSignals()"
            >
              {{ f === 'all' ? 'All' : f === 'active' ? 'Active' : 'Realized' }}
            </NButton>
          </NSpace>

          <!-- Signal Table -->
          <NDataTable
            v-if="signals.length > 0"
            :columns="signalColumns"
            :data="signals"
            :max-height="500"
            :scroll-x="900"
            size="small"
            striped
            :pagination="{ pageSize: 50 }"
          />
          <NEmpty v-else description="No signals yet. Run Auto-Sim to generate signals." />
        </NTabPane>

        <!-- Tab 2: Drift Dashboard -->
        <NTabPane name="drift" tab="Drift Detection" display-directive="show:lazy">
          <NGrid :cols="2" :x-gap="16" :y-gap="16">
            <!-- In-Bounds Rate Card -->
            <NGi>
              <NCard title="In-Bounds Rate" size="small">
                <template v-if="driftReport?.in_bounds">
                  <div style="text-align: center; margin: 16px 0">
                    <span
                      :style="{
                        fontSize: '48px',
                        fontWeight: 'bold',
                        color: inBoundsHealthy ? '#22c55e' : '#ef4444',
                      }"
                    >
                      {{ inBoundsRate != null ? (inBoundsRate * 100).toFixed(0) + '%' : 'N/A' }}
                    </span>
                    <div style="color: #999; margin-top: 4px">
                      {{ driftReport.in_bounds.in_bounds_count }} / {{ driftReport.in_bounds.total_realized }} realized signals
                    </div>
                  </div>

                  <NGrid :cols="3" :x-gap="8">
                    <NGi>
                      <NStatistic label="Total Realized" :value="driftReport.in_bounds.total_realized" />
                    </NGi>
                    <NGi>
                      <NStatistic label="Above CI" :value="driftReport.in_bounds.above_ci" />
                    </NGi>
                    <NGi>
                      <NStatistic label="Below CI" :value="driftReport.in_bounds.below_ci" />
                    </NGi>
                  </NGrid>

                  <NAlert
                    v-if="!inBoundsHealthy"
                    type="warning"
                    style="margin-top: 12px"
                  >
                    In-Bounds Rate below 60% threshold. Post-mortem analysis recommended.
                  </NAlert>
                </template>
                <NEmpty v-else description="No realized signals yet" />
              </NCard>
            </NGi>

            <!-- Z-Score Failure Card -->
            <NGi>
              <NCard title="Z-Score Failure Detection" size="small">
                <template v-if="driftReport?.z_score">
                  <div style="text-align: center; margin: 16px 0">
                    <span
                      :style="{
                        fontSize: '48px',
                        fontWeight: 'bold',
                        color: zScoreAlarm ? '#ef4444' : '#22c55e',
                      }"
                    >
                      {{ driftReport.z_score.max_consecutive }}
                    </span>
                    <div style="color: #999; margin-top: 4px">
                      Max Consecutive Worst-Case Breaches
                    </div>
                  </div>

                  <NGrid :cols="2" :x-gap="8">
                    <NGi>
                      <NStatistic label="Current Streak" :value="driftReport.z_score.consecutive_breaches" />
                    </NGi>
                    <NGi>
                      <NStatistic label="Alarm Threshold" value="3" />
                    </NGi>
                  </NGrid>

                  <NAlert
                    v-if="zScoreAlarm"
                    type="error"
                    style="margin-top: 12px"
                  >
                    MODEL FAILURE: {{ driftReport.z_score.max_consecutive }} consecutive signals breached worst-case scenario.
                  </NAlert>

                  <!-- Breach signal list -->
                  <div v-if="driftReport.z_score.breach_signals.length > 0" style="margin-top: 12px">
                    <h4 style="margin: 0 0 8px">Recent Breaches</h4>
                    <div
                      v-for="bs in driftReport.z_score.breach_signals.slice(-5)"
                      :key="bs.stock_code + bs.signal_date"
                      style="font-size: 12px; color: #ef4444; margin-bottom: 4px"
                    >
                      {{ bs.signal_date }} {{ bs.stock_code }}: actual {{ bs.actual }}% vs worst {{ bs.worst_case }}%
                    </div>
                  </div>
                </template>
                <NEmpty v-else description="No data" />
              </NCard>
            </NGi>

            <!-- Risk Flag Card -->
            <NGi>
              <NCard title="Risk Flag Status" size="small">
                <div style="text-align: center; margin: 16px 0">
                  <NTag
                    :type="riskOn ? 'success' : 'error'"
                    size="large"
                    round
                  >
                    {{ riskOn ? 'RISK ON — Signals Active' : 'RISK OFF — Signals Suppressed' }}
                  </NTag>
                </div>
                <div v-if="riskFlag" style="font-size: 12px; color: #999; text-align: center">
                  <div>Reason: {{ riskFlag.reason || 'default' }}</div>
                  <div v-if="riskFlag.updated_at">Updated: {{ riskFlag.updated_at }}</div>
                </div>
                <div style="text-align: center; margin-top: 12px">
                  <NButton
                    :type="riskOn ? 'error' : 'success'"
                    size="small"
                    @click="toggleRiskFlag"
                  >
                    {{ riskOn ? 'Force Risk OFF' : 'Re-enable Risk ON' }}
                  </NButton>
                </div>
              </NCard>
            </NGi>

            <!-- Audit Actions Card -->
            <NGi>
              <NCard title="Audit Actions" size="small">
                <NSpace vertical>
                  <NButton block @click="triggerRealize">
                    Realize Active Signals (Backfill Returns)
                  </NButton>
                  <NButton block type="warning" @click="triggerAudit">
                    Run Full Weekly Audit
                  </NButton>
                  <NButton block @click="loadAll">
                    Refresh All Data
                  </NButton>
                </NSpace>
                <div style="margin-top: 12px; font-size: 12px; color: #999">
                  Weekly audit runs automatically every Saturday 09:00.
                  Realize runs daily as part of the 8-step pipeline.
                </div>
              </NCard>
            </NGi>
          </NGrid>

          <!-- Failure Analysis Section (P6-P2) -->
          <NCard v-if="failures.length > 0" title="Failure Post-Mortem (Worst Case Breaches)" size="small" style="margin-top: 16px">
            <div v-for="f in failures" :key="f.stock_code + f.signal_date" style="margin-bottom: 12px; padding: 8px; border: 1px solid #e5e7eb; border-radius: 6px">
              <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px">
                <NTag
                  :type="f.category === 'SYSTEMIC' ? 'error' : f.category === 'EARNINGS' ? 'warning' : f.category === 'NEWS' ? 'info' : 'default'"
                  size="small"
                >
                  {{ f.category }}
                </NTag>
                <strong>{{ f.stock_code }}</strong>
                <span style="color: #999; font-size: 12px">{{ f.signal_date }}</span>
              </div>
              <div style="font-size: 13px; margin-bottom: 4px">{{ f.summary }}</div>
              <div style="font-size: 12px; color: #666; font-family: monospace">
                Entry: {{ f.physical_data.entry_price.toFixed(1) }} |
                Exit: {{ f.physical_data.exit_price.toFixed(1) }} |
                Actual: {{ f.physical_data.actual_pct.toFixed(1) }}% |
                Worst: {{ f.physical_data.worst_case_pct.toFixed(1) }}% |
                Excess: {{ f.physical_data.excess_loss_pct.toFixed(1) }}pp
                <span v-if="f.physical_data.atr_at_entry">| ATR: {{ f.physical_data.atr_at_entry.toFixed(2) }}</span>
              </div>
              <div v-if="f.evidence.length > 0" style="margin-top: 4px; font-size: 12px; color: #ef4444">
                <div v-for="(ev, i) in f.evidence" :key="i">{{ ev }}</div>
              </div>
            </div>
          </NCard>

          <!-- Missed Opportunities Log (Phase 7 P2) -->
          <NCard v-if="missedOpps.length > 0" title="Missed Opportunities (Energy Score Filtered)" size="small" style="margin-top: 16px">
            <div style="font-size: 12px; color: #999; margin-bottom: 8px">
              Signals penalized by Energy Score filter. Review to assess: bullets or bombs?
            </div>
            <div style="overflow-x: auto">
              <table style="width: 100%; border-collapse: collapse; font-size: 13px">
                <thead>
                  <tr style="border-bottom: 2px solid #e5e7eb; text-align: left">
                    <th style="padding: 6px 8px">Date</th>
                    <th style="padding: 6px 8px">Code</th>
                    <th style="padding: 6px 8px">Name</th>
                    <th style="padding: 6px 8px">Tier</th>
                    <th style="padding: 6px 8px">Raw</th>
                    <th style="padding: 6px 8px">Final</th>
                    <th style="padding: 6px 8px">TR Ratio</th>
                    <th style="padding: 6px 8px">Vol Ratio</th>
                    <th style="padding: 6px 8px">Reason</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="m in missedOpps"
                    :key="m.stock_code + m.signal_date"
                    style="border-bottom: 1px solid #f3f4f6"
                  >
                    <td style="padding: 4px 8px">{{ m.signal_date }}</td>
                    <td style="padding: 4px 8px; font-weight: 600">{{ m.stock_code }}</td>
                    <td style="padding: 4px 8px">{{ m.stock_name }}</td>
                    <td style="padding: 4px 8px">
                      <NTag size="tiny" :type="m.tier === 'sniper' ? 'success' : m.tier === 'tactical' ? 'warning' : 'default'">
                        {{ m.tier }}
                      </NTag>
                    </td>
                    <td style="padding: 4px 8px; text-decoration: line-through; color: #999">{{ m.raw_score }}</td>
                    <td style="padding: 4px 8px; font-weight: 600">{{ m.final_score }}</td>
                    <td style="padding: 4px 8px; font-family: monospace">
                      <span :style="{ color: m.tr_ratio && m.tr_ratio > 2.5 ? '#ef4444' : '#666' }">
                        {{ m.tr_ratio != null ? m.tr_ratio.toFixed(1) : '-' }}
                      </span>
                    </td>
                    <td style="padding: 4px 8px; font-family: monospace">
                      <span :style="{ color: m.vol_ratio != null && m.vol_ratio < 1.5 ? '#f59e0b' : '#666' }">
                        {{ m.vol_ratio != null ? m.vol_ratio.toFixed(1) : '-' }}
                      </span>
                    </td>
                    <td style="padding: 4px 8px; font-size: 11px; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap">
                      {{ m.filter_reason }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </NCard>
        </NTabPane>

        <!-- Tab 3: Pipeline Monitor -->
        <NTabPane name="pipeline" tab="Pipeline Monitor" display-directive="show:lazy">
          <template v-if="pipeline">
            <!-- Overall Health Banner -->
            <NAlert
              :type="pipeline.overall === 'healthy' ? 'success' : pipeline.overall === 'degraded' ? 'warning' : 'error'"
              style="margin-bottom: 16px"
            >
              Pipeline Status: <strong>{{ pipeline.overall.toUpperCase() }}</strong>
              — {{ pipeline.fresh_count }} / {{ pipeline.total_count }} files fresh
              <span style="margin-left: 12px; font-size: 12px; color: #999">
                Checked: {{ pipeline.checked_at?.slice(0, 19) }}
              </span>
            </NAlert>

            <!-- File Freshness Table -->
            <NCard title="Data File Freshness" size="small" style="margin-bottom: 16px">
              <div style="overflow-x: auto">
                <table style="width: 100%; border-collapse: collapse; font-size: 13px">
                  <thead>
                    <tr style="border-bottom: 2px solid #e5e7eb; text-align: left">
                      <th style="padding: 8px 12px">Status</th>
                      <th style="padding: 8px 12px">File</th>
                      <th style="padding: 8px 12px">Last Modified</th>
                      <th style="padding: 8px 12px">Age (hrs)</th>
                      <th style="padding: 8px 12px">Size</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr
                      v-for="f in pipeline.files"
                      :key="f.key"
                      style="border-bottom: 1px solid #f3f4f6"
                    >
                      <td style="padding: 6px 12px">
                        <NTag
                          :type="f.status === 'fresh' ? 'success' : f.status === 'stale' ? 'warning' : 'error'"
                          size="small"
                        >
                          {{ f.status }}
                        </NTag>
                      </td>
                      <td style="padding: 6px 12px">{{ f.description }}</td>
                      <td style="padding: 6px 12px; font-family: monospace; font-size: 12px">
                        {{ f.last_modified ? f.last_modified.slice(0, 19).replace('T', ' ') : '-' }}
                      </td>
                      <td style="padding: 6px 12px">
                        <span
                          :style="{ color: f.stale ? '#ef4444' : '#22c55e', fontWeight: '600' }"
                        >
                          {{ f.age_hours != null ? f.age_hours.toFixed(1) : '-' }}
                        </span>
                      </td>
                      <td style="padding: 6px 12px">
                        {{ f.size_mb != null ? f.size_mb.toFixed(2) + ' MB' : '-' }}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </NCard>

            <!-- Scheduler Heartbeat -->
            <NCard title="Scheduler Heartbeat" size="small">
              <template v-if="pipeline.scheduler && Object.keys(pipeline.scheduler).length > 0">
                <div style="overflow-x: auto">
                  <table style="width: 100%; border-collapse: collapse; font-size: 13px">
                    <thead>
                      <tr style="border-bottom: 2px solid #e5e7eb; text-align: left">
                        <th style="padding: 8px 12px">Job</th>
                        <th style="padding: 8px 12px">Last Run</th>
                        <th style="padding: 8px 12px">Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr
                        v-for="(val, key) in pipeline.scheduler"
                        :key="key"
                        style="border-bottom: 1px solid #f3f4f6"
                      >
                        <td style="padding: 6px 12px; font-weight: 500">{{ key }}</td>
                        <td style="padding: 6px 12px; font-family: monospace; font-size: 12px">
                          {{ typeof val === 'string' ? val.slice(0, 19).replace('T', ' ') : val?.last_run?.slice(0, 19)?.replace('T', ' ') || '-' }}
                        </td>
                        <td style="padding: 6px 12px">
                          <NTag
                            :type="typeof val === 'object' && val?.status === 'error' ? 'error' : 'success'"
                            size="small"
                          >
                            {{ typeof val === 'object' ? (val?.status || 'ok') : 'ok' }}
                          </NTag>
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </template>
              <NEmpty v-else description="No scheduler heartbeat data yet" />
            </NCard>

            <!-- Self-Healed Events (Phase 8 P0) -->
            <NCard v-if="healedEvents && (healedEvents.total_healed > 0 || healedEvents.total_flagged > 0)" title="Self-Healed Events" size="small" style="margin-top: 16px">
              <NGrid :cols="3" :x-gap="12" style="margin-bottom: 12px">
                <NGi>
                  <NStatistic label="Total Healed" :value="healedEvents.total_healed" />
                </NGi>
                <NGi>
                  <NStatistic label="Total Flagged" :value="healedEvents.total_flagged" />
                </NGi>
                <NGi>
                  <div style="font-size: 12px; color: #999">
                    Last Run: {{ healedEvents.last_run?.slice(0, 19).replace('T', ' ') || 'N/A' }}
                  </div>
                </NGi>
              </NGrid>
              <div v-if="healedEvents.events.length > 0" style="font-size: 12px">
                <div
                  v-for="(ev, i) in healedEvents.events.slice(-10)"
                  :key="i"
                  style="padding: 2px 0; border-bottom: 1px solid #f3f4f6"
                >
                  <NTag :type="ev.action === 'healed' ? 'success' : 'warning'" size="tiny">{{ ev.action }}</NTag>
                  <strong style="margin-left: 6px">{{ ev.stock_code }}</strong>
                  <span style="color: #999; margin-left: 4px">{{ ev.date }}</span>
                  <span :style="{ color: '#ef4444', marginLeft: '4px' }">{{ ev.original_change_pct }}%</span>
                  <span v-if="ev.healed_price" style="color: #22c55e; margin-left: 4px">
                    → {{ ev.healed_price.toFixed(1) }}
                  </span>
                </div>
              </div>
            </NCard>

            <div style="text-align: right; margin-top: 12px">
              <NButton size="small" @click="loadPipeline">
                Refresh Pipeline Status
              </NButton>
            </div>
          </template>
          <NEmpty v-else description="Loading pipeline status..." />
        </NTabPane>

        <!-- Tab 4: Sector Heatmap -->
        <NTabPane name="sector" tab="Sector Rotation" display-directive="show:lazy">
          <template v-if="sectorData && sectorData.sectors.length > 0">
            <!-- Top 3 Banner -->
            <NAlert type="info" style="margin-bottom: 16px">
              Top 3 Sectors (Auto-Sim +5 bonus):
              <strong v-for="(s, i) in sectorData.top3" :key="s">
                {{ s }}{{ i < 2 ? ' | ' : '' }}
              </strong>
            </NAlert>

            <!-- Sector Bar Chart -->
            <NCard title="Sector RS Ranking" size="small">
              <div v-for="sector in sectorData.sectors" :key="sector.name" style="margin-bottom: 6px">
                <div style="display: flex; align-items: center; gap: 8px">
                  <div style="width: 100px; font-size: 12px; text-align: right; flex-shrink: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap">
                    {{ sector.name }}
                  </div>
                  <div style="flex: 1; height: 22px; background: #f3f4f6; border-radius: 4px; overflow: hidden; position: relative">
                    <div
                      :style="{
                        width: Math.min(sector.median_rs, 100) + '%',
                        height: '100%',
                        borderRadius: '4px',
                        background: sector.median_rs >= 70 ? 'linear-gradient(90deg, #22c55e, #16a34a)' :
                                    sector.median_rs >= 50 ? 'linear-gradient(90deg, #f59e0b, #d97706)' :
                                    sector.median_rs >= 30 ? 'linear-gradient(90deg, #94a3b8, #64748b)' :
                                    'linear-gradient(90deg, #ef4444, #dc2626)',
                        transition: 'width 0.3s',
                      }"
                    />
                    <span style="position: absolute; top: 2px; left: 8px; font-size: 11px; font-weight: 600; color: #fff; text-shadow: 0 1px 2px rgba(0,0,0,0.5)">
                      RS {{ sector.median_rs.toFixed(0) }}
                    </span>
                  </div>
                  <div style="width: 60px; font-size: 11px; color: #999; flex-shrink: 0">
                    {{ sector.count }} stocks
                  </div>
                  <div style="width: 50px; flex-shrink: 0">
                    <NTag v-if="sectorData.top3.includes(sector.name)" type="success" size="tiny">TOP</NTag>
                  </div>
                </div>
              </div>
            </NCard>

            <!-- Diamond Distribution -->
            <NCard title="Diamond Concentration" size="small" style="margin-top: 16px">
              <NGrid :cols="4" :x-gap="8" :y-gap="8">
                <NGi v-for="sector in sectorData.sectors.filter(s => s.diamond_count > 0)" :key="sector.name">
                  <div style="text-align: center; padding: 8px; border: 1px solid #e5e7eb; border-radius: 6px">
                    <div style="font-size: 11px; color: #999; margin-bottom: 2px">{{ sector.name }}</div>
                    <div style="font-size: 18px; font-weight: 700; color: #a855f7">{{ sector.diamond_count }}</div>
                    <div style="font-size: 10px; color: #666">{{ (sector.diamond_pct * 100).toFixed(0) }}% Diamond</div>
                  </div>
                </NGi>
              </NGrid>
            </NCard>

            <div style="text-align: right; margin-top: 12px">
              <NButton size="small" @click="loadSectorHeatmap">
                Refresh Sector Data
              </NButton>
            </div>
          </template>
          <NEmpty v-else description="Loading sector data..." />
        </NTabPane>

        <!-- Tab 5: War Room (Phase 9 P1) -->
        <NTabPane name="warroom" tab="War Room" display-directive="show:lazy">
          <template v-if="warRoom">
            <!-- Virtual Label -->
            <NAlert type="info" style="margin-bottom: 12px">
              {{ warRoom.label }} — Assumes every Auto-Sim recommendation was followed with system-computed position sizing.
            </NAlert>

            <!-- MDD Warning -->
            <NAlert v-if="warRoom.mdd_warning" type="error" style="margin-bottom: 12px">
              Max Drawdown exceeds 15% threshold — system volatility is high. Consider reducing position sizes.
            </NAlert>

            <!-- Summary Cards -->
            <NGrid :cols="4" :x-gap="12" :y-gap="12" style="margin-bottom: 16px">
              <NGi>
                <NCard size="small">
                  <NStatistic label="Total Signals" :value="warRoom.total_trades">
                    <template #suffix>
                      <span style="color: #999; font-size: 12px"> ({{ warRoom.active_count }} active)</span>
                    </template>
                  </NStatistic>
                </NCard>
              </NGi>
              <NGi>
                <NCard size="small">
                  <NStatistic label="System Win Rate" :value="warRoom.win_rate + '%'">
                    <template #prefix>
                      <span :style="{ color: warRoom.win_rate >= 50 ? '#22c55e' : '#ef4444' }">
                        {{ warRoom.win_rate >= 50 ? '' : '' }}
                      </span>
                    </template>
                  </NStatistic>
                </NCard>
              </NGi>
              <NGi>
                <NCard size="small">
                  <NStatistic
                    label="Virtual Expectancy"
                    :value="'$' + Math.abs(warRoom.expectancy).toLocaleString()"
                  >
                    <template #prefix>
                      <span :style="{ color: warRoom.expectancy >= 0 ? '#22c55e' : '#ef4444' }">
                        {{ warRoom.expectancy >= 0 ? '+' : '-' }}
                      </span>
                    </template>
                    <template #suffix>
                      <span style="color: #999; font-size: 12px"> /trade</span>
                    </template>
                  </NStatistic>
                </NCard>
              </NGi>
              <NGi>
                <NCard size="small">
                  <NStatistic label="Max Drawdown" :value="warRoom.max_drawdown_pct + '%'">
                    <template #prefix>
                      <span :style="{ color: warRoom.mdd_warning ? '#ef4444' : '#f59e0b' }">
                        {{ warRoom.mdd_warning ? '' : '' }}
                      </span>
                    </template>
                  </NStatistic>
                </NCard>
              </NGi>
            </NGrid>

            <!-- Return Summary -->
            <NGrid :cols="2" :x-gap="12" :y-gap="12" style="margin-bottom: 16px">
              <NGi>
                <NCard size="small">
                  <div style="text-align: center">
                    <div style="color: #999; font-size: 12px">Initial Capital</div>
                    <div style="font-size: 20px; font-weight: 600">
                      ${{ (warRoom.initial_equity / 10000).toFixed(0) }}W
                    </div>
                  </div>
                </NCard>
              </NGi>
              <NGi>
                <NCard size="small">
                  <div style="text-align: center">
                    <div style="color: #999; font-size: 12px">Virtual Final Equity</div>
                    <div :style="{ fontSize: '20px', fontWeight: '600', color: warRoom.total_return_pct >= 0 ? '#22c55e' : '#ef4444' }">
                      ${{ (warRoom.final_equity / 10000).toFixed(0) }}W
                      <span style="font-size: 14px">({{ warRoom.total_return_pct >= 0 ? '+' : '' }}{{ warRoom.total_return_pct }}%)</span>
                    </div>
                  </div>
                </NCard>
              </NGi>
            </NGrid>

            <!-- Equity Curve Chart -->
            <NCard title="Cumulative Equity Curve" size="small" style="margin-bottom: 16px">
              <VChart v-if="equityCurveOption" :option="equityCurveOption" style="height: 320px" autoresize />
              <NEmpty v-else description="Not enough realized signals for equity curve" />
            </NCard>

            <!-- Drawdown Chart -->
            <NCard title="Drawdown Analysis" size="small" style="margin-bottom: 16px">
              <VChart v-if="drawdownOption" :option="drawdownOption" style="height: 200px" autoresize />
              <NEmpty v-else description="No drawdown data" />
            </NCard>

            <!-- Stress Test Overlay (Phase 10 P0) -->
            <NCard size="small" style="margin-bottom: 16px">
              <template #header>
                <div style="display: flex; align-items: center; gap: 12px">
                  <span>Stress Test — Black Swan Scenario</span>
                  <NButton
                    size="tiny"
                    :type="stressMode ? 'error' : 'default'"
                    @click="stressMode = !stressMode; if (stressMode && !stressTest) loadStressTest()"
                  >
                    {{ stressMode ? 'Hide Stress Test' : 'Show Stress Test' }}
                  </NButton>
                </div>
              </template>

              <template v-if="stressMode && stressTest">
                <!-- Bust Warning -->
                <NAlert v-if="stressTest.is_bust" type="error" style="margin-bottom: 12px">
                  BUST ALERT: Under this scenario, portfolio drops below {{ stressTest.bust_threshold_pct }}% of initial capital.
                  Recovery requires +{{ stressTest.recovery_needed_pct }}% gain.
                </NAlert>

                <div style="margin-bottom: 8px; color: #999; font-size: 12px">
                  {{ stressTest.scenario }}
                </div>

                <NGrid :cols="4" :x-gap="12" :y-gap="12" style="margin-bottom: 12px">
                  <NGi>
                    <div style="text-align: center">
                      <div style="color: #999; font-size: 11px">Positions at Risk</div>
                      <div style="font-size: 18px; font-weight: 600">{{ stressTest.positions_at_risk }}</div>
                    </div>
                  </NGi>
                  <NGi>
                    <div style="text-align: center">
                      <div style="color: #999; font-size: 11px">Total Exposure</div>
                      <div style="font-size: 18px; font-weight: 600">{{ stressTest.exposure_pct }}%</div>
                    </div>
                  </NGi>
                  <NGi>
                    <div style="text-align: center">
                      <div style="color: #999; font-size: 11px">Stressed Equity</div>
                      <div :style="{ fontSize: '18px', fontWeight: '600', color: stressTest.is_bust ? '#ef4444' : '#f59e0b' }">
                        ${{ (stressTest.stressed_equity / 10000).toFixed(0) }}W
                      </div>
                    </div>
                  </NGi>
                  <NGi>
                    <div style="text-align: center">
                      <div style="color: #999; font-size: 11px">Max Loss</div>
                      <div :style="{ fontSize: '18px', fontWeight: '600', color: stressTest.total_loss_pct > 15 ? '#ef4444' : '#f59e0b' }">
                        -{{ stressTest.total_loss_pct }}%
                      </div>
                    </div>
                  </NGi>
                </NGrid>

                <!-- Per-Position Stress Details -->
                <NDataTable
                  v-if="stressTest.per_position_details.length > 0"
                  :columns="stressColumns"
                  :data="stressTest.per_position_details"
                  size="small"
                  :max-height="200"
                  striped
                />

                <div style="margin-top: 8px; text-align: right">
                  <NButton size="tiny" @click="loadStressTest()">Refresh Stress Test</NButton>
                </div>
              </template>

              <template v-else-if="!stressMode">
                <div style="color: #999; font-size: 12px; text-align: center; padding: 8px">
                  Toggle "Show Stress Test" to simulate a Flash Crash scenario on current positions.
                </div>
              </template>
            </NCard>

            <div style="text-align: right">
              <NButton size="small" @click="loadWarRoom()">
                Refresh War Room
              </NButton>
            </div>
          </template>
          <NEmpty v-else description="Loading war room data..." />
        </NTabPane>

      </NTabs>
    </NSpin>
  </div>
</template>

<style scoped>
@keyframes pulse-red {
  0%, 100% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.4); }
  50% { box-shadow: 0 0 0 6px rgba(239, 68, 68, 0); }
}
</style>
