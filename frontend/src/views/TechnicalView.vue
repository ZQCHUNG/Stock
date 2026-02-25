<script setup lang="ts">
import { h, ref, watch, onMounted, nextTick, computed } from 'vue'
import { connect } from 'echarts/core'
import { NGrid, NGi, NCard, NSpin, NAlert, NDescriptions, NDescriptionsItem, NText, NDataTable, NButton, NStatistic } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { NTag, NSpace } from 'naive-ui'
import { useAppStore } from '../stores/app'
import { useTechnicalStore } from '../stores/technical'
import { fmtNum, fmtPct, priceColor } from '../utils/format'
import { useResponsive } from '../composables/useResponsive'
import { backtestApi } from '../api/backtest'
import MetricCard from '../components/MetricCard.vue'
import SignalBadge from '../components/SignalBadge.vue'
import CandlestickChart from '../components/CandlestickChart.vue'
import MacdChart from '../components/MacdChart.vue'
import KdChart from '../components/KdChart.vue'
import RsiChart from '../components/RsiChart.vue'
import BiasChart from '../components/BiasChart.vue'
import PositionCalculator from '../components/PositionCalculator.vue'
import SizingAdvisor from '../components/SizingAdvisor.vue'
import TrailModeBadge from '../components/TrailModeBadge.vue'
import BoldStatusPanel from '../components/BoldStatusPanel.vue'
import WinnerDnaCard from '../components/WinnerDnaCard.vue'
import VChart from 'vue-echarts'

const app = useAppStore()
const tech = useTechnicalStore()
const { cols, isMobile } = useResponsive()
const signalCols = cols(2, 4, 4)
const indicatorCols = cols(3, 5, 5)
const chartCols = cols(1, 2, 2)
const descCols = cols(1, 3, 3)

async function loadData() {
  const code = app.currentStockCode
  await tech.loadAll(code)
  await tech.loadV4SignalsFull(code)
  tech.loadAdaptiveSignal(code)  // Non-blocking: load adaptive signal in background
  tech.loadBoldSignal(code)      // Non-blocking: load bold signal in background
  tech.loadBoldStatus(code)      // Non-blocking: load bold status panel (R63)
  tech.loadSectorContext(code)   // Non-blocking: load sector RS context (R64)
  tech.loadVcp(code)             // Non-blocking: load VCP detection (R85)
  // R86: Load stop levels using current close as hypothetical entry
  const lastClose = tech.stockData?.columns?.close?.slice(-1)?.[0]
  if (lastClose) {
    const entryType = tech.v4Enhanced?.entry_type || 'squeeze_breakout'
    tech.loadStopLevels(code, lastClose, entryType)
  }
  tech.loadLiquidity(code)       // Non-blocking: load liquidity score (R69)
  tech.loadRiskBudget(code)      // Non-blocking: load risk budget in background
  tech.loadSignalSummary(code)   // Non-blocking: load forward testing data
  tech.loadSqs(code)             // Non-blocking: load SQS data
  tech.loadFundamentals(code)    // Non-blocking: load fundamental data
  tech.loadTrailClassifier(code) // Non-blocking: load trail mode badge (R76)
  tech.loadWinnerDna(code)       // Non-blocking: load Winner DNA match (R90)
  // Connect charts for crosshair + dataZoom sync after data renders
  nextTick(() => { try { connect('tech') } catch { /* charts not ready */ } })
}

onMounted(loadData)
watch(() => app.currentStockCode, loadData)

// Institutional data → row array for NDataTable
const institutionalData = computed(() => {
  const inst = tech.institutional
  if (!inst?.dates?.length) return []
  return inst.dates.map((date: string, i: number) => ({
    date,
    foreign_net: inst.columns.foreign_net?.[i] ?? 0,
    trust_net: inst.columns.trust_net?.[i] ?? 0,
    dealer_net: inst.columns.dealer_net?.[i] ?? 0,
    total_net: inst.columns.total_net?.[i] ?? 0,
  }))
})

function netColor(v: number) { return v > 0 ? '#e53e3e' : v < 0 ? '#38a169' : undefined }

// Trailing stop / stop loss from PositionCalculator
const trailingStopPrice = ref<number | null>(null)
const staticStopLoss = ref<number | null>(null)

function onRiskLoaded(data: { trailingStop: number | null; stopLoss: number }) {
  trailingStopPrice.value = data.trailingStop
  staticStopLoss.value = data.stopLoss
}

const exitLines = computed(() => {
  const lines: { price: number; source: string }[] = []
  if (trailingStopPrice.value && trailingStopPrice.value > (staticStopLoss.value || 0)) {
    lines.push({ price: trailingStopPrice.value, source: '移動停利 (ATR×2)' })
  }
  if (staticStopLoss.value) {
    lines.push({ price: staticStopLoss.value, source: '靜態停損 (-7%)' })
  }
  // R86: Stop levels from ATR-based calculator
  const sl = tech.stopLevels
  if (sl?.initial_stop > 0) {
    lines.push({ price: sl.initial_stop, source: `停損 R86 (${sl.stop_method})` })
    if (sl.targets?.target_1r > 0) {
      lines.push({ price: sl.targets.target_1r, source: '停利 +1R' })
    }
    if (sl.targets?.target_2r > 0) {
      lines.push({ price: sl.targets.target_2r, source: '停利 +2R' })
    }
  }
  return lines
})

// Quick backtest
const quickBtResult = ref<any>(null)
const quickBtLoading = ref(false)
const quickBtCols = cols(2, 4, 6)
const fundamentalCols = cols(2, 3, 4)

async function runQuickBacktest() {
  quickBtLoading.value = true
  try {
    quickBtResult.value = await backtestApi.v4(app.currentStockCode, { period_days: 730 })
  } catch { /* silent */ }
  quickBtLoading.value = false
}

const institutionalColumns: DataTableColumns = [
  { title: '日期', key: 'date', width: 100 },
  { title: '外資', key: 'foreign_net', width: 90, sorter: (a: any, b: any) => a.foreign_net - b.foreign_net,
    render: (r: any) => h('span', { style: { color: netColor(r.foreign_net) } }, fmtNum(r.foreign_net)) },
  { title: '投信', key: 'trust_net', width: 90, sorter: (a: any, b: any) => a.trust_net - b.trust_net,
    render: (r: any) => h('span', { style: { color: netColor(r.trust_net) } }, fmtNum(r.trust_net)) },
  { title: '自營', key: 'dealer_net', width: 90, sorter: (a: any, b: any) => a.dealer_net - b.dealer_net,
    render: (r: any) => h('span', { style: { color: netColor(r.dealer_net) } }, fmtNum(r.dealer_net)) },
  { title: '合計', key: 'total_net', width: 100, sorter: (a: any, b: any) => a.total_net - b.total_net,
    render: (r: any) => h('span', { style: { color: netColor(r.total_net), fontWeight: 600 } }, fmtNum(r.total_net)) },
]

// SQS radar chart option
const sqsRadarOption = computed(() => {
  const sqs = tech.sqsData
  if (!sqs?.breakdown) return null
  const b = sqs.breakdown
  return {
    tooltip: {},
    radar: {
      indicator: [
        { name: '性格匹配', max: 100 },
        { name: '市場環境', max: 100 },
        { name: '法人動向', max: 100 },
        { name: '期望值', max: 100 },
        { name: '板塊熱度', max: 100 },
        { name: '成熟度', max: 100 },
        { name: '估值合理', max: 100 },
        { name: '成長動能', max: 100 },
      ],
      radius: '65%',
    },
    series: [{
      type: 'radar',
      data: [{
        value: [
          b.fitness, b.regime, b.institutional ?? 50, b.net_ev,
          b.heat, b.maturity, b.valuation ?? 50, b.growth ?? 50,
        ],
        name: `SQS ${sqs.sqs}`,
        areaStyle: { opacity: 0.3 },
        lineStyle: { width: 2 },
        itemStyle: { color: sqs.sqs >= 80 ? '#18a058' : sqs.sqs >= 60 ? '#2080f0' : sqs.sqs >= 40 ? '#f0a020' : '#999' },
      }],
    }],
  }
})

function sqsGradeIcon(grade: string): string {
  if (grade === 'diamond') return '\uD83D\uDC8E'
  if (grade === 'gold') return '\uD83E\uDD47'
  if (grade === 'noise') return '\u26AA'
  return ''
}
</script>

<template>
  <div>
    <h2 style="margin: 0 0 16px">
      {{ app.currentStockCode }} {{ app.currentStockName }} - 技術分析
    </h2>

    <NSpin :show="tech.isLoading">
      <NAlert v-if="tech.error" :type="tech.error.includes('超時') ? 'warning' : 'error'" style="margin-bottom: 16px">
        {{ tech.error }}
        <template v-if="tech.error.includes('超時')">
          <br /><small style="opacity: 0.7">此股票可能尚未被快取，資料將於今晚 20:00 排程計算</small>
        </template>
      </NAlert>

      <!-- R76: 股票性格分類 Badge -->
      <TrailModeBadge :data="tech.trailClassifier" />

      <!-- V4 訊號摘要 (Sprint 15: always show grid, use skeleton when loading) -->
      <NGrid :cols="signalCols" :x-gap="12" :y-gap="12" style="margin-bottom: 16px">
        <NGi>
          <MetricCard
            title="V4 訊號"
            :loading="!tech.v4Enhanced && tech.isLoading"
            :bg-color="tech.v4Enhanced?.signal === 'BUY' ? '#fff5f5' : tech.v4Enhanced?.signal === 'SELL' ? '#f0fff4' : undefined"
          >
            <template #default>
              <SignalBadge v-if="tech.v4Enhanced" :signal="tech.v4Enhanced.signal" size="large" />
              <span v-else style="color: var(--text-dimmed)">--</span>
            </template>
          </MetricCard>
        </NGi>
        <NGi>
          <MetricCard
            title="收盤價"
            :loading="!tech.v4Enhanced && tech.isLoading"
            :value="tech.v4Enhanced ? (tech.v4Enhanced.close?.toFixed(2) || '-') : '--'"
          />
        </NGi>
        <NGi>
          <MetricCard
            title="上升趨勢天數"
            :loading="!tech.v4Enhanced && tech.isLoading"
            :value="tech.v4Enhanced ? (tech.v4Enhanced.uptrend_days || 0) : '--'"
            :subtitle="tech.v4Enhanced?.entry_type || ''"
          />
        </NGi>
        <NGi>
          <MetricCard
            title="信心分數"
            :loading="!tech.v4Enhanced && tech.isLoading"
            :value="tech.v4Enhanced ? (tech.v4Enhanced.confidence_score?.toFixed(1) || '1.0') : '--'"
            :color="(tech.v4Enhanced?.confidence_score || 0) >= 1.5 ? '#e53e3e' : undefined"
          />
        </NGi>
      </NGrid>

      <!-- V4+V5 自適應訊號 (Gemini R36) -->
      <NCard v-if="tech.adaptiveSignal" size="small" style="margin-bottom: 16px">
        <template #header>
          <NSpace align="center" :size="8">
            <span style="font-weight: 700">策略混合訊號</span>
            <NTag size="small" :bordered="false">Adaptive V4+V5</NTag>
            <NTag size="small" :type="tech.adaptiveSignal.adaptive?.regime?.includes('trend') ? 'success' : 'warning'">
              {{ tech.adaptiveSignal.adaptive?.regime === 'trend_explosive' ? '趨勢噴發' :
                 tech.adaptiveSignal.adaptive?.regime === 'trend_mild' ? '溫和趨勢' :
                 tech.adaptiveSignal.adaptive?.regime === 'range_volatile' ? '震盪劇烈' : '低波盤整' }}
            </NTag>
          </NSpace>
        </template>
        <NGrid :cols="signalCols" :x-gap="12" :y-gap="12">
          <NGi>
            <MetricCard title="混合訊號">
              <template #default>
                <SignalBadge :signal="tech.adaptiveSignal.adaptive?.final_signal || 'HOLD'" size="large" />
              </template>
            </MetricCard>
          </NGi>
          <NGi>
            <MetricCard
              title="V4 趨勢"
              :subtitle="`權重 ${((tech.adaptiveSignal.adaptive?.v4_weight || 0) * 100).toFixed(0)}%`"
            >
              <template #default>
                <SignalBadge :signal="tech.adaptiveSignal.v4?.signal || 'HOLD'" />
              </template>
            </MetricCard>
          </NGi>
          <NGi>
            <MetricCard
              title="V5 回歸"
              :subtitle="`權重 ${((tech.adaptiveSignal.adaptive?.v5_weight || 0) * 100).toFixed(0)}%`"
            >
              <template #default>
                <SignalBadge :signal="tech.adaptiveSignal.v5?.signal || 'HOLD'" />
              </template>
            </MetricCard>
          </NGi>
          <NGi>
            <MetricCard
              title="綜合分數"
              :value="tech.adaptiveSignal.adaptive?.composite_score?.toFixed(3) || '0'"
              :color="(tech.adaptiveSignal.adaptive?.composite_score || 0) >= 0.5 ? '#e53e3e' :
                      (tech.adaptiveSignal.adaptive?.composite_score || 0) <= -0.5 ? '#38a169' : undefined"
            />
          </NGi>
        </NGrid>
      </NCard>

      <!-- Bold Status Panel (R63: RS + MLS + ECF) -->
      <BoldStatusPanel v-if="tech.boldStatus" :data="tech.boldStatus" :sector-context="tech.sectorContext" :vcp-context="tech.vcpContext" />

      <!-- R90: Winner DNA Pattern Recognition -->
      <WinnerDnaCard v-if="tech.winnerDna" :data="tech.winnerDna" />

      <!-- 流動性風險評分 (R69) -->
      <NCard v-if="tech.liquidity" size="small" style="margin-bottom: 16px">
        <template #header>
          <NSpace align="center" :size="8">
            <span style="font-weight: 700">流動性風險</span>
            <NTag
              size="small" :bordered="false"
              :type="tech.liquidity.grade === 'green' ? 'success' : tech.liquidity.grade === 'yellow' ? 'warning' : 'error'"
            >
              {{ tech.liquidity.score }} 分 —
              {{ tech.liquidity.grade === 'green' ? '良好' : tech.liquidity.grade === 'yellow' ? '注意' : '危險' }}
            </NTag>
          </NSpace>
        </template>
        <NGrid :cols="signalCols" :x-gap="12" :y-gap="12">
          <NGi>
            <MetricCard
              title="出清天數"
              :value="tech.liquidity.dtl === Infinity ? '∞' : tech.liquidity.dtl?.toFixed(1) + '天'"
              :color="tech.liquidity.dtl > 2 ? '#e53e3e' : tech.liquidity.dtl > 1 ? '#f0a020' : '#38a169'"
            />
          </NGi>
          <NGi>
            <MetricCard
              title="日均量"
              :value="tech.liquidity.adv_20_lots?.toFixed(0) + ' 張'"
            />
          </NGi>
          <NGi>
            <MetricCard
              title="市場衝擊"
              :value="tech.liquidity.market_impact_pct?.toFixed(2) + '%'"
              :color="tech.liquidity.market_impact_pct > 1 ? '#e53e3e' : undefined"
              subtitle="預估滑價"
            />
          </NGi>
          <NGi>
            <MetricCard
              title="Tick 比"
              :value="tech.liquidity.tick_ratio_pct?.toFixed(2) + '%'"
              :subtitle="'跳動 ' + tech.liquidity.tick_size"
            />
          </NGi>
        </NGrid>
        <NText depth="3" style="font-size: 11px; margin-top: 8px; display: block">
          {{ tech.liquidity.details }}
          | 假設持倉 100 萬台幣（{{ tech.liquidity.position_shares?.toFixed(0) }} 股）
        </NText>
      </NCard>

      <!-- SQS 信號品質分數 (Gemini R43) -->
      <NCard v-if="tech.sqsData" size="small" style="margin-bottom: 16px">
        <template #header>
          <NSpace align="center" :size="8">
            <span style="font-weight: 700">SQS 信號品質</span>
            <NTag
              size="small"
              :type="tech.sqsData.grade === 'diamond' ? 'success' : tech.sqsData.grade === 'gold' ? 'warning' : tech.sqsData.grade === 'noise' ? 'default' : 'info'"
            >
              {{ sqsGradeIcon(tech.sqsData.grade) }} {{ tech.sqsData.sqs }} — {{ tech.sqsData.grade_label }}
            </NTag>
            <NTag v-if="tech.sqsData.cost_trap" size="small" :color="{ textColor: '#fff', color: '#f0a020', borderColor: '#f0a020' }">
              成本陷阱
            </NTag>
          </NSpace>
        </template>
        <NGrid :cols="isMobile ? 1 : 2" :x-gap="12" :y-gap="12">
          <NGi>
            <VChart v-if="sqsRadarOption" :option="sqsRadarOption" style="height: 220px" autoresize />
          </NGi>
          <NGi>
            <div style="padding: 8px 0; font-size: 13px">
              <div v-for="(score, dim) in tech.sqsData.breakdown" :key="dim" style="display: flex; justify-content: space-between; padding: 4px 0; border-bottom: 1px solid #f0f0f0">
                <span>{{ dim === 'fitness' ? '性格匹配' : dim === 'regime' ? '市場環境' : dim === 'net_ev' ? '期望值' : dim === 'heat' ? '板塊熱度' : dim === 'institutional' ? '法人動向' : '成熟度' }}</span>
                <span :style="{ fontWeight: 600, color: score >= 70 ? '#18a058' : score >= 40 ? '#333' : '#e53e3e' }">{{ score }}</span>
              </div>
              <div v-if="tech.sqsData.net_ev != null" style="margin-top: 8px; display: flex; justify-content: space-between">
                <span>Net EV (20d)</span>
                <span :style="{ fontWeight: 700, color: tech.sqsData.net_ev >= 0 ? '#18a058' : '#e53e3e' }">
                  {{ (tech.sqsData.net_ev * 100).toFixed(2) }}%
                </span>
              </div>
              <div v-if="tech.sqsData.fitness_tag" style="margin-top: 4px; color: #888; font-size: 11px">
                Fitness Tag: {{ tech.sqsData.fitness_tag }}
              </div>
            </div>
          </NGi>
        </NGrid>
      </NCard>

      <!-- 多策略風險預算 (Gemini R37) -->
      <NCard v-if="tech.riskBudget && tech.riskBudget.divergence" size="small" style="margin-bottom: 16px">
        <template #header>
          <NSpace align="center" :size="8">
            <span style="font-weight: 700">訊號衝突警告</span>
            <NTag size="small" type="error" :bordered="false">Divergence</NTag>
          </NSpace>
        </template>
        <NGrid :cols="signalCols" :x-gap="12" :y-gap="12">
          <NGi>
            <MetricCard title="建議動作">
              <template #default>
                <SignalBadge :signal="tech.riskBudget.action" size="large" />
              </template>
            </MetricCard>
          </NGi>
          <NGi>
            <MetricCard
              title="V4 訊號"
              :subtitle="tech.riskBudget.v4_signal"
              :color="tech.riskBudget.v4_signal === 'BUY' ? '#e53e3e' : tech.riskBudget.v4_signal === 'SELL' ? '#38a169' : undefined"
            />
          </NGi>
          <NGi>
            <MetricCard
              title="V5 訊號"
              :subtitle="tech.riskBudget.v5_signal"
              :color="tech.riskBudget.v5_signal === 'BUY' ? '#e53e3e' : tech.riskBudget.v5_signal === 'SELL' ? '#38a169' : undefined"
            />
          </NGi>
          <NGi>
            <MetricCard
              title="信心衰減"
              :value="tech.riskBudget.confidence_decay?.toFixed(2) || '1.0'"
              :color="(tech.riskBudget.confidence_decay || 1) < 0.5 ? '#e53e3e' : undefined"
            />
          </NGi>
        </NGrid>
        <div v-if="tech.riskBudget.reason" style="margin-top: 8px; font-size: 13px; color: var(--text-dimmed)">
          {{ tech.riskBudget.reason }}
        </div>
        <div v-for="w in tech.riskBudget.warnings" :key="w" style="margin-top: 4px; font-size: 12px; color: #e53e3e">
          {{ w }}
        </div>
      </NCard>

      <!-- V4 指標面板 -->
      <NCard v-if="tech.v4Enhanced?.indicators" size="small" title="V4 指標" style="margin-bottom: 16px">
        <NGrid :cols="indicatorCols" :x-gap="8" :y-gap="8">
          <NGi v-for="(val, key) in tech.v4Enhanced.indicators" :key="key">
            <MetricCard :title="String(key)" :value="val != null ? Number(val).toFixed(1) : '-'" />
          </NGi>
        </NGrid>
      </NCard>

      <!-- R81: 風險倉位顧問 (Macro: sizing → above Micro: position) -->
      <SizingAdvisor
        v-if="tech.v4Enhanced"
        :code="app.currentStockCode"
        :current-price="tech.v4Enhanced.close || 0"
      />

      <!-- 下單計算機 -->
      <PositionCalculator
        v-if="tech.v4Enhanced"
        :code="app.currentStockCode"
        :current-price="tech.v4Enhanced.close || 0"
        @risk-loaded="onRiskLoaded"
      />

      <!-- K 線圖 -->
      <NCard title="K線圖" size="small" style="margin-bottom: 16px">
        <CandlestickChart
          :data="tech.indicators"
          :supports="[...(tech.supportResistance?.supports || []), ...exitLines]"
          :resistances="tech.supportResistance?.resistances"
          :signals="tech.v4SignalsFull"
          group="tech"
        />
      </NCard>

      <!-- MACD + KD -->
      <NGrid :cols="chartCols" :x-gap="12" :y-gap="12" style="margin-bottom: 16px">
        <NGi>
          <NCard title="MACD" size="small">
            <MacdChart :data="tech.indicators" group="tech" />
          </NCard>
        </NGi>
        <NGi>
          <NCard title="KD" size="small">
            <KdChart :data="tech.indicators" group="tech" />
          </NCard>
        </NGi>
      </NGrid>

      <!-- RSI + BIAS (Gemini R39: Dynamic RSI threshold + 乖離率) -->
      <NGrid :cols="chartCols" :x-gap="12" :y-gap="12" style="margin-bottom: 16px">
        <NGi>
          <NCard title="RSI (含動態門檻)" size="small">
            <RsiChart :data="tech.indicators" group="tech" />
          </NCard>
        </NGi>
        <NGi>
          <NCard title="乖離率 BIAS" size="small">
            <BiasChart :data="tech.indicators" group="tech" />
          </NCard>
        </NGi>
      </NGrid>

      <!-- 支撐壓力 -->
      <NCard v-if="tech.supportResistance" title="支撐壓力" size="small" style="margin-bottom: 16px">
        <NGrid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="8">
          <NGi>
            <NText strong style="color: #38a169">支撐位</NText>
            <div v-for="s in tech.supportResistance.supports?.slice(0, 5)" :key="s.price" style="margin: 4px 0">
              {{ s.price?.toFixed(2) }} ({{ s.source }})
            </div>
          </NGi>
          <NGi>
            <NText strong style="color: #e53e3e">壓力位</NText>
            <div v-for="r in tech.supportResistance.resistances?.slice(0, 5)" :key="r.price" style="margin: 4px 0">
              {{ r.price?.toFixed(2) }} ({{ r.source }})
            </div>
          </NGi>
        </NGrid>
      </NCard>

      <!-- 量能型態 -->
      <NCard v-if="tech.volumePatterns" title="量能型態" size="small" style="margin-bottom: 16px">
        <NDescriptions :column="descCols" label-placement="left" size="small">
          <NDescriptionsItem label="當前型態">{{ tech.volumePatterns.current_pattern || '無' }}</NDescriptionsItem>
          <NDescriptionsItem label="量比">{{ tech.volumePatterns.current_vol_ratio?.toFixed(2) || '-' }}</NDescriptionsItem>
          <NDescriptionsItem label="量能趨勢">{{ tech.volumePatterns.volume_trend || '-' }}</NDescriptionsItem>
          <NDescriptionsItem label="近20日爆量">{{ tech.volumePatterns.recent_breakouts || 0 }} 次</NDescriptionsItem>
          <NDescriptionsItem label="近20日縮量">{{ tech.volumePatterns.recent_pullbacks || 0 }} 次</NDescriptionsItem>
          <NDescriptionsItem label="活躍序列">{{ tech.volumePatterns.has_active_sequence ? '是' : '否' }}</NDescriptionsItem>
          <NDescriptionsItem v-if="tech.volumePatterns.signal_maturity" label="訊號成熟度">
            <NTag :type="tech.volumePatterns.signal_confidence === 'high' ? 'success' : tech.volumePatterns.signal_confidence === 'medium' ? 'info' : 'warning'" size="small">
              {{ tech.volumePatterns.signal_maturity_label }}
            </NTag>
            <span style="margin-left: 8px; font-size: 12px; color: var(--text-dimmed)">
              (爆量後 {{ tech.volumePatterns.days_since_breakout }} 日)
            </span>
          </NDescriptionsItem>
        </NDescriptions>
      </NCard>

      <!-- 快速回測 -->
      <NCard title="快速回測 (2年)" size="small" style="margin-bottom: 16px">
        <template #header-extra>
          <NButton size="tiny" type="primary" @click="runQuickBacktest" :loading="quickBtLoading">
            {{ quickBtResult ? '重新回測' : '執行回測' }}
          </NButton>
        </template>
        <NGrid v-if="quickBtResult" :cols="quickBtCols" :x-gap="8" :y-gap="8">
          <NGi><MetricCard title="總報酬" :value="fmtPct(quickBtResult.total_return)" :color="priceColor(quickBtResult.total_return)" /></NGi>
          <NGi><MetricCard title="年化報酬" :value="fmtPct(quickBtResult.annual_return)" :color="priceColor(quickBtResult.annual_return)" /></NGi>
          <NGi><MetricCard title="最大回撤" :value="fmtPct(quickBtResult.max_drawdown)" color="#e53e3e" /></NGi>
          <NGi><MetricCard title="Sharpe" :value="quickBtResult.sharpe_ratio?.toFixed(2) || '-'" /></NGi>
          <NGi><MetricCard title="勝率" :value="fmtPct(quickBtResult.win_rate)" /></NGi>
          <NGi><MetricCard title="交易數" :value="quickBtResult.total_trades" /></NGi>
        </NGrid>
        <NText v-else depth="3" style="font-size: 12px">點擊「執行回測」查看 V4 策略在此股票的回測表現</NText>
      </NCard>

      <!-- 前瞻測試績效 (Gemini R41: Signal Performance Overlay) -->
      <NCard v-if="tech.signalSummary?.has_data" title="前瞻測試績效" size="small" style="margin-bottom: 16px">
        <template #header-extra>
          <NTag size="small" :bordered="false" type="info">Forward Testing</NTag>
        </template>
        <NGrid :cols="descCols" :x-gap="12" :y-gap="12">
          <NGi v-for="(info, strat) in tech.signalSummary.strategies" :key="strat">
            <NCard size="small" :bordered="true">
              <template #header>
                <NSpace align="center" :size="4">
                  <NTag :type="strat === 'V4' ? 'error' : strat === 'V5' ? 'info' : 'success'" size="small">{{ strat }}</NTag>
                  <span style="font-size: 12px; color: var(--text-dimmed)">{{ info.sample_count }} 筆</span>
                </NSpace>
              </template>
              <div style="font-size: 13px; line-height: 1.8">
                <div>5日勝率: <b :style="{ color: (info.win_rate_5d || 0) >= 0.5 ? '#18a058' : '#e53e3e' }">{{ info.win_rate_5d != null ? (info.win_rate_5d * 100).toFixed(1) + '%' : '-' }}</b></div>
                <div>5日均報酬: {{ info.avg_return_5d != null ? fmtPct(info.avg_return_5d) : '-' }}</div>
                <div>20日均報酬: {{ info.avg_return_20d != null ? fmtPct(info.avg_return_20d) : '-' }}</div>
                <div v-if="info.ev_5d != null">
                  EV(5d): <span :style="{ color: info.ev_5d > 0 ? '#18a058' : '#e53e3e', fontWeight: 600 }">{{ (info.ev_5d * 100).toFixed(2) }}%</span>
                </div>
                <div v-if="info.ev_20d != null">
                  EV(20d): <span :style="{ color: info.ev_20d > 0 ? '#18a058' : '#e53e3e', fontWeight: 600 }">{{ (info.ev_20d * 100).toFixed(2) }}%</span>
                </div>
              </div>
              <!-- Recent signals -->
              <div v-if="info.recent_signals?.length" style="margin-top: 8px; border-top: 1px solid var(--border-color); padding-top: 6px">
                <div style="font-size: 11px; color: var(--text-dimmed); margin-bottom: 4px">近期信號</div>
                <div v-for="sig in info.recent_signals" :key="sig.date" style="font-size: 12px; display: flex; gap: 8px">
                  <span>{{ sig.date }}</span>
                  <span v-if="sig.d5_return != null" :style="{ color: sig.d5_return > 0 ? '#18a058' : '#e53e3e' }">5d {{ fmtPct(sig.d5_return) }}</span>
                  <span v-if="sig.d20_return != null" :style="{ color: sig.d20_return > 0 ? '#18a058' : '#e53e3e' }">20d {{ fmtPct(sig.d20_return) }}</span>
                </div>
              </div>
            </NCard>
          </NGi>
        </NGrid>
      </NCard>

      <!-- 法人籌碼 -->
      <NCard v-if="institutionalData.length" title="三大法人買賣超" size="small" style="margin-bottom: 16px">
        <NDataTable
          :columns="institutionalColumns"
          :data="institutionalData"
          :pagination="{ pageSize: 10 }"
          size="small"
          :scroll-x="470"
        />
      </NCard>

      <!-- 基本面數據 (R51-3) -->
      <NCard v-if="tech.fundamentals" title="基本面數據" size="small" style="margin-bottom: 16px">
        <NGrid :cols="fundamentalCols" :x-gap="12" :y-gap="8">
          <NGi v-if="tech.fundamentals.trailing_pe != null">
            <NStatistic label="本益比 (TTM)" :value="tech.fundamentals.trailing_pe?.toFixed(1)" />
          </NGi>
          <NGi v-if="tech.fundamentals.forward_pe != null">
            <NStatistic label="預估本益比" :value="tech.fundamentals.forward_pe?.toFixed(1)" />
          </NGi>
          <NGi v-if="tech.fundamentals.price_to_book != null">
            <NStatistic label="股價淨值比" :value="tech.fundamentals.price_to_book?.toFixed(2)" />
          </NGi>
          <NGi v-if="tech.fundamentals.trailing_eps != null">
            <NStatistic label="EPS (TTM)" :value="tech.fundamentals.trailing_eps?.toFixed(2)" />
          </NGi>
          <NGi v-if="tech.fundamentals.return_on_equity != null">
            <NStatistic label="ROE">
              <template #default>
                <span :style="{ color: (tech.fundamentals.return_on_equity || 0) >= 0.15 ? '#18a058' : undefined }">
                  {{ (tech.fundamentals.return_on_equity * 100).toFixed(1) }}%
                </span>
              </template>
            </NStatistic>
          </NGi>
          <NGi v-if="tech.fundamentals.revenue_growth != null">
            <NStatistic label="營收成長">
              <template #default>
                <span :style="{ color: (tech.fundamentals.revenue_growth || 0) > 0 ? '#18a058' : '#e53e3e' }">
                  {{ (tech.fundamentals.revenue_growth * 100).toFixed(1) }}%
                </span>
              </template>
            </NStatistic>
          </NGi>
          <NGi v-if="tech.fundamentals.profit_margins != null">
            <NStatistic label="淨利率" :value="`${(tech.fundamentals.profit_margins * 100).toFixed(1)}%`" />
          </NGi>
          <NGi v-if="tech.fundamentals.debt_to_equity != null">
            <NStatistic label="負債權益比">
              <template #default>
                <span :style="{ color: (tech.fundamentals.debt_to_equity || 0) > 100 ? '#e53e3e' : undefined }">
                  {{ tech.fundamentals.debt_to_equity?.toFixed(1) }}
                </span>
              </template>
            </NStatistic>
          </NGi>
          <NGi v-if="tech.fundamentals.dividend_yield != null">
            <NStatistic label="殖利率" :value="`${(tech.fundamentals.dividend_yield * 100).toFixed(2)}%`" />
          </NGi>
          <NGi v-if="tech.fundamentals.market_cap != null">
            <NStatistic label="市值">
              <template #default>
                {{ tech.fundamentals.market_cap >= 1e12
                  ? (tech.fundamentals.market_cap / 1e12).toFixed(1) + ' 兆'
                  : tech.fundamentals.market_cap >= 1e8
                    ? (tech.fundamentals.market_cap / 1e8).toFixed(0) + ' 億'
                    : fmtNum(tech.fundamentals.market_cap)
                }}
              </template>
            </NStatistic>
          </NGi>
          <NGi v-if="tech.fundamentals.beta != null">
            <NStatistic label="Beta" :value="tech.fundamentals.beta?.toFixed(2)" />
          </NGi>
          <NGi v-if="tech.fundamentals.current_ratio != null">
            <NStatistic label="流動比率" :value="tech.fundamentals.current_ratio?.toFixed(2)" />
          </NGi>
        </NGrid>
        <div v-if="tech.fundamentals.analyst_rating" style="margin-top: 8px; font-size: 12px; color: #999">
          法人評等: {{ tech.fundamentals.analyst_rating }}
          <span v-if="tech.fundamentals.target_mean_price">
            | 目標均價: {{ tech.fundamentals.target_mean_price?.toFixed(0) }}
          </span>
          <span v-if="tech.fundamentals.number_of_analysts">
            ({{ tech.fundamentals.number_of_analysts }} 位分析師)
          </span>
        </div>
      </NCard>
    </NSpin>
  </div>
</template>
