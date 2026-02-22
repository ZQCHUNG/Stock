<script setup lang="ts">
/**
 * WinnerDnaCard — Phase 6: Decision Assist UI
 *
 * [OFFICIALLY APPROVED — Architect Critic Phase 4-5 Gate]
 * [TRADER R6: Phase 6 UI guidance — Gauge, Traffic Light, Feature Attribution]
 *
 * Design per Wall Street Trader (conversation ea5e43631e2f9350):
 *   - Decision Header: traffic light (Red/Gold/Neutral)
 *   - Final Score gauge (not progress bar)
 *   - Feature Attribution labels
 *   - k-NN neighbors table with forward returns
 *   - Failed Pattern red warning
 *   - Confidence badge (Confident=gold / Speculative=amber)
 */
import { computed } from 'vue'
import { NCard, NGrid, NGi, NTag, NSpace, NText, NProgress, NDataTable } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import MetricCard from './MetricCard.vue'

const props = defineProps<{ data: any }>()

// Status guards
const hasData = computed(() => props.data && props.data.status !== 'no_library' && props.data.status !== 'no_reducer' && props.data.best_cluster_id !== undefined)
const isMatch = computed(() => props.data?.is_match === true)
const isSuper = computed(() => props.data?.is_super_stock_potential === true)
const hasFailed = computed(() => props.data?.failed_pattern_warning === true)
const confidence = computed(() => props.data?.confidence || 'unknown')

// Decision Header — traffic light color
const decisionColor = computed(() => {
  if (hasFailed.value) return '#ef4444'      // Red — Failed Pattern Warning
  if (isSuper.value) return '#f59e0b'         // Gold — Super Stock
  if (isMatch.value) return '#22c55e'         // Green — Match
  return '#6b7280'                             // Neutral gray
})

const decisionLabel = computed(() => {
  if (hasFailed.value) return 'Failed Pattern'
  if (isSuper.value) return 'Super Stock'
  if (isMatch.value) return 'DNA Match'
  return 'No Match'
})

const decisionIcon = computed(() => {
  if (hasFailed.value) return '\u26A0'  // ⚠
  if (isSuper.value) return '\u2B50'    // ⭐
  if (isMatch.value) return '\u2714'    // ✔
  return '\u25CB'                       // ○
})

// Score as percentage (0-100)
const finalScorePct = computed(() => {
  const s = props.data?.final_score
  if (s == null) return 0
  return Math.round(Math.min(s, 1) * 100)
})

const scoreColor = computed(() => {
  const pct = finalScorePct.value
  if (pct >= 80) return '#22c55e'
  if (pct >= 60) return '#f59e0b'
  if (pct >= 40) return '#3b82f6'
  return '#6b7280'
})

// Confidence badge
const confidenceColor = computed(() => {
  if (confidence.value === 'confident') return '#f59e0b'   // Gold
  if (confidence.value === 'speculative') return '#f97316'  // Amber
  return '#94a3b8'
})

const confidenceLabel = computed(() => {
  if (confidence.value === 'confident') return 'Confident'
  if (confidence.value === 'speculative') return 'Speculative'
  return 'Unknown'
})

// Cluster profile — top features (Feature Attribution)
const topFeatures = computed(() => {
  const profile = props.data?.cluster_profile
  if (!profile?.top_features) return []
  return profile.top_features.slice(0, 5)
})

// Cluster label
const clusterLabel = computed(() => {
  const profile = props.data?.cluster_profile
  return profile?.label || `Cluster #${props.data?.best_cluster_id}`
})

// Performance horizons from cluster profile
const horizonPerf = computed(() => {
  const profile = props.data?.cluster_profile
  if (!profile?.recency_performance) {
    return profile?.performance || {}
  }
  return profile.recency_performance
})

// Win rate for display
const winRate = computed(() => {
  const p = horizonPerf.value
  // Find 30-day horizon
  for (const key of ['30', '21', '60']) {
    if (p[key]?.win_rate != null) {
      return { days: key, rate: p[key].win_rate, avg_return: p[key].avg_return }
    }
  }
  return null
})

// k-NN neighbors table
const neighborCols: DataTableColumns = [
  { title: 'Stock', key: 'stock_code', width: 80 },
  { title: 'Date', key: 'date', width: 90 },
  { title: 'Similarity', key: 'similarity', width: 80,
    render: (r: any) => `${(r.similarity * 100).toFixed(0)}%` },
  { title: 'Label', key: 'label', width: 70,
    render: (r: any) => r.is_winner ? 'W' : 'L' },
  { title: '30d Ret', key: 'fwd_30d', width: 80,
    render: (r: any) => r.fwd_30d != null ? `${(r.fwd_30d * 100).toFixed(1)}%` : '-' },
]

const neighborData = computed(() => {
  const nn = props.data?.nearest_neighbors
  if (!nn?.length) return []
  return nn.map((n: any) => ({
    stock_code: n.stock_code || n.code || '?',
    date: n.date || '',
    similarity: n.similarity || 0,
    is_winner: n.is_winner ?? n.label === 'winner',
    fwd_30d: n.forward_returns?.['30'] ?? n.fwd_30d ?? null,
    label: (n.is_winner ?? n.label === 'winner') ? 'W' : 'L',
  }))
})

// Multi-scale DTW
const dtw60 = computed(() => props.data?.dtw_score_60d || 0)
const dtw20 = computed(() => props.data?.dtw_score_20d || 0)
const multiAgree = computed(() => props.data?.multiscale_agreement === true)
</script>

<template>
  <NCard v-if="hasData" size="small" style="margin-bottom: 16px">
    <template #header>
      <NSpace align="center" :size="8">
        <span style="font-weight: 700">Winner DNA</span>
        <!-- Decision Header — Traffic Light -->
        <NTag
          size="small" :bordered="false"
          :color="{ textColor: '#fff', color: decisionColor, borderColor: decisionColor }"
        >
          {{ decisionIcon }} {{ decisionLabel }}
        </NTag>
        <!-- Confidence Badge -->
        <NTag
          size="small" :bordered="false"
          :color="{ textColor: '#fff', color: confidenceColor, borderColor: confidenceColor }"
        >
          {{ confidenceLabel }}
        </NTag>
        <!-- Super Stock -->
        <NTag v-if="isSuper" size="small" type="warning" :bordered="false">
          Super Stock
        </NTag>
      </NSpace>
    </template>

    <!-- Failed Pattern Warning Banner -->
    <div
      v-if="hasFailed"
      style="background: #fef2f2; border: 1px solid #fca5a5; border-radius: 6px; padding: 8px 12px; margin-bottom: 12px; color: #dc2626; font-size: 13px; font-weight: 600"
    >
      {{ '\u26A0' }} Failed Pattern Warning: {{ (data.failed_pattern_ratio * 100).toFixed(0) }}% of nearest neighbors are losers.
      Proceed with extreme caution.
    </div>

    <!-- Score + Match Info -->
    <NGrid :cols="4" :x-gap="12" :y-gap="12">
      <!-- Final Score Gauge -->
      <NGi>
        <div style="text-align: center">
          <div style="font-size: 11px; color: #999; margin-bottom: 4px">Final Score</div>
          <NProgress
            type="circle"
            :percentage="finalScorePct"
            :color="scoreColor"
            :stroke-width="8"
            :show-indicator="true"
            style="width: 80px; margin: 0 auto"
          />
        </div>
      </NGi>
      <!-- Cosine Similarity -->
      <NGi>
        <MetricCard
          title="Cosine Sim"
          :value="((data.cosine_similarity || 0) * 100).toFixed(0) + '%'"
          :color="(data.cosine_similarity || 0) >= 0.85 ? '#22c55e' : '#6b7280'"
        />
      </NGi>
      <!-- Cluster Info -->
      <NGi>
        <MetricCard
          :title="clusterLabel"
          :value="'#' + data.best_cluster_id"
          :subtitle="(data.cluster_profile?.n_samples || 0) + ' samples'"
        />
      </NGi>
      <!-- Win Rate from Cluster -->
      <NGi>
        <MetricCard
          v-if="winRate"
          :title="winRate.days + 'd Win Rate'"
          :value="(winRate.rate * 100).toFixed(0) + '%'"
          :subtitle="'Avg ' + (winRate.avg_return * 100).toFixed(1) + '%'"
          :color="winRate.rate >= 0.55 ? '#22c55e' : winRate.rate < 0.45 ? '#ef4444' : undefined"
        />
        <MetricCard v-else title="Win Rate" value="-" subtitle="No data" />
      </NGi>
    </NGrid>

    <!-- Multi-scale DTW -->
    <div v-if="dtw60 > 0 || dtw20 > 0" style="margin-top: 12px; padding: 8px; background: #f8fafc; border-radius: 6px">
      <NSpace :size="16" align="center">
        <NText style="font-size: 12px; font-weight: 600">DTW Shape Match</NText>
        <NTag size="small" :type="dtw60 < 2 ? 'success' : dtw60 < 5 ? 'warning' : 'error'">
          60d: {{ dtw60.toFixed(2) }}
        </NTag>
        <NTag size="small" :type="dtw20 < 2 ? 'success' : dtw20 < 5 ? 'warning' : 'error'">
          20d: {{ dtw20.toFixed(2) }}
        </NTag>
        <NTag v-if="multiAgree" size="small" type="success" :bordered="false">
          Multi-scale Agree
        </NTag>
      </NSpace>
    </div>

    <!-- Feature Attribution -->
    <div v-if="topFeatures.length" style="margin-top: 12px">
      <NText style="font-size: 12px; font-weight: 600; display: block; margin-bottom: 6px">
        Match Reasons (Top Features)
      </NText>
      <NSpace :size="6" style="flex-wrap: wrap">
        <NTag
          v-for="f in topFeatures" :key="f.feature || f.name"
          size="small" :bordered="true" round
        >
          {{ f.feature || f.name }}: {{ typeof f.z_score === 'number' ? f.z_score.toFixed(1) : f.importance?.toFixed(2) || '?' }}
        </NTag>
      </NSpace>
    </div>

    <!-- k-NN Neighbors Table -->
    <div v-if="neighborData.length" style="margin-top: 12px">
      <NText style="font-size: 12px; font-weight: 600; display: block; margin-bottom: 6px">
        Nearest Neighbors (k={{ neighborData.length }})
      </NText>
      <NDataTable
        :columns="neighborCols"
        :data="neighborData"
        size="small"
        :bordered="false"
        :scroll-x="400"
        :pagination="false"
        :max-height="200"
      />
    </div>

    <!-- Cluster Performance Horizons -->
    <div v-if="Object.keys(horizonPerf).length" style="margin-top: 12px">
      <NText style="font-size: 12px; font-weight: 600; display: block; margin-bottom: 6px">
        Cluster Historical Performance
      </NText>
      <div style="display: flex; gap: 12px; flex-wrap: wrap; font-size: 12px">
        <div
          v-for="(stats, horizon) in horizonPerf" :key="horizon"
          style="background: #f8fafc; padding: 6px 10px; border-radius: 4px; min-width: 80px"
        >
          <div style="color: #999; font-size: 10px">{{ horizon }}d</div>
          <div :style="{ fontWeight: 600, color: (stats as any).avg_return > 0 ? '#22c55e' : '#ef4444' }">
            {{ ((stats as any).avg_return * 100).toFixed(1) }}%
          </div>
          <div style="color: #666">WR {{ ((stats as any).win_rate * 100).toFixed(0) }}%</div>
        </div>
      </div>
    </div>
  </NCard>
</template>
