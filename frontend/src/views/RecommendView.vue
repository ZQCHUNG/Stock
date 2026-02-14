<script setup lang="ts">
import { h, onMounted } from 'vue'
import { NCard, NButton, NGrid, NGi, NSpin, NTag, NSpace, NDataTable, NEmpty } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { useAppStore } from '../stores/app'
import { useRecommendStore } from '../stores/recommend'
import { useWatchlistStore } from '../stores/watchlist'
import { fmtPct, priceColor } from '../utils/format'
import { useResponsive } from '../composables/useResponsive'
import SignalBadge from '../components/SignalBadge.vue'
import ProgressBar from '../components/ProgressBar.vue'

const app = useAppStore()
const rec = useRecommendStore()
const wl = useWatchlistStore()

const { cols } = useResponsive()
const cardCols = cols(1, 2, 3)

onMounted(() => rec.scan())

function selectStock(code: string) {
  app.selectStock(code)
}

function addToWatchlist(code: string) {
  wl.add(code)
}

const buyResults = () => rec.scanResults.filter((r) => r.signal === 'BUY')
const holdResults = () => rec.scanResults.filter((r) => r.signal === 'HOLD')
const sellResults = () => rec.scanResults.filter((r) => r.signal === 'SELL')

const holdColumns: DataTableColumns = [
  { title: '代碼', key: 'code', width: 70, sorter: 'default',
    render: (r: any) => h('span', { style: { fontWeight: 600, cursor: 'pointer' }, onClick: () => selectStock(r.code) }, r.code) },
  { title: '名稱', key: 'name', width: 80,
    render: (r: any) => h('span', { style: { cursor: 'pointer' }, onClick: () => selectStock(r.code) }, r.name) },
  { title: '價格', key: 'price', width: 80, sorter: (a: any, b: any) => (a.price || 0) - (b.price || 0),
    render: (r: any) => r.price?.toFixed(2) || '-' },
  { title: '漲跌%', key: 'price_change', width: 80, sorter: (a: any, b: any) => (a.price_change || 0) - (b.price_change || 0),
    render: (r: any) => h('span', { style: { color: priceColor(r.price_change), fontWeight: 600 } }, fmtPct(r.price_change)) },
  { title: '趨勢天數', key: 'uptrend_days', width: 80, sorter: (a: any, b: any) => (a.uptrend_days || 0) - (b.uptrend_days || 0) },
  { title: 'ADX', key: 'adx', width: 60,
    render: (r: any) => r.indicators?.ADX?.toFixed(1) || '-' },
  { title: 'RSI', key: 'rsi', width: 60,
    render: (r: any) => r.indicators?.RSI?.toFixed(1) || '-' },
]

const sellColumns: DataTableColumns = [
  { title: '代碼', key: 'code', width: 70, sorter: 'default',
    render: (r: any) => h('span', { style: { fontWeight: 600 } }, r.code) },
  { title: '名稱', key: 'name', width: 80 },
  { title: '價格', key: 'price', width: 80,
    render: (r: any) => r.price?.toFixed(2) || '-' },
  { title: '漲跌%', key: 'price_change', width: 80, sorter: (a: any, b: any) => (a.price_change || 0) - (b.price_change || 0),
    render: (r: any) => h('span', { style: { color: priceColor(r.price_change), fontWeight: 600 } }, fmtPct(r.price_change)) },
]
</script>

<template>
  <div>
    <h2 style="margin: 0 0 16px">推薦股票 (V4 掃描)</h2>

    <NSpace style="margin-bottom: 16px">
      <NButton type="primary" @click="rec.scan()" :loading="rec.isScanning">重新掃描</NButton>
      <NTag v-if="rec.scanResults.length" size="small">
        共 {{ rec.scanResults.length }} 隻 | BUY {{ buyResults().length }}
      </NTag>
    </NSpace>

    <ProgressBar
      v-if="rec.isScanning"
      :current="rec.progress.current"
      :total="rec.progress.total"
      :message="rec.progress.message"
    />

    <NSpin :show="rec.isScanning && rec.progress.total === 0">
      <!-- BUY 訊號 -->
      <NCard v-if="buyResults().length" title="買進訊號" size="small" style="margin-bottom: 16px">
        <NGrid :cols="cardCols" :x-gap="12" :y-gap="12">
          <NGi v-for="r in buyResults()" :key="r.code">
            <NCard size="small" hoverable style="cursor: pointer" @click="selectStock(r.code)">
              <div style="display: flex; justify-content: space-between; align-items: center">
                <div>
                  <span style="font-weight: 700; font-size: 16px">{{ r.code }}</span>
                  <span style="margin-left: 8px; color: var(--text-muted)">{{ r.name }}</span>
                </div>
                <SignalBadge :signal="r.signal" size="small" />
              </div>
              <div style="margin-top: 8px; display: flex; gap: 16px; font-size: 13px">
                <span>{{ r.price?.toFixed(2) }}</span>
                <span :style="{ color: priceColor(r.price_change) }">{{ fmtPct(r.price_change) }}</span>
                <span style="color: var(--text-muted)">{{ r.entry_type }}</span>
              </div>
              <div style="margin-top: 4px; font-size: 12px; color: var(--text-dimmed)">
                趨勢 {{ r.uptrend_days }}天 | ADX {{ r.indicators?.ADX?.toFixed(1) || '-' }} | RSI {{ r.indicators?.RSI?.toFixed(1) || '-' }}
              </div>
              <NButton size="tiny" quaternary style="margin-top: 4px" @click.stop="addToWatchlist(r.code)">加入自選</NButton>
            </NCard>
          </NGi>
        </NGrid>
      </NCard>

      <!-- HOLD -->
      <NCard v-if="holdResults().length" :title="`觀望 (${holdResults().length})`" size="small" style="margin-bottom: 16px">
        <NDataTable
          :columns="holdColumns"
          :data="holdResults()"
          :pagination="{ pageSize: 15, showSizePicker: true, pageSizes: [10, 15, 30] }"
          :row-props="(r: any) => ({ style: { cursor: 'pointer' }, onClick: () => selectStock(r.code) })"
          size="small"
          :bordered="false"
          :single-line="false"
          :scroll-x="510"
        />
      </NCard>

      <!-- SELL -->
      <NCard v-if="sellResults().length" :title="`賣出訊號 (${sellResults().length})`" size="small">
        <NDataTable
          :columns="sellColumns"
          :data="sellResults()"
          size="small"
          :bordered="false"
          :single-line="false"
          :scroll-x="310"
        />
      </NCard>

      <NEmpty v-if="!rec.isScanning && rec.scanResults.length === 0" description="無掃描結果，點擊「重新掃描」開始" style="margin: 40px 0" />
    </NSpin>
  </div>
</template>
