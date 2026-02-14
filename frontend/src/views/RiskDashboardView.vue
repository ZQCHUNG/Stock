<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import {
  NCard, NButton, NSpace, NTag, NGrid, NGi, NSpin,
  NStatistic, NAlert, NEmpty, NDataTable, NDivider, NProgress,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import VChart from 'vue-echarts'
import { riskApi } from '../api/risk'

const isLoading = ref(false)
const data = ref<any>(null)
const error = ref('')

async function loadRisk() {
  isLoading.value = true
  error.value = ''
  try {
    data.value = await riskApi.getSummary()
  } catch (e: any) {
    error.value = e?.message || 'Failed to load risk data'
  }
  isLoading.value = false
}

onMounted(loadRisk)

// Correlation Heatmap
const corrChartOption = computed(() => {
  const corr = data.value?.correlation
  if (!corr) return null

  const codes = corr.codes
  const matrixData: any[] = []
  for (let i = 0; i < codes.length; i++) {
    for (let j = 0; j < codes.length; j++) {
      matrixData.push([j, i, +(corr.matrix[i][j] || 0).toFixed(2)])
    }
  }

  return {
    tooltip: {
      formatter: (p: any) => `${codes[p.value[1]]} / ${codes[p.value[0]]}: ${p.value[2]}`,
    },
    xAxis: { type: 'category', data: codes, axisLabel: { rotate: 45 } },
    yAxis: { type: 'category', data: codes },
    visualMap: {
      min: -1, max: 1, calculable: true,
      inRange: { color: ['#2196f3', '#fff', '#f44336'] },
      orient: 'horizontal', left: 'center', bottom: 0,
    },
    series: [{
      type: 'heatmap',
      data: matrixData,
      label: { show: codes.length <= 8, fontSize: 10 },
    }],
  }
})

// Position Concentration Pie
const concPieOption = computed(() => {
  const positions = data.value?.concentration?.by_position
  if (!positions?.length) return null

  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c}% ({d}%)' },
    series: [{
      type: 'pie',
      radius: ['35%', '65%'],
      data: positions.map((p: any) => ({
        name: `${p.code} ${p.name}`,
        value: p.pct,
      })),
      label: { formatter: '{b}\n{c}%', fontSize: 11 },
    }],
  }
})

// Sector Concentration Bar
const sectorBarOption = computed(() => {
  const sectors = data.value?.concentration?.by_sector?.sectors
  if (!sectors) return null

  const entries = Object.entries(sectors).sort((a: any, b: any) => b[1] - a[1])
  return {
    tooltip: { trigger: 'axis' },
    xAxis: {
      type: 'category',
      data: entries.map(([s]) => s),
      axisLabel: { rotate: 30 },
    },
    yAxis: {
      type: 'value', name: '%',
      axisLabel: { formatter: (v: number) => (v * 100).toFixed(0) + '%' },
    },
    series: [{
      type: 'bar',
      data: entries.map(([, v]) => v),
      itemStyle: {
        color: (p: any) => (p.value as number) >= 0.35 ? '#f44336' : '#42a5f5',
      },
    }],
    markLine: {
      data: [{ yAxis: 0.35, label: { formatter: '35%' } }],
    },
  }
})

// Position table columns
const posColumns: DataTableColumns = [
  { title: '代碼', key: 'code', width: 70 },
  { title: '名稱', key: 'name', width: 90 },
  { title: '市值', key: 'value', width: 100, render: (r: any) => `$${(r.value / 10000).toFixed(1)}萬` },
  { title: '佔比', key: 'pct', width: 70, render: (r: any) => r.pct + '%' },
  { title: 'Beta', key: 'beta', width: 60, render: (r: any) => r.beta?.toFixed(2) || '-' },
]

const corrPairColumns: DataTableColumns = [
  { title: '股票A', key: 'stock_a', width: 80 },
  { title: '股票B', key: 'stock_b', width: 80 },
  {
    title: '相關係數', key: 'correlation', width: 100,
    render: (r: any) => r.correlation?.toFixed(3),
    sorter: (a: any, b: any) => Math.abs(b.correlation) - Math.abs(a.correlation),
  },
]
</script>

<template>
  <div>
    <h2 style="margin: 0 0 16px">風險監控儀表板</h2>

    <NAlert v-if="error" type="error" style="margin-bottom: 12px" closable @close="error = ''">
      {{ error }}
    </NAlert>

    <NSpin :show="isLoading">
      <template v-if="data?.has_data">
        <!-- Risk Alerts -->
        <NAlert v-for="(alert, idx) in (data.alerts || [])" :key="idx"
                type="warning" style="margin-bottom: 8px">
          {{ alert }}
        </NAlert>

        <!-- Summary Cards -->
        <NGrid :cols="5" :x-gap="12" :y-gap="12" style="margin-bottom: 16px">
          <NGi>
            <NCard size="small">
              <NStatistic label="組合市值" :value="'$' + ((data.portfolio?.total_value || 0) / 10000).toFixed(1) + '萬'" />
            </NCard>
          </NGi>
          <NGi>
            <NCard size="small">
              <NStatistic label="持股數" :value="data.portfolio?.stock_count || 0" />
            </NCard>
          </NGi>
          <NGi>
            <NCard size="small">
              <NStatistic label="組合 Beta" :value="data.portfolio?.portfolio_beta?.toFixed(2) || '-'" />
            </NCard>
          </NGi>
          <NGi>
            <NCard size="small">
              <NStatistic label="1日 VaR (95%)">
                <template #default>
                  <span :style="{ color: '#f44336' }">
                    {{ data.var?.var_1d_pct?.toFixed(2) || 0 }}%
                  </span>
                </template>
                <template #suffix>
                  <span style="font-size: 12px; color: #999">
                    (${{ Math.abs(data.var?.var_1d_amount || 0).toLocaleString() }})
                  </span>
                </template>
              </NStatistic>
            </NCard>
          </NGi>
          <NGi>
            <NCard size="small">
              <NStatistic label="5日 VaR (95%)">
                <template #default>
                  <span :style="{ color: '#f44336' }">
                    {{ data.var?.var_5d_pct?.toFixed(2) || 0 }}%
                  </span>
                </template>
                <template #suffix>
                  <span style="font-size: 12px; color: #999">
                    (${{ Math.abs(data.var?.var_5d_amount || 0).toLocaleString() }})
                  </span>
                </template>
              </NStatistic>
            </NCard>
          </NGi>
        </NGrid>

        <NGrid :cols="2" :x-gap="16" :y-gap="16">
          <!-- Position Concentration Pie -->
          <NGi>
            <NCard title="持股集中度" size="small">
              <VChart v-if="concPieOption" :option="concPieOption" style="height: 300px" autoresize />
              <NEmpty v-else description="不足 2 檔持股" />
            </NCard>
          </NGi>

          <!-- Sector Concentration -->
          <NGi>
            <NCard title="產業集中度" size="small">
              <VChart v-if="sectorBarOption" :option="sectorBarOption" style="height: 300px" autoresize />
              <NEmpty v-else description="無產業分類資料" />
            </NCard>
          </NGi>
        </NGrid>

        <!-- Correlation Heatmap -->
        <NCard title="相關性矩陣 (60日報酬)" size="small" style="margin-top: 16px">
          <VChart v-if="corrChartOption" :option="corrChartOption" style="height: 350px" autoresize />
          <NEmpty v-else description="不足 2 檔持股計算相關性" />
        </NCard>

        <NGrid :cols="2" :x-gap="16" :y-gap="16" style="margin-top: 16px">
          <!-- Position Details -->
          <NGi>
            <NCard title="持股明細" size="small">
              <NDataTable
                :columns="posColumns"
                :data="data.concentration?.by_position || []"
                size="small"
                :bordered="false"
                :single-line="false"
              />
            </NCard>
          </NGi>

          <!-- High Correlation Pairs -->
          <NGi>
            <NCard title="高相關性配對" size="small">
              <NDataTable
                v-if="(data.high_corr_pairs || []).length"
                :columns="corrPairColumns"
                :data="data.high_corr_pairs"
                size="small"
                :bordered="false"
                :single-line="false"
              />
              <NEmpty v-else description="無高相關性配對 (>0.6)" />
            </NCard>
          </NGi>
        </NGrid>

        <div style="text-align: right; margin-top: 12px">
          <NButton size="small" @click="loadRisk" :loading="isLoading">重新整理</NButton>
        </div>
      </template>

      <NEmpty v-else-if="!isLoading" :description="data?.message || '無持倉資料。請先在模擬倉位中建立部位。'" />
    </NSpin>
  </div>
</template>
