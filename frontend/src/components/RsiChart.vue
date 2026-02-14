<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, MarkLineComponent, DataZoomComponent, AxisPointerComponent, ToolboxComponent, MarkAreaComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { TimeSeriesData } from '../api/stocks'
import { useChartTheme } from '../composables/useChartTheme'

use([LineChart, GridComponent, TooltipComponent, LegendComponent, MarkLineComponent, MarkAreaComponent, DataZoomComponent, AxisPointerComponent, ToolboxComponent, CanvasRenderer])

const props = defineProps<{
  data: TimeSeriesData | null
  group?: string
}>()

const { colors, tooltipStyle, toolboxConfig } = useChartTheme()

// Compute rolling 15th percentile of RSI over 60 days (Dynamic V5 threshold)
function rollingPercentile(arr: number[], window: number, pct: number): number[] {
  const result: number[] = []
  for (let i = 0; i < arr.length; i++) {
    if (i < window - 1) {
      result.push(NaN)
      continue
    }
    const slice = arr.slice(Math.max(0, i - window + 1), i + 1).filter(v => !isNaN(v))
    if (slice.length < 20) {
      result.push(NaN)
      continue
    }
    slice.sort((a, b) => a - b)
    const idx = Math.floor(slice.length * pct)
    result.push(slice[idx] ?? NaN)
  }
  return result
}

const option = computed(() => {
  const d = props.data
  if (!d || !d.dates.length) return {}
  const rsi = d.columns.rsi || []
  const c = colors.value

  // Dynamic RSI threshold (15th percentile of 60-day RSI)
  const dynThreshold = rollingPercentile(rsi.map(v => v ?? NaN), 60, 0.15)

  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      ...tooltipStyle.value,
      formatter: (params: any[]) => {
        if (!params?.length) return ''
        const idx = params[0].dataIndex
        const date = d.dates[idx]
        const rsiVal = rsi[idx]
        const dynVal = dynThreshold[idx] ?? NaN
        return `<div style="font-size:12px"><b>${date}</b><br/>` +
          `RSI: ${rsiVal?.toFixed(1) ?? '-'}<br/>` +
          `動態門檻: ${isNaN(dynVal) ? '-' : dynVal.toFixed(1)}</div>`
      },
    },
    toolbox: { ...toolboxConfig.value, feature: { restore: toolboxConfig.value.feature.restore, saveAsImage: toolboxConfig.value.feature.saveAsImage } },
    legend: { data: ['RSI', '動態門檻 (P15)'], left: 0, textStyle: { fontSize: 11, color: c.legendText } },
    grid: { left: 60, right: 20, top: 30, bottom: 20 },
    xAxis: { type: 'category', data: d.dates, axisLabel: { fontSize: 10, show: false } },
    yAxis: { min: 0, max: 100, splitLine: { lineStyle: { type: 'dashed', color: c.splitLine } } },
    dataZoom: [{ type: 'inside', start: 60, end: 100 }],
    series: [
      {
        name: 'RSI', type: 'line', data: rsi, symbol: 'none',
        lineStyle: { width: 1.5, color: '#9b59b6' },
        markLine: { silent: true, symbol: 'none', data: [
          { yAxis: 70, lineStyle: { color: '#e53e3e', type: 'dashed', width: 1 }, label: { show: true, position: 'insideStartTop', formatter: '70 超買', fontSize: 10 } },
          { yAxis: 30, lineStyle: { color: '#38a169', type: 'dashed', width: 1 }, label: { show: true, position: 'insideStartTop', formatter: '30 超賣', fontSize: 10 } },
        ]},
      },
      {
        name: '動態門檻 (P15)', type: 'line',
        data: dynThreshold.map(v => isNaN(v) ? null : +v.toFixed(1)),
        symbol: 'none',
        lineStyle: { width: 1.5, color: '#2196f3', type: 'dotted' },
        areaStyle: { color: 'rgba(33, 150, 243, 0.05)' },
      },
    ],
  }
})
</script>

<template>
  <VChart :option="option" :group="group" autoresize style="height: 200px" />
</template>
