<script setup lang="ts">
import { h, ref, watch, onMounted, nextTick, computed } from 'vue'
import { connect } from 'echarts/core'
import { NGrid, NGi, NCard, NSpin, NAlert, NDescriptions, NDescriptionsItem, NText, NDataTable, NButton } from 'naive-ui'
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
import PositionCalculator from '../components/PositionCalculator.vue'

const app = useAppStore()
const tech = useTechnicalStore()
const { cols } = useResponsive()
const signalCols = cols(2, 4, 4)
const indicatorCols = cols(3, 5, 5)
const chartCols = cols(1, 2, 2)
const descCols = cols(1, 3, 3)

async function loadData() {
  const code = app.currentStockCode
  await tech.loadAll(code)
  await tech.loadV4SignalsFull(code)
  tech.loadAdaptiveSignal(code)  // Non-blocking: load adaptive signal in background
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
  return lines
})

// Quick backtest
const quickBtResult = ref<any>(null)
const quickBtLoading = ref(false)
const quickBtCols = cols(2, 4, 6)

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
</script>

<template>
  <div>
    <h2 style="margin: 0 0 16px">
      {{ app.currentStockCode }} {{ app.currentStockName }} - 技術分析
    </h2>

    <NSpin :show="tech.isLoading">
      <NAlert v-if="tech.error" type="error" style="margin-bottom: 16px">{{ tech.error }}</NAlert>

      <!-- V4 訊號摘要 -->
      <NGrid v-if="tech.v4Enhanced" :cols="signalCols" :x-gap="12" :y-gap="12" style="margin-bottom: 16px">
        <NGi>
          <MetricCard
            title="V4 訊號"
            :bg-color="tech.v4Enhanced.signal === 'BUY' ? '#fff5f5' : tech.v4Enhanced.signal === 'SELL' ? '#f0fff4' : undefined"
          >
            <template #default>
              <SignalBadge :signal="tech.v4Enhanced.signal" size="large" />
            </template>
          </MetricCard>
        </NGi>
        <NGi>
          <MetricCard
            title="收盤價"
            :value="tech.v4Enhanced.close?.toFixed(2) || '-'"
          />
        </NGi>
        <NGi>
          <MetricCard
            title="上升趨勢天數"
            :value="tech.v4Enhanced.uptrend_days || 0"
            :subtitle="tech.v4Enhanced.entry_type || '-'"
          />
        </NGi>
        <NGi>
          <MetricCard
            title="信心分數"
            :value="tech.v4Enhanced.confidence_score?.toFixed(1) || '1.0'"
            :color="(tech.v4Enhanced.confidence_score || 1) >= 1.5 ? '#e53e3e' : undefined"
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

      <!-- V4 指標面板 -->
      <NCard v-if="tech.v4Enhanced?.indicators" size="small" title="V4 指標" style="margin-bottom: 16px">
        <NGrid :cols="indicatorCols" :x-gap="8" :y-gap="8">
          <NGi v-for="(val, key) in tech.v4Enhanced.indicators" :key="key">
            <MetricCard :title="String(key)" :value="val != null ? Number(val).toFixed(1) : '-'" />
          </NGi>
        </NGrid>
      </NCard>

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

      <!-- 支撐壓力 -->
      <NCard v-if="tech.supportResistance" title="支撐壓力" size="small" style="margin-bottom: 16px">
        <NGrid :cols="2" :x-gap="16">
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
    </NSpin>
  </div>
</template>
