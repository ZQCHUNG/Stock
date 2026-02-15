<script setup lang="ts">
import { h, ref, onMounted } from 'vue'
import {
  NCard, NButton, NSpace, NInputNumber, NSwitch, NInput, NTag, NAlert,
  NDataTable, NGrid, NGi, NSpin, NDivider, NStatistic,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { alertsApi, type AlertConfig, type SchedulerStatus, type CompoundRule, type CompoundCondition, type ConditionTypeOption } from '../api/alerts'
import { systemApi } from '../api/system'
import { portfolioApi } from '../api/portfolio'
import { useWatchlistStore } from '../stores/watchlist'

const wl = useWatchlistStore()

const config = ref<AlertConfig>({
  sqs_threshold: 70,
  notify_browser: true,
  notify_line: false,
  line_token: '',
  watch_codes: [],
  scheduler_interval: 5,
})
const isLoading = ref(false)
const isSaving = ref(false)
const isChecking = ref(false)
const triggered = ref<any[]>([])
const history = ref<any[]>([])
const error = ref('')
const notifPermission = ref(Notification?.permission || 'default')
const schedulerStatus = ref<SchedulerStatus | null>(null)
const healthData = ref<any>(null)
const systemHealth = ref<any>(null)
const isCheckingHealth = ref(false)
const dataQuality = ref<any>(null)
const dqLoading = ref(false)
const omsStats = ref<any>(null)
const omsEvents = ref<any[]>([])
const omsLoading = ref(false)
const omsRunning = ref(false)
const omsEfficiency = ref<any>(null)
const effLoading = ref(false)
// R52 P2: Portfolio correlation alert
const corrData = ref<any>(null)
const corrLoading = ref(false)

// R55-3: Compound alert rules
const compoundRules = ref<CompoundRule[]>([])
const conditionTypes = ref<ConditionTypeOption[]>([])
const rulesLoading = ref(false)
const showRuleEditor = ref(false)
const ruleCheckResult = ref<any>(null)
const ruleChecking = ref(false)
const editingRule = ref({
  name: '',
  codes: [] as string[],
  codesInput: '',
  conditions: [{ type: 'v4_buy_signal', value: 0, params: {} }] as CompoundCondition[],
  combine_mode: 'AND',
  notify_browser: true,
  notify_line: false,
  cooldown_hours: 4,
})

async function loadConfig() {
  isLoading.value = true
  try {
    const data = await alertsApi.getConfig()
    config.value = data
  } catch { /* use default */ }
  isLoading.value = false
}

async function saveConfig() {
  isSaving.value = true
  error.value = ''
  try {
    await alertsApi.saveConfig(config.value)
  } catch (e: any) {
    error.value = e?.message || 'Save failed'
  }
  isSaving.value = false
}

async function loadAlerts() {
  isChecking.value = true
  try {
    const result = await alertsApi.checkAlerts()
    triggered.value = result.triggered || []

    // Browser notification for new triggers
    if (result.notify_browser && triggered.value.length > 0 && Notification?.permission === 'granted') {
      const top = triggered.value[0]
      new Notification(`SQS Alert: ${triggered.value.length} stocks`, {
        body: `${top.code} ${top.name} — SQS ${top.sqs} (${top.grade_label})`,
        icon: '/favicon.ico',
      })
    }
  } catch { /* ignore */ }
  isChecking.value = false
}

async function triggerManualCheck() {
  isChecking.value = true
  try {
    const result = await alertsApi.triggerCheck()
    triggered.value = result.triggered || []
    await loadSchedulerStatus()
  } catch (e: any) {
    error.value = e?.message || 'Check failed'
  }
  isChecking.value = false
}

async function sendLineNotify() {
  try {
    await alertsApi.notifyTriggered()
  } catch (e: any) {
    error.value = e?.message || 'LINE notify failed'
  }
}

async function requestNotifPermission() {
  if ('Notification' in window) {
    const perm = await Notification.requestPermission()
    notifPermission.value = perm
  }
}

async function loadHistory() {
  try {
    history.value = await alertsApi.getHistory()
    history.value.reverse()
  } catch { /* ignore */ }
}

async function loadSchedulerStatus() {
  try {
    schedulerStatus.value = await alertsApi.getSchedulerStatus()
  } catch { /* ignore */ }
}

async function loadHealth() {
  try {
    healthData.value = await alertsApi.getHealth()
  } catch { /* ignore */ }
}

function formatUptime(seconds: number | null): string {
  if (!seconds) return '-'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  return h > 0 ? `${h}h ${m}m` : `${m}m`
}

async function loadSystemHealth(includeSlow: boolean = false) {
  isCheckingHealth.value = true
  try {
    systemHealth.value = await systemApi.health(includeSlow)
  } catch { /* ignore */ }
  isCheckingHealth.value = false
}

async function loadDataQuality() {
  dqLoading.value = true
  try {
    dataQuality.value = await systemApi.dataQuality()
  } catch { dataQuality.value = null }
  dqLoading.value = false
}

async function loadOms() {
  omsLoading.value = true
  try {
    const [stats, evts] = await Promise.all([
      systemApi.omsStats(),
      systemApi.omsEvents(30),
    ])
    omsStats.value = stats
    omsEvents.value = evts.events || []
  } catch { /* ignore */ }
  omsLoading.value = false
}

async function runOmsNow() {
  omsRunning.value = true
  try {
    await systemApi.omsRunNow()
    await loadOms()
  } catch { /* ignore */ }
  omsRunning.value = false
}

async function loadOmsEfficiency() {
  effLoading.value = true
  try {
    omsEfficiency.value = await systemApi.omsEfficiency()
  } catch { omsEfficiency.value = null }
  effLoading.value = false
}

async function loadCorrelation() {
  corrLoading.value = true
  try {
    corrData.value = await portfolioApi.correlation()
  } catch { corrData.value = null }
  corrLoading.value = false
}

function healthStatusType(status: string): 'success' | 'warning' | 'error' | 'default' {
  if (status === 'healthy') return 'success'
  if (status === 'degraded') return 'warning'
  if (status === 'stopped') return 'error'
  return 'default'
}

function useWatchlistAsFilter() {
  config.value.watch_codes = wl.watchlist.map(s => s.code)
}

// R55-3: Compound rules methods
async function loadCompoundRules() {
  rulesLoading.value = true
  try {
    compoundRules.value = await alertsApi.listRules()
  } catch { compoundRules.value = [] }
  rulesLoading.value = false
}

async function loadConditionTypes() {
  try {
    conditionTypes.value = await alertsApi.getConditionTypes()
  } catch { /* use empty */ }
}

function openRuleEditor() {
  editingRule.value = {
    name: '',
    codes: [],
    codesInput: '',
    conditions: [{ type: 'v4_buy_signal', value: 0, params: {} }],
    combine_mode: 'AND',
    notify_browser: true,
    notify_line: false,
    cooldown_hours: 4,
  }
  showRuleEditor.value = true
}

function addCondition() {
  editingRule.value.conditions.push({ type: 'price_above', value: 0, params: {} })
}

function removeCondition(idx: number) {
  editingRule.value.conditions.splice(idx, 1)
}

async function saveRule() {
  const r = editingRule.value
  const codes = r.codesInput ? r.codesInput.split(',').map(s => s.trim()).filter(Boolean) : []
  try {
    await alertsApi.createRule({
      name: r.name || '未命名規則',
      codes,
      conditions: r.conditions,
      combine_mode: r.combine_mode,
      notify_browser: r.notify_browser,
      notify_line: r.notify_line,
      cooldown_hours: r.cooldown_hours,
    })
    showRuleEditor.value = false
    await loadCompoundRules()
  } catch { /* error toast from interceptor */ }
}

async function toggleRule(rule: CompoundRule) {
  try {
    await alertsApi.updateRule(rule.id, { enabled: !rule.enabled })
    await loadCompoundRules()
  } catch { /* ignore */ }
}

async function deleteRuleById(id: string) {
  try {
    await alertsApi.deleteRule(id)
    await loadCompoundRules()
  } catch { /* ignore */ }
}

async function checkAllRules() {
  ruleChecking.value = true
  try {
    ruleCheckResult.value = await alertsApi.checkRules()
  } catch { ruleCheckResult.value = null }
  ruleChecking.value = false
}

function conditionLabel(type: string): string {
  const found = conditionTypes.value.find(ct => ct.value === type)
  return found?.label || type
}

onMounted(async () => {
  await loadConfig()
  await loadAlerts()
  await Promise.all([loadHistory(), loadSchedulerStatus(), loadHealth(), loadSystemHealth(), loadDataQuality(), loadOms(), loadOmsEfficiency(), loadCorrelation(), loadCompoundRules(), loadConditionTypes()])
})

const triggeredColumns: DataTableColumns = [
  { title: '代碼', key: 'code', width: 80 },
  { title: '名稱', key: 'name', width: 100 },
  { title: 'SQS', key: 'sqs', width: 70, sorter: (a: any, b: any) => a.sqs - b.sqs },
  { title: '等級', key: 'grade_label', width: 100 },
  { title: '成熟度', key: 'maturity', width: 120 },
  { title: '信心分數', key: 'confidence', width: 80, render: (r: any) => r.confidence?.toFixed(2) || '-' },
]

const historyColumns: DataTableColumns = [
  { title: '時間', key: 'timestamp', width: 180, render: (r: any) => r.timestamp?.slice(0, 19).replace('T', ' ') || '' },
  { title: '觸發數', key: 'count', width: 60 },
  { title: '新觸發', key: 'new_count', width: 60, render: (r: any) => r.new_count ?? '-' },
  { title: '閾值', key: 'threshold', width: 60 },
  { title: '來源', key: 'source', width: 80, render: (r: any) => r.source || 'manual' },
  { title: 'Top 股票', key: 'top_stocks', render: (r: any) => (r.top_stocks || []).join(', ') },
]
</script>

<template>
  <div>
    <h2 style="margin: 0 0 16px">SQS 警報系統</h2>

    <NAlert v-if="error" type="error" style="margin-bottom: 12px" closable @close="error = ''">
      {{ error }}
    </NAlert>

    <!-- Scheduler Status Bar -->
    <NCard size="small" style="margin-bottom: 12px">
      <NSpace align="center" :size="20">
        <NStatistic label="排程器" :value="schedulerStatus?.running ? '運行中' : '未啟動'" />
        <NStatistic label="上次檢查" :value="schedulerStatus?.last_check?.timestamp?.slice(11, 19) || '-'" />
        <NStatistic label="觸發數" :value="schedulerStatus?.last_check?.triggered_count ?? 0" />
        <NStatistic v-if="schedulerStatus?.next_run" label="下次檢查" :value="schedulerStatus?.next_run?.slice(11, 19) || '-'" />
        <NStatistic v-if="healthData" label="運行時間" :value="formatUptime(healthData.uptime_seconds)" />
        <NStatistic v-if="healthData" label="檢查/錯誤" :value="`${healthData.total_checks || 0}/${healthData.total_errors || 0}`" />
        <NTag v-if="healthData?.status === 'healthy'" type="success" size="small">Healthy</NTag>
        <NTag v-else-if="healthData?.status === 'degraded'" type="error" size="small">Degraded</NTag>
        <NTag v-else-if="schedulerStatus?.running" type="success" size="small">APScheduler</NTag>
        <NTag v-else type="warning" size="small">Fallback</NTag>
      </NSpace>
      <NAlert v-if="healthData?.stale" type="warning" style="margin-top: 8px" :bordered="false">
        排程器心跳超過 15 分鐘未更新，可能需要重啟。
      </NAlert>
    </NCard>

    <NGrid :cols="2" :x-gap="16" :y-gap="16">
      <!-- Settings -->
      <NGi>
        <NCard title="警報設定" size="small">
          <NSpin :show="isLoading">
            <NSpace vertical :size="12">
              <div style="display: flex; align-items: center; gap: 12px">
                <span style="min-width: 80px">SQS 閾值</span>
                <NInputNumber v-model:value="config.sqs_threshold" :min="0" :max="100" :step="5" size="small" style="width: 120px" />
              </div>

              <div style="display: flex; align-items: center; gap: 12px">
                <span style="min-width: 80px">瀏覽器通知</span>
                <NSwitch v-model:value="config.notify_browser" />
                <NTag v-if="notifPermission === 'granted'" type="success" size="small">已授權</NTag>
                <NButton v-else size="tiny" @click="requestNotifPermission">授權</NButton>
              </div>

              <div style="display: flex; align-items: center; gap: 12px">
                <span style="min-width: 80px">LINE 通知</span>
                <NSwitch v-model:value="config.notify_line" />
              </div>

              <div v-if="config.notify_line" style="display: flex; align-items: center; gap: 12px">
                <span style="min-width: 80px">LINE Token</span>
                <NInput v-model:value="config.line_token" type="password" show-password-on="click" size="small" placeholder="LINE Notify Token" style="flex: 1" />
              </div>

              <div>
                <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 6px">
                  <span style="min-width: 80px">監控範圍</span>
                  <NTag v-if="config.watch_codes.length" size="small">{{ config.watch_codes.length }} 檔</NTag>
                  <NTag v-else size="small" type="info">全部 BUY 信號</NTag>
                </div>
                <NSpace :size="4">
                  <NButton size="tiny" @click="useWatchlistAsFilter">使用自選股</NButton>
                  <NButton size="tiny" @click="config.watch_codes = []">監控全部</NButton>
                </NSpace>
              </div>

              <NDivider style="margin: 8px 0" />
              <NSpace>
                <NButton type="primary" @click="saveConfig" :loading="isSaving" size="small">儲存設定</NButton>
                <NButton @click="triggerManualCheck" :loading="isChecking" size="small">立即檢查</NButton>
                <NButton v-if="config.notify_line" @click="sendLineNotify" size="small" type="warning">發送 LINE 通知</NButton>
              </NSpace>
            </NSpace>
          </NSpin>
        </NCard>
      </NGi>

      <!-- Current Triggered -->
      <NGi>
        <NCard size="small">
          <template #header>
            <NSpace align="center" :size="8">
              <span>當前觸發 (SQS ≥ {{ config.sqs_threshold }})</span>
              <NTag type="error" size="small" v-if="triggered.length">{{ triggered.length }} 檔</NTag>
              <NTag size="small" v-else type="default">無觸發</NTag>
            </NSpace>
          </template>
          <NDataTable
            v-if="triggered.length"
            :columns="triggeredColumns"
            :data="triggered"
            :pagination="{ pageSize: 10 }"
            size="small"
            :bordered="false"
            :single-line="false"
            :scroll-x="560"
          />
          <div v-else style="padding: 20px; text-align: center; color: #999">
            目前沒有 SQS ≥ {{ config.sqs_threshold }} 的信號。
            {{ schedulerStatus?.running ? '排程器每 5 分鐘自動檢查。' : '點擊「立即檢查」手動觸發。' }}
          </div>
        </NCard>
      </NGi>
    </NGrid>

    <!-- System Health -->
    <NCard size="small" style="margin-top: 16px">
      <template #header>
        <NSpace align="center" :size="8">
          <span>系統健康狀態</span>
          <NTag v-if="systemHealth" :type="healthStatusType(systemHealth.status)" size="small">
            {{ systemHealth.status }}
          </NTag>
          <NButton size="tiny" @click="loadSystemHealth(true)" :loading="isCheckingHealth">
            完整檢查（含數據源）
          </NButton>
        </NSpace>
      </template>
      <NGrid v-if="systemHealth?.components" :cols="4" :x-gap="12" :y-gap="8">
        <NGi>
          <NSpace align="center" :size="4">
            <NTag :type="healthStatusType(systemHealth.components.redis?.status)" size="small">
              Redis: {{ systemHealth.components.redis?.status }}
            </NTag>
            <span v-if="systemHealth.components.redis?.keys != null" style="font-size: 11px; color: #999">
              {{ systemHealth.components.redis.keys }} keys
            </span>
          </NSpace>
        </NGi>
        <NGi>
          <NTag :type="healthStatusType(systemHealth.components.database?.status)" size="small">
            DB: {{ systemHealth.components.database?.status }}
          </NTag>
        </NGi>
        <NGi>
          <NTag :type="healthStatusType(systemHealth.components.scheduler?.status)" size="small">
            Scheduler: {{ systemHealth.components.scheduler?.status }}
          </NTag>
        </NGi>
        <NGi v-if="systemHealth.components.yfinance">
          <NSpace align="center" :size="4">
            <NTag :type="healthStatusType(systemHealth.components.yfinance?.status)" size="small">
              yfinance: {{ systemHealth.components.yfinance?.status }}
            </NTag>
            <span v-if="systemHealth.components.yfinance?.latency_s" style="font-size: 11px; color: #999">
              {{ systemHealth.components.yfinance.latency_s }}s
            </span>
          </NSpace>
        </NGi>
        <NGi v-if="systemHealth.components.finmind">
          <NSpace align="center" :size="4">
            <NTag :type="healthStatusType(systemHealth.components.finmind?.status)" size="small">
              FinMind: {{ systemHealth.components.finmind?.status }}
            </NTag>
            <span v-if="systemHealth.components.finmind?.latency_s" style="font-size: 11px; color: #999">
              {{ systemHealth.components.finmind.latency_s }}s
            </span>
          </NSpace>
        </NGi>
      </NGrid>
      <div v-else style="padding: 8px; color: #999; font-size: 12px">載入中...</div>
    </NCard>

    <!-- Data Quality (R48-2) -->
    <NCard title="數據品質監控" size="small" style="margin-top: 16px">
      <template #header-extra>
        <NButton size="tiny" @click="loadDataQuality" :loading="dqLoading">檢查</NButton>
      </template>
      <NSpin :show="dqLoading">
        <template v-if="dataQuality && dataQuality.total_stocks > 0">
          <NSpace :size="12" style="margin-bottom: 8px">
            <NStatistic label="總檢查" :value="dataQuality.total_stocks" />
            <NStatistic label="正常">
              <template #default>
                <span style="color: #18a058">{{ dataQuality.ok_count }}</span>
              </template>
            </NStatistic>
            <NStatistic label="警告">
              <template #default>
                <span style="color: #f0a020">{{ dataQuality.warning_count }}</span>
              </template>
            </NStatistic>
            <NStatistic label="異常">
              <template #default>
                <span style="color: #e53e3e">{{ dataQuality.error_count }}</span>
              </template>
            </NStatistic>
            <NStatistic label="完整度">
              <template #default>
                <NTag :type="(dataQuality.overall_score || 0) >= 0.8 ? 'success' : (dataQuality.overall_score || 0) >= 0.5 ? 'warning' : 'error'" size="small">
                  {{ ((dataQuality.overall_score || 0) * 100).toFixed(0) }}%
                </NTag>
              </template>
            </NStatistic>
          </NSpace>
          <NAlert v-for="issue in (dataQuality.critical_issues || []).slice(0, 5)" :key="issue.code + issue.type"
                  type="error" style="margin-bottom: 4px" :bordered="false">
            {{ issue.code }}: {{ issue.detail }}
          </NAlert>
          <NDataTable
            v-if="dataQuality.stocks?.length"
            :columns="[
              { title: '代碼', key: 'code', width: 70 },
              { title: '狀態', key: 'status', width: 70, render: (r: any) => h(NTag, { type: r.status === 'ok' ? 'success' : r.status === 'warning' ? 'warning' : 'error', size: 'small' }, () => r.status) },
              { title: '完整度', key: 'completeness_score', width: 80, render: (r: any) => ((r.completeness_score || 0) * 100).toFixed(0) + '%' },
              { title: '最新日期', key: 'last_date', width: 100 },
              { title: '問題', key: 'issues', render: (r: any) => (r.issues || []).map((i: any) => i.detail).join('; ') || '無' },
            ]"
            :data="dataQuality.stocks"
            :pagination="{ pageSize: 10 }"
            size="small"
            :bordered="false"
            :single-line="false"
            style="margin-top: 8px"
          />
        </template>
        <div v-else-if="dataQuality?.message" style="padding: 12px; color: #999; font-size: 12px">{{ dataQuality.message }}</div>
        <div v-else-if="!dqLoading" style="padding: 12px; color: #999; font-size: 12px">點擊「檢查」開始數據品質掃描</div>
      </NSpin>
    </NCard>

    <!-- OMS Panel (R50-2) -->
    <NCard title="OMS 自動出場監控" size="small" style="margin-top: 16px">
      <template #header-extra>
        <NSpace :size="8">
          <NButton size="tiny" @click="loadOms" :loading="omsLoading">刷新</NButton>
          <NButton size="tiny" type="primary" @click="runOmsNow" :loading="omsRunning">立即檢查</NButton>
        </NSpace>
      </template>
      <NSpin :show="omsLoading">
        <NSpace :size="12" style="margin-bottom: 8px" v-if="omsStats">
          <NStatistic label="總事件" :value="omsStats.total_events || 0" />
          <NStatistic label="自動出場" :value="omsStats.auto_exits || 0" />
          <NStatistic label="移動停利更新" :value="omsStats.trailing_updates || 0" />
          <NStatistic label="累計自動損益">
            <template #default>
              <span :style="{ color: (omsStats.total_auto_pnl || 0) >= 0 ? '#18a058' : '#e53e3e' }">
                ${{ (omsStats.total_auto_pnl || 0).toLocaleString() }}
              </span>
            </template>
          </NStatistic>
          <NStatistic v-if="omsStats.last_event" label="最後事件" :value="omsStats.last_event?.slice(0, 19).replace('T', ' ') || '-'" />
        </NSpace>
        <NGrid v-if="omsStats?.exit_reasons && Object.keys(omsStats.exit_reasons).length" :cols="3" :x-gap="8" style="margin-bottom: 8px">
          <NGi v-for="(count, reason) in omsStats.exit_reasons" :key="reason">
            <NTag :type="reason === 'take_profit' ? 'success' : reason === 'stop_loss' ? 'error' : 'warning'" size="small">
              {{ reason === 'stop_loss' ? '停損' : reason === 'take_profit' ? '停利' : '移動停利' }}: {{ count }}
            </NTag>
          </NGi>
        </NGrid>
        <NDataTable
          v-if="omsEvents.length"
          :columns="[
            { title: '時間', key: 'timestamp', width: 150, render: (r: any) => r.timestamp?.slice(0, 19).replace('T', ' ') || '' },
            { title: '代碼', key: 'code', width: 70 },
            { title: '類型', key: 'event_type', width: 90, render: (r: any) => h(NTag, { type: r.event_type === 'auto_exit' ? 'error' : 'info', size: 'small' }, () => r.event_type === 'auto_exit' ? '自動出場' : '停利更新') },
            { title: '原因', key: 'exit_reason', width: 80, render: (r: any) => r.exit_reason === 'stop_loss' ? '停損' : r.exit_reason === 'take_profit' ? '停利' : r.exit_reason === 'trailing_stop' ? '移動停利' : r.exit_reason || '-' },
            { title: '價格', key: 'exit_price', width: 80, render: (r: any) => r.exit_price > 0 ? `$${r.exit_price.toFixed(2)}` : '-' },
            { title: '損益', key: 'pnl', width: 80, render: (r: any) => r.pnl ? h('span', { style: { color: r.pnl >= 0 ? '#18a058' : '#e53e3e' } }, `$${r.pnl.toLocaleString()}`) : '-' },
            { title: '說明', key: 'detail', ellipsis: { tooltip: true } },
          ]"
          :data="omsEvents"
          :pagination="{ pageSize: 10 }"
          size="small"
          :bordered="false"
          :single-line="false"
        />
        <div v-else-if="!omsLoading" style="padding: 12px; color: #999; font-size: 12px">
          尚無 OMS 事件。系統每 5 分鐘自動檢查持倉停損/停利條件。
        </div>
      </NSpin>
    </NCard>

    <!-- OMS Efficiency (R51-2) -->
    <NCard size="small" style="margin-top: 16px" v-if="omsEfficiency?.has_data">
      <template #header>
        <NSpace align="center" :size="8">
          <span>OMS 效率分析</span>
          <NButton size="tiny" @click="loadOmsEfficiency" :loading="effLoading">刷新</NButton>
        </NSpace>
      </template>
      <NGrid :cols="4" :x-gap="12" :y-gap="8" style="margin-bottom: 8px">
        <NGi>
          <NStatistic label="自動化覆蓋率" :value="`${((omsEfficiency.auto_coverage || 0) * 100).toFixed(0)}%`" />
        </NGi>
        <NGi>
          <NStatistic label="最大連續虧損" :value="omsEfficiency.max_consecutive_losses || 0" />
        </NGi>
        <NGi>
          <NStatistic label="平均損益" :value="`$${(omsEfficiency.avg_pnl || 0).toLocaleString()}`" />
        </NGi>
        <NGi>
          <NStatistic label="已平倉總數" :value="omsEfficiency.total_closed || 0" />
        </NGi>
      </NGrid>
      <NDataTable
        v-if="omsEfficiency.by_exit_type"
        :columns="[
          { title: '出場類型', key: 'label', width: 100 },
          { title: '次數', key: 'count', width: 60 },
          { title: '勝率', key: 'win_rate', width: 70, render: (r: any) => `${((r.win_rate || 0) * 100).toFixed(0)}%` },
          { title: '平均損益', key: 'avg_pnl', width: 90, render: (r: any) => h('span', { style: { color: (r.avg_pnl || 0) >= 0 ? '#18a058' : '#e53e3e' } }, `$${(r.avg_pnl || 0).toLocaleString()}`) },
          { title: '累計損益', key: 'total_pnl', width: 100, render: (r: any) => h('span', { style: { color: (r.total_pnl || 0) >= 0 ? '#18a058' : '#e53e3e' } }, `$${(r.total_pnl || 0).toLocaleString()}`) },
          { title: '平均持有天數', key: 'avg_days', width: 90 },
        ]"
        :data="(Object.values(omsEfficiency.by_exit_type) as any[]).filter((v) => v.count > 0)"
        size="small"
        :bordered="false"
        :single-line="false"
      />
    </NCard>

    <!-- History -->
    <NCard title="警報歷史" size="small" style="margin-top: 16px">
      <NDataTable
        v-if="history.length"
        :columns="historyColumns"
        :data="history"
        :pagination="{ pageSize: 15 }"
        size="small"
        :bordered="false"
        :single-line="false"
      />
      <div v-else style="padding: 20px; text-align: center; color: #999">尚無歷史紀錄</div>
    </NCard>

    <!-- R52 P2: Portfolio Correlation Alert -->
    <NCard size="small" style="margin-top: 16px" v-if="corrData?.has_data">
      <template #header>
        <NSpace align="center" :size="8">
          <span>Portfolio Correlation Monitor</span>
          <NTag v-if="corrData.high_corr_alert" type="error" size="small">HIGH CORRELATION</NTag>
          <NButton size="tiny" @click="loadCorrelation" :loading="corrLoading">Refresh</NButton>
        </NSpace>
      </template>
      <NSpin :show="corrLoading">
        <NAlert v-if="corrData.high_corr_alert" type="error" style="margin-bottom: 8px">
          High correlation detected among {{ corrData.high_corr_group?.length || 0 }} stocks
          ({{ corrData.high_corr_group?.join(', ') }}).
          Consider reducing exposure to correlated positions.
        </NAlert>
        <template v-if="corrData.high_corr_pairs?.length">
          <NDataTable
            :columns="[
              { title: 'Stock A', key: 'code_a', width: 80 },
              { title: '', key: 'name_a', width: 100 },
              { title: 'Stock B', key: 'code_b', width: 80 },
              { title: '', key: 'name_b', width: 100 },
              { title: 'Correlation', key: 'correlation', width: 100,
                render: (row: any) => h('span', { style: { color: Math.abs(row.correlation) > 0.8 ? '#e53e3e' : '#f0a020', fontWeight: 'bold' } }, row.correlation.toFixed(3)),
                sorter: (a: any, b: any) => Math.abs(b.correlation) - Math.abs(a.correlation) },
            ]"
            :data="corrData.high_corr_pairs"
            size="small"
            :bordered="false"
            :pagination="false"
          />
        </template>
        <div v-else style="padding: 12px; text-align: center; color: #18a058">
          No high-correlation pairs detected (threshold: |p| > 0.7). Portfolio is well-diversified.
        </div>
      </NSpin>
    </NCard>

    <!-- R55-3: Compound Alert Rules -->
    <NCard size="small" style="margin-top: 16px">
      <template #header>
        <NSpace align="center" :size="8">
          <span>複合條件警報規則</span>
          <NTag size="small" type="info">{{ compoundRules.length }} rules</NTag>
          <NButton size="tiny" @click="openRuleEditor">新增規則</NButton>
          <NButton size="tiny" type="primary" @click="checkAllRules" :loading="ruleChecking">檢查所有規則</NButton>
        </NSpace>
      </template>

      <!-- Rule check results -->
      <NAlert v-if="ruleCheckResult?.triggered?.length" type="success" style="margin-bottom: 8px" closable @close="ruleCheckResult = null">
        觸發 {{ ruleCheckResult.triggered.length }} 筆警報！
        <div v-for="(t, i) in ruleCheckResult.triggered" :key="i" style="font-size: 12px; margin-top: 2px">
          {{ t.rule_name }}: {{ t.code }} ({{ t.combine_mode }}, {{ t.conditions_met }} conditions)
        </div>
      </NAlert>
      <NAlert v-else-if="ruleCheckResult && !ruleCheckResult.triggered?.length" type="info" style="margin-bottom: 8px" closable @close="ruleCheckResult = null">
        檢查完成，無觸發。({{ ruleCheckResult.rules_checked }} rules checked)
      </NAlert>

      <!-- Existing rules list -->
      <NSpin :show="rulesLoading">
        <template v-if="compoundRules.length">
          <div v-for="rule in compoundRules" :key="rule.id" style="padding: 8px; margin-bottom: 6px; border: 1px solid #e8e8e8; border-radius: 6px">
            <NSpace align="center" justify="space-between">
              <NSpace align="center" :size="8">
                <NSwitch :value="rule.enabled" size="small" @update:value="toggleRule(rule)" />
                <strong>{{ rule.name }}</strong>
                <NTag size="tiny" :type="rule.combine_mode === 'AND' ? 'info' : 'warning'">{{ rule.combine_mode }}</NTag>
                <NTag v-if="rule.codes.length" size="tiny">{{ rule.codes.join(', ') }}</NTag>
                <NTag v-else size="tiny" type="default">全部</NTag>
              </NSpace>
              <NSpace :size="4">
                <NTag v-if="rule.trigger_count > 0" size="tiny" type="success">{{ rule.trigger_count }}x triggered</NTag>
                <NButton size="tiny" type="error" quaternary @click="deleteRuleById(rule.id)">刪除</NButton>
              </NSpace>
            </NSpace>
            <div style="margin-top: 4px; font-size: 12px; color: #666">
              條件: <NTag v-for="(c, ci) in rule.conditions" :key="ci" size="tiny" style="margin: 1px">
                {{ conditionLabel(c.type) }} {{ c.value || '' }}
              </NTag>
            </div>
          </div>
        </template>
        <div v-else style="padding: 20px; text-align: center; color: #999">
          尚無複合條件規則。點擊「新增規則」建立。
        </div>
      </NSpin>

      <!-- Rule editor (inline) -->
      <NCard v-if="showRuleEditor" size="small" style="margin-top: 12px; border-color: #2080f0" title="新增複合條件規則">
        <NSpace vertical :size="10">
          <div style="display: flex; gap: 10px; align-items: center">
            <span style="min-width: 60px">規則名稱</span>
            <NInput v-model:value="editingRule.name" size="small" placeholder="例：量增價漲突破" style="width: 200px" />
          </div>
          <div style="display: flex; gap: 10px; align-items: center">
            <span style="min-width: 60px">監控股票</span>
            <NInput v-model:value="editingRule.codesInput" size="small" placeholder="代碼以逗號分隔，留空=全部" style="width: 300px" />
          </div>
          <div style="display: flex; gap: 10px; align-items: center">
            <span style="min-width: 60px">組合模式</span>
            <NTag :type="editingRule.combine_mode === 'AND' ? 'info' : 'warning'"
                  style="cursor: pointer"
                  @click="editingRule.combine_mode = editingRule.combine_mode === 'AND' ? 'OR' : 'AND'">
              {{ editingRule.combine_mode }} (點擊切換)
            </NTag>
          </div>

          <NDivider style="margin: 4px 0">條件</NDivider>

          <div v-for="(cond, idx) in editingRule.conditions" :key="idx"
               style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap">
            <select v-model="cond.type" style="padding: 4px; border: 1px solid #ddd; border-radius: 4px; font-size: 12px">
              <option v-for="ct in conditionTypes" :key="ct.value" :value="ct.value">{{ ct.label }}</option>
            </select>
            <NInputNumber v-model:value="cond.value" size="small" style="width: 100px"
                          :disabled="['macd_cross_up','macd_cross_down','kd_cross_up','kd_cross_down','ma_cross_up','ma_cross_down','bb_upper_break','bb_lower_break','v4_buy_signal','v4_sell_signal'].includes(cond.type)" />
            <NButton size="tiny" type="error" quaternary @click="removeCondition(idx)" :disabled="editingRule.conditions.length <= 1">X</NButton>
          </div>

          <NButton size="tiny" dashed @click="addCondition">+ 新增條件</NButton>

          <NSpace :size="8">
            <NSwitch v-model:value="editingRule.notify_browser" size="small" /> 瀏覽器通知
            <NSwitch v-model:value="editingRule.notify_line" size="small" /> LINE 通知
          </NSpace>

          <NSpace>
            <NButton type="primary" size="small" @click="saveRule">建立規則</NButton>
            <NButton size="small" @click="showRuleEditor = false">取消</NButton>
          </NSpace>
        </NSpace>
      </NCard>
    </NCard>
  </div>
</template>
