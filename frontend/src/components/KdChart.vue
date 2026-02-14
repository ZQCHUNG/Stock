<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, MarkLineComponent, DataZoomComponent, AxisPointerComponent, ToolboxComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { TimeSeriesData } from '../api/stocks'
import { useChartTheme } from '../composables/useChartTheme'

use([LineChart, GridComponent, TooltipComponent, LegendComponent, MarkLineComponent, DataZoomComponent, AxisPointerComponent, ToolboxComponent, CanvasRenderer])

const props = defineProps<{
  data: TimeSeriesData | null
  group?: string
}>()

const { colors, tooltipStyle, toolboxConfig } = useChartTheme()

const option = computed(() => {
  const d = props.data
  if (!d || !d.dates.length) return {}
  const k = d.columns.k || []
  const dVal = d.columns.d || []
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
        return `<div style="font-size:12px"><b>${date}</b><br/>K ${k[idx]?.toFixed(1) ?? '-'} D ${dVal[idx]?.toFixed(1) ?? '-'}</div>`
      },
    },
    toolbox: { ...toolboxConfig.value, feature: { restore: toolboxConfig.value.feature.restore, saveAsImage: toolboxConfig.value.feature.saveAsImage } },
    legend: { data: ['K', 'D'], left: 0, textStyle: { fontSize: 11, color: c.legendText } },
    grid: { left: 60, right: 20, top: 30, bottom: 20 },
    xAxis: { type: 'category', data: d.dates, axisLabel: { fontSize: 10, show: false } },
    yAxis: { min: 0, max: 100, splitLine: { lineStyle: { type: 'dashed', color: c.splitLine } } },
    dataZoom: [{ type: 'inside', start: 60, end: 100 }],
    series: [
      {
        name: 'K', type: 'line', data: k, symbol: 'none',
        lineStyle: { width: 1.5, color: '#2196f3' },
        markLine: { silent: true, symbol: 'none', data: [
          { yAxis: 80, lineStyle: { color: '#e53e3e', type: 'dashed' } },
          { yAxis: 20, lineStyle: { color: '#38a169', type: 'dashed' } },
        ]},
      },
      { name: 'D', type: 'line', data: dVal, symbol: 'none', lineStyle: { width: 1.5, color: '#ff9800' } },
    ],
  }
})
</script>

<template>
  <VChart :option="option" :group="group" autoresize style="height: 200px" />
</template>
