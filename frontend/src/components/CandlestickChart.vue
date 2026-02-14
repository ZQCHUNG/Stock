<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CandlestickChart as Candle, LineChart, BarChart, ScatterChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, MarkPointComponent, AxisPointerComponent, ToolboxComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { TimeSeriesData } from '../api/stocks'
import { useChartTheme } from '../composables/useChartTheme'

use([Candle, LineChart, BarChart, ScatterChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, MarkPointComponent, AxisPointerComponent, ToolboxComponent, CanvasRenderer])

const props = defineProps<{
  data: TimeSeriesData | null
  supports?: { price: number; source: string }[]
  resistances?: { price: number; source: string }[]
  signals?: TimeSeriesData | null
  group?: string
}>()

const { colors, tooltipStyle, toolboxConfig } = useChartTheme()

const option = computed(() => {
  const d = props.data
  if (!d || !d.dates.length) return {}
  const c = colors.value

  const dates = d.dates
  const open = d.columns.open || []
  const close = d.columns.close || []
  const low = d.columns.low || []
  const high = d.columns.high || []
  const volume = d.columns.volume || []
  const ma5 = d.columns.ma5 || []
  const ma20 = d.columns.ma20 || []
  const ma60 = d.columns.ma60 || []
  const bbUpper = d.columns.bb_upper || []
  const bbLower = d.columns.bb_lower || []

  // Candlestick data: [open, close, low, high]
  const candleData = dates.map((_, i) => [open[i], close[i], low[i], high[i]])

  // Buy/Sell signal markers
  const buyMarkers: any[] = []
  const sellMarkers: any[] = []
  if (props.signals) {
    const sig = (props.signals.columns as Record<string, any[]>).v4_signal || []
    const sigDates = props.signals.dates
    sigDates.forEach((date, i) => {
      const idx = dates.indexOf(date)
      if (idx < 0) return
      if (sig[i] === 'BUY') buyMarkers.push({ coord: [idx, low[idx]], value: 'B', itemStyle: { color: '#e53e3e' } })
      else if (sig[i] === 'SELL') sellMarkers.push({ coord: [idx, high[idx]], value: 'S', itemStyle: { color: '#38a169' } })
    })
  }

  // Support/Resistance lines
  const markLines: any[] = []
  for (const s of props.supports || []) {
    markLines.push({ yAxis: s.price, name: `S ${s.source}`, lineStyle: { color: '#38a169', type: 'dashed' } })
  }
  for (const r of props.resistances || []) {
    markLines.push({ yAxis: r.price, name: `R ${r.source}`, lineStyle: { color: '#e53e3e', type: 'dashed' } })
  }

  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      ...tooltipStyle.value,
      formatter: (params: any[]) => {
        if (!params?.length) return ''
        const idx = params[0].dataIndex
        const date = dates[idx]
        let html = `<div style="font-size:12px"><b>${date}</b><br/>`
        if (open[idx] != null) {
          const o = open[idx] ?? 0, c = close[idx] ?? 0, h = high[idx] ?? 0, l = low[idx] ?? 0, vol = volume[idx] ?? 0
          const clr = c >= o ? '#e53e3e' : '#38a169'
          html += `開 <b>${o.toFixed(2)}</b> 高 <b>${h.toFixed(2)}</b> 低 <b>${l.toFixed(2)}</b> 收 <b style="color:${clr}">${c.toFixed(2)}</b><br/>`
          html += `量 ${(vol / 1000).toFixed(0)} 張`
          if (ma5[idx] != null) html += ` MA5 ${(ma5[idx] ?? 0).toFixed(2)}`
          if (ma20[idx] != null) html += ` MA20 ${(ma20[idx] ?? 0).toFixed(2)}`
        }
        return html + '</div>'
      },
    },
    toolbox: toolboxConfig.value,
    legend: { data: ['K線', 'MA5', 'MA20', 'MA60', 'BB上', 'BB下'], top: 0, left: 0, textStyle: { fontSize: 11, color: c.legendText } },
    grid: [
      { left: 60, right: 20, top: 40, height: '55%' },
      { left: 60, right: 20, top: '72%', height: '18%' },
    ],
    xAxis: [
      { type: 'category', data: dates, gridIndex: 0, axisLabel: { show: false } },
      { type: 'category', data: dates, gridIndex: 1, axisLabel: { fontSize: 10 } },
    ],
    yAxis: [
      { scale: true, gridIndex: 0, splitLine: { lineStyle: { type: 'dashed', color: c.splitLine } } },
      { scale: true, gridIndex: 1, splitLine: { show: false } },
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1], start: 60, end: 100 },
      { type: 'slider', xAxisIndex: [0, 1], start: 60, end: 100, top: '95%', height: 16 },
    ],
    series: [
      {
        name: 'K線', type: 'candlestick', data: candleData, xAxisIndex: 0, yAxisIndex: 0,
        itemStyle: { color: '#e53e3e', color0: '#38a169', borderColor: '#e53e3e', borderColor0: '#38a169' },
        markPoint: buyMarkers.length || sellMarkers.length ? {
          data: [
            ...buyMarkers.map((m) => ({ ...m, symbol: 'triangle', symbolSize: 10, symbolRotate: 0 })),
            ...sellMarkers.map((m) => ({ ...m, symbol: 'triangle', symbolSize: 10, symbolRotate: 180 })),
          ],
        } : undefined,
        markLine: markLines.length ? { silent: true, symbol: 'none', data: markLines } : undefined,
      },
      { name: 'MA5', type: 'line', data: ma5, xAxisIndex: 0, yAxisIndex: 0, lineStyle: { width: 1 }, symbol: 'none', itemStyle: { color: '#ff6b35' } },
      { name: 'MA20', type: 'line', data: ma20, xAxisIndex: 0, yAxisIndex: 0, lineStyle: { width: 1 }, symbol: 'none', itemStyle: { color: '#2196f3' } },
      { name: 'MA60', type: 'line', data: ma60, xAxisIndex: 0, yAxisIndex: 0, lineStyle: { width: 1 }, symbol: 'none', itemStyle: { color: '#9c27b0' } },
      { name: 'BB上', type: 'line', data: bbUpper, xAxisIndex: 0, yAxisIndex: 0, lineStyle: { width: 1, type: 'dotted', color: c.bbLine }, symbol: 'none' },
      { name: 'BB下', type: 'line', data: bbLower, xAxisIndex: 0, yAxisIndex: 0, lineStyle: { width: 1, type: 'dotted', color: c.bbLine }, symbol: 'none' },
      {
        name: '成交量', type: 'bar', data: volume.map((v, i) => ({
          value: v,
          itemStyle: { color: (close[i] ?? 0) >= (open[i] ?? 0) ? '#e53e3e80' : '#38a16980' },
        })),
        xAxisIndex: 1, yAxisIndex: 1,
      },
    ],
  }
})
</script>

<template>
  <VChart :option="option" :group="group" autoresize style="height: 500px" />
</template>
