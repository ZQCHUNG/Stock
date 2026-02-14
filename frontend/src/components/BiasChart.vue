<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, MarkLineComponent, DataZoomComponent, AxisPointerComponent, ToolboxComponent, MarkAreaComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { TimeSeriesData } from '../api/stocks'
import { useChartTheme } from '../composables/useChartTheme'

use([BarChart, GridComponent, TooltipComponent, MarkLineComponent, MarkAreaComponent, DataZoomComponent, AxisPointerComponent, ToolboxComponent, CanvasRenderer])

const props = defineProps<{
  data: TimeSeriesData | null
  group?: string
}>()

const { colors, tooltipStyle, toolboxConfig } = useChartTheme()

const option = computed(() => {
  const d = props.data
  if (!d || !d.dates.length) return {}
  const close = d.columns.close || []
  const ma20 = d.columns.ma20 || []

  // BIAS = (close - MA20) / MA20
  const bias = close.map((c: number | null, i: number) => {
    const m = ma20[i]
    if (!c || !m || m === 0) return null
    return +((c - m) / m * 100).toFixed(2)
  })

  const c = colors.value

  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      ...tooltipStyle.value,
      formatter: (params: any[]) => {
        if (!params?.length) return ''
        const idx = params[0].dataIndex
        const date = d.dates[idx]
        const b = bias[idx]
        return `<div style="font-size:12px"><b>${date}</b><br/>` +
          `BIAS: ${b != null ? b.toFixed(2) + '%' : '-'}</div>`
      },
    },
    toolbox: { ...toolboxConfig.value, feature: { restore: toolboxConfig.value.feature.restore, saveAsImage: toolboxConfig.value.feature.saveAsImage } },
    grid: { left: 60, right: 20, top: 20, bottom: 20 },
    xAxis: { type: 'category', data: d.dates, axisLabel: { fontSize: 10, show: false } },
    yAxis: {
      splitLine: { lineStyle: { type: 'dashed', color: c.splitLine } },
      axisLabel: { formatter: '{value}%' },
    },
    dataZoom: [{ type: 'inside', start: 60, end: 100 }],
    series: [
      {
        name: 'BIAS', type: 'bar', data: bias,
        itemStyle: {
          color: (params: any) => {
            const val = params.value
            if (val == null) return '#ccc'
            if (val <= -5) return '#e53e3e'  // Oversold zone
            if (val < 0) return '#f0a020'
            if (val >= 5) return '#38a169'
            return '#2196f3'
          },
        },
        markLine: { silent: true, symbol: 'none', data: [
          { yAxis: -5, lineStyle: { color: '#e53e3e', type: 'dashed', width: 1 }, label: { show: true, position: 'insideStartTop', formatter: '-5% 超跌', fontSize: 10 } },
          { yAxis: 0, lineStyle: { color: '#999', type: 'solid', width: 1 } },
          { yAxis: 5, lineStyle: { color: '#38a169', type: 'dashed', width: 1 }, label: { show: true, position: 'insideStartTop', formatter: '+5%', fontSize: 10 } },
        ]},
        markArea: {
          silent: true, data: [[
            { yAxis: -100, itemStyle: { color: 'rgba(229, 62, 62, 0.05)' } },
            { yAxis: -5 },
          ]],
        },
      },
    ],
  }
})
</script>

<template>
  <VChart :option="option" :group="group" autoresize style="height: 160px" />
</template>
