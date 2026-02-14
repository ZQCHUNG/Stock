<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, MarkLineComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { TimeSeriesData } from '../api/stocks'

use([LineChart, GridComponent, TooltipComponent, LegendComponent, MarkLineComponent, CanvasRenderer])

const props = defineProps<{ data: TimeSeriesData | null }>()

const option = computed(() => {
  const d = props.data
  if (!d || !d.dates.length) return {}

  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['K', 'D'], textStyle: { fontSize: 11 } },
    grid: { left: 60, right: 20, top: 30, bottom: 30 },
    xAxis: { type: 'category', data: d.dates, axisLabel: { fontSize: 10 } },
    yAxis: { min: 0, max: 100, splitLine: { lineStyle: { type: 'dashed', color: '#eee' } } },
    series: [
      {
        name: 'K', type: 'line', data: d.columns.k || [], symbol: 'none',
        lineStyle: { width: 1.5, color: '#2196f3' },
        markLine: { silent: true, symbol: 'none', data: [
          { yAxis: 80, lineStyle: { color: '#e53e3e', type: 'dashed' } },
          { yAxis: 20, lineStyle: { color: '#38a169', type: 'dashed' } },
        ]},
      },
      { name: 'D', type: 'line', data: d.columns.d || [], symbol: 'none', lineStyle: { width: 1.5, color: '#ff9800' } },
    ],
  }
})
</script>

<template>
  <VChart :option="option" autoresize style="height: 200px" />
</template>
