<script setup lang="ts">
import { h, ref, onMounted, reactive, computed } from 'vue'
import { NCard, NButton, NDataTable, NSpin, NSpace, NTag, NEmpty, NAlert, NGrid, NGi, NCollapse, NCollapseItem, NTooltip, NProgress, NBadge } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { useRouter } from 'vue-router'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { PieChart, BarChart } from 'echarts/charts'
import { TooltipComponent, LegendComponent, GridComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useAppStore } from '../stores/app'
import { useWatchlistStore } from '../stores/watchlist'
import { systemApi } from '../api/system'
import { fmtPct, fmtNum, priceColor } from '../utils/format'
import ProgressBar from '../components/ProgressBar.vue'

use([PieChart, BarChart, TooltipComponent, LegendComponent, GridComponent, CanvasRenderer])

const app = useAppStore()
const wl = useWatchlistStore()
const router = useRouter()

// Maturity Transition Alerts (Gemini R24 P2)
const transitionAlerts = ref<any[]>([])
const transitionLoading = ref(false)

async function loadTransitionAlerts() {
  transitionLoading.value = true
  try {
    transitionAlerts.value = await systemApi.transitionAlerts(20)
  } catch {
    transitionAlerts.value = []
  }
  transitionLoading.value = false
}

const highValueAlerts = computed(() => transitionAlerts.value.filter(a => a.is_high_value))
const normalAlerts = computed(() => transitionAlerts.value.filter(a => !a.is_high_value))

onMounted(() => {
  wl.load()
  wl.loadOverview()
  wl.loadSectorHeat()
  loadTransitionAlerts()
})

function selectStock(code: string) {
  app.selectStock(code)
}

function analyzeStock(code: string) {
  app.selectStock(code)
  router.push({ name: 'technical' })
}

function addToWatchlist(code: string) {
  wl.add(code)
}

// Check if stock is in watchlist
const watchlistCodes = computed(() => new Set(wl.watchlist.map(s => s.code)))

// Hot Spot Detector: BUY Leaders in Surge/Heating sectors
const hotSpots = computed(() => {
  const sectors = wl.sectorHeat?.sectors || []
  const spots: { code: string; name: string; sector: string; momentum: string; score: number; maturity: string }[] = []
  for (const sec of sectors) {
    if (!['surge', 'heating'].includes(sec.momentum)) continue
    // All BUY stocks in hot sectors, prioritize leaders
    for (const bs of (sec.buy_stocks || [])) {
      spots.push({
        code: bs.code,
        name: bs.name,
        sector: sec.sector,
        momentum: sec.momentum,
        score: bs.leader_score || 0,
        maturity: bs.maturity || 'N/A',
      })
    }
  }
  // Sort by leader_score desc, then momentum (surge first)
  return spots.sort((a, b) => {
    if (a.momentum !== b.momentum) return a.momentum === 'surge' ? -1 : 1
    return b.score - a.score
  })
})

// High-risk sectors (biotech, pharma, etc.)
const HIGH_RISK_SECTORS = new Set([
  'Biotechnology', 'Drug Manufacturers', 'Diagnostics & Research',
  'Medical Devices', 'Medical Instruments & Supplies',
  '生技醫療', '生技', '新藥研發', '醫療器材',
  'Healthcare',
])

// Sector concentration analysis
const sectorDistribution = computed(() => {
  const data = wl.overview.filter((s: any) => !s.error && s.sector)
  if (!data.length) return []
  const counts: Record<string, number> = {}
  for (const s of data) {
    const sector = s.sector || '未分類'
    counts[sector] = (counts[sector] || 0) + 1
  }
  return Object.entries(counts)
    .map(([name, value]) => ({ name, value }))
    .sort((a, b) => b.value - a.value)
})

const sectorConcentrationWarning = computed(() => {
  const total = wl.overview.filter((s: any) => !s.error).length
  if (total < 2) return null
  for (const { name, value } of sectorDistribution.value) {
    const pct = value / total * 100
    if (pct >= 30 && HIGH_RISK_SECTORS.has(name)) {
      return { sector: name, pct: pct.toFixed(0), count: value, total }
    }
  }
  return null
})

const sectorChartOption = computed(() => ({
  tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
  legend: { orient: 'vertical', right: 10, top: 'center', textStyle: { fontSize: 11 } },
  series: [{
    type: 'pie',
    radius: ['40%', '70%'],
    center: ['35%', '50%'],
    avoidLabelOverlap: true,
    itemStyle: { borderRadius: 4, borderColor: '#fff', borderWidth: 2 },
    label: { show: false },
    emphasis: { label: { show: true, fontSize: 13, fontWeight: 'bold' } },
    data: sectorDistribution.value.map(d => ({
      ...d,
      itemStyle: HIGH_RISK_SECTORS.has(d.name)
        ? { color: '#e53e3e' }
        : undefined,
    })),
  }],
}))

// Sector heat bar chart (market-wide V4 signal density)
const watchlistSectors = computed(() => new Set(wl.overview.filter((s: any) => !s.error && s.sector).map((s: any) => s.sector)))

const sectorHeatChartOption = computed(() => {
  const data = wl.sectorHeat?.sectors || []
  if (!data.length) return null
  // Top 10 sectors with at least 2 stocks
  const filtered = data.filter((s: any) => s.total >= 2).slice(0, 10).reverse()
  if (!filtered.length) return null

  const wlSectors = watchlistSectors.value
  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: any) => {
        const d = params[0]
        const sector = filtered[d.dataIndex]
        const buyList = (sector.buy_stocks || []).map((s: any) => {
          const leaderMark = s.leader_score && s.leader_score > 0.6 ? ' ★' : ''
          return `${s.code} ${s.name} (${s.maturity})${leaderMark}`
        }).join('<br/>')
        const momLabels: Record<string, string> = { surge: '🔥 Surge', heating: '↑ Heating', cooling: '↓ Cooling', stable: '→ Stable', new: '🆕 New' }
        const momLabel = momLabels[sector.momentum] || ''
        const deltaStr = sector.delta_heat ? ` (${sector.delta_heat > 0 ? '+' : ''}${(sector.delta_heat * 100).toFixed(0)}pp)` : ''
        const leaderStr = sector.leader ? `<br/>Leader: ${sector.leader.code} ${sector.leader.name} (Score ${sector.leader.score.toFixed(2)})` : ''
        return `<b>${sector.sector}</b>${momLabel ? ' ' + momLabel : ''}<br/>` +
          `訊號密度: ${(sector.heat * 100).toFixed(0)}% (${sector.buy_count}/${sector.total})<br/>` +
          `加權熱度: ${(sector.weighted_heat * 100).toFixed(0)}%${deltaStr}` +
          leaderStr +
          (buyList ? `<br/><br/>BUY 標的:<br/>${buyList}` : '')
      },
    },
    grid: { left: 100, right: 30, top: 10, bottom: 30 },
    xAxis: { type: 'value', max: 1, axisLabel: { formatter: (v: number) => `${(v * 100).toFixed(0)}%` } },
    yAxis: {
      type: 'category',
      data: filtered.map((s: any) => s.sector),
      axisLabel: {
        formatter: (v: string) => wlSectors.has(v) ? `* ${v}` : v,
        fontWeight: (idx: number) => wlSectors.has(filtered[idx]?.sector) ? 'bold' : 'normal',
      },
    },
    series: [{
      type: 'bar',
      data: filtered.map((s: any) => ({
        value: s.heat,
        itemStyle: { color: s.heat >= 0.3 ? '#e53e3e' : s.heat >= 0.15 ? '#dd6b20' : '#38a169' },
      })),
      label: {
        show: true, position: 'right',
        formatter: (p: any) => {
          const sector = filtered[p.dataIndex]
          const pct = `${(p.value * 100).toFixed(0)}%`
          const mom = sector?.momentum
          if (mom === 'surge') return `${pct} 🔥`
          if (mom === 'heating') return `${pct} ↑`
          if (mom === 'cooling') return `${pct} ↓`
          return pct
        },
      },
    }],
  }
})

// Sector heat data freshness
const sectorHeatUpdatedAt = computed(() => {
  const ts = wl.sectorHeat?._updated_at
  if (!ts) return null
  return new Date(ts)
})

const sectorHeatStale = computed(() => {
  const dt = sectorHeatUpdatedAt.value
  if (!dt) return false
  const diffMin = (Date.now() - dt.getTime()) / 60000
  return diffMin > 60 // Stale if > 1 hour old
})

const sectorHeatStatus = computed(() => wl.sectorHeat?._status || 'ok')

const sectorHeatTimeLabel = computed(() => {
  const dt = sectorHeatUpdatedAt.value
  if (!dt) return '即時計算'
  const hh = String(dt.getHours()).padStart(2, '0')
  const mm = String(dt.getMinutes()).padStart(2, '0')
  return `${hh}:${mm} 更新`
})

// L1/L2 drill-down data
const sectorHeatSectors = computed(() => {
  const data = wl.sectorHeat?.sectors || []
  return data.filter((s: any) => s.total >= 2)
})

// Expanded sector state
const expandedSectors = ref<string[]>([])

// Momentum display helpers
function momentumTag(mom: string) {
  switch (mom) {
    case 'surge': return { label: 'Surge', type: 'error' as const, icon: '🔥' }
    case 'heating': return { label: 'Heating', type: 'warning' as const, icon: '↑' }
    case 'cooling': return { label: 'Cooling', type: 'info' as const, icon: '↓' }
    case 'stable': return { label: 'Stable', type: 'default' as const, icon: '→' }
    case 'new': return { label: 'New', type: 'default' as const, icon: '🆕' }
    default: return { label: '', type: 'default' as const, icon: '' }
  }
}

function heatColor(heat: number): string {
  if (heat >= 0.3) return '#e53e3e'
  if (heat >= 0.15) return '#dd6b20'
  return '#38a169'
}

function maturityColor(m: string): string {
  if (m === 'Structural Shift') return '#18a058'
  if (m === 'Trend Formation') return '#f0a020'
  return '#e53e3e'
}

const overviewPagination = reactive({ page: 1, pageSize: 20, showSizePicker: true, pageSizes: [10, 20, 50] })
const btPagination = reactive({ page: 1, pageSize: 15, showSizePicker: true, pageSizes: [10, 15, 25] })

const overviewColumns: DataTableColumns = [
  { title: '代碼', key: 'code', width: 70, sorter: 'default',
    render: (r: any) => h('span', { style: { fontWeight: 600, cursor: 'pointer' }, onClick: () => selectStock(r.code) }, r.code) },
  { title: '名稱', key: 'name', width: 80,
    render: (r: any) => h('span', { style: { cursor: 'pointer' }, onClick: () => selectStock(r.code) }, r.name) },
  { title: '收盤價', key: 'price', width: 90, sorter: (a: any, b: any) => (a.price || 0) - (b.price || 0),
    render: (r: any) => r.price?.toFixed(2) || '-' },
  { title: '漲跌%', key: 'change_pct', width: 80, sorter: (a: any, b: any) => (a.change_pct || 0) - (b.change_pct || 0),
    render: (r: any) => h('span', { style: { color: priceColor(r.change_pct), fontWeight: 600 } }, fmtPct(r.change_pct)) },
  { title: '成交量(張)', key: 'volume_lots', width: 110, sorter: (a: any, b: any) => (a.volume_lots || 0) - (b.volume_lots || 0),
    render: (r: any) => fmtNum(r.volume_lots, 0) },
  { title: '訊號', key: 'signal', width: 70, filterOptions: [
      { label: 'BUY', value: 'BUY' }, { label: 'SELL', value: 'SELL' }, { label: 'HOLD', value: 'HOLD' },
    ], filter: (value: any, row: any) => row.signal === value,
    render: (r: any) => h(NTag, { type: r.signal === 'BUY' ? 'error' : r.signal === 'SELL' ? 'success' : 'default', size: 'small' }, () => r.signal || '-') },
  { title: '成熟度', key: 'signal_maturity', width: 110,
    render: (r: any) => {
      const m = r.signal_maturity || 'N/A'
      const color = m === 'Structural Shift' ? 'success' : m === 'Trend Formation' ? 'warning' : m === 'Speculative Spike' ? 'error' : 'default'
      return h(NTag, { type: color, size: 'small' }, () => m)
    } },
  { title: '趨勢天數', key: 'uptrend_days', width: 80, sorter: (a: any, b: any) => (a.uptrend_days || 0) - (b.uptrend_days || 0) },
  { title: 'RSI', key: 'rsi', width: 60, sorter: (a: any, b: any) => (a.rsi || 0) - (b.rsi || 0),
    render: (r: any) => r.rsi?.toFixed(1) || '-' },
  { title: 'ADX', key: 'adx', width: 60, sorter: (a: any, b: any) => (a.adx || 0) - (b.adx || 0),
    render: (r: any) => r.adx?.toFixed(1) || '-' },
  { title: '產業', key: 'sector', width: 100,
    render: (r: any) => r.sector ? h(NTag, { size: 'small', type: HIGH_RISK_SECTORS.has(r.sector) ? 'error' : 'default' }, () => r.sector) : '-' },
  { title: '操作', key: 'actions', width: 70,
    render: (r: any) => h(NButton, { size: 'tiny', quaternary: true, type: 'error', onClick: (e: Event) => { e.stopPropagation(); wl.remove(r.code) } }, () => '移除') },
]

const btColumns: DataTableColumns = [
  { title: '代碼', key: 'code', width: 70, sorter: 'default' },
  { title: '名稱', key: 'name', width: 80 },
  { title: '總報酬', key: 'total_return', width: 90, sorter: (a: any, b: any) => (a.total_return || 0) - (b.total_return || 0),
    render: (r: any) => h('span', { style: { color: priceColor(r.total_return), fontWeight: 600 } }, fmtPct(r.total_return)) },
  { title: '年化報酬', key: 'annual_return', width: 90, sorter: (a: any, b: any) => (a.annual_return || 0) - (b.annual_return || 0),
    render: (r: any) => h('span', { style: { color: priceColor(r.annual_return) } }, fmtPct(r.annual_return)) },
  { title: '最大回撤', key: 'max_drawdown', width: 90, sorter: (a: any, b: any) => (a.max_drawdown || 0) - (b.max_drawdown || 0),
    render: (r: any) => h('span', { style: { color: '#e53e3e' } }, fmtPct(r.max_drawdown)) },
  { title: 'Sharpe', key: 'sharpe_ratio', width: 80, sorter: (a: any, b: any) => (a.sharpe_ratio || 0) - (b.sharpe_ratio || 0),
    render: (r: any) => r.sharpe_ratio?.toFixed(2) || '-' },
  { title: '勝率', key: 'win_rate', width: 70, render: (r: any) => fmtPct(r.win_rate) },
  { title: '交易次數', key: 'total_trades', width: 80, sorter: (a: any, b: any) => (a.total_trades || 0) - (b.total_trades || 0) },
]
</script>

<template>
  <div>
    <h2 style="margin: 0 0 16px">自選股總覽</h2>

    <!-- Sector concentration warning -->
    <NAlert v-if="sectorConcentrationWarning" type="error" style="margin-bottom: 16px">
      產業集中度警告：{{ sectorConcentrationWarning.sector }} 佔自選股
      {{ sectorConcentrationWarning.pct }}%（{{ sectorConcentrationWarning.count }}/{{ sectorConcentrationWarning.total }}），
      建議分散至不同產業以降低系統性風險
    </NAlert>

    <NSpace style="margin-bottom: 16px">
      <NButton @click="wl.loadOverview()" :loading="wl.isLoading" type="primary">重新載入</NButton>
      <NButton @click="wl.runBatchBacktest()" :loading="wl.isLoading">批次回測</NButton>
      <NButton @click="wl.exportRiskAudit()" :loading="wl.isExporting" type="warning">匯出風險報告</NButton>
    </NSpace>

    <ProgressBar
      v-if="wl.batchProgress.total > 0"
      :current="wl.batchProgress.current"
      :total="wl.batchProgress.total"
      :message="wl.batchProgress.message"
    />

    <NSpin :show="wl.isLoading && wl.batchProgress.total === 0">
      <NEmpty v-if="!wl.overview.length && !wl.isLoading" description="尚無自選股，請在技術分析頁面加入股票" style="margin: 40px 0" />

      <!-- Sector distribution pie chart -->
      <NGrid v-if="sectorDistribution.length >= 2" :cols="1" style="margin-bottom: 16px">
        <NGi>
          <NCard title="產業分佈" size="small">
            <VChart :option="sectorChartOption" style="height: 240px" autoresize />
          </NCard>
        </NGi>
      </NGrid>

      <!-- Sector heat bar chart (market-wide V4 signal density) -->
      <NCard v-if="sectorHeatChartOption" title="產業熱度（全市場 V4 訊號密度）" size="small" style="margin-bottom: 16px">
        <template #header-extra>
          <NSpace align="center" :size="8">
            <NTag v-if="sectorHeatStale" type="warning" size="small">數據可能過期</NTag>
            <NTag v-else-if="sectorHeatStatus !== 'ok'" type="error" size="small">掃描異常</NTag>
            <span style="font-size: 11px; color: #999">{{ sectorHeatTimeLabel }}</span>
            <NButton size="tiny" quaternary @click="wl.loadSectorHeat()" :loading="wl.isSectorHeatLoading">更新</NButton>
          </NSpace>
        </template>
        <VChart :option="sectorHeatChartOption" style="height: 280px" autoresize />
        <div style="font-size: 11px; color: #888; margin-top: 4px">
          * 標記為自選股持有的產業。紅色 >= 30%（熱點板塊），橘色 >= 15%，綠色 &lt; 15%。掃描池: {{ wl.sectorHeat?.scanned || 0 }} 股
        </div>
      </NCard>

      <!-- Hot Spot Detector (Gemini R23 P1) -->
      <NCard v-if="hotSpots.length" size="small" style="margin-bottom: 16px">
        <template #header>
          <NSpace align="center" :size="8">
            <span>🔥 今日熱點標的</span>
            <NTag type="error" size="small">{{ hotSpots.length }} 檔</NTag>
          </NSpace>
        </template>
        <NSpace :size="8" style="flex-wrap: wrap">
          <NTooltip v-for="hs in hotSpots" :key="hs.code" trigger="hover">
            <template #trigger>
              <NTag
                :type="hs.score > 0.6 ? 'warning' : 'error'"
                size="small"
                style="cursor: pointer"
                @click="analyzeStock(hs.code)"
              >
                <template v-if="hs.score > 0.6">★ </template>
                {{ hs.code }} {{ hs.name }}
                <NButton
                  v-if="!watchlistCodes.has(hs.code)"
                  size="tiny"
                  quaternary
                  style="padding: 0 2px; margin-left: 4px; min-width: auto"
                  @click.stop="addToWatchlist(hs.code)"
                >+</NButton>
              </NTag>
            </template>
            <div>
              <div style="font-weight: 600">{{ hs.code }} {{ hs.name }}</div>
              <div>板塊: {{ hs.sector }} {{ hs.momentum === 'surge' ? '🔥 Surge' : '↑ Heating' }}</div>
              <div :style="{ color: maturityColor(hs.maturity) }">{{ hs.maturity }}</div>
              <div v-if="hs.score > 0">Leader Score: {{ hs.score.toFixed(2) }}</div>
              <div style="font-size: 11px; color: #aaa; margin-top: 4px">點擊分析 | + 加入自選</div>
            </div>
          </NTooltip>
        </NSpace>
      </NCard>

      <!-- Maturity Transition Alerts (Gemini R24 P2) -->
      <NCard v-if="transitionAlerts.length" size="small" style="margin-bottom: 16px">
        <template #header>
          <NSpace align="center" :size="8">
            <span>📊 成熟度躍遷通知</span>
            <NBadge v-if="highValueAlerts.length" :value="highValueAlerts.length" type="error" />
            <NTag size="small" :bordered="false">{{ transitionAlerts.length }} 筆</NTag>
          </NSpace>
        </template>
        <template #header-extra>
          <NButton size="tiny" quaternary @click="loadTransitionAlerts()" :loading="transitionLoading">刷新</NButton>
        </template>

        <!-- High-value alerts -->
        <div v-if="highValueAlerts.length" style="margin-bottom: 12px">
          <div style="font-size: 11px; color: #e53e3e; font-weight: 600; margin-bottom: 6px">🔥 高價值躍遷（Leader + 熱板塊）</div>
          <NSpace :size="6" style="flex-wrap: wrap">
            <NTooltip v-for="(a, i) in highValueAlerts" :key="'hv-' + i" trigger="hover">
              <template #trigger>
                <NTag type="error" size="small" style="cursor: pointer; font-weight: 600" @click="analyzeStock(a.code)">
                  ★ {{ a.code }} {{ a.name }}
                  <span style="margin-left: 4px; font-size: 10px">{{ a.from_maturity?.split(' ')[0] }} → {{ a.to_maturity?.split(' ')[0] }}</span>
                  <NButton
                    v-if="!watchlistCodes.has(a.code)"
                    size="tiny"
                    quaternary
                    style="padding: 0 2px; margin-left: 4px; min-width: auto"
                    @click.stop="addToWatchlist(a.code)"
                  >+</NButton>
                </NTag>
              </template>
              <div>
                <div style="font-weight: 600">{{ a.code }} {{ a.name }}</div>
                <div>{{ a.from_maturity }} → {{ a.to_maturity }}</div>
                <div>板塊: {{ a.sector }} ({{ a.momentum }}) Hw={{ ((a.weighted_heat || 0) * 100).toFixed(0) }}%</div>
                <div>Leader Score: {{ (a.leader_score || 0).toFixed(2) }}</div>
                <div style="font-size: 11px; color: #aaa; margin-top: 4px">{{ a.timestamp?.slice(11, 16) }} | 點擊分析</div>
              </div>
            </NTooltip>
          </NSpace>
        </div>

        <!-- Normal alerts -->
        <div v-if="normalAlerts.length">
          <div v-if="highValueAlerts.length" style="font-size: 11px; color: #999; margin-bottom: 6px">其他躍遷</div>
          <NSpace :size="6" style="flex-wrap: wrap">
            <NTooltip v-for="(a, i) in normalAlerts" :key="'na-' + i" trigger="hover">
              <template #trigger>
                <NTag size="small" style="cursor: pointer" @click="analyzeStock(a.code)">
                  {{ a.code }} {{ a.name }}
                  <span style="margin-left: 4px; font-size: 10px; color: #999">{{ a.from_maturity?.split(' ')[0] }} → {{ a.to_maturity?.split(' ')[0] }}</span>
                </NTag>
              </template>
              <div>
                <div>{{ a.code }} {{ a.name }}</div>
                <div>{{ a.from_maturity }} → {{ a.to_maturity }}</div>
                <div>板塊: {{ a.sector }} ({{ a.momentum }})</div>
                <div style="font-size: 11px; color: #aaa; margin-top: 2px">{{ a.timestamp?.slice(11, 16) }}</div>
              </div>
            </NTooltip>
          </NSpace>
        </div>
      </NCard>

      <!-- L1/L2 Sector Drill-down (Gemini R22) -->
      <NCard v-if="sectorHeatSectors.length" title="產業板塊下鑽" size="small" style="margin-bottom: 16px">
        <template #header-extra>
          <NSpace align="center" :size="8">
            <span style="font-size: 11px; color: #999">{{ sectorHeatSectors.length }} 板塊 / {{ wl.sectorHeat?.total_buy || 0 }} BUY</span>
            <span v-if="sectorHeatUpdatedAt" style="font-size: 11px; color: #aaa">{{ sectorHeatTimeLabel }}</span>
          </NSpace>
        </template>
        <NCollapse v-model:expanded-names="expandedSectors" accordion>
          <NCollapseItem v-for="sector in sectorHeatSectors" :key="sector.sector" :name="sector.sector">
            <template #header>
              <div style="display: flex; align-items: center; gap: 8px; width: 100%">
                <!-- Sector name -->
                <span style="font-weight: 600; min-width: 80px">{{ sector.sector }}</span>
                <!-- Heat bar -->
                <NProgress
                  type="line"
                  :percentage="Math.round(sector.weighted_heat * 100)"
                  :color="heatColor(sector.weighted_heat)"
                  :rail-color="'#f0f0f0'"
                  :height="14"
                  :show-indicator="false"
                  style="width: 120px"
                />
                <NTooltip trigger="hover">
                  <template #trigger>
                    <span style="font-size: 12px; min-width: 36px; color: #666">{{ (sector.weighted_heat * 100).toFixed(0) }}%</span>
                  </template>
                  <div>
                    <div>加權熱度: {{ (sector.weighted_heat * 100).toFixed(0) }}%</div>
                    <div>原始熱度: {{ (sector.heat * 100).toFixed(0) }}%</div>
                    <div v-if="sector.weighted_heat !== sector.heat" style="font-size: 11px; color: #aaa; margin-top: 2px">
                      差異來自成熟度加權 (Structural Shift ×2)
                    </div>
                  </div>
                </NTooltip>
                <!-- BUY count -->
                <NTag :type="sector.buy_count > 0 ? 'error' : 'default'" size="small">
                  {{ sector.buy_count }}/{{ sector.total }}
                </NTag>
                <!-- Momentum -->
                <NTag v-if="sector.momentum && sector.momentum !== 'stable'" :type="momentumTag(sector.momentum).type" size="small">
                  {{ momentumTag(sector.momentum).icon }} {{ momentumTag(sector.momentum).label }}
                  <template v-if="sector.delta_heat">
                    {{ sector.delta_heat > 0 ? '+' : '' }}{{ (sector.delta_heat * 100).toFixed(0) }}pp
                  </template>
                </NTag>
                <!-- Crowded trade warning (Gemini R24) -->
                <NTooltip v-if="sector.weighted_heat > 0.8" trigger="hover">
                  <template #trigger>
                    <NTag size="small" :color="{ textColor: '#fff', color: '#9333ea', borderColor: '#9333ea' }">
                      擁擠交易
                    </NTag>
                  </template>
                  <div>
                    <div style="font-weight: 600">擁擠交易警告 (Crowded Trade)</div>
                    <div>加權熱度 {{ (sector.weighted_heat * 100).toFixed(0) }}% > 80%</div>
                    <div>大量資金聚集，信心乘數自動衰減</div>
                    <div style="font-size: 11px; color: #aaa; margin-top: 4px">板塊過熱時，即使訊號為 BUY，也應縮減部位</div>
                  </div>
                </NTooltip>
                <!-- Leader badge -->
                <NTooltip v-if="sector.leader" trigger="hover">
                  <template #trigger>
                    <NTag type="warning" size="small" :bordered="false" style="font-weight: 700">
                      ★ {{ sector.leader.code }} {{ sector.leader.name }}
                    </NTag>
                  </template>
                  <div>
                    <div style="font-weight: 600; margin-bottom: 4px">Leader Score: {{ sector.leader.score.toFixed(2) }}</div>
                    <div>成熟度: {{ sector.leader.maturity }}</div>
                    <div v-if="sector.total < 5" style="font-size: 11px; color: #f0a020; margin-top: 2px">
                      (樣本數: {{ sector.total }}，僅供參考)
                    </div>
                  </div>
                </NTooltip>
              </div>
            </template>

            <!-- Expanded: L2 Subsector breakdown -->
            <div style="padding: 4px 0">
              <!-- L2 subsector list -->
              <div v-if="sector.subsectors?.length" style="margin-bottom: 12px">
                <div style="font-size: 11px; color: #999; margin-bottom: 6px">子產業熱度</div>
                <div v-for="sub in sector.subsectors" :key="sub.sector" style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px; padding: 2px 0">
                  <span style="font-size: 12px; min-width: 80px; color: #555">{{ sub.sector }}</span>
                  <NProgress
                    type="line"
                    :percentage="Math.round(sub.heat * 100)"
                    :color="heatColor(sub.heat)"
                    :rail-color="'#f5f5f5'"
                    :height="10"
                    :show-indicator="false"
                    style="width: 100px"
                  />
                  <span style="font-size: 11px; color: #888; min-width: 60px">
                    {{ (sub.heat * 100).toFixed(0) }}% ({{ sub.buy_count }}/{{ sub.total }})
                  </span>
                  <NTag v-if="sub.total < 3" size="tiny" :bordered="false" style="font-size: 10px; color: #bbb">小樣本</NTag>
                </div>
              </div>

              <!-- BUY stocks detail -->
              <div v-if="sector.buy_stocks?.length">
                <div style="font-size: 11px; color: #999; margin-bottom: 6px">BUY 標的（點擊分析）</div>
                <NSpace :size="6" style="flex-wrap: wrap">
                  <NTooltip v-for="bs in sector.buy_stocks" :key="bs.code" trigger="hover">
                    <template #trigger>
                      <NTag
                        :type="bs.leader_score && bs.leader_score > 0.6 ? 'warning' : 'default'"
                        size="small"
                        style="cursor: pointer"
                        @click="analyzeStock(bs.code)"
                      >
                        <template v-if="bs.leader_score && bs.leader_score > 0.6">★ </template>
                        {{ bs.code }} {{ bs.name }}
                        <NButton
                          v-if="!watchlistCodes.has(bs.code)"
                          size="tiny"
                          quaternary
                          style="padding: 0 2px; margin-left: 4px; min-width: auto"
                          @click.stop="addToWatchlist(bs.code)"
                        >+</NButton>
                      </NTag>
                    </template>
                    <div>
                      <div>{{ bs.code }} {{ bs.name }}</div>
                      <div :style="{ color: maturityColor(bs.maturity) }">{{ bs.maturity }}</div>
                      <div v-if="bs.leader_score">Leader Score: {{ bs.leader_score.toFixed(2) }}</div>
                      <div style="font-size: 11px; color: #aaa; margin-top: 2px">點擊 → 技術分析 | + → 加入自選</div>
                    </div>
                  </NTooltip>
                </NSpace>
              </div>

              <!-- No BUY stocks -->
              <div v-else style="font-size: 12px; color: #aaa">目前無 BUY 訊號</div>
            </div>
          </NCollapseItem>
        </NCollapse>
      </NCard>

      <NCard v-if="wl.overview.length" title="即時總覽" size="small" style="margin-bottom: 16px">
        <NDataTable
          :columns="overviewColumns"
          :data="wl.overview"
          :pagination="overviewPagination"
          :row-props="(r: any) => ({ style: { cursor: 'pointer' }, onClick: () => selectStock(r.code) })"
          size="small"
          :bordered="false"
          :single-line="false"
          :scroll-x="960"
        />
      </NCard>

      <NCard v-if="wl.batchResults.length" title="批次回測結果" size="small">
        <NDataTable
          :columns="btColumns"
          :data="wl.batchResults"
          :pagination="btPagination"
          size="small"
          :scroll-x="650"
        />
      </NCard>
    </NSpin>
  </div>
</template>
