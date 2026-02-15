<script setup lang="ts">
import { computed } from 'vue'
import { NButton, NCard, NGrid, NGi, NTag, NDataTable, NAlert, NSpace } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { useAppStore } from '../stores/app'
import { useBacktestStore } from '../stores/backtest'
import { useResponsive } from '../composables/useResponsive'
import { fmtPct } from '../utils/format'
import MetricCard from './MetricCard.vue'

const props = defineProps<{ periodDays: number; capital: number }>()

const app = useAppStore()
const bt = useBacktestStore()
const { cols } = useResponsive()
const metricCols = cols(2, 4, 4)

async function run() {
  await bt.runStrategyComparison(app.currentStockCode, {
    period_days: props.periodDays,
    initial_capital: props.capital,
  })
}

const data = computed(() => bt.strategyComparison)

const comparisonRows = computed(() => {
  if (!data.value) return []
  const v4 = data.value.v4_summary
  const v5 = data.value.v5_summary
  const ad = data.value.adaptive_summary
  const bd = data.value.bold_summary
  if (!v4 || !v5 || !ad) return []

  const metrics = [
    { label: '總報酬', key: 'total_return', fmt: fmtPct },
    { label: '年化報酬', key: 'annual_return', fmt: fmtPct },
    { label: '最大回撤', key: 'max_drawdown', fmt: fmtPct },
    { label: 'Sharpe', key: 'sharpe_ratio', fmt: (v: number) => v?.toFixed(2) || '-' },
    { label: 'Sortino', key: 'sortino_ratio', fmt: (v: number) => v?.toFixed(2) || '-' },
    { label: 'Calmar', key: 'calmar_ratio', fmt: (v: number) => v?.toFixed(2) || '-' },
    { label: '勝率', key: 'win_rate', fmt: fmtPct },
    { label: '盈虧比', key: 'profit_factor', fmt: (v: number) => v?.toFixed(2) || '-' },
    { label: '交易數', key: 'total_trades', fmt: (v: number) => String(v || 0) },
    { label: '平均持有天數', key: 'avg_holding_days', fmt: (v: number) => v?.toFixed(1) || '-' },
  ]

  return metrics.map(m => ({
    metric: m.label,
    v4: m.fmt(v4[m.key]),
    v5: m.fmt(v5[m.key]),
    adaptive: m.fmt(ad[m.key]),
    bold: bd ? m.fmt(bd[m.key]) : '-',
  }))
})

// Find best strategy for each metric
const bestStrategy = computed(() => {
  if (!data.value) return null
  const v4 = data.value.v4_summary
  const v5 = data.value.v5_summary
  const ad = data.value.adaptive_summary
  const bd = data.value.bold_summary
  if (!v4 || !v5 || !ad) return null

  const strategies = [
    { name: 'V4', data: v4 },
    { name: 'V5', data: v5 },
    { name: 'Adaptive', data: ad },
    ...(bd ? [{ name: 'Bold', data: bd }] : []),
  ]

  // Best by Sharpe
  const bySharpe = strategies.reduce((best, s) =>
    (s.data.sharpe_ratio || 0) > (best.data.sharpe_ratio || 0) ? s : best
  )
  // Best by total return
  const byReturn = strategies.reduce((best, s) =>
    (s.data.total_return || 0) > (best.data.total_return || 0) ? s : best
  )
  // Best by drawdown (least negative)
  const byDrawdown = strategies.reduce((best, s) =>
    (s.data.max_drawdown || -999) > (best.data.max_drawdown || -999) ? s : best
  )

  return { bySharpe: bySharpe.name, byReturn: byReturn.name, byDrawdown: byDrawdown.name }
})

const tableColumns: DataTableColumns = [
  { title: '指標', key: 'metric', width: 120 },
  { title: 'V4 趨勢', key: 'v4', width: 100 },
  { title: 'V5 均值回歸', key: 'v5', width: 100 },
  { title: 'Adaptive 混合', key: 'adaptive', width: 100 },
  { title: 'Bold 大膽', key: 'bold', width: 100 },
]
</script>

<template>
  <div>
    <NCard title="V4 vs V5 vs Adaptive vs Bold 策略比較" size="small" style="margin-bottom: 16px">
      <template #header-extra>
        <NSpace align="center" :size="8">
          <NTag v-if="data?.regime" size="small" :type="data.regime?.includes('trend') ? 'success' : 'warning'">
            {{ data.regime === 'trend_explosive' ? '趨勢噴發' :
               data.regime === 'trend_mild' ? '溫和趨勢' :
               data.regime === 'range_volatile' ? '震盪劇烈' : '低波盤整' }}
          </NTag>
          <NButton size="small" type="primary" @click="run" :loading="bt.isLoading">
            {{ data ? '重新比較' : '執行策略比較' }}
          </NButton>
        </NSpace>
      </template>

      <template v-if="data">
        <!-- Best Strategy Summary -->
        <NAlert v-if="bestStrategy" type="info" style="margin-bottom: 12px">
          最佳 Sharpe: <b>{{ bestStrategy.bySharpe }}</b> /
          最高報酬: <b>{{ bestStrategy.byReturn }}</b> /
          最小回撤: <b>{{ bestStrategy.byDrawdown }}</b>
        </NAlert>

        <!-- Delta Summary -->
        <NAlert v-if="data.comparison" :type="data.comparison.sharpe_delta > 0 ? 'success' : 'warning'" style="margin-bottom: 12px">
          Adaptive vs V4: Sharpe {{ data.comparison.sharpe_delta > 0 ? '+' : '' }}{{ data.comparison.sharpe_delta?.toFixed(3) }}
          / 報酬 {{ data.comparison.return_delta > 0 ? '+' : '' }}{{ fmtPct(data.comparison.return_delta) }}
          / Recovery Factor V4={{ data.comparison.recovery_v4 }} Bold={{ data.comparison.recovery_bold || '-' }}
        </NAlert>

        <!-- Side-by-side key metrics -->
        <NGrid :cols="metricCols" :x-gap="12" :y-gap="12" style="margin-bottom: 16px">
          <NGi>
            <MetricCard title="V4 Sharpe" :value="data.v4_summary?.sharpe_ratio?.toFixed(2) || '-'" subtitle="趨勢追蹤" />
          </NGi>
          <NGi>
            <MetricCard title="V5 Sharpe" :value="data.v5_summary?.sharpe_ratio?.toFixed(2) || '-'" subtitle="均值回歸" />
          </NGi>
          <NGi>
            <MetricCard title="Adaptive Sharpe" :value="data.adaptive_summary?.sharpe_ratio?.toFixed(2) || '-'" subtitle="混合策略" />
          </NGi>
          <NGi>
            <MetricCard
              title="Bold Sharpe"
              :value="data.bold_summary?.sharpe_ratio?.toFixed(2) || '-'"
              subtitle="爆發波段"
              :color="(data.bold_summary?.sharpe_ratio || 0) > (data.v4_summary?.sharpe_ratio || 0) ? '#38a169' : undefined"
            />
          </NGi>
        </NGrid>

        <!-- Full comparison table -->
        <NDataTable
          :columns="tableColumns"
          :data="comparisonRows"
          :pagination="false"
          size="small"
          :bordered="true"
        />
      </template>

      <div v-else style="padding: 24px; text-align: center; color: var(--text-dimmed)">
        點擊「執行策略比較」同時回測 V4 / V5 / Adaptive / Bold 四種策略，找出最適合此股票的策略
      </div>
    </NCard>
  </div>
</template>
