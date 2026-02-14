<script setup lang="ts">
import { h, ref, reactive, onMounted } from 'vue'
import { NCard, NButton, NGrid, NGi, NInputNumber, NSwitch, NSelect, NTag, NText, NDataTable } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { useAppStore } from '../stores/app'
import { useScreenerStore } from '../stores/screener'
import { useWatchlistStore } from '../stores/watchlist'
import { fmtPct, fmtNum, priceColor } from '../utils/format'
import { useResponsive } from '../composables/useResponsive'
import ProgressBar from '../components/ProgressBar.vue'
import ConfigManager from '../components/ConfigManager.vue'
import { parseUrlConfig } from '../utils/urlConfig'

const app = useAppStore()
const scr = useScreenerStore()
const wl = useWatchlistStore()

// Filter refs
const minPrice = ref<number | null>(null)
const maxPrice = ref<number | null>(null)
const minVolume = ref<number | null>(500)
const minRsi = ref<number | null>(null)
const maxRsi = ref<number | null>(null)
const minAdx = ref<number | null>(18)
const ma20AboveMa60 = ref(false)
const minUptrendDays = ref<number | null>(null)
const signalFilter = ref<string | null>(null)
const marketFilter = ref<string | null>(null)

const { cols } = useResponsive()
const filterCols = cols(2, 3, 4)

const signalOptions = [
  { label: '不限', value: '' },
  { label: '只看 BUY', value: 'BUY' },
  { label: '只看 SELL', value: 'SELL' },
]

const marketOptions = [
  { label: '不限', value: '' },
  { label: '上市', value: '上市' },
  { label: '上櫃', value: '上櫃' },
]

const pagination = reactive({ page: 1, pageSize: 20, showSizePicker: true, pageSizes: [10, 20, 50, 100] })

const resultColumns: DataTableColumns = [
  { title: '代碼', key: 'code', width: 70, sorter: 'default',
    render: (r: any) => h('span', { style: { fontWeight: 600, cursor: 'pointer' }, onClick: () => app.selectStock(r.code) }, r.code) },
  { title: '名稱', key: 'name', width: 80,
    render: (r: any) => h('span', { style: { cursor: 'pointer' }, onClick: () => app.selectStock(r.code) }, r.name) },
  { title: '市場', key: 'market', width: 60 },
  { title: '價格', key: 'price', width: 80, sorter: (a: any, b: any) => (a.price || 0) - (b.price || 0),
    render: (r: any) => r.price?.toFixed(2) || '-' },
  { title: '漲跌%', key: 'change_pct', width: 80, sorter: (a: any, b: any) => (a.change_pct || 0) - (b.change_pct || 0),
    render: (r: any) => h('span', { style: { color: priceColor(r.change_pct), fontWeight: 600 } }, fmtPct(r.change_pct)) },
  { title: '成交量(張)', key: 'volume_lots', width: 100, sorter: (a: any, b: any) => (a.volume_lots || 0) - (b.volume_lots || 0),
    render: (r: any) => fmtNum(r.volume_lots, 0) },
  { title: '訊號', key: 'signal', width: 70,
    filterOptions: [{ label: 'BUY', value: 'BUY' }, { label: 'SELL', value: 'SELL' }],
    filter: (value: any, row: any) => row.signal === value,
    render: (r: any) => r.signal ? h(NTag, { type: r.signal === 'BUY' ? 'error' : r.signal === 'SELL' ? 'success' : 'default', size: 'small' }, () => r.signal) : '-' },
  { title: '操作', key: 'actions', width: 80,
    render: (r: any) => h(NButton, { size: 'tiny', quaternary: true, onClick: (e: Event) => { e.stopPropagation(); wl.add(r.code) } }, () => '加入自選') },
]

function getScreenerConfig() {
  return {
    minPrice: minPrice.value,
    maxPrice: maxPrice.value,
    minVolume: minVolume.value,
    minAdx: minAdx.value,
    minRsi: minRsi.value,
    maxRsi: maxRsi.value,
    ma20AboveMa60: ma20AboveMa60.value,
    minUptrendDays: minUptrendDays.value,
    signalFilter: signalFilter.value,
    marketFilter: marketFilter.value,
  }
}

function loadScreenerConfig(config: Record<string, any>) {
  minPrice.value = config.minPrice ?? null
  maxPrice.value = config.maxPrice ?? null
  minVolume.value = config.minVolume ?? null
  minAdx.value = config.minAdx ?? null
  minRsi.value = config.minRsi ?? null
  maxRsi.value = config.maxRsi ?? null
  ma20AboveMa60.value = config.ma20AboveMa60 ?? false
  minUptrendDays.value = config.minUptrendDays ?? null
  signalFilter.value = config.signalFilter ?? null
  marketFilter.value = config.marketFilter ?? null
}

onMounted(() => {
  const urlCfg = parseUrlConfig()
  if (urlCfg?.type === 'screener') {
    loadScreenerConfig(urlCfg.config)
    window.history.replaceState({}, '', window.location.pathname)
  }
})

function runScreener() {
  pagination.page = 1
  scr.run({
    min_price: minPrice.value ?? undefined,
    max_price: maxPrice.value ?? undefined,
    min_volume: minVolume.value ?? undefined,
    min_rsi: minRsi.value ?? undefined,
    max_rsi: maxRsi.value ?? undefined,
    min_adx: minAdx.value ?? undefined,
    ma20_above_ma60: ma20AboveMa60.value || undefined,
    min_uptrend_days: minUptrendDays.value ?? undefined,
    signal_filter: signalFilter.value || undefined,
    market_filter: marketFilter.value || undefined,
  })
}
</script>

<template>
  <div>
    <h2 style="margin: 0 0 16px">條件選股</h2>

    <NCard title="篩選條件" size="small" style="margin-bottom: 16px">
      <NGrid :cols="filterCols" :x-gap="12" :y-gap="8">
        <NGi>
          <NText depth="3" style="font-size: 12px">最低價格</NText>
          <NInputNumber v-model:value="minPrice" :min="0" :max="99999" size="small" placeholder="不限" clearable style="width: 100%" />
        </NGi>
        <NGi>
          <NText depth="3" style="font-size: 12px">最高價格</NText>
          <NInputNumber v-model:value="maxPrice" :min="0" :max="99999" size="small" placeholder="不限" clearable style="width: 100%" />
        </NGi>
        <NGi>
          <NText depth="3" style="font-size: 12px">最低成交量(張)</NText>
          <NInputNumber v-model:value="minVolume" :min="0" :step="100" size="small" placeholder="500" clearable style="width: 100%" />
        </NGi>
        <NGi>
          <NText depth="3" style="font-size: 12px">最低 ADX</NText>
          <NInputNumber v-model:value="minAdx" :min="0" :max="100" size="small" placeholder="18" clearable style="width: 100%" />
        </NGi>
        <NGi>
          <NText depth="3" style="font-size: 12px">RSI 下限</NText>
          <NInputNumber v-model:value="minRsi" :min="0" :max="100" size="small" placeholder="不限" clearable style="width: 100%" />
        </NGi>
        <NGi>
          <NText depth="3" style="font-size: 12px">RSI 上限</NText>
          <NInputNumber v-model:value="maxRsi" :min="0" :max="100" size="small" placeholder="不限" clearable style="width: 100%" />
        </NGi>
        <NGi>
          <NText depth="3" style="font-size: 12px">訊號</NText>
          <NSelect v-model:value="signalFilter" :options="signalOptions" size="small" placeholder="不限" clearable />
        </NGi>
        <NGi>
          <NText depth="3" style="font-size: 12px">市場</NText>
          <NSelect v-model:value="marketFilter" :options="marketOptions" size="small" placeholder="不限" clearable />
        </NGi>
        <NGi>
          <NText depth="3" style="font-size: 12px">MA20 > MA60</NText>
          <NSwitch v-model:value="ma20AboveMa60" />
        </NGi>
        <NGi>
          <NText depth="3" style="font-size: 12px">最低趨勢天數</NText>
          <NInputNumber v-model:value="minUptrendDays" :min="0" :max="999" size="small" placeholder="不限" clearable style="width: 100%" />
        </NGi>
      </NGrid>
      <NSpace align="center" style="margin-top: 12px">
        <NButton type="primary" @click="runScreener" :loading="scr.isLoading">開始篩選</NButton>
        <ConfigManager config-type="screener" :get-current-config="getScreenerConfig" @load="loadScreenerConfig" />
      </NSpace>
    </NCard>

    <ProgressBar
      v-if="scr.isLoading"
      :current="scr.progress.current"
      :total="scr.progress.total"
      :message="scr.progress.message"
    />

    <NCard v-if="scr.results.length" :title="`篩選結果 (${scr.results.length} 隻)`" size="small">
      <NDataTable
        :columns="resultColumns"
        :data="scr.results"
        :pagination="pagination"
        :row-props="(r: any) => ({ style: { cursor: 'pointer' }, onClick: () => app.selectStock(r.code) })"
        size="small"
        :bordered="false"
        :single-line="false"
        :scroll-x="620"
      />
    </NCard>
  </div>
</template>
