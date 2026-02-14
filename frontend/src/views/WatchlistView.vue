<script setup lang="ts">
import { onMounted } from 'vue'
import { NCard, NButton, NDataTable, NSpin, NSpace, NTag } from 'naive-ui'
import { useAppStore } from '../stores/app'
import { useWatchlistStore } from '../stores/watchlist'
import { fmtPct, fmtNum, priceColor } from '../utils/format'

const app = useAppStore()
const wl = useWatchlistStore()

onMounted(() => {
  wl.load()
  wl.loadOverview()
})

function selectStock(code: string) {
  app.selectStock(code)
}

const overviewColumns = [
  { title: '代碼', key: 'code', width: 70, render: (r: any) => r.code },
  { title: '名稱', key: 'name', width: 80 },
  { title: '收盤價', key: 'price', width: 90, render: (r: any) => r.price?.toFixed(2) || '-' },
  { title: '漲跌%', key: 'change_pct', width: 80, sorter: (a: any, b: any) => (a.change_pct || 0) - (b.change_pct || 0),
    render: (r: any) => {
      const v = r.change_pct
      if (v == null) return '-'
      return `<span style="color: ${priceColor(v)}; font-weight: 600">${fmtPct(v)}</span>`
    },
    // Use cellProps for coloring in setup
  },
  { title: '成交量(張)', key: 'volume_lots', width: 100, render: (r: any) => fmtNum(r.volume_lots, 0) },
  { title: '訊號', key: 'signal', width: 70, render: (r: any) => r.signal || '-' },
  { title: '趨勢天數', key: 'uptrend_days', width: 80 },
  { title: 'RSI', key: 'rsi', width: 60, render: (r: any) => r.rsi?.toFixed(1) || '-' },
  { title: 'ADX', key: 'adx', width: 60, render: (r: any) => r.adx?.toFixed(1) || '-' },
  {
    title: '操作', key: 'actions', width: 100,
    render: (r: any) => {
      return undefined // handled via template
    },
  },
]

const btColumns = [
  { title: '代碼', key: 'code', width: 70 },
  { title: '名稱', key: 'name', width: 80 },
  { title: '總報酬', key: 'total_return', width: 90, sorter: (a: any, b: any) => (a.total_return || 0) - (b.total_return || 0), render: (r: any) => fmtPct(r.total_return) },
  { title: '年化報酬', key: 'annual_return', width: 90, render: (r: any) => fmtPct(r.annual_return) },
  { title: '最大回撤', key: 'max_drawdown', width: 90, render: (r: any) => fmtPct(r.max_drawdown) },
  { title: 'Sharpe', key: 'sharpe_ratio', width: 80, render: (r: any) => r.sharpe_ratio?.toFixed(2) || '-' },
  { title: '勝率', key: 'win_rate', width: 70, render: (r: any) => fmtPct(r.win_rate) },
  { title: '交易次數', key: 'total_trades', width: 80 },
]
</script>

<template>
  <div>
    <h2 style="margin: 0 0 16px">自選股總覽</h2>

    <NSpace style="margin-bottom: 16px">
      <NButton @click="wl.loadOverview()" :loading="wl.isLoading" type="primary">重新載入</NButton>
      <NButton @click="wl.runBatchBacktest()" :loading="wl.isLoading">批次回測</NButton>
    </NSpace>

    <NSpin :show="wl.isLoading">
      <NCard title="即時總覽" size="small" style="margin-bottom: 16px">
        <table style="width: 100%; font-size: 13px; border-collapse: collapse">
          <thead>
            <tr style="border-bottom: 2px solid #e2e8f0; text-align: left">
              <th style="padding: 6px">代碼</th>
              <th style="padding: 6px">名稱</th>
              <th style="padding: 6px; text-align: right">收盤價</th>
              <th style="padding: 6px; text-align: right">漲跌%</th>
              <th style="padding: 6px; text-align: right">成交量(張)</th>
              <th style="padding: 6px; text-align: center">訊號</th>
              <th style="padding: 6px; text-align: right">RSI</th>
              <th style="padding: 6px">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="s in wl.overview" :key="s.code" style="border-bottom: 1px solid #f0f0f0; cursor: pointer" @click="selectStock(s.code)">
              <td style="padding: 6px; font-weight: 600">{{ s.code }}</td>
              <td style="padding: 6px">{{ s.name }}</td>
              <td style="padding: 6px; text-align: right">{{ s.price?.toFixed(2) || '-' }}</td>
              <td style="padding: 6px; text-align: right; font-weight: 600" :style="{ color: priceColor(s.change_pct) }">{{ fmtPct(s.change_pct) }}</td>
              <td style="padding: 6px; text-align: right">{{ fmtNum(s.volume_lots, 0) }}</td>
              <td style="padding: 6px; text-align: center">
                <NTag :type="s.signal === 'BUY' ? 'error' : s.signal === 'SELL' ? 'success' : 'default'" size="small">{{ s.signal || '-' }}</NTag>
              </td>
              <td style="padding: 6px; text-align: right">{{ s.rsi?.toFixed(1) || '-' }}</td>
              <td style="padding: 6px">
                <NButton size="tiny" quaternary type="error" @click.stop="wl.remove(s.code)">移除</NButton>
              </td>
            </tr>
          </tbody>
        </table>
      </NCard>

      <NCard v-if="wl.batchResults.length" title="批次回測結果" size="small">
        <NDataTable :columns="btColumns" :data="wl.batchResults" size="small" :max-height="400" />
      </NCard>
    </NSpin>
  </div>
</template>
