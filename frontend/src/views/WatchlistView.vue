<script setup lang="ts">
import { h, onMounted, reactive } from 'vue'
import { NCard, NButton, NDataTable, NSpin, NSpace, NTag } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { useAppStore } from '../stores/app'
import { useWatchlistStore } from '../stores/watchlist'
import { fmtPct, fmtNum, priceColor } from '../utils/format'
import ProgressBar from '../components/ProgressBar.vue'

const app = useAppStore()
const wl = useWatchlistStore()

onMounted(() => {
  wl.load()
  wl.loadOverview()
})

function selectStock(code: string) {
  app.selectStock(code)
}

const overviewPagination = reactive({ page: 1, pageSize: 20, showSizePicker: true, pageSizes: [10, 20, 50] })
const btPagination = reactive({ page: 1, pageSize: 15, showSizePicker: true, pageSizes: [10, 15, 25] })

const overviewColumns: DataTableColumns = [
  { title: '代碼', key: 'code', width: 70, sorter: 'default',
    render: (r: any) => h('span', { style: { fontWeight: 600, cursor: 'pointer' }, onClick: () => selectStock(r.code) }, r.code) },
  { title: '名稱', key: 'name', width: 80,
    render: (r: any) => h('span', { style: { cursor: 'pointer' }, onClick: () => selectStock(r.code) }, r.name) },
  { title: '收盤價', key: 'price', width: 90, sorter: (a: any, b: any) => (a.price || 0) - (b.price || 0),
    render: (r: any) => r.price?.toFixed(2) || '-' },
  { title: '漲跌%', key: 'change_pct', width: 80, sorter: (a: any, b: any) => (a.change_pct || 0) - (b.change_pct || 0),
    render: (r: any) => h('span', { style: { color: priceColor(r.change_pct), fontWeight: 600 } }, fmtPct(r.change_pct)) },
  { title: '成交量(張)', key: 'volume_lots', width: 110, sorter: (a: any, b: any) => (a.volume_lots || 0) - (b.volume_lots || 0),
    render: (r: any) => fmtNum(r.volume_lots, 0) },
  { title: '訊號', key: 'signal', width: 70, filterOptions: [
      { label: 'BUY', value: 'BUY' }, { label: 'SELL', value: 'SELL' }, { label: 'HOLD', value: 'HOLD' },
    ], filter: (value: any, row: any) => row.signal === value,
    render: (r: any) => h(NTag, { type: r.signal === 'BUY' ? 'error' : r.signal === 'SELL' ? 'success' : 'default', size: 'small' }, () => r.signal || '-') },
  { title: '趨勢天數', key: 'uptrend_days', width: 80, sorter: (a: any, b: any) => (a.uptrend_days || 0) - (b.uptrend_days || 0) },
  { title: 'RSI', key: 'rsi', width: 60, sorter: (a: any, b: any) => (a.rsi || 0) - (b.rsi || 0),
    render: (r: any) => r.rsi?.toFixed(1) || '-' },
  { title: 'ADX', key: 'adx', width: 60, sorter: (a: any, b: any) => (a.adx || 0) - (b.adx || 0),
    render: (r: any) => r.adx?.toFixed(1) || '-' },
  { title: '操作', key: 'actions', width: 70,
    render: (r: any) => h(NButton, { size: 'tiny', quaternary: true, type: 'error', onClick: (e: Event) => { e.stopPropagation(); wl.remove(r.code) } }, () => '移除') },
]

const btColumns: DataTableColumns = [
  { title: '代碼', key: 'code', width: 70, sorter: 'default' },
  { title: '名稱', key: 'name', width: 80 },
  { title: '總報酬', key: 'total_return', width: 90, sorter: (a: any, b: any) => (a.total_return || 0) - (b.total_return || 0),
    render: (r: any) => h('span', { style: { color: priceColor(r.total_return), fontWeight: 600 } }, fmtPct(r.total_return)) },
  { title: '年化報酬', key: 'annual_return', width: 90, sorter: (a: any, b: any) => (a.annual_return || 0) - (b.annual_return || 0),
    render: (r: any) => h('span', { style: { color: priceColor(r.annual_return) } }, fmtPct(r.annual_return)) },
  { title: '最大回撤', key: 'max_drawdown', width: 90, sorter: (a: any, b: any) => (a.max_drawdown || 0) - (b.max_drawdown || 0),
    render: (r: any) => h('span', { style: { color: '#e53e3e' } }, fmtPct(r.max_drawdown)) },
  { title: 'Sharpe', key: 'sharpe_ratio', width: 80, sorter: (a: any, b: any) => (a.sharpe_ratio || 0) - (b.sharpe_ratio || 0),
    render: (r: any) => r.sharpe_ratio?.toFixed(2) || '-' },
  { title: '勝率', key: 'win_rate', width: 70, render: (r: any) => fmtPct(r.win_rate) },
  { title: '交易次數', key: 'total_trades', width: 80, sorter: (a: any, b: any) => (a.total_trades || 0) - (b.total_trades || 0) },
]
</script>

<template>
  <div>
    <h2 style="margin: 0 0 16px">自選股總覽</h2>

    <NSpace style="margin-bottom: 16px">
      <NButton @click="wl.loadOverview()" :loading="wl.isLoading" type="primary">重新載入</NButton>
      <NButton @click="wl.runBatchBacktest()" :loading="wl.isLoading">批次回測</NButton>
    </NSpace>

    <ProgressBar
      v-if="wl.batchProgress.total > 0"
      :current="wl.batchProgress.current"
      :total="wl.batchProgress.total"
      :message="wl.batchProgress.message"
    />

    <NSpin :show="wl.isLoading && wl.batchProgress.total === 0">
      <NCard title="即時總覽" size="small" style="margin-bottom: 16px">
        <NDataTable
          :columns="overviewColumns"
          :data="wl.overview"
          :pagination="overviewPagination"
          :row-props="(r: any) => ({ style: { cursor: 'pointer' }, onClick: () => selectStock(r.code) })"
          size="small"
          :bordered="false"
          :single-line="false"
          :scroll-x="760"
        />
      </NCard>

      <NCard v-if="wl.batchResults.length" title="批次回測結果" size="small">
        <NDataTable
          :columns="btColumns"
          :data="wl.batchResults"
          :pagination="btPagination"
          size="small"
          :scroll-x="650"
        />
      </NCard>
    </NSpin>
  </div>
</template>
