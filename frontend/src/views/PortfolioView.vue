<script setup lang="ts">
import { h, onMounted, computed, ref } from 'vue'
import {
  NCard, NButton, NGrid, NGi, NSpin, NTag, NSpace, NDataTable, NEmpty,
  NAlert, NModal, NInputNumber, NInput, NProgress, NPopconfirm,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { useRouter } from 'vue-router'
import { useAppStore } from '../stores/app'
import { usePortfolioStore } from '../stores/portfolio'
import { fmtNum, fmtPct, priceColor } from '../utils/format'
import MetricCard from '../components/MetricCard.vue'

const app = useAppStore()
const pf = usePortfolioStore()
const router = useRouter()

onMounted(() => {
  pf.load()
  pf.loadHealth()
})

function analyzeStock(code: string) {
  app.selectStock(code)
  router.push({ name: 'technical' })
}

// Close position modal
const showCloseModal = ref(false)
const closingPosition = ref<any>(null)
const closePrice = ref(0)
const closeReason = ref('manual')

function openCloseModal(pos: any) {
  closingPosition.value = pos
  closePrice.value = pos.current_price || pos.entry_price
  closeReason.value = 'manual'
  showCloseModal.value = true
}

async function confirmClose() {
  if (!closingPosition.value) return
  await pf.closePosition(closingPosition.value.id, {
    exit_price: closePrice.value,
    exit_reason: closeReason.value,
  })
  showCloseModal.value = false
  pf.loadHealth()
}

// Active positions table
const positionColumns: DataTableColumns = [
  {
    title: '代碼', key: 'code', width: 70, fixed: 'left',
    render: (r: any) => h('span', {
      style: { fontWeight: 600, cursor: 'pointer', color: '#2080f0' },
      onClick: () => analyzeStock(r.code),
    }, r.code),
  },
  { title: '名稱', key: 'name', width: 80 },
  { title: '張', key: 'lots', width: 45, align: 'right' },
  {
    title: '成本', key: 'entry_price', width: 75, align: 'right',
    render: (r: any) => r.entry_price?.toFixed(2) || '-',
  },
  {
    title: '現價', key: 'current_price', width: 75, align: 'right',
    render: (r: any) => r.current_price?.toFixed(2) || '-',
  },
  {
    title: '損益%', key: 'pnl_pct', width: 80, align: 'right',
    sorter: (a: any, b: any) => (a.pnl_pct || 0) - (b.pnl_pct || 0),
    render: (r: any) => h('span', {
      style: { color: priceColor(r.pnl_pct), fontWeight: 600 },
    }, fmtPct(r.pnl_pct)),
  },
  {
    title: '損益', key: 'pnl', width: 90, align: 'right',
    sorter: (a: any, b: any) => (a.pnl || 0) - (b.pnl || 0),
    render: (r: any) => h('span', {
      style: { color: priceColor(r.pnl) },
    }, `$${fmtNum(r.pnl, 0)}`),
  },
  {
    title: '停損', key: 'stop_loss', width: 75, align: 'right',
    render: (r: any) => r.stop_loss?.toFixed(2) || '-',
  },
  {
    title: '天', key: 'days_held', width: 45, align: 'right',
    sorter: (a: any, b: any) => (a.days_held || 0) - (b.days_held || 0),
  },
  {
    title: '信號', key: 'exit_signals', width: 120,
    render: (r: any) => {
      const signals = r.exit_signals || []
      if (!signals.length) return h('span', { style: { color: '#999', fontSize: '12px' } }, '持有中')
      return h(NSpace, { size: 4 }, () =>
        signals.map((s: string) => h(NTag, { type: 'error', size: 'small' }, () => s))
      )
    },
  },
  {
    title: '操作', key: 'actions', width: 80, fixed: 'right',
    render: (r: any) => h(NSpace, { size: 4 }, () => [
      h(NButton, { size: 'tiny', type: 'warning', onClick: () => openCloseModal(r) }, () => '平倉'),
      h(NPopconfirm, { onPositiveClick: () => pf.deletePosition(r.id) }, {
        default: () => '確定刪除此倉位？',
        trigger: () => h(NButton, { size: 'tiny', quaternary: true }, () => '×'),
      }),
    ]),
  },
]

// Closed trades table
const closedColumns: DataTableColumns = [
  {
    title: '代碼', key: 'code', width: 70,
    render: (r: any) => h('span', {
      style: { fontWeight: 600, cursor: 'pointer' },
      onClick: () => analyzeStock(r.code),
    }, r.code),
  },
  { title: '名稱', key: 'name', width: 80 },
  { title: '買入', key: 'entry_price', width: 70, render: (r: any) => r.entry_price?.toFixed(2) },
  { title: '賣出', key: 'exit_price', width: 70, render: (r: any) => r.exit_price?.toFixed(2) },
  {
    title: '淨損益', key: 'net_pnl', width: 90,
    sorter: (a: any, b: any) => (a.net_pnl || 0) - (b.net_pnl || 0),
    render: (r: any) => h('span', {
      style: { color: priceColor(r.net_pnl), fontWeight: 600 },
    }, `$${fmtNum(r.net_pnl, 0)}`),
  },
  {
    title: '報酬', key: 'return_pct', width: 70,
    render: (r: any) => h('span', { style: { color: priceColor(r.return_pct) } }, fmtPct(r.return_pct)),
  },
  { title: '天數', key: 'days_held', width: 55 },
  { title: '出場', key: 'exit_reason', width: 80 },
  { title: '日期', key: 'exit_date', width: 90 },
]

// Health warnings
const healthWarnings = computed(() => pf.health?.warnings || [])
const sectorAllocation = computed(() => pf.health?.sector_allocation || [])
const maxSectorPct = computed(() => {
  const allocs = sectorAllocation.value
  return allocs.length ? Math.max(...allocs.map((a: any) => a.pct)) : 0
})
</script>

<template>
  <div>
    <h2 style="margin: 0 0 16px">模擬倉位 — Portfolio Commander</h2>

    <NSpace style="margin-bottom: 16px" align="center">
      <NButton type="primary" @click="pf.load()" :loading="pf.isLoading">
        刷新倉位
      </NButton>
      <NTag v-if="pf.summary.total_positions" size="small">
        {{ pf.summary.total_positions }} 檔持有
      </NTag>
      <NTag v-if="pf.summary.exit_alert_count" type="error" size="small">
        {{ pf.summary.exit_alert_count }} 檔出場警告
      </NTag>
    </NSpace>

    <NSpin :show="pf.isLoading">
      <!-- Summary Cards -->
      <NGrid v-if="pf.summary.total_positions" :cols="5" :x-gap="12" :y-gap="12" style="margin-bottom: 16px">
        <NGi>
          <MetricCard title="持有市值" :value="`$${fmtNum(pf.summary.total_value, 0)}`" />
        </NGi>
        <NGi>
          <MetricCard
            title="未實現損益"
            :value="`$${fmtNum(pf.summary.unrealized_pnl, 0)}`"
            :color="priceColor(pf.summary.unrealized_pnl)"
          />
        </NGi>
        <NGi>
          <MetricCard
            title="未實現報酬"
            :value="fmtPct(pf.summary.unrealized_pnl_pct)"
            :color="priceColor(pf.summary.unrealized_pnl_pct)"
          />
        </NGi>
        <NGi>
          <MetricCard title="已平倉筆數" :value="pf.summary.closed_trades" />
        </NGi>
        <NGi>
          <MetricCard
            title="已實現損益"
            :value="`$${fmtNum(pf.summary.closed_pnl, 0)}`"
            :color="priceColor(pf.summary.closed_pnl)"
          />
        </NGi>
      </NGrid>

      <!-- Health Warnings -->
      <NAlert
        v-for="(w, i) in healthWarnings"
        :key="i"
        :type="w.severity === 'high' ? 'error' : w.severity === 'medium' ? 'warning' : 'info'"
        style="margin-bottom: 8px"
      >
        {{ w.message }}
      </NAlert>

      <!-- Sector Allocation -->
      <NCard v-if="sectorAllocation.length" size="small" style="margin-bottom: 16px">
        <template #header>
          <NSpace align="center" :size="8">
            <span style="font-weight: 700">板塊配置</span>
            <NTag v-if="maxSectorPct > 40" type="error" size="small">集中風險</NTag>
          </NSpace>
        </template>
        <div style="display: flex; gap: 12px; flex-wrap: wrap">
          <div v-for="sa in sectorAllocation" :key="sa.sector" style="min-width: 140px">
            <div style="display: flex; justify-content: space-between; font-size: 12px; margin-bottom: 2px">
              <span>{{ sa.sector }}</span>
              <span style="font-weight: 600">{{ sa.pct }}% ({{ sa.count }}檔)</span>
            </div>
            <NProgress
              type="line"
              :percentage="sa.pct"
              :color="sa.pct > 40 ? '#e53e3e' : sa.pct > 25 ? '#f0a020' : '#18a058'"
              :height="8"
              :show-indicator="false"
            />
          </div>
        </div>
      </NCard>

      <!-- Active Positions -->
      <NCard title="持有部位" size="small" style="margin-bottom: 16px">
        <NDataTable
          v-if="pf.positions.length"
          :columns="positionColumns"
          :data="pf.positions"
          :pagination="false"
          size="small"
          :bordered="false"
          :single-line="false"
          :scroll-x="900"
          :row-class-name="(r: any) => r.exit_signals?.length ? 'exit-alert-row' : ''"
        />
        <NEmpty v-else description="尚無模擬倉位，請在技術分析頁的「部位計算機」點擊「模擬買入」" />
      </NCard>

      <!-- Closed Trades -->
      <NCard v-if="pf.closed.length" size="small" style="margin-bottom: 16px">
        <template #header>
          <NSpace align="center" :size="8">
            <span>已平倉記錄</span>
            <NTag v-if="pf.summary.win_rate > 0" size="small">
              勝率 {{ fmtPct(pf.summary.win_rate) }}
            </NTag>
          </NSpace>
        </template>
        <NDataTable
          :columns="closedColumns"
          :data="[...pf.closed].reverse()"
          :pagination="{ pageSize: 10 }"
          size="small"
          :bordered="false"
          :single-line="false"
          :scroll-x="700"
        />
      </NCard>

      <NEmpty
        v-if="!pf.isLoading && !pf.positions.length && !pf.closed.length"
        description="尚無任何模擬倉位記錄"
        style="margin: 40px 0"
      />
    </NSpin>

    <!-- Close Position Modal -->
    <NModal v-model:show="showCloseModal" preset="dialog" title="平倉確認" positive-text="確認平倉" @positive-click="confirmClose">
      <div v-if="closingPosition" style="margin: 8px 0">
        <p><strong>{{ closingPosition.code }}</strong> {{ closingPosition.name }} — {{ closingPosition.lots }} 張</p>
        <p>成本: ${{ closingPosition.entry_price?.toFixed(2) }}</p>
        <div style="margin: 8px 0">
          <span style="font-size: 12px; color: #666">賣出價格</span>
          <NInputNumber v-model:value="closePrice" :min="0" :step="0.5" style="margin-top: 4px" />
        </div>
        <div>
          <span style="font-size: 12px; color: #666">出場原因</span>
          <NInput v-model:value="closeReason" placeholder="manual / stop_loss / trailing / take_profit" style="margin-top: 4px" />
        </div>
        <div v-if="closePrice > 0" style="margin-top: 8px; font-size: 13px">
          <span :style="{ color: priceColor(closePrice - closingPosition.entry_price), fontWeight: 600 }">
            預估損益: ${{ fmtNum((closePrice - closingPosition.entry_price) * closingPosition.lots * 1000, 0) }}
            ({{ fmtPct(closePrice / closingPosition.entry_price - 1) }})
          </span>
        </div>
      </div>
    </NModal>
  </div>
</template>

<style>
.exit-alert-row td {
  background-color: rgba(229, 62, 62, 0.05) !important;
}
</style>
