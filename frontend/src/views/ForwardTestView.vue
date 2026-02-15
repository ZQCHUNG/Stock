<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import {
  NCard, NButton, NGrid, NGi, NSpin, NTag, NAlert,
  NStatistic, NDataTable, NEmpty, NTabs, NTabPane,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import VChart from 'vue-echarts'
import { backtestApi } from '../api/backtest'
import { useResponsive } from '../composables/useResponsive'

const { isMobile } = useResponsive()

const summary = ref<any>(null)
const signals = ref<any[]>([])
const positions = ref<any[]>([])
const comparison = ref<any>(null)
const loading = ref(false)
const scanLoading = ref(false)
const updateLoading = ref(false)
const error = ref('')
const activeTab = ref('overview')

async function loadAll() {
  loading.value = true
  error.value = ''
  try {
    const [s, sig, pos, cmp] = await Promise.all([
      backtestApi.forwardTestSummary(),
      backtestApi.forwardTestSignals(100),
      backtestApi.forwardTestPositions(100),
      backtestApi.forwardTestCompare(),
    ])
    summary.value = s
    signals.value = sig
    positions.value = pos
    comparison.value = cmp
  } catch (e: any) {
    error.value = e?.message || 'Failed to load data'
  }
  loading.value = false
}

async function runScan() {
  scanLoading.value = true
  try {
    const result = await backtestApi.forwardTestScan()
    await loadAll()
    error.value = ''
  } catch (e: any) {
    error.value = e?.message || 'Scan failed'
  }
  scanLoading.value = false
}

async function runUpdate() {
  updateLoading.value = true
  try {
    await backtestApi.forwardTestUpdate()
    await loadAll()
  } catch (e: any) {
    error.value = e?.message || 'Update failed'
  }
  updateLoading.value = false
}

async function openPosition(signalId: number) {
  try {
    await backtestApi.forwardTestOpen(signalId)
    await loadAll()
  } catch (e: any) {
    error.value = e?.message || 'Open failed'
  }
}

onMounted(loadAll)

// Signal table columns
const signalColumns = computed<DataTableColumns>(() => [
  { title: 'ID', key: 'id', width: 50 },
  { title: '日期', key: 'scan_date', width: 100 },
  { title: '代碼', key: 'stock_code', width: 70 },
  { title: '信號', key: 'signal_type', width: 60,
    render: (r: any) => r.signal_type === 'BUY' ? 'BUY' : r.signal_type || '-' },
  { title: '信號價', key: 'signal_price', width: 80,
    render: (r: any) => r.signal_price?.toFixed(2) || '-' },
  { title: '信心度', key: 'confidence', width: 70,
    render: (r: any) => r.confidence ? (r.confidence * 100).toFixed(0) + '%' : '-' },
  { title: '量(張)', key: 'volume_lots', width: 70 },
  { title: '狀態', key: 'status', width: 80,
    render: (r: any) => {
      const map: Record<string, string> = { pending: 'info', opened: 'success', skipped: 'default' }
      return r.status
    },
  },
  ...(isMobile.value ? [] : [{
    title: '操作', key: 'action', width: 80,
    render: (r: any) => r.status === 'pending' ? 'Open' : '-',
  }]),
])

// Position table columns
const positionColumns = computed<DataTableColumns>(() => [
  { title: 'ID', key: 'id', width: 50 },
  { title: '代碼', key: 'stock_code', width: 70 },
  { title: '開倉價', key: 'open_price', width: 80,
    render: (r: any) => r.open_price?.toFixed(2) || '-' },
  { title: '股數', key: 'shares', width: 70 },
  { title: 'TP', key: 'tp_price', width: 70,
    render: (r: any) => r.tp_price?.toFixed(2) || '-' },
  { title: 'SL', key: 'sl_price', width: 70,
    render: (r: any) => r.sl_price?.toFixed(2) || '-' },
  { title: '狀態', key: 'status', width: 70 },
  { title: '平倉價', key: 'close_price', width: 80,
    render: (r: any) => r.close_price?.toFixed(2) || '-' },
  { title: '損益', key: 'pnl', width: 80,
    render: (r: any) => {
      if (r.pnl == null) return '-'
      const v = r.pnl
      return (v >= 0 ? '+' : '') + v.toFixed(0)
    },
  },
  { title: '報酬%', key: 'return_pct', width: 70,
    render: (r: any) => {
      if (r.return_pct == null) return '-'
      return (r.return_pct >= 0 ? '+' : '') + (r.return_pct * 100).toFixed(2) + '%'
    },
  },
])

// Comparison chart
const compareChartOption = computed(() => {
  const fwd = comparison.value?.forward
  const cmp = comparison.value?.comparison
  if (!fwd || !cmp) return null

  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['Forward Test', 'Backtest 預期'] },
    xAxis: {
      type: 'category',
      data: ['勝率%', '平均報酬%', '夏普比率'],
    },
    yAxis: { type: 'value' },
    series: [
      {
        name: 'Forward Test',
        type: 'bar',
        data: [
          fwd.win_rate ? (fwd.win_rate * 100) : 0,
          fwd.avg_return ? (fwd.avg_return * 100) : 0,
          fwd.sharpe_ratio || 0,
        ],
        itemStyle: { color: '#42a5f5' },
      },
      {
        name: 'Backtest 預期',
        type: 'bar',
        data: [
          cmp.backtest_win_rate ? (cmp.backtest_win_rate * 100) : 0,
          cmp.backtest_avg_return ? (cmp.backtest_avg_return * 100) : 0,
          cmp.backtest_sharpe || 0,
        ],
        itemStyle: { color: '#66bb6a' },
      },
    ],
  }
})
</script>

<template>
  <div>
    <h2 style="margin: 0 0 16px">Forward Testing</h2>

    <NAlert v-if="error" type="error" style="margin-bottom: 12px" closable @close="error = ''">
      {{ error }}
    </NAlert>

    <div style="margin-bottom: 12px">
      <NButton type="primary" @click="runScan" :loading="scanLoading" style="margin-right: 8px">
        掃描信號
      </NButton>
      <NButton @click="runUpdate" :loading="updateLoading" style="margin-right: 8px">
        更新部位
      </NButton>
      <NButton @click="loadAll" :loading="loading">
        重新整理
      </NButton>
    </div>

    <NSpin :show="loading">
      <NTabs v-model:value="activeTab" type="line">
        <!-- Overview Tab -->
        <NTabPane name="overview" tab="總覽">
          <template v-if="summary">
            <NGrid :cols="isMobile ? 2 : 4" :x-gap="12" :y-gap="12" style="margin-bottom: 16px">
              <NGi>
                <NCard size="small">
                  <NStatistic label="總信號數" :value="summary.total_signals" />
                </NCard>
              </NGi>
              <NGi>
                <NCard size="small">
                  <NStatistic label="已開倉" :value="summary.signals_opened" />
                </NCard>
              </NGi>
              <NGi>
                <NCard size="small">
                  <NStatistic label="持倉中" :value="summary.open_positions" />
                </NCard>
              </NGi>
              <NGi>
                <NCard size="small">
                  <NStatistic label="已平倉" :value="summary.closed_positions" />
                </NCard>
              </NGi>
            </NGrid>

            <NGrid :cols="isMobile ? 2 : 4" :x-gap="12" :y-gap="12" style="margin-bottom: 16px">
              <NGi>
                <NCard size="small">
                  <NStatistic label="勝率">
                    <template #default>
                      <span :style="{ color: (summary.win_rate || 0) >= 0.5 ? '#4caf50' : '#f44336' }">
                        {{ ((summary.win_rate || 0) * 100).toFixed(1) }}%
                      </span>
                    </template>
                  </NStatistic>
                </NCard>
              </NGi>
              <NGi>
                <NCard size="small">
                  <NStatistic label="平均報酬">
                    <template #default>
                      <span :style="{ color: (summary.avg_return || 0) >= 0 ? '#4caf50' : '#f44336' }">
                        {{ ((summary.avg_return || 0) * 100).toFixed(2) }}%
                      </span>
                    </template>
                  </NStatistic>
                </NCard>
              </NGi>
              <NGi>
                <NCard size="small">
                  <NStatistic label="累計損益">
                    <template #default>
                      <span :style="{ color: (summary.total_pnl || 0) >= 0 ? '#4caf50' : '#f44336' }">
                        ${{ (summary.total_pnl || 0).toLocaleString() }}
                      </span>
                    </template>
                  </NStatistic>
                </NCard>
              </NGi>
              <NGi>
                <NCard size="small">
                  <NStatistic label="平均持有天數" :value="(summary.avg_hold_days || 0).toFixed(1)" />
                </NCard>
              </NGi>
            </NGrid>
          </template>
          <NEmpty v-else-if="!loading" description="尚無 Forward Test 資料。點擊「掃描信號」開始。" />

          <!-- Forward vs Backtest Comparison -->
          <NCard v-if="comparison" title="Forward vs Backtest 對比" size="small" style="margin-top: 16px">
            <template v-if="comparison.comparison?.sufficient_data">
              <VChart v-if="compareChartOption" :option="compareChartOption" style="height: 280px" autoresize />
            </template>
            <NAlert v-else type="info">
              資料不足（需 >= 10 筆已平倉交易才能進行對比分析）
            </NAlert>
          </NCard>
        </NTabPane>

        <!-- Signals Tab -->
        <NTabPane name="signals" tab="信號記錄">
          <NDataTable
            v-if="signals.length"
            :columns="signalColumns"
            :data="signals"
            size="small"
            :bordered="false"
            :single-line="false"
            max-height="500"
            virtual-scroll
          />
          <NEmpty v-else description="尚無信號記錄" />
        </NTabPane>

        <!-- Positions Tab -->
        <NTabPane name="positions" tab="部位追蹤">
          <NDataTable
            v-if="positions.length"
            :columns="positionColumns"
            :data="positions"
            size="small"
            :bordered="false"
            :single-line="false"
            max-height="500"
            virtual-scroll
          />
          <NEmpty v-else description="尚無部位記錄" />
        </NTabPane>
      </NTabs>
    </NSpin>
  </div>
</template>
