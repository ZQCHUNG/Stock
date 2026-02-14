<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import {
  TooltipComponent, GridComponent, DataZoomComponent,
  MarkLineComponent, LegendComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

use([LineChart, TooltipComponent, GridComponent, DataZoomComponent, MarkLineComponent, LegendComponent, CanvasRenderer])

const props = defineProps<{
  dates: string[]
  equity: number[]
  hwm: number[]
  drawdown: number[]
  shadowDates?: string[] | null
  shadowEquity?: number[] | null
}>()

const hasShadow = computed(() =>
  props.shadowDates && props.shadowEquity && props.shadowEquity.length >= 2
)

const option = computed(() => {
  const legendData = ['資產淨值', 'HWM', '回撤']
  const seriesList: any[] = [
    {
      name: '資產淨值',
      type: 'line',
      data: props.equity,
      xAxisIndex: 0,
      yAxisIndex: 0,
      lineStyle: { width: 2, color: '#2080f0' },
      itemStyle: { color: '#2080f0' },
      showSymbol: false,
      areaStyle: { color: 'rgba(32,128,240,0.08)' },
    },
    {
      name: 'HWM',
      type: 'line',
      data: props.hwm,
      xAxisIndex: 0,
      yAxisIndex: 0,
      lineStyle: { width: 1, type: 'dashed', color: '#999' },
      itemStyle: { color: '#999' },
      showSymbol: false,
    },
    {
      name: '回撤',
      type: 'line',
      data: props.drawdown,
      xAxisIndex: 1,
      yAxisIndex: 1,
      lineStyle: { width: 1, color: '#e53e3e' },
      itemStyle: { color: '#e53e3e' },
      showSymbol: false,
      areaStyle: { color: 'rgba(229,62,62,0.15)' },
    },
  ]

  // Shadow portfolio overlay (Gemini R30)
  if (hasShadow.value) {
    legendData.push('AI 影子組合')
    // Align shadow data to main dates
    const shadowMap = new Map<string, number>()
    props.shadowDates!.forEach((d, i) => shadowMap.set(d, props.shadowEquity![i] ?? 0))
    const alignedShadow = props.dates.map(d => shadowMap.get(d) ?? null)

    seriesList.push({
      name: 'AI 影子組合',
      type: 'line',
      data: alignedShadow,
      xAxisIndex: 0,
      yAxisIndex: 0,
      lineStyle: { width: 2, type: 'dashed', color: '#f0a020' },
      itemStyle: { color: '#f0a020' },
      showSymbol: false,
      connectNulls: true,
    })
  }

  return {
    tooltip: {
      trigger: 'axis',
      formatter: (params: any) => {
        const date = params[0]?.axisValue || ''
        let html = `<b>${date}</b><br/>`
        for (const p of params) {
          if (p.value == null) continue
          const val = p.seriesName === '回撤'
            ? `${(p.value * 100).toFixed(2)}%`
            : `$${Math.round(p.value).toLocaleString()}`
          html += `${p.marker} ${p.seriesName}: ${val}<br/>`
        }
        return html
      },
    },
    legend: {
      data: legendData,
      top: 0,
      textStyle: { fontSize: 11 },
    },
    grid: [
      { left: 60, right: 20, top: 30, height: '55%' },
      { left: 60, right: 20, top: '72%', height: '20%' },
    ],
    xAxis: [
      { type: 'category', data: props.dates, gridIndex: 0, show: false },
      { type: 'category', data: props.dates, gridIndex: 1 },
    ],
    yAxis: [
      {
        type: 'value', gridIndex: 0, name: '淨值',
        axisLabel: { formatter: (v: number) => `${(v / 1000).toFixed(0)}K` },
      },
      {
        type: 'value', gridIndex: 1, name: '回撤',
        axisLabel: { formatter: (v: number) => `${(v * 100).toFixed(0)}%` },
      },
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1], start: 0, end: 100 },
    ],
    series: seriesList,
  }
})
</script>

<template>
  <VChart :option="option" style="height: 320px" autoresize />
</template>
