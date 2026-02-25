<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import {
  NCard, NButton, NSpace, NSelect, NSpin, NAlert, NTag,
  NStatistic, NGrid, NGi, NDivider, NText, NTooltip,
} from 'naive-ui'
import VChart from 'vue-echarts'
import { backtestApi, type HeatmapResult, type HeatmapPreset } from '../api/backtest'

const loading = ref(false)
const error = ref('')
const result = ref<HeatmapResult | null>(null)
const presets = ref<Record<string, HeatmapPreset>>({})
const selectedPreset = ref('entry_d_threshold_vs_lookback')
const selectedMetric = ref('sharpe_ratio')

const presetOptions = computed(() =>
  Object.entries(presets.value).map(([key, p]) => ({
    label: `${p.x_label} × ${p.y_label}`,
    value: key,
  }))
)

const metricOptions = [
  { label: 'Sharpe Ratio', value: 'sharpe_ratio' },
  { label: 'Calmar Ratio', value: 'calmar_ratio' },
  { label: 'Win Rate', value: 'win_rate' },
  { label: 'Profit Factor', value: 'profit_factor' },
  { label: 'Total Return', value: 'total_return' },
  { label: 'Max Drawdown', value: 'max_drawdown' },
  { label: 'Avg Trades', value: 'total_trades' },
]

const metricLabel = computed(() => {
  const m = metricOptions.find((o) => o.value === selectedMetric.value)
  return m ? m.label : selectedMetric.value
})

// Build echarts heatmap option
const heatmapOption = computed(() => {
  if (!result.value) return {}
  const r = result.value
  const mat = r.all_metrics[selectedMetric.value] || r.matrix

  // Format X labels
  const xLabels = r.x_values.map((v) => {
    if (r.x_param === 'momentum_high_pct') return `${(v * 100).toFixed(0)}%`
    return String(v)
  })
  const yLabels = r.y_values.map((v) => String(v))

  // Build data: [x_idx, y_idx, value]
  const data: [number, number, number | null][] = []
  let minVal = Infinity
  let maxVal = -Infinity
  for (let yi = 0; yi < r.y_values.length; yi++) {
    for (let xi = 0; xi < r.x_values.length; xi++) {
      const val = mat[yi]?.[xi] ?? null
      data.push([xi, yi, val])
      if (val !== null && isFinite(val)) {
        if (val < minVal) minVal = val
        if (val > maxVal) maxVal = val
      }
    }
  }
  if (!isFinite(minVal)) minVal = 0
  if (!isFinite(maxVal)) maxVal = 1

  // Mark default parameter position
  const defaultXIdx = r.x_values.indexOf(r.default_x)
  const defaultYIdx = r.y_values.indexOf(r.default_y)
  const markData =
    defaultXIdx >= 0 && defaultYIdx >= 0
      ? [{ coord: [defaultXIdx, defaultYIdx], symbol: 'diamond', symbolSize: 16 }]
      : []

  // Color: green (good) for positive metrics, red-green inverted for max_drawdown
  const isInverse = selectedMetric.value === 'max_drawdown'

  return {
    tooltip: {
      position: 'top',
      formatter: (p: any) => {
        const xi = p.data[0]
        const yi = p.data[1]
        const val = p.data[2]
        const zone = r.zones[yi]?.[xi] || ''
        const xv = r.x_values[xi]
        const yv = r.y_values[yi]
        const zoneEmoji = zone === 'plateau' ? '🟢' : zone === 'island' ? '🔴' : '⚪'
        // Show all metrics for this cell
        const lines = [`<b>${r.x_label}</b>: ${xv}`, `<b>${r.y_label}</b>: ${yv}`]
        for (const [mk, label] of metricOptions.map((o) => [o.value, o.label])) {
          const mv = r.all_metrics[mk]?.[yi]?.[xi]
          if (mv !== null && mv !== undefined) {
            const fmt =
              mk === 'win_rate' ? `${(mv * 100).toFixed(1)}%`
              : mk === 'max_drawdown' ? `${(mv * 100).toFixed(1)}%`
              : mk === 'total_trades' ? mv.toFixed(1)
              : mv.toFixed(3)
            lines.push(`${label}: <b>${fmt}</b>`)
          }
        }
        lines.push(`Zone: ${zoneEmoji} ${zone}`)
        return lines.join('<br/>')
      },
    },
    grid: { top: 40, right: 80, bottom: 60, left: 80 },
    xAxis: {
      type: 'category',
      data: xLabels,
      name: r.x_label,
      nameLocation: 'center',
      nameGap: 35,
      splitArea: { show: true },
    },
    yAxis: {
      type: 'category',
      data: yLabels,
      name: r.y_label,
      nameLocation: 'center',
      nameGap: 55,
      splitArea: { show: true },
    },
    visualMap: {
      min: minVal,
      max: maxVal,
      calculable: true,
      orient: 'vertical',
      right: 0,
      top: 'center',
      inRange: {
        color: isInverse
          ? ['#50a14f', '#e6c07b', '#e06c75'] // green→yellow→red for drawdown
          : ['#e06c75', '#e6c07b', '#50a14f'], // red→yellow→green for returns
      },
    },
    series: [
      {
        type: 'heatmap',
        data,
        label: {
          show: true,
          formatter: (p: any) => {
            const v = p.data[2]
            if (v === null) return '-'
            if (selectedMetric.value === 'win_rate' || selectedMetric.value === 'max_drawdown')
              return `${(v * 100).toFixed(0)}%`
            if (selectedMetric.value === 'total_trades') return v.toFixed(0)
            return v.toFixed(2)
          },
          fontSize: 11,
        },
        emphasis: {
          itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.5)' },
        },
        markPoint: markData.length
          ? {
              data: markData,
              itemStyle: { color: 'transparent', borderColor: '#fff', borderWidth: 2 },
              label: { show: true, formatter: '★', fontSize: 14, color: '#fff' },
            }
          : undefined,
      },
    ],
  }
})

// Summary stats
const summary = computed(() => {
  if (!result.value) return null
  const r = result.value
  const mat = r.all_metrics[selectedMetric.value] || r.matrix
  const flat = mat.flat().filter((v): v is number => v !== null && isFinite(v))
  if (flat.length === 0) return null

  const mean = flat.reduce((a, b) => a + b, 0) / flat.length
  const std = Math.sqrt(flat.reduce((a, v) => a + (v - mean) ** 2, 0) / flat.length)
  const cv = mean !== 0 ? std / Math.abs(mean) : Infinity

  // Count zones
  const zones = r.zones.flat()
  const plateau = zones.filter((z) => z === 'plateau').length
  const island = zones.filter((z) => z === 'island').length

  return {
    mean: mean.toFixed(3),
    std: std.toFixed(3),
    cv: cv.toFixed(2),
    max: Math.max(...flat).toFixed(3),
    min: Math.min(...flat).toFixed(3),
    plateau,
    island,
    total: zones.length,
    robust: plateau / zones.length > 0.6,
  }
})

async function loadPresets() {
  try {
    presets.value = await backtestApi.parameterHeatmapPresets()
  } catch {
    // Use defaults
    presets.value = {
      entry_d_threshold_vs_lookback: {
        x_param: 'momentum_high_pct',
        x_values: [0.93, 0.94, 0.95, 0.96, 0.97, 0.98, 0.99],
        x_label: 'Near-High Threshold',
        y_param: 'momentum_ma20_slope_days',
        y_values: [5, 10, 15, 20, 25, 30, 35, 40],
        y_label: 'MA20 Slope Persistence (days)',
      },
      entry_d_rsi_vs_volume: {
        x_param: 'momentum_rsi_min',
        x_values: [45, 50, 55, 60, 65],
        x_label: 'RSI Lower Bound',
        y_param: 'momentum_vol_ratio',
        y_values: [0.8, 1.0, 1.2, 1.5, 2.0],
        y_label: 'Volume Ratio (5d/20d)',
      },
    }
  }
}

async function runHeatmap() {
  loading.value = true
  error.value = ''
  result.value = null
  try {
    result.value = await backtestApi.parameterHeatmap({
      preset: selectedPreset.value,
      metric: selectedMetric.value,
    })
  } catch (e: any) {
    error.value = e.response?.data?.detail || e.message || 'Heatmap computation failed'
  }
  loading.value = false
}

onMounted(loadPresets)
</script>

<template>
  <NCard title="Entry D Parameter Sensitivity Heatmap" size="small">
    <template #header-extra>
      <NTag type="info" size="small">P2-A CTO Directive</NTag>
    </template>

    <NSpace align="center" style="margin-bottom: 16px">
      <NSelect
        v-model:value="selectedPreset"
        :options="presetOptions"
        style="width: 320px"
        placeholder="Select parameter pair"
      />
      <NSelect
        v-model:value="selectedMetric"
        :options="metricOptions"
        style="width: 180px"
      />
      <NButton type="primary" :loading="loading" @click="runHeatmap">
        Run Sweep (20 stocks, ~5min)
      </NButton>
    </NSpace>

    <NAlert v-if="error" type="error" style="margin-bottom: 12px">{{ error }}</NAlert>

    <NSpin :show="loading" description="Running grid search across 56 parameter combinations...">
      <template v-if="result">
        <!-- Summary -->
        <NGrid :cols="6" :x-gap="12" style="margin-bottom: 16px">
          <NGi>
            <NStatistic :label="`Avg ${metricLabel}`" :value="summary?.mean || '-'" />
          </NGi>
          <NGi>
            <NStatistic label="Std Dev" :value="summary?.std || '-'" />
          </NGi>
          <NGi>
            <NStatistic label="CV (lower=robust)" :value="summary?.cv || '-'" />
          </NGi>
          <NGi>
            <NStatistic label="Plateau Cells" :value="`${summary?.plateau}/${summary?.total}`" />
          </NGi>
          <NGi>
            <NStatistic label="Island Cells" :value="`${summary?.island}/${summary?.total}`" />
          </NGi>
          <NGi>
            <NStatistic label="Stocks Used" :value="result.stocks_used" />
          </NGi>
        </NGrid>

        <NAlert
          v-if="summary?.robust"
          type="success"
          style="margin-bottom: 12px"
        >
          Profit Plateau detected — >60% of cells in stable zone. Entry D parameters are robust.
        </NAlert>
        <NAlert
          v-else-if="summary && summary.island > 2"
          type="warning"
          style="margin-bottom: 12px"
        >
          Parameter Islands detected — {{ summary.island }} cells show anomalous performance. Possible overfitting risk.
        </NAlert>

        <!-- Heatmap Chart -->
        <VChart
          :option="heatmapOption"
          style="height: 450px; width: 100%"
          autoresize
        />

        <NDivider />

        <NSpace>
          <NText depth="3" style="font-size: 12px">
            Computed in {{ result.compute_time_sec }}s | Default: ★
            | Zone: 🟢 Plateau (robust) | 🔴 Island (overfit risk) | ⚪ Desert (poor)
          </NText>
        </NSpace>
      </template>
    </NSpin>
  </NCard>
</template>
