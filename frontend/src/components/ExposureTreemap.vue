<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { TreemapChart } from 'echarts/charts'
import { TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { fmtNum, fmtPct } from '../utils/format'

use([TreemapChart, TooltipComponent, CanvasRenderer])

interface Position {
  code: string
  name: string
  market_value?: number
  pnl_pct?: number
  sector?: string
  lots?: number
}

const props = defineProps<{
  positions: Position[]
}>()

const option = computed(() => {
  // Group by sector
  const sectorMap = new Map<string, Position[]>()
  for (const p of props.positions) {
    const sec = p.sector || '未分類'
    if (!sectorMap.has(sec)) sectorMap.set(sec, [])
    sectorMap.get(sec)!.push(p)
  }

  const data = Array.from(sectorMap.entries()).map(([sector, positions]) => ({
    name: sector,
    children: positions.map(p => ({
      name: `${p.code}\n${p.name}`,
      value: Math.max(p.market_value || 0, 1),
      pnl_pct: p.pnl_pct || 0,
      code: p.code,
      lots: p.lots || 0,
    })),
  }))

  return {
    tooltip: {
      formatter: (info: any) => {
        if (!info.data?.code) return info.name
        const d = info.data
        return `<b>${d.code}</b> ${d.name?.replace('\n', ' ')}<br/>` +
          `市值: $${fmtNum(d.value, 0)}<br/>` +
          `損益: <span style="color:${d.pnl_pct >= 0 ? '#18a058' : '#e53e3e'}">${fmtPct(d.pnl_pct)}</span><br/>` +
          `張數: ${d.lots}`
      },
    },
    series: [{
      type: 'treemap',
      data,
      width: '100%',
      height: '100%',
      roam: false,
      nodeClick: false,
      breadcrumb: { show: false },
      label: {
        show: true,
        formatter: '{b}',
        fontSize: 11,
      },
      upperLabel: {
        show: true,
        height: 20,
        fontSize: 12,
        fontWeight: 600,
        color: '#fff',
      },
      levels: [
        {
          // Sector level
          itemStyle: { borderWidth: 2, borderColor: '#333', gapWidth: 2 },
          upperLabel: { show: true },
        },
        {
          // Stock level — color by P&L
          colorSaturation: [0.3, 0.8],
          itemStyle: {
            borderWidth: 1,
            borderColorSaturation: 0.6,
            gapWidth: 1,
          },
        },
      ],
      visualMin: -0.1,
      visualMax: 0.1,
      visualDimension: 'pnl_pct',
      color: ['#e53e3e', '#f0a020', '#ddd', '#a3d977', '#18a058'],
    }],
  }
})
</script>

<template>
  <VChart :option="option" style="height: 240px" autoresize />
</template>
