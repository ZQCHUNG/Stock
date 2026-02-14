<script setup lang="ts">
import { h, watch, onMounted, nextTick, computed } from 'vue'
import { connect } from 'echarts/core'
import { NGrid, NGi, NCard, NSpin, NAlert, NDescriptions, NDescriptionsItem, NText, NDataTable } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { useAppStore } from '../stores/app'
import { useTechnicalStore } from '../stores/technical'
import { fmtNum } from '../utils/format'
import { useResponsive } from '../composables/useResponsive'
import MetricCard from '../components/MetricCard.vue'
import SignalBadge from '../components/SignalBadge.vue'
import CandlestickChart from '../components/CandlestickChart.vue'
import MacdChart from '../components/MacdChart.vue'
import KdChart from '../components/KdChart.vue'

const app = useAppStore()
const tech = useTechnicalStore()
const { cols } = useResponsive()
const signalCols = cols(2, 4, 4)
const indicatorCols = cols(3, 5, 5)
const chartCols = cols(1, 2, 2)
const descCols = cols(1, 3, 3)

async function loadData() {
  const code = app.currentStockCode
  await tech.loadAll(code)
  await tech.loadV4SignalsFull(code)
  // Connect charts for crosshair + dataZoom sync after data renders
  nextTick(() => { try { connect('tech') } catch { /* charts not ready */ } })
}

onMounted(loadData)
watch(() => app.currentStockCode, loadData)

// Institutional data → row array for NDataTable
const institutionalData = computed(() => {
  const inst = tech.institutional
  if (!inst?.dates?.length) return []
  return inst.dates.map((date: string, i: number) => ({
    date,
    foreign_net: inst.columns.foreign_net?.[i] ?? 0,
    trust_net: inst.columns.trust_net?.[i] ?? 0,
    dealer_net: inst.columns.dealer_net?.[i] ?? 0,
    total_net: inst.columns.total_net?.[i] ?? 0,
  }))
})

function netColor(v: number) { return v > 0 ? '#e53e3e' : v < 0 ? '#38a169' : undefined }

const institutionalColumns: DataTableColumns = [
  { title: '日期', key: 'date', width: 100 },
  { title: '外資', key: 'foreign_net', width: 90, sorter: (a: any, b: any) => a.foreign_net - b.foreign_net,
    render: (r: any) => h('span', { style: { color: netColor(r.foreign_net) } }, fmtNum(r.foreign_net)) },
  { title: '投信', key: 'trust_net', width: 90, sorter: (a: any, b: any) => a.trust_net - b.trust_net,
    render: (r: any) => h('span', { style: { color: netColor(r.trust_net) } }, fmtNum(r.trust_net)) },
  { title: '自營', key: 'dealer_net', width: 90, sorter: (a: any, b: any) => a.dealer_net - b.dealer_net,
    render: (r: any) => h('span', { style: { color: netColor(r.dealer_net) } }, fmtNum(r.dealer_net)) },
  { title: '合計', key: 'total_net', width: 100, sorter: (a: any, b: any) => a.total_net - b.total_net,
    render: (r: any) => h('span', { style: { color: netColor(r.total_net), fontWeight: 600 } }, fmtNum(r.total_net)) },
]
</script>

<template>
  <div>
    <h2 style="margin: 0 0 16px">
      {{ app.currentStockCode }} {{ app.currentStockName }} - 技術分析
    </h2>

    <NSpin :show="tech.isLoading">
      <NAlert v-if="tech.error" type="error" style="margin-bottom: 16px">{{ tech.error }}</NAlert>

      <!-- V4 訊號摘要 -->
      <NGrid v-if="tech.v4Enhanced" :cols="signalCols" :x-gap="12" :y-gap="12" style="margin-bottom: 16px">
        <NGi>
          <MetricCard
            title="V4 訊號"
            :bg-color="tech.v4Enhanced.signal === 'BUY' ? '#fff5f5' : tech.v4Enhanced.signal === 'SELL' ? '#f0fff4' : undefined"
          >
            <template #default>
              <SignalBadge :signal="tech.v4Enhanced.signal" size="large" />
            </template>
          </MetricCard>
        </NGi>
        <NGi>
          <MetricCard
            title="收盤價"
            :value="tech.v4Enhanced.close?.toFixed(2) || '-'"
          />
        </NGi>
        <NGi>
          <MetricCard
            title="上升趨勢天數"
            :value="tech.v4Enhanced.uptrend_days || 0"
            :subtitle="tech.v4Enhanced.entry_type || '-'"
          />
        </NGi>
        <NGi>
          <MetricCard
            title="信心分數"
            :value="tech.v4Enhanced.confidence_score?.toFixed(1) || '1.0'"
            :color="(tech.v4Enhanced.confidence_score || 1) >= 1.5 ? '#e53e3e' : undefined"
          />
        </NGi>
      </NGrid>

      <!-- V4 指標面板 -->
      <NCard v-if="tech.v4Enhanced?.indicators" size="small" title="V4 指標" style="margin-bottom: 16px">
        <NGrid :cols="indicatorCols" :x-gap="8" :y-gap="8">
          <NGi v-for="(val, key) in tech.v4Enhanced.indicators" :key="key">
            <MetricCard :title="String(key)" :value="val != null ? Number(val).toFixed(1) : '-'" />
          </NGi>
        </NGrid>
      </NCard>

      <!-- K 線圖 -->
      <NCard title="K線圖" size="small" style="margin-bottom: 16px">
        <CandlestickChart
          :data="tech.indicators"
          :supports="tech.supportResistance?.supports"
          :resistances="tech.supportResistance?.resistances"
          :signals="tech.v4SignalsFull"
          group="tech"
        />
      </NCard>

      <!-- MACD + KD -->
      <NGrid :cols="chartCols" :x-gap="12" :y-gap="12" style="margin-bottom: 16px">
        <NGi>
          <NCard title="MACD" size="small">
            <MacdChart :data="tech.indicators" group="tech" />
          </NCard>
        </NGi>
        <NGi>
          <NCard title="KD" size="small">
            <KdChart :data="tech.indicators" group="tech" />
          </NCard>
        </NGi>
      </NGrid>

      <!-- 支撐壓力 -->
      <NCard v-if="tech.supportResistance" title="支撐壓力" size="small" style="margin-bottom: 16px">
        <NGrid :cols="2" :x-gap="16">
          <NGi>
            <NText strong style="color: #38a169">支撐位</NText>
            <div v-for="s in tech.supportResistance.supports?.slice(0, 5)" :key="s.price" style="margin: 4px 0">
              {{ s.price?.toFixed(2) }} ({{ s.source }})
            </div>
          </NGi>
          <NGi>
            <NText strong style="color: #e53e3e">壓力位</NText>
            <div v-for="r in tech.supportResistance.resistances?.slice(0, 5)" :key="r.price" style="margin: 4px 0">
              {{ r.price?.toFixed(2) }} ({{ r.source }})
            </div>
          </NGi>
        </NGrid>
      </NCard>

      <!-- 量能型態 -->
      <NCard v-if="tech.volumePatterns" title="量能型態" size="small" style="margin-bottom: 16px">
        <NDescriptions :column="descCols" label-placement="left" size="small">
          <NDescriptionsItem label="當前型態">{{ tech.volumePatterns.current_pattern || '無' }}</NDescriptionsItem>
          <NDescriptionsItem label="量比">{{ tech.volumePatterns.current_vol_ratio?.toFixed(2) || '-' }}</NDescriptionsItem>
          <NDescriptionsItem label="量能趨勢">{{ tech.volumePatterns.volume_trend || '-' }}</NDescriptionsItem>
          <NDescriptionsItem label="近20日爆量">{{ tech.volumePatterns.recent_breakouts || 0 }} 次</NDescriptionsItem>
          <NDescriptionsItem label="近20日縮量">{{ tech.volumePatterns.recent_pullbacks || 0 }} 次</NDescriptionsItem>
          <NDescriptionsItem label="活躍序列">{{ tech.volumePatterns.has_active_sequence ? '是' : '否' }}</NDescriptionsItem>
        </NDescriptions>
      </NCard>

      <!-- 法人籌碼 -->
      <NCard v-if="institutionalData.length" title="三大法人買賣超" size="small" style="margin-bottom: 16px">
        <NDataTable
          :columns="institutionalColumns"
          :data="institutionalData"
          :pagination="{ pageSize: 10 }"
          size="small"
          :scroll-x="470"
        />
      </NCard>
    </NSpin>
  </div>
</template>
