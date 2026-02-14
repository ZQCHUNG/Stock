<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'

const props = defineProps<{
  codes: string[]
  names: string[]
  matrix: number[][]
}>()

const option = computed(() => {
  const labels = props.codes.map((c, i) => `${c} ${props.names[i] || ''}`.trim())
  const n = labels.length

  // Build heatmap data: [x, y, value]
  const data: [number, number, number][] = []
  for (let i = 0; i < n; i++) {
    for (let j = 0; j < n; j++) {
      data.push([j, i, props.matrix[i]?.[j] ?? 0])
    }
  }

  return {
    tooltip: {
      formatter: (p: any) => {
        const xi = p.data[0]
        const yi = p.data[1]
        const val = p.data[2]
        return `${labels[yi]} × ${labels[xi]}<br/>ρ = <b>${val.toFixed(3)}</b>`
      },
    },
    grid: {
      top: 10,
      bottom: 60,
      left: 90,
      right: 20,
    },
    xAxis: {
      type: 'category',
      data: labels,
      axisLabel: { rotate: 45, fontSize: 11 },
      splitArea: { show: true },
    },
    yAxis: {
      type: 'category',
      data: labels,
      axisLabel: { fontSize: 11 },
      splitArea: { show: true },
    },
    visualMap: {
      min: -1,
      max: 1,
      calculable: true,
      orient: 'horizontal',
      left: 'center',
      bottom: 0,
      inRange: {
        color: ['#2166ac', '#67a9cf', '#d1e5f0', '#f7f7f7', '#fddbc7', '#ef8a62', '#b2182b'],
      },
      textStyle: { fontSize: 11 },
    },
    series: [{
      type: 'heatmap',
      data,
      label: {
        show: n <= 8,
        formatter: (p: any) => p.data[2].toFixed(2),
        fontSize: 11,
      },
      emphasis: {
        itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.3)' },
      },
    }],
  }
})
</script>

<template>
  <VChart :option="option" style="height: 320px" autoresize />
</template>
