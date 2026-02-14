<script setup lang="ts">
import { ref } from 'vue'
import { NCard, NButton, NGrid, NGi, NInputNumber, NSwitch, NSelect, NSpin, NTag, NSpace, NText } from 'naive-ui'
import { useAppStore } from '../stores/app'
import { useScreenerStore } from '../stores/screener'
import { useWatchlistStore } from '../stores/watchlist'
import { fmtPct, fmtNum, priceColor } from '../utils/format'

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

function runScreener() {
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
      <NGrid :cols="4" :x-gap="12" :y-gap="8">
        <NGi>
          <NText depth="3" style="font-size: 12px">最低價格</NText>
          <NInputNumber v-model:value="minPrice" size="small" placeholder="不限" clearable style="width: 100%" />
        </NGi>
        <NGi>
          <NText depth="3" style="font-size: 12px">最高價格</NText>
          <NInputNumber v-model:value="maxPrice" size="small" placeholder="不限" clearable style="width: 100%" />
        </NGi>
        <NGi>
          <NText depth="3" style="font-size: 12px">最低成交量(張)</NText>
          <NInputNumber v-model:value="minVolume" size="small" placeholder="500" clearable style="width: 100%" />
        </NGi>
        <NGi>
          <NText depth="3" style="font-size: 12px">最低 ADX</NText>
          <NInputNumber v-model:value="minAdx" size="small" placeholder="18" clearable style="width: 100%" />
        </NGi>
        <NGi>
          <NText depth="3" style="font-size: 12px">RSI 下限</NText>
          <NInputNumber v-model:value="minRsi" size="small" placeholder="不限" clearable style="width: 100%" />
        </NGi>
        <NGi>
          <NText depth="3" style="font-size: 12px">RSI 上限</NText>
          <NInputNumber v-model:value="maxRsi" size="small" placeholder="不限" clearable style="width: 100%" />
        </NGi>
        <NGi>
          <NText depth="3" style="font-size: 12px">訊號</NText>
          <NSelect v-model:value="signalFilter" :options="signalOptions" size="small" />
        </NGi>
        <NGi>
          <NText depth="3" style="font-size: 12px">市場</NText>
          <NSelect v-model:value="marketFilter" :options="marketOptions" size="small" />
        </NGi>
        <NGi>
          <NText depth="3" style="font-size: 12px">MA20 > MA60</NText>
          <NSwitch v-model:value="ma20AboveMa60" />
        </NGi>
        <NGi>
          <NText depth="3" style="font-size: 12px">最低趨勢天數</NText>
          <NInputNumber v-model:value="minUptrendDays" size="small" placeholder="不限" clearable style="width: 100%" />
        </NGi>
      </NGrid>
      <NButton type="primary" style="margin-top: 12px" @click="runScreener" :loading="scr.isLoading">
        開始篩選
      </NButton>
    </NCard>

    <NSpin :show="scr.isLoading">
      <NCard v-if="scr.results.length" :title="`篩選結果 (${scr.results.length} 隻)`" size="small">
        <table style="width: 100%; font-size: 13px; border-collapse: collapse">
          <thead>
            <tr style="border-bottom: 2px solid #e2e8f0; text-align: left">
              <th style="padding: 6px">代碼</th>
              <th style="padding: 6px">名稱</th>
              <th style="padding: 6px">市場</th>
              <th style="padding: 6px; text-align: right">價格</th>
              <th style="padding: 6px; text-align: right">漲跌%</th>
              <th style="padding: 6px; text-align: right">成交量(張)</th>
              <th style="padding: 6px; text-align: center">訊號</th>
              <th style="padding: 6px">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="s in scr.results" :key="s.code" style="border-bottom: 1px solid #f0f0f0; cursor: pointer" @click="app.selectStock(s.code)">
              <td style="padding: 6px; font-weight: 600">{{ s.code }}</td>
              <td style="padding: 6px">{{ s.name }}</td>
              <td style="padding: 6px">{{ s.market }}</td>
              <td style="padding: 6px; text-align: right">{{ s.price?.toFixed(2) }}</td>
              <td style="padding: 6px; text-align: right; font-weight: 600" :style="{ color: priceColor(s.change_pct) }">{{ fmtPct(s.change_pct) }}</td>
              <td style="padding: 6px; text-align: right">{{ fmtNum(s.volume_lots, 0) }}</td>
              <td style="padding: 6px; text-align: center">
                <NTag v-if="s.signal" :type="s.signal === 'BUY' ? 'error' : s.signal === 'SELL' ? 'success' : 'default'" size="small">{{ s.signal }}</NTag>
              </td>
              <td style="padding: 6px">
                <NButton size="tiny" quaternary @click.stop="wl.add(s.code)">加入自選</NButton>
              </td>
            </tr>
          </tbody>
        </table>
      </NCard>
    </NSpin>
  </div>
</template>
