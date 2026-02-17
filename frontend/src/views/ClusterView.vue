<script setup lang="ts">
import { h, computed, onMounted } from 'vue'
import {
  NGrid, NGi, NCard, NAlert, NButton, NCheckboxGroup, NCheckbox,
  NInputNumber, NStatistic, NDataTable, NSpace, NTag, NSwitch, NText,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import VChart from 'vue-echarts'
import { useAppStore } from '../stores/app'
import { useClusterStore } from '../stores/cluster'
import { useResponsive } from '../composables/useResponsive'
import { useChartTheme } from '../composables/useChartTheme'
import { fmtPct, priceColor } from '../utils/format'

const app = useAppStore()
const store = useClusterStore()
const { isMobile, cols } = useResponsive()
const { colors, tooltipStyle, baseOption } = useChartTheme()

const responsiveCols = cols(1, 2, 3)

// --- Dimension labels [CONVERGED: news → attention] ---
const dimensionLabels: Record<string, string> = {
  technical: '技術面',
  institutional: '籌碼面',
  industry: '產業面',
  fundamental: '基本面',
  attention: '關注度',
}

// --- Regime labels ---
const regimeLabels: Record<number, string> = {
  1: '多頭',
  0: '盤整',
  [-1]: '空頭',
}

// --- Init ---
onMounted(async () => {
  await store.loadDimensions()
  await store.loadFeatureStatus()
})

// --- Query ---
async function doSearch() {
  await store.loadSimilar(app.currentStockCode)
}

// --- Win rate horizons ---
const horizons = ['d3', 'd7', 'd21', 'd90', 'd180'] as const
const horizonLabels: Record<string, string> = {
  d3: 'D3 (3日)',
  d7: 'D7 (7日)',
  d21: 'D21 (21日)',
  d90: 'D90 (90日)',
  d180: 'D180 (180日)',
}

// --- Table columns ---
const tableColumns = computed<DataTableColumns<any>>(() => [
  { title: '股票', key: 'stock_code', width: 70, fixed: 'left' as const },
  { title: '日期', key: 'date', width: 110 },
  {
    title: '相似度',
    key: 'similarity',
    width: 90,
    sorter: (a: any, b: any) => a.similarity - b.similarity,
    render: (row: any) => `${(row.similarity * 100).toFixed(1)}%`,
  },
  ...horizons.map((hz) => ({
    title: hz.toUpperCase(),
    key: hz,
    width: 80,
    sorter: (a: any, b: any) => (a.forward_returns?.[hz] ?? 0) - (b.forward_returns?.[hz] ?? 0),
    render: (row: any) => {
      const v = row.forward_returns?.[hz]
      if (v == null) return '-'
      const pct = (v * 100).toFixed(2) + '%'
      const color = priceColor(v)
      return color ? h('span', { style: { color } }, pct) : pct
    },
  })),
])

// --- Table data ---
const tableData = computed(() => store.result?.similar_cases ?? [])

// --- Box plot chart ---
const boxPlotOption = computed(() => {
  if (!store.result) return null
  const stats = store.result.statistics

  const categories = horizons.map((hz) => horizonLabels[hz])
  const boxData: number[][] = []
  const scatterData: [number, number][] = []

  horizons.forEach((hz, i) => {
    const s = stats[hz]
    if (s.mean != null && s.std != null && s.min != null && s.max != null && s.median != null) {
      const p5 = s.p5 ?? s.min
      const p95 = s.p95 ?? s.max
      boxData.push([p5, Math.max(p5, s.mean - s.std), s.median, Math.min(p95, s.mean + s.std), p95])
    } else {
      boxData.push([0, 0, 0, 0, 0])
    }

    for (const c of store.result!.similar_cases) {
      const v = c.forward_returns[hz]
      if (v != null) {
        scatterData.push([i, v])
      }
    }
  })

  return {
    ...baseOption.value,
    tooltip: {
      ...tooltipStyle.value,
      trigger: 'item',
      formatter: (p: any) => {
        if (p.seriesType === 'scatter') {
          return `${categories[p.data[0]]}: ${(p.data[1] * 100).toFixed(2)}%`
        }
        return ''
      },
    },
    grid: { left: 60, right: 20, top: 20, bottom: 40 },
    xAxis: {
      type: 'category',
      data: categories,
      axisLabel: { color: colors.value.axisLabel },
    },
    yAxis: {
      type: 'value',
      axisLabel: {
        color: colors.value.axisLabel,
        formatter: (v: number) => (v * 100).toFixed(0) + '%',
      },
      splitLine: { lineStyle: { color: colors.value.splitLine } },
    },
    series: [
      {
        type: 'boxplot',
        data: boxData,
        itemStyle: { color: '#5470c6', borderColor: '#5470c6' },
      },
      {
        type: 'scatter',
        data: scatterData,
        symbolSize: 5,
        itemStyle: { color: '#91cc75', opacity: 0.6 },
      },
    ],
  }
})

// --- Feature status ---
const dataReady = computed(() => store.featureStatus?.features_exists === true)
</script>

<template>
  <NGrid :cols="1" x-gap="12" y-gap="8">
    <!-- Feature status warning -->
    <NGi v-if="!dataReady && store.featureStatus">
      <NAlert type="warning" title="特徵資料尚未建立">
        請先執行 <code>python data/build_features.py</code>
        產生 Parquet 檔案，放到 <code>data/pattern_data/features/</code> 目錄。
      </NAlert>
    </NGi>

    <!-- Controls -->
    <NGi>
      <NCard title="多維度相似股分群" size="small">
        <template #header-extra>
          <NText depth="3" style="font-size: 11px">僅供參考，非投資建議</NText>
        </template>
        <NGrid :cols="responsiveCols.value" x-gap="12" y-gap="8">
          <!-- Dimension selector -->
          <NGi>
            <div style="margin-bottom: 8px; font-weight: 600">維度選擇</div>
            <NCheckboxGroup v-model:value="store.selectedDimensions">
              <NSpace vertical size="small">
                <NCheckbox
                  v-for="dim in store.dimensions"
                  :key="dim.name"
                  :value="dim.name"
                  :label="`${dimensionLabels[dim.name] || dim.name} (${dim.feature_count})`"
                />
              </NSpace>
            </NCheckboxGroup>
          </NGi>

          <!-- Parameters -->
          <NGi>
            <NSpace vertical size="small">
              <div>
                <span style="font-size: 13px; color: var(--n-text-color-3)">Window (天數)</span>
                <NInputNumber v-model:value="store.window" :min="5" :max="120" size="small" style="width: 120px" />
              </div>
              <div>
                <span style="font-size: 13px; color: var(--n-text-color-3)">Top-K (筆數)</span>
                <NInputNumber v-model:value="store.topK" :min="5" :max="100" size="small" style="width: 120px" />
              </div>
              <NSpace align="center" :size="8">
                <span style="font-size: 13px; color: var(--n-text-color-3)">排除自身</span>
                <NSwitch v-model:value="store.excludeSelf" size="small" />
              </NSpace>
              <NSpace align="center" :size="8">
                <span style="font-size: 13px; color: var(--n-text-color-3)">同環境限定</span>
                <NSwitch v-model:value="store.regimeMatch" size="small" />
              </NSpace>
            </NSpace>
          </NGi>

          <!-- Search button -->
          <NGi>
            <NSpace vertical justify="center" style="height: 100%">
              <NButton
                type="primary"
                :loading="store.isLoading"
                :disabled="!dataReady || store.selectedDimensions.length === 0"
                @click="doSearch"
                block
              >
                查詢相似案例
              </NButton>
              <NTag v-if="store.result" size="small" :bordered="false">
                {{ app.currentStockCode }} @ {{ store.result.query.date }}
                · {{ store.result.descriptor_count }} descriptors
                · {{ regimeLabels[store.result.query.regime] || '?' }}
              </NTag>
            </NSpace>
          </NGi>
        </NGrid>
      </NCard>
    </NGi>

    <!-- Error -->
    <NGi v-if="store.error">
      <NAlert type="error" :title="store.error" closable />
    </NGi>

    <!-- Small sample warning [ARCHITECT INSTRUCTION] -->
    <NGi v-if="store.result?.statistics?.small_sample_warning">
      <NAlert type="warning" title="樣本數不足">
        相似案例數量 {{ store.result.statistics.sample_count }} 筆，低於 30 筆門檻。
        統計結果可能不穩定，請謹慎解讀。
      </NAlert>
    </NGi>

    <!-- Win rate cards + Expectancy -->
    <NGi v-if="store.result">
      <NGrid :cols="cols(2, 3, 5).value" x-gap="8" y-gap="8">
        <NGi v-for="hz in horizons" :key="hz">
          <NCard size="small">
            <NStatistic :label="horizonLabels[hz]">
              <template #default>
                <span
                  :style="{
                    color:
                      store.result.statistics[hz].win_rate != null
                        ? store.result.statistics[hz].win_rate! > 0.5
                          ? '#e53e3e'
                          : '#38a169'
                        : '',
                    fontSize: '22px',
                    fontWeight: 700,
                  }"
                >
                  {{
                    store.result.statistics[hz].win_rate != null
                      ? (store.result.statistics[hz].win_rate! * 100).toFixed(1) + '%'
                      : '-'
                  }}
                </span>
              </template>
              <template #suffix>
                <span style="font-size: 11px; color: var(--n-text-color-3); margin-left: 4px">
                  EV {{ store.result.statistics[hz].expectancy != null ? fmtPct(store.result.statistics[hz].expectancy!) : '-' }}
                </span>
              </template>
            </NStatistic>
            <!-- P5/P95 tail risk [CONVERGED] -->
            <div v-if="store.result.statistics[hz].p5 != null" style="font-size: 11px; margin-top: 4px; color: var(--n-text-color-3)">
              <span :style="{ color: '#38a169', fontWeight: 600 }">
                P5: {{ fmtPct(store.result.statistics[hz].p5!) }}
              </span>
              <span style="margin: 0 4px">|</span>
              <span :style="{ color: '#e53e3e', fontWeight: 600 }">
                P95: {{ fmtPct(store.result.statistics[hz].p95!) }}
              </span>
            </div>
          </NCard>
        </NGi>
      </NGrid>
    </NGi>

    <!-- Sample count + transaction cost info -->
    <NGi v-if="store.result">
      <NSpace size="small">
        <NTag size="small" :bordered="false">
          樣本數: {{ store.result.statistics.sample_count }}
          · 維度: {{ store.result.dimensions_used.map(d => dimensionLabels[d] || d).join(', ') }}
        </NTag>
        <NTag size="small" :bordered="false" type="info">
          已扣交易成本 {{ (store.result.transaction_cost_deducted * 100).toFixed(3) }}%
        </NTag>
      </NSpace>
    </NGi>

    <!-- Box plot chart -->
    <NGi v-if="boxPlotOption">
      <NCard title="報酬分布圖 (P5-P95)" size="small">
        <VChart :option="boxPlotOption" style="height: 300px; width: 100%" autoresize />
      </NCard>
    </NGi>

    <!-- Similar cases table -->
    <NGi v-if="store.result">
      <NCard title="相似案例" size="small">
        <NDataTable
          :columns="tableColumns"
          :data="tableData"
          :pagination="{ pageSize: 20 }"
          :scroll-x="700"
          size="small"
          striped
        />
      </NCard>
    </NGi>

    <!-- Disclaimer [ARCHITECT INSTRUCTION] -->
    <NGi v-if="store.result">
      <NText depth="3" style="font-size: 11px; text-align: center; display: block">
        歷史相似性不代表未來必然性。本系統為情境分析工具，非投資建議。
      </NText>
    </NGi>
  </NGrid>
</template>
