<script setup lang="ts">
import { onMounted } from 'vue'
import { NCard, NButton, NGrid, NGi, NSpin, NTag, NSpace } from 'naive-ui'
import { useAppStore } from '../stores/app'
import { useRecommendStore } from '../stores/recommend'
import { useWatchlistStore } from '../stores/watchlist'
import { fmtPct, priceColor } from '../utils/format'
import SignalBadge from '../components/SignalBadge.vue'

const app = useAppStore()
const rec = useRecommendStore()
const wl = useWatchlistStore()

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

    <NSpin :show="rec.isScanning">
      <!-- BUY 訊號 -->
      <NCard v-if="buyResults().length" title="買進訊號" size="small" style="margin-bottom: 16px">
        <NGrid :cols="3" :x-gap="12" :y-gap="12">
          <NGi v-for="r in buyResults()" :key="r.code">
            <NCard size="small" hoverable style="cursor: pointer" @click="selectStock(r.code)">
              <div style="display: flex; justify-content: space-between; align-items: center">
                <div>
                  <span style="font-weight: 700; font-size: 16px">{{ r.code }}</span>
                  <span style="margin-left: 8px; color: #718096">{{ r.name }}</span>
                </div>
                <SignalBadge :signal="r.signal" size="small" />
              </div>
              <div style="margin-top: 8px; display: flex; gap: 16px; font-size: 13px">
                <span>{{ r.price?.toFixed(2) }}</span>
                <span :style="{ color: priceColor(r.price_change) }">{{ fmtPct(r.price_change) }}</span>
                <span style="color: #718096">{{ r.entry_type }}</span>
              </div>
              <div style="margin-top: 4px; font-size: 12px; color: #a0aec0">
                趨勢 {{ r.uptrend_days }}天 | ADX {{ r.indicators?.ADX?.toFixed(1) || '-' }} | RSI {{ r.indicators?.RSI?.toFixed(1) || '-' }}
              </div>
              <NButton size="tiny" quaternary style="margin-top: 4px" @click.stop="addToWatchlist(r.code)">加入自選</NButton>
            </NCard>
          </NGi>
        </NGrid>
      </NCard>

      <!-- HOLD -->
      <NCard v-if="holdResults().length" title="觀望" size="small" style="margin-bottom: 16px">
        <table style="width: 100%; font-size: 12px; border-collapse: collapse">
          <thead>
            <tr style="border-bottom: 1px solid #e2e8f0">
              <th style="text-align: left; padding: 4px">代碼</th>
              <th style="text-align: left; padding: 4px">名稱</th>
              <th style="text-align: right; padding: 4px">價格</th>
              <th style="text-align: right; padding: 4px">漲跌%</th>
              <th style="text-align: right; padding: 4px">趨勢天數</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in holdResults()" :key="r.code" style="border-bottom: 1px solid #f0f0f0; cursor: pointer" @click="selectStock(r.code)">
              <td style="padding: 4px; font-weight: 600">{{ r.code }}</td>
              <td style="padding: 4px">{{ r.name }}</td>
              <td style="padding: 4px; text-align: right">{{ r.price?.toFixed(2) }}</td>
              <td style="padding: 4px; text-align: right" :style="{ color: priceColor(r.price_change) }">{{ fmtPct(r.price_change) }}</td>
              <td style="padding: 4px; text-align: right">{{ r.uptrend_days }}</td>
            </tr>
          </tbody>
        </table>
      </NCard>

      <!-- SELL -->
      <NCard v-if="sellResults().length" title="賣出訊號" size="small">
        <table style="width: 100%; font-size: 12px; border-collapse: collapse">
          <thead>
            <tr style="border-bottom: 1px solid #e2e8f0">
              <th style="text-align: left; padding: 4px">代碼</th>
              <th style="text-align: left; padding: 4px">名稱</th>
              <th style="text-align: right; padding: 4px">價格</th>
              <th style="text-align: right; padding: 4px">漲跌%</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in sellResults()" :key="r.code" style="border-bottom: 1px solid #f0f0f0">
              <td style="padding: 4px; font-weight: 600">{{ r.code }}</td>
              <td style="padding: 4px">{{ r.name }}</td>
              <td style="padding: 4px; text-align: right">{{ r.price?.toFixed(2) }}</td>
              <td style="padding: 4px; text-align: right" :style="{ color: priceColor(r.price_change) }">{{ fmtPct(r.price_change) }}</td>
            </tr>
          </tbody>
        </table>
      </NCard>
    </NSpin>
  </div>
</template>
