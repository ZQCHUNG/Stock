<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'

const props = defineProps<{
  simReturns: number[]
  simVols: number[]
  simSharpes: number[]
  current: { return: number; volatility: number; sharpe: number }
  maxSharpe: { return: number; volatility: number; sharpe: number }
}>()

const option = computed(() => {
  // Scatter data: [vol, return, sharpe]
  const simData = props.simVols.map((v, i) => [
    +(v * 100).toFixed(2),
    +((props.simReturns[i] ?? 0) * 100).toFixed(2),
    props.simSharpes[i] ?? 0,
  ])

  return {
    tooltip: {
      formatter: (p: any) => {
        if (p.seriesName === '模擬組合') {
          return `波動率: ${p.data[0].toFixed(1)}%<br/>報酬率: ${p.data[1].toFixed(1)}%<br/>Sharpe: ${p.data[2].toFixed(2)}`
        }
        return `<b>${p.seriesName}</b><br/>波動率: ${p.data[0].toFixed(1)}%<br/>報酬率: ${p.data[1].toFixed(1)}%`
      },
    },
    grid: { top: 30, bottom: 40, left: 55, right: 20 },
    xAxis: {
      name: '波動率 (%)',
      nameLocation: 'center',
      nameGap: 25,
      type: 'value',
    },
    yAxis: {
      name: '年化報酬 (%)',
      nameLocation: 'center',
      nameGap: 40,
      type: 'value',
    },
    series: [
      {
        name: '模擬組合',
        type: 'scatter',
        data: simData,
        symbolSize: 4,
        itemStyle: {
          color: (p: any) => {
            const s = p.data[2]
            if (s > 1.5) return '#18a058'
            if (s > 0.5) return '#2080f0'
            return '#ccc'
          },
          opacity: 0.5,
        },
      },
      {
        name: '目前組合',
        type: 'scatter',
        data: [[+(props.current.volatility * 100).toFixed(2), +(props.current.return * 100).toFixed(2)]],
        symbolSize: 16,
        symbol: 'diamond',
        itemStyle: { color: '#e53e3e', borderColor: '#fff', borderWidth: 2 },
        label: { show: true, formatter: '目前', position: 'right', fontSize: 11 },
      },
      {
        name: 'Max Sharpe',
        type: 'scatter',
        data: [[+(props.maxSharpe.volatility * 100).toFixed(2), +(props.maxSharpe.return * 100).toFixed(2)]],
        symbolSize: 16,
        symbol: 'star',
        itemStyle: { color: '#f0a020', borderColor: '#fff', borderWidth: 2 },
        label: { show: true, formatter: '最佳', position: 'right', fontSize: 11 },
      },
    ],
  }
})
</script>

<template>
  <VChart :option="option" style="height: 300px" autoresize />
</template>
