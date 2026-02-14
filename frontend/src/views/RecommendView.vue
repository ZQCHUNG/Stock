<script setup lang="ts">
import { h, ref, onMounted, computed } from 'vue'
import { NCard, NButton, NGrid, NGi, NSpin, NTag, NSpace, NDataTable, NEmpty, NTooltip, NProgress, NAlert } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { useRouter } from 'vue-router'
import { useAppStore } from '../stores/app'
import { useRecommendStore } from '../stores/recommend'
import { useWatchlistStore } from '../stores/watchlist'
import { analysisApi } from '../api/analysis'
import { fmtPct, priceColor } from '../utils/format'
import ProgressBar from '../components/ProgressBar.vue'

const app = useAppStore()
const rec = useRecommendStore()
const wl = useWatchlistStore()
const router = useRouter()

// Fitness tags for character-aware recommendations (Gemini R40)
const fitnessMap = ref<Map<string, any>>(new Map())

onMounted(async () => {
  // Load alpha hunter + fitness tags in parallel
  const alphaPromise = rec.loadAlphaHunter()
  try {
    const fitness = await analysisApi.strategyFitness()
    if (fitness?.stocks) {
      const map = new Map<string, any>()
      for (const s of fitness.stocks) {
        map.set(s.code, s)
      }
      fitnessMap.value = map
    }
  } catch { /* fitness data optional */ }

  // After alpha hunter loads, batch-load SQS for all BUY stocks
  await alphaPromise
  const allBuyStocks: any[] = []
  for (const g of (rec.alphaHunter?.sectors || [])) {
    for (const s of (g.stocks || [])) {
      allBuyStocks.push(s)
    }
  }
  if (allBuyStocks.length) loadBatchSqs(allBuyStocks)
})

const watchlistCodes = computed(() => new Set(wl.watchlist.map(s => s.code)))

function analyzeStock(code: string) {
  app.selectStock(code)
  router.push({ name: 'technical' })
}

function addToWatchlist(code: string) {
  wl.add(code)
}

// Visual helpers
function maturityProgress(maturity: string): number {
  if (maturity === 'Structural Shift') return 100
  if (maturity === 'Trend Formation') return 60
  if (maturity === 'Speculative Spike') return 25
  return 0
}

function maturityColor(maturity: string): string {
  if (maturity === 'Structural Shift') return '#18a058'
  if (maturity === 'Trend Formation') return '#f0a020'
  return '#e53e3e'
}

function confidenceColor(c: number): string {
  if (c >= 1.2) return '#18a058'
  if (c >= 1.0) return '#2080f0'
  if (c >= 0.5) return '#f0a020'
  return '#e53e3e'
}

function momentumLabel(m: string): { icon: string; label: string; type: 'error' | 'warning' | 'info' | 'default' } {
  if (m === 'surge') return { icon: '🔥', label: 'Surge', type: 'error' }
  if (m === 'heating') return { icon: '↑', label: 'Heating', type: 'warning' }
  if (m === 'cooling') return { icon: '↓', label: 'Cooling', type: 'info' }
  return { icon: '', label: 'Stable', type: 'default' }
}

// Fitness tag helpers (Gemini R40)
function getFitnessTag(code: string): string {
  return fitnessMap.value.get(code)?.fitness_tag || ''
}

function fitnessTagLabel(tag: string): { label: string; type: 'error' | 'info' | 'success' | 'warning' | 'default' } {
  if (tag.includes('Trend')) return { label: '趨勢性格', type: 'error' }
  if (tag.includes('Volatility')) return { label: '波動性格', type: 'info' }
  if (tag === 'Balanced') return { label: '均衡', type: 'success' }
  if (tag.includes('Only')) return { label: tag.includes('V4') ? '僅趨勢' : '僅回歸', type: 'warning' }
  return { label: '', type: 'default' }
}

function isRegimeMismatch(code: string): string | null {
  const tag = getFitnessTag(code)
  if (!tag || !app.marketRegime) return null
  const regime = app.marketRegime.regime
  if (regime === 'bull' && tag.includes('Volatility')) {
    return '策略不匹配：此股適合盤整操作，目前為多頭環境，建議觀望或縮減部位'
  }
  if (regime === 'bear' && tag.includes('Trend')) {
    return '策略不匹配：此股適合趨勢操作，目前為空頭環境，建議觀望'
  }
  return null
}

// SQS data (Gemini R42)
const sqsMap = ref<Map<string, any>>(new Map())

async function loadBatchSqs(stocks: any[]) {
  if (!stocks.length) return
  try {
    const payload = stocks.map((s: any) => ({
      code: s.code,
      strategy: 'V4',
      maturity: s.maturity || 'N/A',
    }))
    const result = await analysisApi.batchSqs(payload)
    const map = new Map<string, any>()
    for (const [code, sqs] of Object.entries(result)) {
      map.set(code, sqs)
    }
    sqsMap.value = map
  } catch { /* SQS data optional */ }
}

function getSqs(code: string): any { return sqsMap.value.get(code) }
function sqsGradeIcon(grade: string): string {
  if (grade === 'diamond') return '💎'
  if (grade === 'gold') return '🥇'
  if (grade === 'noise') return '⚪'
  return ''
}
function sqsColor(sqs: number): string {
  if (sqs >= 80) return '#18a058'
  if (sqs >= 60) return '#2080f0'
  if (sqs >= 40) return '#f0a020'
  return '#999'
}

// Alpha hunter data
const alphaData = computed(() => rec.alphaHunter)
// Sort high confidence by SQS (Gemini R42: SQS-Ledger replaces R40 regime sort)
const highConfidence = computed(() => {
  const list = [...(alphaData.value?.high_confidence || [])]
  return list.sort((a: any, b: any) => {
    const aSqs = getSqs(a.code)?.sqs ?? 50
    const bSqs = getSqs(b.code)?.sqs ?? 50
    return bSqs - aSqs  // Descending by SQS
  })
})
const sectorGroups = computed(() => alphaData.value?.sectors || [])
const transitions = computed(() => alphaData.value?.transitions || [])
const updatedAt = computed(() => {
  const ts = alphaData.value?.updated_at
  if (!ts) return null
  const dt = new Date(ts)
  return `${String(dt.getHours()).padStart(2, '0')}:${String(dt.getMinutes()).padStart(2, '0')}`
})

// Traditional scan columns (kept for fallback)
const holdColumns: DataTableColumns = [
  { title: '代碼', key: 'code', width: 70, sorter: 'default',
    render: (r: any) => h('span', { style: { fontWeight: 600, cursor: 'pointer' }, onClick: () => analyzeStock(r.code) }, r.code) },
  { title: '名稱', key: 'name', width: 80 },
  { title: '價格', key: 'price', width: 80, render: (r: any) => r.price?.toFixed(2) || '-' },
  { title: '漲跌%', key: 'price_change', width: 80, sorter: (a: any, b: any) => (a.price_change || 0) - (b.price_change || 0),
    render: (r: any) => h('span', { style: { color: priceColor(r.price_change), fontWeight: 600 } }, fmtPct(r.price_change)) },
  { title: '趨勢天數', key: 'uptrend_days', width: 80, sorter: (a: any, b: any) => (a.uptrend_days || 0) - (b.uptrend_days || 0) },
]
</script>

<template>
  <div>
    <h2 style="margin: 0 0 16px">推薦股票 — Alpha Hunter</h2>

    <NSpace style="margin-bottom: 16px" align="center">
      <NButton type="primary" @click="rec.loadAlphaHunter()" :loading="rec.isLoadingAlpha">
        刷新推薦
      </NButton>
      <NButton @click="rec.scan()" :loading="rec.isScanning" type="default">
        完整掃描 (SSE)
      </NButton>
      <NTag v-if="alphaData" size="small">
        {{ alphaData.total_buy || 0 }} BUY / {{ sectorGroups.length }} 板塊
      </NTag>
      <span v-if="updatedAt" style="font-size: 11px; color: #999">{{ updatedAt }} 更新</span>
    </NSpace>

    <ProgressBar
      v-if="rec.isScanning"
      :current="rec.progress.current"
      :total="rec.progress.total"
      :message="rec.progress.message"
    />

    <NSpin :show="rec.isLoadingAlpha">
      <!-- High Confidence Picks -->
      <NCard v-if="highConfidence.length" size="small" style="margin-bottom: 16px">
        <template #header>
          <NSpace align="center" :size="8">
            <span style="font-weight: 700">⭐ 高信心推薦 (SQS 排序)</span>
            <NTag type="error" size="small">{{ highConfidence.length }} 檔</NTag>
          </NSpace>
        </template>
        <NGrid :cols="3" :x-gap="12" :y-gap="12">
          <NGi v-for="stock in highConfidence" :key="stock.code">
            <NCard size="small" hoverable style="cursor: pointer" @click="analyzeStock(stock.code)">
              <div style="display: flex; justify-content: space-between; align-items: center">
                <div>
                  <span style="font-weight: 700; font-size: 16px">{{ stock.code }}</span>
                  <span style="margin-left: 8px; color: #666">{{ stock.name }}</span>
                </div>
                <NSpace :size="4" align="center">
                  <NTag
                    v-if="getSqs(stock.code)"
                    :color="{ textColor: '#fff', color: sqsColor(getSqs(stock.code).sqs), borderColor: sqsColor(getSqs(stock.code).sqs) }"
                    size="small"
                    style="font-weight: 700"
                  >
                    {{ sqsGradeIcon(getSqs(stock.code).grade) }} {{ getSqs(stock.code).sqs }}
                  </NTag>
                  <NTag
                    :color="{ textColor: '#fff', color: confidenceColor(stock.confidence), borderColor: confidenceColor(stock.confidence) }"
                    size="small"
                    style="font-weight: 700"
                  >
                    C={{ stock.confidence.toFixed(2) }}
                  </NTag>
                </NSpace>
              </div>
              <!-- Maturity progress bar -->
              <div style="margin-top: 8px">
                <div style="display: flex; align-items: center; gap: 8px">
                  <NProgress
                    type="line"
                    :percentage="maturityProgress(stock.maturity)"
                    :color="maturityColor(stock.maturity)"
                    :height="8"
                    :show-indicator="false"
                    style="flex: 1"
                  />
                  <NTag :type="stock.maturity === 'Structural Shift' ? 'success' : stock.maturity === 'Trend Formation' ? 'warning' : 'error'" size="small">
                    {{ stock.maturity }}
                  </NTag>
                </div>
              </div>
              <!-- Sector + Leader + Fitness Tag -->
              <div style="margin-top: 6px; display: flex; gap: 6px; flex-wrap: wrap">
                <NTag size="small" :bordered="false" :type="momentumLabel(stock.momentum).type">
                  {{ stock.sector }} {{ momentumLabel(stock.momentum).icon }}
                </NTag>
                <NTag v-if="stock.is_leader" type="warning" size="small" :bordered="false" style="font-weight: 700">
                  ★ Leader ({{ stock.leader_score.toFixed(2) }})
                </NTag>
                <NTag
                  v-if="getFitnessTag(stock.code)"
                  :type="fitnessTagLabel(getFitnessTag(stock.code)).type"
                  size="small"
                  :bordered="false"
                >
                  {{ fitnessTagLabel(getFitnessTag(stock.code)).label }}
                </NTag>
                <NButton
                  v-if="!watchlistCodes.has(stock.code)"
                  size="tiny"
                  quaternary
                  @click.stop="addToWatchlist(stock.code)"
                  style="min-width: auto"
                >+ 自選</NButton>
              </div>
              <!-- SQS Net EV detail -->
              <div v-if="getSqs(stock.code)" style="margin-top: 4px; font-size: 11px; color: #666">
                Net EV:
                <span :style="{ color: (getSqs(stock.code).net_ev ?? 0) >= 0 ? '#18a058' : '#e53e3e', fontWeight: 600 }">
                  {{ ((getSqs(stock.code).net_ev ?? 0) * 100).toFixed(2) }}%
                </span>
                <span v-if="getSqs(stock.code).cost_trap" style="margin-left: 4px; color: #f0a020; font-weight: 600">
                  成本陷阱
                </span>
              </div>
              <!-- Regime mismatch warning -->
              <div v-if="isRegimeMismatch(stock.code)" style="margin-top: 4px; font-size: 11px; color: #e53e3e">
                {{ isRegimeMismatch(stock.code) }}
              </div>
            </NCard>
          </NGi>
        </NGrid>
      </NCard>

      <!-- Maturity Transitions -->
      <NAlert v-if="transitions.length" type="info" style="margin-bottom: 16px">
        <template #header>📊 近期成熟度躍遷</template>
        <NSpace :size="6" style="flex-wrap: wrap">
          <NTooltip v-for="(t, i) in transitions" :key="i" trigger="hover">
            <template #trigger>
              <NTag
                :type="t.is_high_value ? 'error' : 'default'"
                size="small"
                style="cursor: pointer"
                @click="analyzeStock(t.code)"
              >
                <template v-if="t.is_high_value">🔥 </template>
                {{ t.code }} {{ t.name }}
                <span style="font-size: 10px; margin-left: 4px">{{ t.from_maturity?.split(' ')[0] }} → {{ t.to_maturity?.split(' ')[0] }}</span>
              </NTag>
            </template>
            <div>
              <div>{{ t.from_maturity }} → {{ t.to_maturity }}</div>
              <div>板塊: {{ t.sector }} ({{ t.momentum }})</div>
              <div v-if="t.is_leader">Leader Score: {{ (t.leader_score || 0).toFixed(2) }}</div>
            </div>
          </NTooltip>
        </NSpace>
      </NAlert>

      <!-- Sector Groups ("Battle Briefing") -->
      <div v-for="group in sectorGroups" :key="group.sector" style="margin-bottom: 16px">
        <NCard size="small">
          <template #header>
            <NSpace align="center" :size="8">
              <span style="font-weight: 700">{{ group.sector }}</span>
              <NTag :type="momentumLabel(group.momentum).type" size="small">
                {{ momentumLabel(group.momentum).icon }} {{ momentumLabel(group.momentum).label }}
              </NTag>
              <NTag size="small" :bordered="false">{{ group.buy_count }}/{{ group.total }} BUY</NTag>
              <NTooltip v-if="group.is_crowded" trigger="hover">
                <template #trigger>
                  <NTag size="small" :color="{ textColor: '#fff', color: '#9333ea', borderColor: '#9333ea' }">
                    擁擠交易
                  </NTag>
                </template>
                <div>加權熱度 {{ (group.weighted_heat * 100).toFixed(0) }}% > 80%，信心乘數自動衰減</div>
              </NTooltip>
              <NTooltip v-if="group.leader" trigger="hover">
                <template #trigger>
                  <NTag type="warning" size="small" :bordered="false" style="font-weight: 700">
                    ★ {{ group.leader.code }} {{ group.leader.name }}
                  </NTag>
                </template>
                <div>Leader Score: {{ group.leader.score.toFixed(2) }} | {{ group.leader.maturity }}</div>
              </NTooltip>
            </NSpace>
          </template>
          <template #header-extra>
            <NProgress
              type="line"
              :percentage="Math.round(group.weighted_heat * 100)"
              :color="group.weighted_heat >= 0.3 ? '#e53e3e' : group.weighted_heat >= 0.15 ? '#dd6b20' : '#38a169'"
              :height="12"
              :show-indicator="false"
              style="width: 100px"
            />
            <span style="font-size: 11px; color: #888; margin-left: 8px">
              {{ (group.weighted_heat * 100).toFixed(0) }}%
            </span>
          </template>

          <NGrid :cols="3" :x-gap="8" :y-gap="8">
            <NGi v-for="stock in group.stocks" :key="stock.code">
              <div
                style="padding: 8px; border: 1px solid #eee; border-radius: 6px; cursor: pointer; transition: background 0.15s"
                @click="analyzeStock(stock.code)"
                @mouseenter="($event.currentTarget as HTMLElement).style.background = '#f8f8f8'"
                @mouseleave="($event.currentTarget as HTMLElement).style.background = ''"
              >
                <div style="display: flex; justify-content: space-between; align-items: center">
                  <div>
                    <span style="font-weight: 600">{{ stock.code }}</span>
                    <span style="margin-left: 6px; font-size: 12px; color: #666">{{ stock.name }}</span>
                  </div>
                  <NSpace :size="2" align="center">
                    <NTag
                      v-if="getSqs(stock.code)"
                      :color="{ textColor: '#fff', color: sqsColor(getSqs(stock.code).sqs), borderColor: sqsColor(getSqs(stock.code).sqs) }"
                      size="tiny"
                      style="font-weight: 600"
                    >
                      {{ sqsGradeIcon(getSqs(stock.code).grade) }}{{ getSqs(stock.code).sqs }}
                    </NTag>
                    <NTag
                      :color="{ textColor: '#fff', color: confidenceColor(stock.confidence), borderColor: confidenceColor(stock.confidence) }"
                      size="tiny"
                      style="font-weight: 600"
                    >
                      C={{ stock.confidence.toFixed(2) }}
                    </NTag>
                  </NSpace>
                </div>
                <!-- Maturity mini progress -->
                <div style="margin-top: 4px; display: flex; align-items: center; gap: 6px">
                  <NProgress
                    type="line"
                    :percentage="maturityProgress(stock.maturity)"
                    :color="maturityColor(stock.maturity)"
                    :height="6"
                    :show-indicator="false"
                    style="flex: 1"
                  />
                  <span style="font-size: 10px; color: #888; min-width: 60px">{{ stock.maturity }}</span>
                  <NTag v-if="stock.is_leader" type="warning" size="tiny" :bordered="false" style="font-weight: 700; font-size: 10px">★</NTag>
                  <NTag
                    v-if="getFitnessTag(stock.code)"
                    :type="fitnessTagLabel(getFitnessTag(stock.code)).type"
                    size="tiny"
                    :bordered="false"
                    style="font-size: 10px"
                  >{{ fitnessTagLabel(getFitnessTag(stock.code)).label }}</NTag>
                  <NButton
                    v-if="!watchlistCodes.has(stock.code)"
                    size="tiny"
                    quaternary
                    style="padding: 0 2px; min-width: auto"
                    @click.stop="addToWatchlist(stock.code)"
                  >+</NButton>
                </div>
              </div>
            </NGi>
          </NGrid>
        </NCard>
      </div>

      <NEmpty v-if="!rec.isLoadingAlpha && !sectorGroups.length && !rec.scanResults.length"
              description="尚無推薦數據，請先啟動 Worker 或點擊「完整掃描」"
              style="margin: 40px 0" />

      <!-- Traditional scan results (fallback) -->
      <NCard v-if="rec.scanResults.length && !sectorGroups.length" title="V4 掃描結果 (傳統)" size="small" style="margin-top: 16px">
        <NDataTable
          :columns="holdColumns"
          :data="rec.scanResults"
          :pagination="{ pageSize: 20 }"
          size="small"
          :bordered="false"
          :single-line="false"
          :scroll-x="390"
        />
      </NCard>
    </NSpin>
  </div>
</template>
