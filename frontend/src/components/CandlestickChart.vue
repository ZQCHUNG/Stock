<script setup lang="ts">
import { computed, ref } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CandlestickChart as Candle, LineChart, BarChart, ScatterChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, MarkPointComponent, MarkAreaComponent, AxisPointerComponent, ToolboxComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { TimeSeriesData } from '../api/stocks'
import { fmtPrice, fmtVol } from '../utils/format'
import { useChartTheme } from '../composables/useChartTheme'

use([Candle, LineChart, BarChart, ScatterChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, MarkPointComponent, MarkAreaComponent, AxisPointerComponent, ToolboxComponent, CanvasRenderer])

export interface TradeMarker {
  date_open: string
  date_close: string
  price_open: number
  price_close: number
  pnl: number
  return_pct?: number
  exit_reason?: string
}

const props = defineProps<{
  data: TimeSeriesData | null
  supports?: { price: number; source: string }[]
  resistances?: { price: number; source: string }[]
  signals?: TimeSeriesData | null
  trades?: TradeMarker[]
  group?: string
  activeTradeIdx?: number  // Phase 8C: Highlight active trade
  showTradeAreas?: boolean // Phase 8C: Show holding period areas
}>()

const { colors, tooltipStyle, toolboxConfig } = useChartTheme()

const chartRef = ref<any>(null)

/** Phase 8C: Zoom to trade with contextual padding (-20d, +10d) */
function zoomToTrade(trade: TradeMarker) {
  const d = props.data
  if (!d || !chartRef.value) return
  const dates = d.dates
  const dateIdx: Record<string, number> = {}
  dates.forEach((dt: string, i: number) => { dateIdx[dt.slice(0, 10)] = i })

  const openIdx = dateIdx[trade.date_open?.slice(0, 10)] ?? 0
  const closeIdx = dateIdx[trade.date_close?.slice(0, 10)] ?? dates.length - 1
  const padBefore = 20
  const padAfter = 10
  const startIdx = Math.max(0, openIdx - padBefore)
  const endIdx = Math.min(dates.length - 1, closeIdx + padAfter)
  const startPct = (startIdx / dates.length) * 100
  const endPct = (endIdx / dates.length) * 100

  chartRef.value.dispatchAction({
    type: 'dataZoom',
    start: startPct,
    end: endPct,
  })
}

defineExpose({ zoomToTrade })

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

  // Trade markers (from backtest results)
  const tradeBuyScatter: any[] = []
  const tradeSellScatter: any[] = []
  if (props.trades?.length) {
    const dateIdx: Record<string, number> = {}
    dates.forEach((d: string, i: number) => { dateIdx[d.slice(0, 10)] = i })

    props.trades.forEach((t) => {
      const openDate = t.date_open?.slice(0, 10)
      const closeDate = t.date_close?.slice(0, 10)
      if (openDate && dateIdx[openDate] !== undefined) {
        const idx = dateIdx[openDate]
        tradeBuyScatter.push([idx, t.price_open])
      }
      if (closeDate && dateIdx[closeDate] !== undefined) {
        const idx = dateIdx[closeDate]
        tradeSellScatter.push([idx, t.price_close])
      }
    })
  }

  // Trade holding period areas (Phase 8C)
  const tradeAreas: any[] = []
  if (props.trades?.length && props.showTradeAreas) {
    const dateIdx: Record<string, number> = {}
    dates.forEach((d: string, i: number) => { dateIdx[d.slice(0, 10)] = i })

    props.trades.forEach((t, tidx) => {
      const od = t.date_open?.slice(0, 10)
      const cd = t.date_close?.slice(0, 10)
      if (od && cd && dateIdx[od] !== undefined && dateIdx[cd] !== undefined) {
        const isProfit = (t.return_pct ?? 0) > 0
        const isActive = tidx === props.activeTradeIdx
        const opacity = isActive ? 0.2 : 0.06
        const color = isProfit ? `rgba(56,161,105,${opacity})` : `rgba(229,62,62,${opacity})`
        tradeAreas.push([
          { xAxis: dateIdx[od], itemStyle: { color } },
          { xAxis: dateIdx[cd] },
        ])
      }
    })
  }

  // Build trade lookup for rich tooltips
  const tradeByDate: Record<string, { type: 'entry' | 'exit'; trade: TradeMarker }[]> = {}
  if (props.trades?.length) {
    const dateIdxMap: Record<string, number> = {}
    dates.forEach((d: string, i: number) => { dateIdxMap[d.slice(0, 10)] = i })
    props.trades.forEach((t) => {
      const od = t.date_open?.slice(0, 10)
      const cd = t.date_close?.slice(0, 10)
      if (od) { (tradeByDate[od] = tradeByDate[od] || []).push({ type: 'entry', trade: t }) }
      if (cd) { (tradeByDate[cd] = tradeByDate[cd] || []).push({ type: 'exit', trade: t }) }
    })
  }

  // Support/Resistance lines + exit lines
  const markLines: any[] = []
  for (const s of props.supports || []) {
    const isExit = s.source.includes('停損') || s.source.includes('停利')
    const color = s.source.includes('停利') ? '#2080f0' : s.source.includes('停損') ? '#f59e0b' : '#38a169'
    markLines.push({ yAxis: s.price, name: s.source, lineStyle: { color, type: 'dashed', width: isExit ? 2 : 1 } })
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
          const o = open[idx] ?? 0, c = close[idx] ?? 0
          const clr = c >= o ? '#e53e3e' : '#38a169'
          html += `開 <b>${fmtPrice(open[idx])}</b> 高 <b>${fmtPrice(high[idx])}</b> 低 <b>${fmtPrice(low[idx])}</b> 收 <b style="color:${clr}">${fmtPrice(close[idx])}</b><br/>`
          html += `量 ${fmtVol(volume[idx])}`
          if (ma5[idx] != null) html += ` MA5 ${fmtPrice(ma5[idx])}`
          if (ma20[idx] != null) html += ` MA20 ${fmtPrice(ma20[idx])}`
        }
        // Rich trade marker info (Phase 8C)
        const dateStr = date?.slice(0, 10) || ''
        const tradeInfos = tradeByDate[dateStr]
        if (tradeInfos?.length) {
          tradeInfos.forEach(({ type, trade }) => {
            if (type === 'entry') {
              html += `<br/><span style="color:#e53e3e; font-weight:bold">▲ Entry</span> @${fmtPrice(trade.price_open)}`
              if ((trade as any).sqs_score) html += ` | SQS: ${(trade as any).sqs_score}`
              if ((trade as any).rs_rating) html += ` | RS: ${(trade as any).rs_rating}`
              if ((trade as any).entry_type) html += ` | ${(trade as any).entry_type}`
            } else {
              html += `<br/><span style="color:#38a169; font-weight:bold">▼ Exit</span> @${fmtPrice(trade.price_close)}`
              const ret = trade.return_pct ?? 0
              const retColor = ret >= 0 ? '#e53e3e' : '#38a169'
              html += ` <span style="color:${retColor}">${ret >= 0 ? '+' : ''}${(ret * 100).toFixed(1)}%</span>`
              if (trade.exit_reason) html += ` | ${trade.exit_reason}`
              const days = trade.date_open && trade.date_close
                ? Math.round((new Date(trade.date_close).getTime() - new Date(trade.date_open).getTime()) / 86400000)
                : null
              if (days != null) html += ` | ${days}d`
            }
          })
        } else {
          // Fallback to simple markers
          params.forEach((p: any) => {
            if (p.seriesName === '買入點') html += `<br/><span style="color:#e53e3e">▲ 買入</span> $${fmtPrice(p.value[1])}`
            else if (p.seriesName === '賣出點') html += `<br/><span style="color:#38a169">▼ 賣出</span> $${fmtPrice(p.value[1])}`
          })
        }
        return html + '</div>'
      },
    },
    toolbox: toolboxConfig.value,
    legend: {
      data: [
        'K線', 'MA5', 'MA20', 'MA60', 'BB上', 'BB下',
        ...(tradeBuyScatter.length ? ['買入點'] : []),
        ...(tradeSellScatter.length ? ['賣出點'] : []),
      ],
      top: 0, left: 0, textStyle: { fontSize: 11, color: c.legendText },
    },
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
      { type: 'inside', xAxisIndex: [0, 1], start: props.trades?.length ? 0 : 60, end: 100 },
      { type: 'slider', xAxisIndex: [0, 1], start: props.trades?.length ? 0 : 60, end: 100, top: '95%', height: 16 },
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
        markArea: tradeAreas.length ? { silent: true, data: tradeAreas } : undefined,
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
      // Trade markers (backtest buy/sell points)
      ...(tradeBuyScatter.length ? [{
        name: '買入點', type: 'scatter' as const,
        data: tradeBuyScatter, symbol: 'triangle', symbolSize: 12,
        itemStyle: { color: '#e53e3e' },
        xAxisIndex: 0, yAxisIndex: 0, z: 20,
      }] : []),
      ...(tradeSellScatter.length ? [{
        name: '賣出點', type: 'scatter' as const,
        data: tradeSellScatter, symbol: 'pin', symbolSize: 14,
        symbolRotate: 180,
        itemStyle: { color: '#38a169' },
        xAxisIndex: 0, yAxisIndex: 0, z: 20,
      }] : []),
    ],
  }
})
</script>

<template>
  <VChart ref="chartRef" :option="option" :group="group" autoresize style="height: 500px" />
</template>
