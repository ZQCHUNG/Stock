<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import {
  NCard, NGrid, NGi, NSpin, NTag, NSpace, NButton, NAlert,
} from 'naive-ui'
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

onMounted(() => {
  loadDashboard()
})

const statusBar = computed(() => data.value?.status_bar || {})
const scan = computed(() => data.value?.scan || {})
const portfolio = computed(() => data.value?.portfolio || {})

function regimeColor(regime: string): string {
  if (regime === 'NORMAL') return '#18a058'
  if (regime === 'CAUTION') return '#f0a020'
  if (regime === 'LOCKDOWN') return '#e53e3e'
  return '#999'
}

function nav(route: string) {
  router.push({ name: route })
}
</script>

<template>
  <div style="max-width: 960px; margin: 0 auto">
    <NSpace align="center" justify="space-between" style="margin-bottom: 16px">
      <h2 style="margin: 0">Dashboard</h2>
      <NButton size="small" @click="loadDashboard" :loading="loading">Refresh</NButton>
    </NSpace>

    <NSpin :show="loading">
      <!-- Section 1: System Status Bar -->
      <NCard size="small" :bordered="true" style="margin-bottom: 16px">
        <div style="display: flex; flex-wrap: wrap; gap: 24px; align-items: center; font-size: 13px">
          <div>
            <span style="color: #999; margin-right: 6px">Data Date</span>
            <NTag size="small" :bordered="false">{{ statusBar.latest_data_date || '-' }}</NTag>
          </div>
          <div>
            <span style="color: #999; margin-right: 6px">Stock Count</span>
            <NTag size="small" :bordered="false">{{ statusBar.stock_count || '-' }}</NTag>
          </div>
          <div>
            <span style="color: #999; margin-right: 6px">Last Update</span>
            <NTag size="small" :bordered="false">
              {{ statusBar.last_update ? new Date(statusBar.last_update).toLocaleString('zh-TW') : '-' }}
            </NTag>
          </div>
          <div>
            <span style="color: #999; margin-right: 6px">Regime</span>
            <NTag size="small" :bordered="true"
                  :style="{ color: regimeColor(statusBar.regime), borderColor: regimeColor(statusBar.regime) }">
              {{ statusBar.regime || 'unknown' }}
            </NTag>
          </div>
        </div>
      </NCard>

      <!-- Section 2: Scan Top 15 (placeholder) -->
      <NCard size="small" title="Scan Top 15" :bordered="true"
             style="margin-bottom: 16px; min-height: 300px">
        <template #header-extra>
          <NButton size="tiny" text @click="nav('recommend')">Go to Scan</NButton>
        </template>
        <div style="display: flex; align-items: center; justify-content: center; height: 240px; color: #999; font-size: 14px">
          {{ scan.message || 'Loading...' }}
        </div>
      </NCard>

      <!-- Section 3: Portfolio Tracking (placeholder) -->
      <NCard size="small" title="Portfolio Tracking" :bordered="true"
             style="margin-bottom: 16px; min-height: 160px">
        <template #header-extra>
          <NButton size="tiny" text @click="nav('portfolio')">Go to Portfolio</NButton>
        </template>
        <div style="display: flex; align-items: center; justify-content: center; height: 120px; color: #999; font-size: 14px">
          {{ portfolio.message || 'Loading...' }}
        </div>
      </NCard>

      <!-- Quick Navigation -->
      <NSpace :size="6" :wrap="true" style="margin-top: 8px">
        <NButton size="small" @click="nav('technical')">Technical</NButton>
        <NButton size="small" @click="nav('recommend')">Recommend</NButton>
        <NButton size="small" @click="nav('screener')">Screener</NButton>
        <NButton size="small" @click="nav('portfolio')">Portfolio</NButton>
        <NButton size="small" @click="nav('risk')">Risk</NButton>
        <NButton size="small" @click="nav('strategies')">Strategies</NButton>
      </NSpace>
    </NSpin>
  </div>
</template>
