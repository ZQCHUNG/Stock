<script setup lang="ts">
/**
 * ExceptionDashboard — R89: Risk Exception Cards
 *
 * [APPROVED — Architect Critic Maiden Voyage prep]
 *
 * 6 exception cards from /api/system/exception-dashboard:
 * 1. Market Guard — circuit breaker level
 * 2. Heat & Concentration — sector / ATR risk
 * 3. Signal Drift — SQS degradation on held stocks
 * 4. Liquidity Trap — days to exit > 3
 * 5. Price Gap — TAIEX gap-down alert
 * 6. Data Health — fetcher freshness
 */
import { ref, computed, onMounted } from 'vue'
import { NCard, NGrid, NGi, NTag, NSpace, NText, NSpin, NCollapse, NCollapseItem, NButton, NPopconfirm, useMessage } from 'naive-ui'
import { systemApi } from '../api/system'

const message = useMessage()
const loading = ref(true)
const stopping = ref(false)
const data = ref<any>(null)
const error = ref('')

async function loadExceptions() {
  loading.value = true
  error.value = ''
  try {
    data.value = await systemApi.exceptionDashboard()
  } catch (e: any) {
    error.value = e?.message || 'Failed to load'
    data.value = null
  }
  loading.value = false
}

onMounted(loadExceptions)

// Count total active alerts
const alertCount = computed(() => {
  if (!data.value) return 0
  let count = 0
  for (const key of ['market_guard', 'heat_concentration', 'signal_drift', 'liquidity_trap', 'price_gap', 'data_health']) {
    if (data.value[key]?.is_alert) count++
  }
  return count
})

const mg = computed(() => data.value?.market_guard || {})
const heat = computed(() => data.value?.heat_concentration || {})
const drift = computed(() => data.value?.signal_drift || {})
const liq = computed(() => data.value?.liquidity_trap || {})
const gap = computed(() => data.value?.price_gap || {})
const health = computed(() => data.value?.data_health || {})

function guardColor(level: number): string {
  if (level >= 2) return '#dc2626' // LOCKDOWN
  if (level >= 1) return '#f59e0b' // CAUTION
  return '#22c55e'                 // NORMAL
}

function guardLabel(level: number): string {
  if (level >= 2) return 'LOCKDOWN'
  if (level >= 1) return 'CAUTION'
  return 'NORMAL'
}

// R91: Emergency Stop
async function triggerEmergencyStop() {
  stopping.value = true
  try {
    const result = await systemApi.emergencyStop()
    message.warning('Emergency Stop executed. Scheduler halted.', { duration: 10000 })
    // Reload to show updated state
    await loadExceptions()
  } catch (e: any) {
    message.error(`Emergency Stop failed: ${e?.message || 'Unknown error'}`)
  }
  stopping.value = false
}
</script>

<template>
  <NCollapse :default-expanded-names="alertCount > 0 ? ['exceptions'] : []">
    <NCollapseItem name="exceptions">
      <template #header>
        <NSpace align="center" :size="8">
          <NText style="font-weight: 700; font-size: 14px">Exception Monitor</NText>
          <NTag v-if="alertCount > 0" type="error" size="small" :bordered="false" round>
            {{ alertCount }} alert{{ alertCount > 1 ? 's' : '' }}
          </NTag>
          <NTag v-else-if="!loading && data" type="success" size="small" :bordered="false" round>
            All Clear
          </NTag>
        </NSpace>
      </template>

      <!-- Emergency Stop Button -->
      <div style="display: flex; justify-content: flex-end; margin-bottom: 8px">
        <NPopconfirm @positive-click="triggerEmergencyStop">
          <template #trigger>
            <NButton type="error" size="small" ghost :loading="stopping">
              Emergency Stop
            </NButton>
          </template>
          Are you sure? This will stop all automated trading immediately.
        </NPopconfirm>
      </div>

      <NSpin :show="loading" size="small">
        <div v-if="error" style="color: #dc2626; font-size: 12px; padding: 8px">{{ error }}</div>

        <NGrid v-else-if="data" :cols="3" :x-gap="10" :y-gap="10" responsive="screen" :collapsed-rows="2">
          <!-- 1. Market Guard -->
          <NGi>
            <div class="exc-card" :class="{ 'exc-alert': mg.is_alert }">
              <div class="exc-header">
                <span class="exc-icon">{{ mg.is_alert ? '\u26A0' : '\u2714' }}</span>
                <span class="exc-title">Market Guard</span>
              </div>
              <NTag size="small" :bordered="false"
                :color="{ textColor: '#fff', color: guardColor(mg.level || 0) }">
                {{ guardLabel(mg.level || 0) }}
              </NTag>
              <div class="exc-detail">{{ mg.detail || '-' }}</div>
              <div v-if="mg.taiex_close" class="exc-sub">
                TAIEX {{ mg.taiex_close?.toLocaleString() }}
                <span v-if="mg.exposure_limit != null"> | Exp {{ (mg.exposure_limit * 100).toFixed(0) }}%</span>
              </div>
            </div>
          </NGi>

          <!-- 2. Heat & Concentration -->
          <NGi>
            <div class="exc-card" :class="{ 'exc-alert': heat.is_alert }">
              <div class="exc-header">
                <span class="exc-icon">{{ heat.is_alert ? '\u26A0' : '\u2714' }}</span>
                <span class="exc-title">Heat & Concentration</span>
              </div>
              <div v-if="heat.is_alert" class="exc-alerts">
                <div v-for="(a, i) in (heat.alerts || [])" :key="i" class="exc-alert-item">{{ a }}</div>
              </div>
              <div class="exc-detail">{{ heat.detail || '-' }}</div>
              <div v-if="heat.max_sector_name" class="exc-sub">
                Top: {{ heat.max_sector_name }} {{ ((heat.max_sector_pct || 0) * 100).toFixed(0) }}%
                | Risk {{ ((heat.total_risk_pct || 0) * 100).toFixed(1) }}%
              </div>
            </div>
          </NGi>

          <!-- 3. Signal Drift -->
          <NGi>
            <div class="exc-card" :class="{ 'exc-alert': drift.is_alert }">
              <div class="exc-header">
                <span class="exc-icon">{{ drift.is_alert ? '\u26A0' : '\u2714' }}</span>
                <span class="exc-title">Signal Drift</span>
              </div>
              <div class="exc-detail">{{ drift.detail || '-' }}</div>
              <div v-if="drift.drifted?.length" style="margin-top: 4px">
                <div v-for="d in drift.drifted.slice(0, 3)" :key="d.code" class="exc-sub">
                  {{ d.code }} {{ d.name }}: {{ d.entry_sqs }} → {{ d.current_sqs }} (-{{ d.drift }})
                </div>
                <div v-if="drift.drifted.length > 3" class="exc-sub" style="color: #999">
                  +{{ drift.drifted.length - 3 }} more
                </div>
              </div>
            </div>
          </NGi>

          <!-- 4. Liquidity Trap -->
          <NGi>
            <div class="exc-card" :class="{ 'exc-alert': liq.is_alert }">
              <div class="exc-header">
                <span class="exc-icon">{{ liq.is_alert ? '\u26A0' : '\u2714' }}</span>
                <span class="exc-title">Liquidity Trap</span>
              </div>
              <div class="exc-detail">{{ liq.detail || '-' }}</div>
              <div v-if="liq.trapped?.length" style="margin-top: 4px">
                <div v-for="t in liq.trapped.slice(0, 3)" :key="t.code" class="exc-sub">
                  {{ t.code }}: {{ t.days_to_exit }}d to exit ({{ t.lots }} lots)
                </div>
                <div v-if="liq.trapped.length > 3" class="exc-sub" style="color: #999">
                  +{{ liq.trapped.length - 3 }} more
                </div>
              </div>
            </div>
          </NGi>

          <!-- 5. Price Gap -->
          <NGi>
            <div class="exc-card" :class="{ 'exc-alert': gap.is_alert }">
              <div class="exc-header">
                <span class="exc-icon">{{ gap.is_alert ? '\u26A0' : '\u2714' }}</span>
                <span class="exc-title">Price Gap</span>
              </div>
              <div class="exc-detail">{{ gap.detail || '-' }}</div>
              <div v-if="gap.gap_pct != null" class="exc-sub">
                Gap: {{ (gap.gap_pct * 100).toFixed(2) }}%
              </div>
            </div>
          </NGi>

          <!-- 6. Data Health -->
          <NGi>
            <div class="exc-card" :class="{ 'exc-alert': health.is_alert }">
              <div class="exc-header">
                <span class="exc-icon">{{ health.is_alert ? '\u26A0' : '\u2714' }}</span>
                <span class="exc-title">Data Health</span>
              </div>
              <NTag size="small" :bordered="false"
                :type="health.overall === 'PASS' ? 'success' : health.overall === 'FAIL' ? 'error' : 'warning'">
                {{ health.overall || '-' }}
              </NTag>
              <div class="exc-detail">{{ health.detail || '-' }}</div>
              <div v-if="health.checks?.length" style="margin-top: 4px">
                <div v-for="c in health.checks.filter((x: any) => x.status !== 'PASS').slice(0, 3)" :key="c.name"
                     class="exc-sub" style="color: #dc2626">
                  {{ c.name }}: {{ c.status }} — {{ c.detail }}
                </div>
              </div>
            </div>
          </NGi>
        </NGrid>
      </NSpin>
    </NCollapseItem>
  </NCollapse>
</template>

<style scoped>
.exc-card {
  background: var(--card-bg, #fff);
  border: 1px solid var(--card-border, #e5e7eb);
  border-radius: 8px;
  padding: 10px 12px;
  min-height: 80px;
}
.exc-card.exc-alert {
  border-color: #fca5a5;
  background: #fef2f2;
}
.exc-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}
.exc-icon { font-size: 14px; }
.exc-title { font-size: 12px; font-weight: 700; color: var(--text-primary, #333); }
.exc-detail { font-size: 11px; color: var(--text-muted, #666); margin-top: 4px; }
.exc-sub { font-size: 10px; color: var(--text-dimmed, #999); margin-top: 2px; }
.exc-alerts { margin-top: 2px; }
.exc-alert-item { font-size: 11px; color: #dc2626; font-weight: 600; }
</style>
