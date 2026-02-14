<script setup lang="ts">
import { ref, onMounted } from 'vue'
import {
  NCard, NButton, NSpace, NInputNumber, NSwitch, NInput, NTag, NAlert,
  NDataTable, NGrid, NGi, NSpin, NDivider, NStatistic,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { alertsApi, type AlertConfig, type SchedulerStatus } from '../api/alerts'
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

function useWatchlistAsFilter() {
  config.value.watch_codes = wl.watchlist.map(s => s.code)
}

onMounted(async () => {
  await loadConfig()
  await loadAlerts()
  await Promise.all([loadHistory(), loadSchedulerStatus(), loadHealth()])
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
  </div>
</template>
