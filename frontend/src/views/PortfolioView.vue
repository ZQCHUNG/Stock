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
import EquityCurveChart from '../components/EquityCurveChart.vue'
import ExposureTreemap from '../components/ExposureTreemap.vue'
import CorrelationHeatmap from '../components/CorrelationHeatmap.vue'
import EfficientFrontierChart from '../components/EfficientFrontierChart.vue'

const app = useAppStore()
const pf = usePortfolioStore()
const router = useRouter()

onMounted(() => {
  pf.load()
  pf.loadHealth()
  pf.loadExitAlerts()
  pf.loadEquityLedger()
  pf.loadAnalytics()
  pf.loadPerformance()
  pf.loadBriefing()
  pf.loadStressTest()
  pf.loadCorrelation()
  pf.loadOptimalExposure()
  pf.loadMarketRegime()
  pf.loadEfficientFrontier()
  pf.loadBehavioralAudit()
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

// Confidence accuracy table columns
const confidenceColumns: DataTableColumns = [
  { title: '信心區間', key: 'bracket', width: 140 },
  { title: '筆數', key: 'count', width: 60, align: 'right' },
  {
    title: '平均報酬', key: 'avg_return', width: 90, align: 'right',
    render: (r: any) => h('span', { style: { color: priceColor(r.avg_return) } }, fmtPct(r.avg_return)),
  },
  {
    title: '勝率', key: 'win_rate', width: 80, align: 'right',
    render: (r: any) => h('span', {
      style: { color: (r.win_rate || 0) >= 0.5 ? '#18a058' : '#e53e3e' },
    }, fmtPct(r.win_rate)),
  },
]

// Health warnings
const healthWarnings = computed(() => pf.health?.warnings || [])
const sectorAllocation = computed(() => pf.health?.sector_allocation || [])
const maxSectorPct = computed(() => {
  const allocs = sectorAllocation.value
  return allocs.length ? Math.max(...allocs.map((a: any) => a.pct)) : 0
})

// Worker exit alerts (from Redis)
const workerExitAlerts = computed(() => pf.exitAlerts || [])

// Delta equity (today vs yesterday)
const deltaEquity = computed(() => pf.equityLedger?.delta_equity)

// Briefing insights
const briefingInsights = computed(() => pf.briefing?.insights || [])

// Analytics
const analyticsData = computed(() => pf.analytics)

// Performance data (equity curve + MDD)
const perfData = computed(() => pf.performance)

// Stress test data (Gemini R32)
const stressData = computed(() => pf.stressTest)

// Correlation matrix (Gemini R33)
const corrData = computed(() => pf.correlation)

// Priority actions — Action Hub (Gemini R33)
const priorityActions = computed(() => pf.briefing?.priority_actions || [])

const actionSeverityType = (s: string) => s === 'high' ? 'error' : s === 'medium' ? 'warning' : 'info'

// Kelly Criterion / Optimal Exposure (Gemini R34)
const kellyData = computed(() => pf.optimalExposure)

// Risk ratios (Gemini R34)
const riskRatios = computed(() => perfData.value?.risk_ratios)

// Rebalancing simulator (Gemini R34)
const simData = computed(() => pf.rebalanceSim)
const simLoading = ref(false)

// Market regime (Gemini R35)
const regimeData = computed(() => pf.marketRegime)
const regimeColor = computed(() => {
  const r = regimeData.value?.regime_en
  if (r === 'trend_explosive') return '#18a058'
  if (r === 'trend_mild') return '#2080f0'
  if (r === 'range_volatile') return '#e53e3e'
  return '#f0a020'
})

// Efficient frontier (Gemini R35)
const efData = computed(() => pf.efficientFrontier)

// Behavioral audit (Gemini R35)
const behaviorData = computed(() => pf.behavioralAudit)

async function runRebalanceSim() {
  // Collect current position codes + rotation suggestion targets
  const currentCodes = pf.positions.map((p: any) => p.code)
  // Extract rotation suggestion target codes from briefing
  const rotationInsights = briefingInsights.value.filter((i: any) => i.type === 'rotation')
  const newCodes = new Set(currentCodes)
  for (const ins of rotationInsights) {
    // Parse "轉進 XXXX" from message
    const m = ins.message.match(/轉進\s+(\d{4})/)
    if (m) newCodes.add(m[1])
  }
  simLoading.value = true
  await pf.simulateRebalance([...newCodes])
  simLoading.value = false
}
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
      <NTag v-if="workerExitAlerts.length" type="error" size="small" :bordered="false" style="font-weight: 700">
        🔴 Worker 偵測 {{ workerExitAlerts.length }} 檔觸發
      </NTag>
      <span v-if="deltaEquity" style="font-size: 12px">
        今日 Delta:
        <span :style="{ color: priceColor(deltaEquity.change), fontWeight: 600 }">
          ${{ fmtNum(deltaEquity.change, 0) }} ({{ fmtPct(deltaEquity.change_pct) }})
        </span>
      </span>
    </NSpace>

    <NSpin :show="pf.isLoading">
      <!-- Action Hub: Top 3 Priority Actions (Gemini R33) -->
      <NCard v-if="priorityActions.length" size="small" style="margin-bottom: 12px; border-left: 4px solid #e53e3e">
        <template #header>
          <NSpace align="center" :size="8">
            <span style="font-weight: 700">三大核心決策</span>
            <NTag size="small" type="error" :bordered="false">Action Hub</NTag>
          </NSpace>
        </template>
        <NGrid :cols="3" :x-gap="12" :y-gap="12">
          <NGi v-for="(action, i) in priorityActions" :key="i">
            <div
              :style="{
                border: `1px solid ${action.severity === 'high' ? '#e53e3e' : action.severity === 'medium' ? '#f0a020' : '#ccc'}`,
                borderRadius: '6px',
                padding: '10px 12px',
                background: action.severity === 'high' ? 'rgba(229,62,62,0.04)' : 'transparent',
              }"
            >
              <NSpace align="center" :size="6" style="margin-bottom: 4px">
                <span style="font-size: 16px">{{ action.icon }}</span>
                <NTag :type="actionSeverityType(action.severity)" size="small">{{ action.label }}</NTag>
              </NSpace>
              <div style="font-size: 12px; line-height: 1.5">{{ action.message }}</div>
            </div>
          </NGi>
        </NGrid>
      </NCard>

      <!-- AI Strategic Briefing (Gemini R26) -->
      <NCard v-if="briefingInsights.length" size="small" style="margin-bottom: 12px">
        <template #header>
          <NSpace align="center" :size="8">
            <span style="font-weight: 700">今日戰略簡報</span>
            <NTag size="small" :bordered="false">Chief of Staff</NTag>
          </NSpace>
        </template>
        <div v-for="(insight, i) in briefingInsights" :key="i" style="margin-bottom: 6px; font-size: 13px">
          <span style="margin-right: 6px">{{ insight.icon }}</span>
          <span :style="{ fontWeight: insight.severity === 'high' ? 600 : 400 }">{{ insight.message }}</span>
        </div>
      </NCard>

      <!-- Worker Exit Alerts (Gemini R25) -->
      <NAlert v-if="workerExitAlerts.length" type="error" style="margin-bottom: 12px">
        <template #header>🔴 Worker 偵測出場信號（{{ workerExitAlerts.length }} 檔）</template>
        <NSpace :size="6" style="flex-wrap: wrap">
          <NTag
            v-for="(a, i) in workerExitAlerts"
            :key="i"
            type="error"
            size="small"
            style="cursor: pointer"
            @click="analyzeStock(a.code)"
          >
            {{ a.code }} {{ a.name }} @ ${{ a.current_price?.toFixed(2) }}
            ({{ fmtPct(a.pnl_pct) }}) — {{ a.exit_signals?.join(', ') }}
          </NTag>
        </NSpace>
      </NAlert>

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

      <!-- Kelly Optimal Exposure (Gemini R34) -->
      <NCard v-if="kellyData?.has_data" size="small" style="margin-bottom: 16px">
        <template #header>
          <NSpace align="center" :size="8">
            <span style="font-weight: 700">曝險水位</span>
            <NTag size="small" :bordered="false">Kelly Criterion</NTag>
            <NTag size="small" :type="kellyData.regime === '攻擊' ? 'success' : kellyData.regime === '盤整' ? 'warning' : 'error'">
              {{ kellyData.regime }}模式
            </NTag>
            <NTag v-if="regimeData?.has_data" size="small" :style="{ color: regimeColor, borderColor: regimeColor }">
              {{ regimeData.regime }} (ADX {{ regimeData.adx }})
            </NTag>
          </NSpace>
        </template>
        <NGrid :cols="4" :x-gap="12" :y-gap="12">
          <NGi>
            <MetricCard title="建議曝險" :value="fmtPct(kellyData.suggested_exposure)" />
          </NGi>
          <NGi>
            <MetricCard
              title="目前曝險"
              :value="fmtPct(kellyData.current_exposure)"
              :color="Math.abs(kellyData.current_exposure - kellyData.suggested_exposure) > 0.15 ? '#e53e3e' : '#18a058'"
            />
          </NGi>
          <NGi>
            <MetricCard title="建議現金" :value="fmtPct(kellyData.suggested_cash)" />
          </NGi>
          <NGi>
            <MetricCard title="勝率/賠率" :value="`${fmtPct(kellyData.win_rate)} / ${kellyData.payoff_ratio}x`" />
          </NGi>
        </NGrid>
        <div style="margin-top: 8px; font-size: 12px">
          <NProgress
            type="line"
            :percentage="Math.min(100, kellyData.current_exposure * 100)"
            :color="Math.abs(kellyData.current_exposure - kellyData.suggested_exposure) > 0.15 ? '#e53e3e' : '#18a058'"
            :height="10"
            :show-indicator="false"
          />
          <div style="display: flex; justify-content: space-between; margin-top: 2px; color: #999">
            <span>0%</span>
            <span style="color: #2080f0; font-weight: 600">Kelly: {{ fmtPct(kellyData.suggested_exposure) }}</span>
            <span>100%</span>
          </div>
          <div style="margin-top: 4px; font-weight: 500">{{ kellyData.advice }}</div>
        </div>
      </NCard>

      <!-- Equity Curve + MDD (Gemini R28) -->
      <NCard v-if="perfData?.has_data" size="small" style="margin-bottom: 16px">
        <template #header>
          <NSpace align="center" :size="8">
            <span style="font-weight: 700">績效曲線</span>
            <NTag v-if="perfData.summary" size="small" :type="perfData.summary.total_return >= 0 ? 'success' : 'error'">
              累計 {{ fmtPct(perfData.summary.total_return) }}
            </NTag>
            <NTag v-if="perfData.summary?.max_drawdown" size="small" type="warning">
              MDD {{ fmtPct(-perfData.summary.max_drawdown) }}
            </NTag>
            <NTag v-if="perfData.shadow_equity" size="small" :bordered="false" style="color: #f0a020">
              vs AI 影子組合
            </NTag>
            <template v-if="perfData.alpha_beta">
              <NTag size="small" :type="(perfData.alpha_beta.alpha_annual || 0) >= 0 ? 'success' : 'error'">
                Alpha {{ fmtPct(perfData.alpha_beta.alpha_annual) }}
              </NTag>
              <NTag size="small" :bordered="false">
                Beta {{ perfData.alpha_beta.beta?.toFixed(2) }}
              </NTag>
            </template>
            <template v-if="riskRatios?.sortino != null">
              <NTag size="small" :type="(riskRatios.sortino || 0) >= 1.5 ? 'success' : (riskRatios.sortino || 0) >= 0.5 ? 'warning' : 'error'">
                Sortino {{ riskRatios.sortino?.toFixed(2) }}
              </NTag>
            </template>
            <template v-if="riskRatios?.calmar != null">
              <NTag size="small" :bordered="false">
                Calmar {{ riskRatios.calmar?.toFixed(2) }}
              </NTag>
            </template>
          </NSpace>
        </template>
        <EquityCurveChart
          :dates="perfData.dates"
          :equity="perfData.equity"
          :hwm="perfData.hwm"
          :drawdown="perfData.drawdown"
          :shadow-dates="perfData.shadow_dates"
          :shadow-equity="perfData.shadow_equity"
        />
      </NCard>

      <!-- Exposure Treemap (Gemini R28) -->
      <NCard v-if="pf.positions.length >= 2" size="small" style="margin-bottom: 16px">
        <template #header>
          <NSpace align="center" :size="8">
            <span style="font-weight: 700">曝險矩陣</span>
            <NTag size="small" :bordered="false">Exposure Treemap</NTag>
          </NSpace>
        </template>
        <ExposureTreemap :positions="pf.positions" />
      </NCard>

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
          <div v-for="sa in sectorAllocation" :key="sa.sector" style="min-width: 180px">
            <div style="display: flex; justify-content: space-between; font-size: 12px; margin-bottom: 2px">
              <span>{{ sa.sector }}</span>
              <span style="font-weight: 600">{{ sa.pct }}% · ${{ fmtNum(sa.value, 0) }} ({{ sa.count }}檔)</span>
            </div>
            <NProgress
              type="line"
              :percentage="sa.pct"
              :color="sa.pct > 50 ? '#e53e3e' : sa.pct > 30 ? '#f0a020' : '#18a058'"
              :height="8"
              :show-indicator="false"
            />
            <div style="font-size: 11px; color: #999; margin-top: 1px">{{ sa.codes?.join(', ') }}</div>
          </div>
        </div>
      </NCard>

      <!-- Stress Test (Gemini R32) -->
      <NCard v-if="stressData?.has_data" size="small" style="margin-bottom: 16px">
        <template #header>
          <NSpace align="center" :size="8">
            <span style="font-weight: 700">壓力測試</span>
            <NTag size="small" :bordered="false">Stress Test</NTag>
            <NTag size="small">{{ stressData.position_count }} 檔 · ${{ fmtNum(stressData.total_value, 0) }}</NTag>
          </NSpace>
        </template>
        <NGrid :cols="3" :x-gap="12" :y-gap="12">
          <NGi v-for="s in stressData.scenarios" :key="s.name">
            <div style="border: 1px solid var(--n-border-color); border-radius: 6px; padding: 12px">
              <div style="font-size: 12px; color: var(--n-text-color-3); margin-bottom: 4px">{{ s.name }}</div>
              <div style="font-size: 11px; color: #999; margin-bottom: 6px">{{ s.description }}</div>
              <div :style="{ fontSize: '20px', fontWeight: 700, color: '#e53e3e' }">
                ${{ fmtNum(s.estimated_loss, 0) }}
              </div>
              <div style="font-size: 12px; color: #e53e3e">
                {{ fmtPct(s.loss_pct) }}
              </div>
            </div>
          </NGi>
        </NGrid>
      </NCard>

      <!-- Correlation Heatmap (Gemini R33) -->
      <NCard v-if="corrData?.has_data" size="small" style="margin-bottom: 16px">
        <template #header>
          <NSpace align="center" :size="8">
            <span style="font-weight: 700">相關性矩陣</span>
            <NTag size="small" :bordered="false">Correlation Matrix</NTag>
            <NTag size="small">{{ corrData.data_points }} 日數據</NTag>
            <NTag v-if="corrData.high_corr_pairs?.length" type="error" size="small">
              {{ corrData.high_corr_pairs.length }} 組高相關 (ρ>0.7)
            </NTag>
          </NSpace>
        </template>
        <CorrelationHeatmap
          :codes="corrData.codes"
          :names="corrData.names"
          :matrix="corrData.matrix"
        />
        <div v-if="corrData.high_corr_pairs?.length" style="margin-top: 8px; font-size: 12px">
          <div style="font-weight: 600; margin-bottom: 4px; color: #e53e3e">高相關配對 (|ρ| > 0.7):</div>
          <NSpace :size="6" style="flex-wrap: wrap">
            <NTag
              v-for="(pair, i) in corrData.high_corr_pairs"
              :key="i"
              :type="pair.correlation > 0.85 ? 'error' : 'warning'"
              size="small"
            >
              {{ pair.code_a }} × {{ pair.code_b }} = {{ pair.correlation.toFixed(3) }}
            </NTag>
          </NSpace>
        </div>
      </NCard>

      <!-- Rebalancing Simulator (Gemini R34) -->
      <NCard v-if="pf.positions.length >= 2" size="small" style="margin-bottom: 16px">
        <template #header>
          <NSpace align="center" :size="8">
            <span style="font-weight: 700">模擬重組</span>
            <NTag size="small" :bordered="false">What-If Simulator</NTag>
            <NButton size="tiny" type="primary" :loading="simLoading" @click="runRebalanceSim">
              執行模擬
            </NButton>
          </NSpace>
        </template>
        <div v-if="!simData" style="font-size: 12px; color: #999">
          點擊「執行模擬」，系統將以目前持股 + 換股建議標的計算新的相關性矩陣與壓力測試
        </div>
        <div v-if="simData?.has_data">
          <NGrid :cols="2" :x-gap="12" :y-gap="12">
            <NGi>
              <div style="font-size: 13px; font-weight: 600; margin-bottom: 6px">重組後相關性</div>
              <CorrelationHeatmap
                :codes="simData.codes"
                :names="simData.codes"
                :matrix="simData.matrix"
              />
              <NSpace v-if="simData.high_corr_pairs?.length" :size="4" style="margin-top: 4px; flex-wrap: wrap">
                <NTag
                  v-for="(p, i) in simData.high_corr_pairs"
                  :key="i"
                  :type="p.correlation > 0.85 ? 'error' : 'warning'"
                  size="small"
                >
                  {{ p.code_a }} × {{ p.code_b }} = {{ p.correlation }}
                </NTag>
              </NSpace>
              <div v-else style="font-size: 12px; color: #18a058; margin-top: 4px">
                無高相關配對 — 分散度良好
              </div>
            </NGi>
            <NGi>
              <div style="font-size: 13px; font-weight: 600; margin-bottom: 6px">重組後壓力測試</div>
              <div v-if="simData.stress_test" style="display: flex; flex-direction: column; gap: 8px">
                <div style="border: 1px solid var(--n-border-color); border-radius: 6px; padding: 8px">
                  <div style="font-size: 11px; color: #999">基準回調 (-3%)</div>
                  <div style="font-size: 18px; font-weight: 700; color: #e53e3e">
                    ${{ fmtNum(simData.stress_test.base_loss, 0) }}
                  </div>
                </div>
                <div style="border: 1px solid var(--n-border-color); border-radius: 6px; padding: 8px">
                  <div style="font-size: 11px; color: #999">黑天鵝 (-7%)</div>
                  <div style="font-size: 18px; font-weight: 700; color: #e53e3e">
                    ${{ fmtNum(simData.stress_test.swan_loss, 0) }}
                  </div>
                </div>
                <div style="border: 1px solid var(--n-border-color); border-radius: 6px; padding: 8px">
                  <div style="font-size: 11px; color: #999">ATR 殺盤 (-2×ATR)</div>
                  <div style="font-size: 18px; font-weight: 700; color: #e53e3e">
                    ${{ fmtNum(simData.stress_test.atr_loss, 0) }}
                  </div>
                </div>
              </div>
            </NGi>
          </NGrid>
        </div>
      </NCard>

      <!-- Efficient Frontier (Gemini R35) -->
      <NCard v-if="efData?.has_data" size="small" style="margin-bottom: 16px">
        <template #header>
          <NSpace align="center" :size="8">
            <span style="font-weight: 700">效率前緣</span>
            <NTag size="small" :bordered="false">Efficient Frontier</NTag>
            <NTag size="small">目前 Sharpe {{ efData.current?.sharpe }}</NTag>
            <NTag size="small" type="success">最佳 Sharpe {{ efData.max_sharpe?.sharpe }}</NTag>
          </NSpace>
        </template>
        <EfficientFrontierChart
          :sim-returns="efData.sim_returns"
          :sim-vols="efData.sim_vols"
          :sim-sharpes="efData.sim_sharpes"
          :current="efData.current"
          :max-sharpe="efData.max_sharpe"
        />
        <div v-if="efData.max_sharpe?.weights" style="margin-top: 8px; font-size: 12px">
          <div style="font-weight: 600; margin-bottom: 4px">最佳配置權重:</div>
          <NSpace :size="6" style="flex-wrap: wrap">
            <NTag v-for="(w, code) in efData.max_sharpe.weights" :key="code" size="small">
              {{ code }}: {{ (w * 100).toFixed(1) }}%
            </NTag>
          </NSpace>
        </div>
      </NCard>

      <!-- Behavioral Audit (Gemini R35) -->
      <NCard v-if="behaviorData?.has_data && behaviorData.tag_stats?.length" size="small" style="margin-bottom: 16px">
        <template #header>
          <NSpace align="center" :size="8">
            <span style="font-weight: 700">行為鏡像</span>
            <NTag size="small" :bordered="false">Behavioral Mirror</NTag>
          </NSpace>
        </template>
        <NDataTable
          :columns="[
            { title: '標籤', key: 'tag', width: 120 },
            { title: '筆數', key: 'count', width: 60, align: 'right' },
            { title: '勝率', key: 'win_rate', width: 80, align: 'right',
              render: (r: any) => h('span', { style: { color: (r.win_rate || 0) >= 0.5 ? '#18a058' : '#e53e3e' } }, fmtPct(r.win_rate)) },
            { title: '平均報酬', key: 'avg_return', width: 90, align: 'right',
              render: (r: any) => h('span', { style: { color: priceColor(r.avg_return) } }, fmtPct(r.avg_return)) },
            { title: '淨損益', key: 'total_pnl', width: 100, align: 'right',
              render: (r: any) => h('span', { style: { color: priceColor(r.total_pnl) } }, '$' + fmtNum(r.total_pnl, 0)) },
          ]"
          :data="behaviorData.tag_stats"
          :pagination="false"
          size="small"
          :bordered="false"
          :single-line="false"
        />
        <NAlert v-if="behaviorData.worst_pattern" type="error" style="margin-top: 8px" :bordered="false">
          心理導師建議：帶有「{{ behaviorData.worst_pattern.tag }}」標籤的交易勝率僅
          {{ fmtPct(behaviorData.worst_pattern.win_rate) }}（{{ behaviorData.worst_pattern.count }} 筆），
          建議在此類交易前強制執行 5 分鐘冷靜期
        </NAlert>
        <NAlert v-if="behaviorData.best_pattern" type="success" style="margin-top: 8px" :bordered="false">
          優勢模式：「{{ behaviorData.best_pattern.tag }}」標籤交易勝率高達
          {{ fmtPct(behaviorData.best_pattern.win_rate) }}，持續保持此決策模式
        </NAlert>
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

      <!-- Win-Loss Analytics (Gemini R26) -->
      <NCard v-if="analyticsData && pf.closed.length >= 3" size="small" style="margin-bottom: 16px">
        <template #header>
          <NSpace align="center" :size="8">
            <span style="font-weight: 700">戰果統計</span>
            <NTag size="small" :bordered="false">Win-Loss Analytics</NTag>
          </NSpace>
        </template>
        <NGrid :cols="5" :x-gap="12" :y-gap="12" style="margin-bottom: 12px">
          <NGi>
            <MetricCard
              title="勝率"
              :value="fmtPct(analyticsData.win_rate)"
              :color="(analyticsData.win_rate || 0) >= 0.5 ? '#18a058' : '#e53e3e'"
            />
          </NGi>
          <NGi>
            <MetricCard
              title="獲利因子"
              :value="analyticsData.profit_factor?.toFixed(2) || '-'"
              :color="(analyticsData.profit_factor || 0) >= 1.5 ? '#18a058' : (analyticsData.profit_factor || 0) >= 1 ? '#f0a020' : '#e53e3e'"
            />
          </NGi>
          <NGi>
            <MetricCard
              title="期望值"
              :value="`$${fmtNum(analyticsData.expectancy, 0)}`"
              :color="priceColor(analyticsData.expectancy)"
            />
          </NGi>
          <NGi>
            <MetricCard
              title="平均持有天數"
              :value="analyticsData.avg_days_held?.toFixed(1) || '-'"
            />
          </NGi>
          <NGi>
            <MetricCard
              title="紀律分數"
              :value="analyticsData.discipline?.score || '-'"
              :color="(analyticsData.discipline?.score || 0) >= 80 ? '#18a058' : (analyticsData.discipline?.score || 0) >= 60 ? '#f0a020' : '#e53e3e'"
            />
          </NGi>
        </NGrid>

        <!-- Confidence Accuracy Table -->
        <div v-if="analyticsData.confidence_accuracy?.length" style="margin-top: 8px">
          <div style="font-size: 13px; font-weight: 600; margin-bottom: 6px">信心乘數準確度驗證</div>
          <NDataTable
            :columns="confidenceColumns"
            :data="analyticsData.confidence_accuracy"
            :pagination="false"
            size="small"
            :bordered="false"
            :single-line="false"
          />
        </div>

        <!-- Best / Worst -->
        <div v-if="analyticsData.best_trade || analyticsData.worst_trade" style="margin-top: 10px; font-size: 12px; display: flex; gap: 16px">
          <span v-if="analyticsData.best_trade" style="color: #18a058">
            最佳: {{ analyticsData.best_trade.code }} {{ fmtPct(analyticsData.best_trade.return_pct) }}
          </span>
          <span v-if="analyticsData.worst_trade" style="color: #e53e3e">
            最差: {{ analyticsData.worst_trade.code }} {{ fmtPct(analyticsData.worst_trade.return_pct) }}
          </span>
        </div>
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
