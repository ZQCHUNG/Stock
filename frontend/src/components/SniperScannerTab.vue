<script setup lang="ts">
import { h, ref, computed } from 'vue'
import {
  NCard, NButton, NSpace, NDataTable, NSpin, NTag, NStatistic,
  NGrid, NGi, NSwitch, NInputNumber, useMessage,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { screenerApi, type BoldScanResult } from '../api/screener'
import { useAppStore } from '../stores/app'
import { useRouter } from 'vue-router'

const msg = useMessage()
const app = useAppStore()
const router = useRouter()

const loading = ref(false)
const scanResults = ref<BoldScanResult[]>([])
const scanDate = ref('')
const totalScanned = ref(0)
const errorCount = ref(0)

// Filters
const minRs = ref(60)
const minVolume = ref(50)
const includeNoSignal = ref(false)

async function runScan() {
  loading.value = true
  try {
    const resp = await screenerApi.boldScan({
      min_rs: minRs.value,
      min_volume_lots: minVolume.value,
      include_no_signal: includeNoSignal.value,
    })
    scanResults.value = resp.results || []
    scanDate.value = resp.scan_date || ''
    totalScanned.value = resp.total_scanned || 0
    errorCount.value = resp.error_count || 0
    msg.success(`Scan complete: ${scanResults.value.length} targets found`)
  } catch (e: any) {
    msg.error(`Scan failed: ${e?.message || e}`)
  }
  loading.value = false
}

function goToTechnical(code: string) {
  app.currentStockCode = code
  router.push('/technical')
}

function rsGradeType(grade: string) {
  if (grade === 'Diamond') return 'success'
  if (grade === 'Gold') return 'warning'
  if (grade === 'Silver') return 'default'
  return 'error'
}

function sniperScoreColor(score: number) {
  if (score >= 70) return '#18a058'
  if (score >= 50) return '#f0a020'
  return '#d03050'
}

const signalCount = computed(() => scanResults.value.filter(r => r.has_signal).length)
const diamondCount = computed(() => scanResults.value.filter(r => r.rs_grade === 'Diamond').length)
const avgSniperScore = computed(() => {
  if (!scanResults.value.length) return 0
  return scanResults.value.reduce((s, r) => s + r.sniper_score, 0) / scanResults.value.length
})

const columns: DataTableColumns<BoldScanResult> = [
  {
    title: '#',
    key: 'rank',
    width: 45,
    render: (_row, index) => h('span', { style: 'color: #999' }, `${index + 1}`),
  },
  {
    title: 'Code',
    key: 'code',
    width: 70,
    render: (row) => h(
      'a',
      {
        style: 'cursor: pointer; color: #2080f0; text-decoration: none',
        onClick: () => goToTechnical(row.code),
      },
      row.code,
    ),
  },
  { title: 'Name', key: 'name', width: 80, ellipsis: { tooltip: true } },
  { title: 'Sector', key: 'sector', width: 80, ellipsis: { tooltip: true } },
  {
    title: 'Price',
    key: 'price',
    width: 75,
    sorter: (a, b) => a.price - b.price,
  },
  {
    title: 'Chg%',
    key: 'change_pct',
    width: 65,
    sorter: (a, b) => a.change_pct - b.change_pct,
    render: (row) => h(
      'span',
      { style: `color: ${row.change_pct >= 0 ? '#d03050' : '#18a058'}` },
      `${row.change_pct >= 0 ? '+' : ''}${row.change_pct.toFixed(2)}%`,
    ),
  },
  {
    title: 'Signal',
    key: 'has_signal',
    width: 85,
    filterOptions: [
      { label: 'BUY', value: 'true' },
      { label: 'None', value: 'false' },
    ],
    filter: (value, row) => String(row.has_signal) === value,
    render: (row) => {
      if (!row.has_signal) return h(NTag, { size: 'small', type: 'default' }, () => 'None')
      return h(NTag, { size: 'small', type: 'success' }, () => row.entry_type || 'BUY')
    },
  },
  {
    title: 'RS',
    key: 'rs_rating',
    width: 70,
    sorter: (a, b) => (a.rs_rating || 0) - (b.rs_rating || 0),
    render: (row) => {
      if (row.rs_rating == null) return '-'
      return h(NTag, { size: 'small', type: rsGradeType(row.rs_grade), round: true },
        () => `${row.rs_rating!.toFixed(0)}`)
    },
  },
  {
    title: 'VCP',
    key: 'vcp_score',
    width: 55,
    sorter: (a, b) => a.vcp_score - b.vcp_score,
    render: (row) => {
      if (row.vcp_score >= 70) return h(NTag, { size: 'small', type: 'success' }, () => `${row.vcp_score}`)
      if (row.vcp_score >= 30) return h(NTag, { size: 'small', type: 'warning' }, () => `${row.vcp_score}`)
      return h('span', { style: 'color: #999' }, `${row.vcp_score}`)
    },
  },
  {
    title: 'SQS',
    key: 'sqs_score',
    width: 55,
    sorter: (a, b) => (a.sqs_score || 0) - (b.sqs_score || 0),
    render: (row) => {
      if (row.sqs_score == null) return '-'
      if (row.sqs_score >= 80) return h(NTag, { size: 'small', type: 'success' }, () => `${row.sqs_score.toFixed(0)}`)
      if (row.sqs_score >= 60) return h(NTag, { size: 'small', type: 'warning' }, () => `${row.sqs_score.toFixed(0)}`)
      return h('span', { style: 'color: #999' }, `${row.sqs_score.toFixed(0)}`)
    },
  },
  {
    title: 'Sniper',
    key: 'sniper_score',
    width: 70,
    defaultSortOrder: 'descend',
    sorter: (a, b) => a.sniper_score - b.sniper_score,
    render: (row) => h(
      'span',
      {
        style: `font-weight: 700; color: ${sniperScoreColor(row.sniper_score)}`,
      },
      row.sniper_score.toFixed(1),
    ),
  },
  {
    title: '',
    key: 'action',
    width: 50,
    render: (row) => h(
      NButton,
      { size: 'tiny', type: 'primary', ghost: true, onClick: () => goToTechnical(row.code) },
      () => 'View',
    ),
  },
]
</script>

<template>
  <div>
    <!-- Controls -->
    <NCard size="small" style="margin-bottom: 12px">
      <NSpace align="center" :wrap="false" :size="16">
        <NButton type="primary" :loading="loading" @click="runScan">
          Scan Market
        </NButton>
        <NSpace align="center" :size="8">
          <span style="font-size: 13px; color: #999">Min RS:</span>
          <NInputNumber v-model:value="minRs" :min="0" :max="100" :step="5" size="small" style="width: 80px" />
        </NSpace>
        <NSpace align="center" :size="8">
          <span style="font-size: 13px; color: #999">Min Vol:</span>
          <NInputNumber v-model:value="minVolume" :min="0" :step="10" size="small" style="width: 80px" />
        </NSpace>
        <NSpace align="center" :size="8">
          <span style="font-size: 13px; color: #999">No Signal:</span>
          <NSwitch v-model:value="includeNoSignal" size="small" />
        </NSpace>
        <span v-if="scanDate" style="font-size: 12px; color: #999; margin-left: auto">
          {{ scanDate }} | {{ totalScanned }} scanned | {{ errorCount }} errors
        </span>
      </NSpace>
    </NCard>

    <!-- Stats -->
    <NGrid v-if="scanResults.length" :cols="4" :x-gap="12" style="margin-bottom: 12px">
      <NGi>
        <NCard size="small">
          <NStatistic label="Targets" :value="scanResults.length" />
        </NCard>
      </NGi>
      <NGi>
        <NCard size="small">
          <NStatistic label="Active Signals" :value="signalCount" />
        </NCard>
      </NGi>
      <NGi>
        <NCard size="small">
          <NStatistic label="Diamond RS" :value="diamondCount" />
        </NCard>
      </NGi>
      <NGi>
        <NCard size="small">
          <NStatistic label="Avg Sniper Score">
            <span :style="{ color: sniperScoreColor(avgSniperScore) }">
              {{ avgSniperScore.toFixed(1) }}
            </span>
          </NStatistic>
        </NCard>
      </NGi>
    </NGrid>

    <!-- Results Table -->
    <NSpin :show="loading">
      <NDataTable
        :columns="columns"
        :data="scanResults"
        :bordered="true"
        :single-line="false"
        :pagination="{ pageSize: 30 }"
        size="small"
        :row-key="(row: BoldScanResult) => row.code"
        style="font-size: 13px"
        max-height="600"
        virtual-scroll
      />
    </NSpin>
  </div>
</template>
