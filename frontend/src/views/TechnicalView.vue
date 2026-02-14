<script setup lang="ts">
import { watch, onMounted } from 'vue'
import { NGrid, NGi, NCard, NSpin, NAlert, NDescriptions, NDescriptionsItem, NSpace, NDivider, NText, NCollapse, NCollapseItem } from 'naive-ui'
import { useAppStore } from '../stores/app'
import { useTechnicalStore } from '../stores/technical'
import { fmtPct, fmtNum } from '../utils/format'
import MetricCard from '../components/MetricCard.vue'
import SignalBadge from '../components/SignalBadge.vue'
import CandlestickChart from '../components/CandlestickChart.vue'
import MacdChart from '../components/MacdChart.vue'
import KdChart from '../components/KdChart.vue'

const app = useAppStore()
const tech = useTechnicalStore()

async function loadData() {
  const code = app.currentStockCode
  await tech.loadAll(code)
  await tech.loadV4SignalsFull(code)
}

onMounted(loadData)
watch(() => app.currentStockCode, loadData)
</script>

<template>
  <div>
    <h2 style="margin: 0 0 16px">
      {{ app.currentStockCode }} {{ app.currentStockName }} - 技術分析
    </h2>

    <NSpin :show="tech.isLoading">
      <NAlert v-if="tech.error" type="error" style="margin-bottom: 16px">{{ tech.error }}</NAlert>

      <!-- V4 訊號摘要 -->
      <NGrid v-if="tech.v4Enhanced" :cols="4" :x-gap="12" :y-gap="12" style="margin-bottom: 16px">
        <NGi>
          <MetricCard title="V4 訊號">
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
        <NGrid :cols="5" :x-gap="8">
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
        />
      </NCard>

      <!-- MACD + KD -->
      <NGrid :cols="2" :x-gap="12" style="margin-bottom: 16px">
        <NGi>
          <NCard title="MACD" size="small">
            <MacdChart :data="tech.indicators" />
          </NCard>
        </NGi>
        <NGi>
          <NCard title="KD" size="small">
            <KdChart :data="tech.indicators" />
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
        <NDescriptions :column="3" label-placement="left" size="small">
          <NDescriptionsItem label="當前型態">{{ tech.volumePatterns.current_pattern || '無' }}</NDescriptionsItem>
          <NDescriptionsItem label="量比">{{ tech.volumePatterns.current_vol_ratio?.toFixed(2) || '-' }}</NDescriptionsItem>
          <NDescriptionsItem label="量能趨勢">{{ tech.volumePatterns.volume_trend || '-' }}</NDescriptionsItem>
          <NDescriptionsItem label="近20日爆量">{{ tech.volumePatterns.recent_breakouts || 0 }} 次</NDescriptionsItem>
          <NDescriptionsItem label="近20日縮量">{{ tech.volumePatterns.recent_pullbacks || 0 }} 次</NDescriptionsItem>
          <NDescriptionsItem label="活躍序列">{{ tech.volumePatterns.has_active_sequence ? '是' : '否' }}</NDescriptionsItem>
        </NDescriptions>
      </NCard>

      <!-- 法人籌碼 -->
      <NCard v-if="tech.institutional?.dates?.length" title="三大法人買賣超" size="small" style="margin-bottom: 16px">
        <NCollapse>
          <NCollapseItem title="法人資料表">
            <table style="width: 100%; font-size: 12px; border-collapse: collapse">
              <thead>
                <tr style="border-bottom: 1px solid #e2e8f0">
                  <th style="text-align: left; padding: 4px">日期</th>
                  <th style="text-align: right; padding: 4px">外資</th>
                  <th style="text-align: right; padding: 4px">投信</th>
                  <th style="text-align: right; padding: 4px">自營</th>
                  <th style="text-align: right; padding: 4px">合計</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(date, i) in tech.institutional.dates" :key="date" style="border-bottom: 1px solid #f0f0f0">
                  <td style="padding: 4px">{{ date }}</td>
                  <td style="text-align: right; padding: 4px" :style="{ color: (tech.institutional.columns.foreign_net?.[i] ?? 0) > 0 ? '#e53e3e' : '#38a169' }">
                    {{ fmtNum(tech.institutional.columns.foreign_net?.[i]) }}
                  </td>
                  <td style="text-align: right; padding: 4px" :style="{ color: (tech.institutional.columns.trust_net?.[i] ?? 0) > 0 ? '#e53e3e' : '#38a169' }">
                    {{ fmtNum(tech.institutional.columns.trust_net?.[i]) }}
                  </td>
                  <td style="text-align: right; padding: 4px" :style="{ color: (tech.institutional.columns.dealer_net?.[i] ?? 0) > 0 ? '#e53e3e' : '#38a169' }">
                    {{ fmtNum(tech.institutional.columns.dealer_net?.[i]) }}
                  </td>
                  <td style="text-align: right; padding: 4px; font-weight: 600" :style="{ color: (tech.institutional.columns.total_net?.[i] ?? 0) > 0 ? '#e53e3e' : '#38a169' }">
                    {{ fmtNum(tech.institutional.columns.total_net?.[i]) }}
                  </td>
                </tr>
              </tbody>
            </table>
          </NCollapseItem>
        </NCollapse>
      </NCard>
    </NSpin>
  </div>
</template>
