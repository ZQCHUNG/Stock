<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import {
  NCard, NButton, NTag, NGrid, NGi, NSpin,
  NStatistic, NAlert, NEmpty, NDataTable,
  NTabs, NTabPane,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import VChart from 'vue-echarts'
import { riskApi } from '../api/risk'
import AlertsView from './AlertsView.vue'
import SqsPerformanceView from './SqsPerformanceView.vue'
import { useResponsive } from '../composables/useResponsive'

const { isMobile, isTablet } = useResponsive()
const isLoading = ref(false)
const data = ref<any>(null)
const error = ref('')
const scenarioData = ref<any>(null)
const scenarioLoading = ref(false)
const varValidation = ref<any>(null)
const varValidLoading = ref(false)
const activeTab = ref('risk')

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

async function loadScenario() {
  scenarioLoading.value = true
  try {
    scenarioData.value = await riskApi.getScenario()
  } catch { scenarioData.value = null }
  scenarioLoading.value = false
}

async function runVarValidation() {
  varValidLoading.value = true
  try {
    varValidation.value = await riskApi.validateVar()
  } catch (e: any) {
    varValidation.value = { error: e?.message || 'Validation failed' }
  }
  varValidLoading.value = false
}

onMounted(() => {
  loadRisk()
  loadScenario()
})

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

    <NTabs v-model:value="activeTab" type="line" style="margin-bottom: 16px">
      <NTabPane name="risk" tab="風險概覽" display-directive="show:lazy">

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
        <NGrid :cols="isMobile ? 2 : isTablet ? 3 : 5" :x-gap="12" :y-gap="12" style="margin-bottom: 16px">
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

        <NGrid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="16">
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

        <NGrid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="16" style="margin-top: 16px">
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

        <!-- Scenario Analysis (R48-1) -->
        <NCard title="情境壓力測試" size="small" style="margin-top: 16px">
          <NSpin :show="scenarioLoading">
            <template v-if="scenarioData?.scenarios?.length">
              <table style="width: 100%; border-collapse: collapse; font-size: 13px">
                <thead>
                  <tr style="border-bottom: 2px solid #e0e0e0; text-align: right">
                    <th style="text-align: left; padding: 6px">情境</th>
                    <th style="padding: 6px">市場衝擊</th>
                    <th style="padding: 6px">波動倍數</th>
                    <th style="padding: 6px">組合損失</th>
                    <th style="padding: 6px">損失佔比</th>
                    <th style="padding: 6px">壓力VaR</th>
                    <th style="padding: 6px">高風險部位</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="s in scenarioData.scenarios" :key="s.name"
                      style="border-bottom: 1px solid #eee; text-align: right">
                    <td style="text-align: left; padding: 6px; font-weight: 600">{{ s.name }}</td>
                    <td style="padding: 6px; color: #f44336">{{ (s.market_shock_pct * 100).toFixed(0) }}%</td>
                    <td style="padding: 6px">{{ s.vol_multiplier }}x</td>
                    <td style="padding: 6px; color: #f44336; font-weight: 600">
                      ${{ Math.abs(s.portfolio_loss).toLocaleString() }}
                    </td>
                    <td style="padding: 6px; color: #f44336">
                      {{ (Math.abs(s.portfolio_loss_pct) * 100).toFixed(2) }}%
                    </td>
                    <td style="padding: 6px">
                      {{ ((s.var_stressed_pct || 0) * 100).toFixed(2) }}%
                    </td>
                    <td style="text-align: left; padding: 6px">
                      <NTag v-for="p in s.positions_at_risk" :key="p.code" size="small" type="error" style="margin-right: 4px">
                        {{ p.code }} {{ (p.loss_pct * 100).toFixed(1) }}%
                      </NTag>
                      <span v-if="!s.positions_at_risk?.length" style="color: #999">—</span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </template>
            <NEmpty v-else description="無持倉可進行壓力測試" />
          </NSpin>
        </NCard>

        <!-- VaR Model Validation (R49-1) -->
        <NCard title="VaR 模型回測驗證" size="small" style="margin-top: 16px">
          <template #header-extra>
            <NButton size="tiny" type="warning" @click="runVarValidation" :loading="varValidLoading">
              執行驗證
            </NButton>
          </template>
          <NSpin :show="varValidLoading">
            <template v-if="varValidation && !varValidation.error">
              <NGrid :cols="isMobile ? 2 : 4" :x-gap="12" :y-gap="8" style="margin-bottom: 12px">
                <NGi>
                  <NStatistic label="測試天數" :value="varValidation.test_days" />
                </NGi>
                <NGi>
                  <NStatistic label="突破次數" :value="varValidation.breach_count" />
                </NGi>
                <NGi>
                  <NStatistic label="預期突破率">
                    <template #default>{{ ((varValidation.expected_breach_rate || 0) * 100).toFixed(1) }}%</template>
                  </NStatistic>
                </NGi>
                <NGi>
                  <NStatistic label="實際突破率">
                    <template #default>
                      <span :style="{ color: (varValidation.breach_ratio || 0) > 1.5 ? '#f44336' : (varValidation.breach_ratio || 0) < 0.5 ? '#ff9800' : '#4caf50' }">
                        {{ ((varValidation.actual_breach_rate || 0) * 100).toFixed(1) }}%
                      </span>
                    </template>
                  </NStatistic>
                </NGi>
              </NGrid>
              <NAlert :type="(varValidation.breach_ratio || 0) <= 1.5 ? 'success' : 'warning'" style="margin-bottom: 8px">
                <strong>{{ varValidation.calibration }}</strong> — {{ varValidation.calibration_action }}
              </NAlert>
              <div v-if="varValidation.parameter_recommendations?.length" style="margin-top: 8px">
                <div style="font-weight: 600; font-size: 13px; margin-bottom: 4px">參數調優建議:</div>
                <div v-for="rec in varValidation.parameter_recommendations" :key="rec.parameter"
                     style="font-size: 12px; margin-bottom: 2px; color: var(--n-text-color-3)">
                  <NTag size="small" :bordered="false">{{ rec.parameter }}</NTag>
                  {{ rec.current }} → {{ rec.suggested }} — {{ rec.reason }}
                </div>
              </div>
            </template>
            <NAlert v-else-if="varValidation?.error" type="error">{{ varValidation.error }}</NAlert>
            <div v-else-if="!varValidLoading" style="padding: 12px; color: #999; font-size: 12px">
              點擊「執行驗證」以回測 VaR 模型校準度（需 1-2 分鐘）
            </div>
          </NSpin>
        </NCard>

        <div style="text-align: right; margin-top: 12px">
          <NButton size="small" @click="loadRisk(); loadScenario()" :loading="isLoading">重新整理</NButton>
        </div>
      </template>

      <NEmpty v-else-if="!isLoading" :description="data?.message || '無持倉資料。請先在模擬倉位中建立部位。'" />
    </NSpin>

      </NTabPane>

      <NTabPane name="alerts" tab="警報監控" display-directive="if">
        <AlertsView />
      </NTabPane>

      <NTabPane name="sqs" tab="SQS 績效" display-directive="if">
        <SqsPerformanceView />
      </NTabPane>
    </NTabs>
  </div>
</template>
