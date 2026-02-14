<script setup lang="ts">
import { h, ref, onMounted, reactive } from 'vue'
import { NButton, NDataTable, NEmpty, NSpace, NTag } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { btResultsApi, type SavedBtResult } from '../api/btResults'
import { fmtPct, fmtNum, priceColor } from '../utils/format'
import { message } from '../utils/discrete'
import { useAppStore } from '../stores/app'

const app = useAppStore()
const results = ref<SavedBtResult[]>([])
const isLoading = ref(false)
const pagination = reactive({ page: 1, pageSize: 15, showSizePicker: true, pageSizes: [10, 15, 30] })

async function load() {
  isLoading.value = true
  try {
    results.value = await btResultsApi.list()
  } catch { /* handled */ }
  isLoading.value = false
}

async function remove(index: number) {
  try {
    await btResultsApi.remove(index)
    message.success('已刪除')
    await load()
  } catch { /* handled */ }
}

onMounted(load)

const columns: DataTableColumns = [
  { title: '名稱', key: 'name', width: 120, sorter: 'default' },
  { title: '股票', key: 'stockCode', width: 80,
    render: (r: any) => h('span', { style: { fontWeight: 600, cursor: 'pointer' }, onClick: () => app.selectStock(r.stockCode) },
      `${r.stockCode}`) },
  { title: '總報酬', key: 'total_return', width: 90,
    sorter: (a: any, b: any) => (a.metrics?.total_return || 0) - (b.metrics?.total_return || 0),
    render: (r: any) => h('span', { style: { color: priceColor(r.metrics?.total_return), fontWeight: 600 } }, fmtPct(r.metrics?.total_return)) },
  { title: '年化報酬', key: 'annual_return', width: 90,
    sorter: (a: any, b: any) => (a.metrics?.annual_return || 0) - (b.metrics?.annual_return || 0),
    render: (r: any) => h('span', { style: { color: priceColor(r.metrics?.annual_return) } }, fmtPct(r.metrics?.annual_return)) },
  { title: '最大回撤', key: 'max_drawdown', width: 90,
    render: (r: any) => h('span', { style: { color: '#e53e3e' } }, fmtPct(r.metrics?.max_drawdown)) },
  { title: 'Sharpe', key: 'sharpe_ratio', width: 80,
    sorter: (a: any, b: any) => (a.metrics?.sharpe_ratio || 0) - (b.metrics?.sharpe_ratio || 0),
    render: (r: any) => r.metrics?.sharpe_ratio?.toFixed(2) || '-' },
  { title: '勝率', key: 'win_rate', width: 70,
    render: (r: any) => fmtPct(r.metrics?.win_rate) },
  { title: '交易次數', key: 'total_trades', width: 80,
    render: (r: any) => r.metrics?.total_trades ?? '-' },
  { title: '日期', key: 'savedAt', width: 100,
    render: (r: any) => r.savedAt?.slice(0, 10) },
  { title: '操作', key: 'actions', width: 70,
    render: (_r: any, index: number) =>
      h(NButton, { size: 'tiny', quaternary: true, type: 'error', onClick: () => remove(index) }, () => '刪除') },
]
</script>

<template>
  <div>
    <NSpace style="margin-bottom: 12px">
      <NButton size="small" @click="load" :loading="isLoading">重新載入</NButton>
      <NTag v-if="results.length" size="small">共 {{ results.length }} 筆</NTag>
    </NSpace>

    <NEmpty v-if="!results.length && !isLoading" description="尚無保存的回測結果" style="margin: 40px 0" />

    <NDataTable
      v-if="results.length"
      :columns="columns"
      :data="results"
      :pagination="pagination"
      size="small"
      :bordered="false"
      :single-line="false"
      :scroll-x="870"
    />
  </div>
</template>
