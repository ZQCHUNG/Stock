<script setup lang="ts">
import { ref, computed, onMounted, h } from 'vue'
import {
  NCard, NButton, NTag, NGrid, NGi, NSpin, NStatistic, NSpace,
  NAlert, NEmpty, NDataTable, NTabs, NTabPane, NTooltip,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { systemApi } from '../api/system'
import type { DriftReport, RiskFlag, PipelineMonitor } from '../api/system'

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

async function loadAll() {
  await Promise.all([loadSignals(), loadDrift(), loadRiskFlag(), loadPipeline()])
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
  { title: 'Industry', key: 'industry', width: 80 },
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

      <!-- Z-Score Alarm -->
      <NTag v-if="zScoreAlarm" type="error" size="small">
        Z-Score ALARM
      </NTag>

      <div style="flex: 1" />

      <NButton size="small" @click="triggerRealize">
        Realize Signals
      </NButton>
      <NButton size="small" type="warning" @click="triggerAudit">
        Run Audit
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
                  Realize runs daily as part of the 7-step pipeline.
                </div>
              </NCard>
            </NGi>
          </NGrid>
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

            <div style="text-align: right; margin-top: 12px">
              <NButton size="small" @click="loadPipeline">
                Refresh Pipeline Status
              </NButton>
            </div>
          </template>
          <NEmpty v-else description="Loading pipeline status..." />
        </NTabPane>

      </NTabs>
    </NSpin>
  </div>
</template>
