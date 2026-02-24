<script setup lang="ts">
import { h, ref, reactive, computed, onMounted, watch } from 'vue'
import {
  NCard, NButton, NGrid, NGi, NInputNumber, NSelect,
  NTag, NText, NDataTable, NSpace, NTabs, NTabPane,
  NCollapse, NCollapseItem, NSpin, NStatistic, NAlert,
  NBadge
} from 'naive-ui'
import type { DataTableColumns, DataTableSortState } from 'naive-ui'
import { useAppStore } from '../stores/app'
import { useWatchlistStore } from '../stores/watchlist'
import { screenerApi, type ScreenerV2Filter, type FilterCategory } from '../api/screener'
import { fmtPct, fmtNum, priceColor } from '../utils/format'
import { useResponsive } from '../composables/useResponsive'

const app = useAppStore()
const wl = useWatchlistStore()
const { cols } = useResponsive()

// ─── State ───────────────────────────────────────────────────────

const activeTab = ref('filter')
const isLoading = ref(false)
const results = ref<Record<string, any>[]>([])
const resultCount = ref(0)
const filterDefs = ref<Record<string, FilterCategory>>({})
const dbStats = ref({ stock_count: 0, last_updated: '', status: '' })

// Filter state: { column_key: { min?: number, max?: number } }
const filters = reactive<Record<string, { min: number | null; max: number | null }>>({})

// Sort & pagination
const sortBy = ref('rs_rating')
const sortDesc = ref(true)
const pagination = reactive({ page: 1, pageSize: 50, showSizePicker: true, pageSizes: [20, 50, 100, 200] })

// Rankings state
const rankMetric = ref('dividend_yield')
const rankAscending = ref(false)
const rankResults = ref<Record<string, any>[]>([])
const isRankLoading = ref(false)

// Collapsed filter sections
const expandedSections = ref<string[]>(['valuation', 'growth', 'technical'])

// ─── Metric options for rankings ─────────────────────────────────

const rankMetricOptions = [
  { label: '殖利率 (高→低)', value: 'dividend_yield', asc: false },
  { label: '本益比 (低→高)', value: 'pe', asc: true },
  { label: 'ROE (高→低)', value: 'roe', asc: false },
  { label: '毛利率 (高→低)', value: 'gross_margin', asc: false },
  { label: '營收年增 (高→低)', value: 'revenue_yoy', asc: false },
  { label: 'EPS年增 (高→低)', value: 'eps_yoy', asc: false },
  { label: 'RS強度 (高→低)', value: 'rs_rating', asc: false },
  { label: '漲跌幅 (高→低)', value: 'change_pct', asc: false },
  { label: '負債比 (低→高)', value: 'debt_ratio', asc: true },
  { label: '流動比率 (高→低)', value: 'current_ratio', asc: false },
  { label: '營收連續成長月', value: 'revenue_consecutive_up', asc: false },
]

// ─── Column definitions ──────────────────────────────────────────

function numSorter(key: string) {
  return (a: any, b: any) => (a[key] ?? -Infinity) - (b[key] ?? -Infinity)
}

function fmtVal(v: any, digits = 2): string {
  if (v === null || v === undefined) return '-'
  return typeof v === 'number' ? v.toFixed(digits) : String(v)
}

const resultColumns = computed<DataTableColumns>(() => [
  { title: '代碼', key: 'code', width: 70, sorter: 'default', fixed: 'left',
    render: (r: any) => h('span', { style: { fontWeight: 600, cursor: 'pointer', color: '#18a058' }, onClick: () => app.selectStock(r.code) }, r.code) },
  { title: '名稱', key: 'name', width: 90, ellipsis: true,
    render: (r: any) => h('span', { style: { cursor: 'pointer' }, onClick: () => app.selectStock(r.code) }, r.name) },
  { title: '收盤', key: 'close', width: 75, sorter: numSorter('close'),
    render: (r: any) => fmtVal(r.close) },
  { title: '漲跌%', key: 'change_pct', width: 75, sorter: numSorter('change_pct'),
    render: (r: any) => r.change_pct != null
      ? h('span', { style: { color: priceColor(r.change_pct), fontWeight: 600 } }, fmtPct(r.change_pct))
      : '-' },
  { title: 'RS', key: 'rs_rating', width: 60, sorter: numSorter('rs_rating'),
    render: (r: any) => {
      if (r.rs_rating == null) return '-'
      const v = r.rs_rating
      const type = v >= 80 ? 'error' : v >= 60 ? 'warning' : v >= 40 ? 'info' : 'default'
      return h(NTag, { size: 'small', type, bordered: false }, () => v.toFixed(0))
    }},
  { title: 'PE', key: 'pe', width: 65, sorter: numSorter('pe'),
    render: (r: any) => fmtVal(r.pe, 1) },
  { title: 'PB', key: 'pb', width: 60, sorter: numSorter('pb'),
    render: (r: any) => fmtVal(r.pb, 2) },
  { title: '殖利率%', key: 'dividend_yield', width: 75, sorter: numSorter('dividend_yield'),
    render: (r: any) => fmtVal(r.dividend_yield, 1) },
  { title: '營收YoY%', key: 'revenue_yoy', width: 85, sorter: numSorter('revenue_yoy'),
    render: (r: any) => {
      if (r.revenue_yoy == null) return '-'
      const color = r.revenue_yoy > 0 ? '#d03050' : r.revenue_yoy < 0 ? '#18a058' : undefined
      return h('span', { style: { color, fontWeight: r.revenue_yoy > 20 ? 600 : undefined } }, r.revenue_yoy.toFixed(1))
    }},
  { title: 'RSI', key: 'rsi_14', width: 55, sorter: numSorter('rsi_14'),
    render: (r: any) => fmtVal(r.rsi_14, 0) },
  { title: 'MA20比', key: 'ma20_ratio', width: 75, sorter: numSorter('ma20_ratio'),
    render: (r: any) => r.ma20_ratio != null ? r.ma20_ratio.toFixed(3) : '-' },
  { title: '產業', key: 'industry', width: 80, ellipsis: true },
  { title: '', key: 'actions', width: 70,
    render: (r: any) => h(NButton, { size: 'tiny', quaternary: true, onClick: (e: Event) => { e.stopPropagation(); wl.add(r.code) } }, () => '+ 自選') },
])

// ─── API calls ───────────────────────────────────────────────────

async function loadFilterDefs() {
  try {
    filterDefs.value = await screenerApi.indicatorsV2()
    dbStats.value = await screenerApi.statsV2()
  } catch (e) {
    console.error('Failed to load filter definitions:', e)
  }
}

async function runFilter() {
  isLoading.value = true
  pagination.page = 1
  try {
    const apiFilters: Record<string, any> = {}
    for (const [key, range] of Object.entries(filters)) {
      if (range.min != null || range.max != null) {
        apiFilters[key] = {}
        if (range.min != null) apiFilters[key].min = range.min
        if (range.max != null) apiFilters[key].max = range.max
      }
    }
    const req: ScreenerV2Filter = {
      filters: apiFilters,
      sort_by: sortBy.value,
      sort_desc: sortDesc.value,
      limit: 500,
      offset: 0,
    }
    const resp = await screenerApi.filterV2(req)
    results.value = resp.results
    resultCount.value = resp.count
  } catch (e) {
    console.error('Screener filter failed:', e)
  } finally {
    isLoading.value = false
  }
}

async function loadRankings() {
  isRankLoading.value = true
  try {
    const opt = rankMetricOptions.find(o => o.value === rankMetric.value)
    const asc = opt?.asc ?? rankAscending.value
    const resp = await screenerApi.rankingsV2(rankMetric.value, 100, asc)
    rankResults.value = resp.results
  } catch (e) {
    console.error('Rankings failed:', e)
  } finally {
    isRankLoading.value = false
  }
}

function handleSortChange(state: DataTableSortState) {
  if (state.columnKey && state.order) {
    sortBy.value = state.columnKey as string
    sortDesc.value = state.order === 'descend'
  }
}

function clearFilters() {
  Object.keys(filters).forEach(k => { filters[k] = { min: null, max: null } })
}

function setFilter(key: string, min: number | null, max: number | null) {
  if (!filters[key]) filters[key] = { min: null, max: null }
  filters[key].min = min
  filters[key].max = max
}

// Active filter count per category
function activeCountFor(category: string): number {
  const cat = filterDefs.value[category]
  if (!cat) return 0
  return cat.filters.filter(f => {
    const r = filters[f.key]
    return r && (r.min != null || r.max != null)
  }).length
}

const totalActiveFilters = computed(() => {
  return Object.values(filters).filter(r => r.min != null || r.max != null).length
})

// ─── Quick filter presets ────────────────────────────────────────

const presets = [
  { label: '高殖利率', fn: () => { clearFilters(); setFilter('dividend_yield', 5, null); setFilter('pe', 1, 20) }},
  { label: '高成長+強RS', fn: () => { clearFilters(); setFilter('revenue_yoy', 20, null); setFilter('rs_rating', 70, null) }},
  { label: '低PE高RS', fn: () => { clearFilters(); setFilter('pe', 1, 15); setFilter('rs_rating', 80, null) }},
  { label: 'RSI超賣+RS強', fn: () => { clearFilters(); setFilter('rsi_14', null, 35); setFilter('rs_rating', 60, null) }},
  { label: '價值型', fn: () => { clearFilters(); setFilter('pe', 1, 12); setFilter('dividend_yield', 4, null); setFilter('debt_ratio', null, 50) }},
]

// ─── Lifecycle ───────────────────────────────────────────────────

onMounted(async () => {
  await loadFilterDefs()
  // Initialize filter state for all known filters
  for (const cat of Object.values(filterDefs.value)) {
    for (const f of cat.filters) {
      if (!filters[f.key]) filters[f.key] = { min: null, max: null }
    }
  }
})

watch(rankMetric, () => { if (activeTab.value === 'rankings') loadRankings() })
watch(activeTab, (tab) => { if (tab === 'rankings' && rankResults.value.length === 0) loadRankings() })
</script>

<template>
  <div>
    <h2 style="margin: 0 0 12px; display: flex; align-items: center; gap: 8px">
      條件選股
      <NTag size="small" :bordered="false" type="info">V2</NTag>
      <span style="flex: 1" />
      <NText depth="3" style="font-size: 12px" v-if="dbStats.stock_count">
        {{ dbStats.stock_count }} 支股票 · 更新: {{ dbStats.last_updated?.split('T')[0] || '—' }}
      </NText>
    </h2>

    <NTabs v-model:value="activeTab" type="line" animated>
      <!-- ═══ Filter Tab ═══ -->
      <NTabPane name="filter" tab="篩選條件">
        <!-- Quick presets -->
        <NSpace size="small" style="margin-bottom: 12px">
          <NText depth="3" style="font-size: 12px">快速篩選：</NText>
          <NButton v-for="p in presets" :key="p.label" size="tiny" quaternary @click="() => { p.fn(); runFilter() }">
            {{ p.label }}
          </NButton>
          <NButton size="tiny" quaternary type="warning" @click="clearFilters" v-if="totalActiveFilters > 0">
            清除 ({{ totalActiveFilters }})
          </NButton>
        </NSpace>

        <!-- Filter categories (collapsible) -->
        <NCollapse v-model:expanded-names="expandedSections" style="margin-bottom: 16px">
          <NCollapseItem
            v-for="(cat, catKey) in filterDefs"
            :key="catKey"
            :name="catKey"
          >
            <template #header>
              <NSpace align="center" :size="4">
                {{ cat.label }}
                <NBadge :value="activeCountFor(catKey as string)" :max="9" v-if="activeCountFor(catKey as string) > 0" />
              </NSpace>
            </template>

            <NGrid :cols="cols(2, 3, 4)" :x-gap="12" :y-gap="8">
              <NGi v-for="f in cat.filters" :key="f.key">
                <NText depth="3" style="font-size: 12px; display: block; margin-bottom: 2px">{{ f.label }}</NText>
                <NSpace :size="4" v-if="f.type === 'range'">
                  <NInputNumber
                    :value="filters[f.key]?.min ?? null"
                    @update:value="v => setFilter(f.key, v, filters[f.key]?.max ?? null)"
                    size="small" placeholder="Min" clearable style="width: 100%"
                  />
                  <span style="line-height: 28px; color: #999">~</span>
                  <NInputNumber
                    :value="filters[f.key]?.max ?? null"
                    @update:value="v => setFilter(f.key, filters[f.key]?.min ?? null, v)"
                    size="small" placeholder="Max" clearable style="width: 100%"
                  />
                </NSpace>
                <NInputNumber
                  v-else
                  :value="filters[f.key]?.min ?? null"
                  @update:value="v => setFilter(f.key, v, null)"
                  size="small" placeholder="Min" clearable style="width: 100%"
                />
              </NGi>
            </NGrid>
          </NCollapseItem>
        </NCollapse>

        <!-- Run button -->
        <NSpace align="center" style="margin-bottom: 16px">
          <NButton type="primary" @click="runFilter" :loading="isLoading" size="large">
            篩選 ({{ totalActiveFilters }} 條件)
          </NButton>
        </NSpace>

        <!-- Results -->
        <NSpin :show="isLoading">
          <NCard v-if="results.length > 0" :title="`篩選結果 (${resultCount} 支)`" size="small">
            <NDataTable
              :columns="resultColumns"
              :data="results"
              :pagination="pagination"
              :row-props="(r: any) => ({ style: { cursor: 'pointer' }, onClick: () => app.selectStock(r.code) })"
              size="small"
              :bordered="false"
              :single-line="false"
              :scroll-x="950"
              @update:sorter="handleSortChange"
            />
          </NCard>
          <NAlert v-else-if="!isLoading && resultCount === 0 && totalActiveFilters > 0" type="info" style="margin-top: 8px">
            沒有符合條件的股票，請調整篩選條件
          </NAlert>
        </NSpin>
      </NTabPane>

      <!-- ═══ Rankings Tab ═══ -->
      <NTabPane name="rankings" tab="排行榜">
        <NSpace align="center" style="margin-bottom: 16px">
          <NSelect
            v-model:value="rankMetric"
            :options="rankMetricOptions"
            style="width: 240px"
            size="small"
          />
          <NButton size="small" @click="loadRankings" :loading="isRankLoading">刷新</NButton>
        </NSpace>

        <NSpin :show="isRankLoading">
          <NDataTable
            v-if="rankResults.length > 0"
            :columns="resultColumns"
            :data="rankResults"
            :pagination="{ pageSize: 50, showSizePicker: true, pageSizes: [20, 50, 100] }"
            :row-props="(r: any) => ({ style: { cursor: 'pointer' }, onClick: () => app.selectStock(r.code) })"
            size="small"
            :bordered="false"
            :single-line="false"
            :scroll-x="950"
          />
        </NSpin>
      </NTabPane>
    </NTabs>
  </div>
</template>
