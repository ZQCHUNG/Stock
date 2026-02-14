<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart, BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { TimeSeriesData } from '../api/stocks'

use([LineChart, BarChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const props = defineProps<{ data: TimeSeriesData | null }>()

const option = computed(() => {
  const d = props.data
  if (!d || !d.dates.length) return {}
  const macd = d.columns.macd || []
  const signal = d.columns.macd_signal || []
  const hist = d.columns.macd_hist || []

  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['MACD', 'Signal', 'Histogram'], textStyle: { fontSize: 11 } },
    grid: { left: 60, right: 20, top: 30, bottom: 30 },
    xAxis: { type: 'category', data: d.dates, axisLabel: { fontSize: 10 } },
    yAxis: { scale: true, splitLine: { lineStyle: { type: 'dashed', color: '#eee' } } },
    series: [
      { name: 'MACD', type: 'line', data: macd, symbol: 'none', lineStyle: { width: 1.5, color: '#2196f3' } },
      { name: 'Signal', type: 'line', data: signal, symbol: 'none', lineStyle: { width: 1.5, color: '#ff9800' } },
      {
        name: 'Histogram', type: 'bar', data: hist.map((v) => ({
          value: v,
          itemStyle: { color: (v ?? 0) >= 0 ? '#e53e3e80' : '#38a16980' },
        })),
      },
    ],
  }
})
</script>

<template>
  <VChart :option="option" autoresize style="height: 200px" />
</template>
