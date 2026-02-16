<script setup lang="ts">
import { computed } from 'vue'
import { NCard, NGrid, NGi, NTag, NSpace, NText, NTooltip } from 'naive-ui'
import MetricCard from './MetricCard.vue'
import SignalBadge from './SignalBadge.vue'

const props = defineProps<{ data: any; sectorContext?: any; vcpContext?: any }>()

const bold = computed(() => props.data?.bold)
const rs = computed(() => props.data?.rs)
const params = computed(() => props.data?.params)
const sc = computed(() => props.sectorContext)
const vcp = computed(() => props.vcpContext)

const rsGradeColor = computed(() => {
  const g = rs.value?.grade
  if (g === 'Diamond') return '#a855f7'
  if (g === 'Gold') return '#eab308'
  if (g === 'Silver') return '#94a3b8'
  return '#6b7280'
})

const rsGradeIcon = computed(() => {
  const g = rs.value?.grade
  if (g === 'Diamond') return '\u25C6'   // ◆
  if (g === 'Gold') return '\u2605'       // ★
  if (g === 'Silver') return '\u25CF'     // ●
  return '\u25CB'                          // ○
})

const entryTypeLabel = computed(() => {
  const t = bold.value?.entry_type
  if (t === 'squeeze_breakout') return 'Squeeze'
  if (t === 'oversold_bounce') return 'Oversold'
  if (t === 'volume_ramp') return 'Vol Ramp'
  if (t === 'momentum_breakout') return 'Momentum'
  return '--'
})

const rsQualified = computed(() => {
  if (!params.value?.rs_filter_enabled) return true
  const rating = rs.value?.rs_rating
  if (rating == null) return false
  return rating >= (params.value?.rs_min_rating ?? 80)
})

// R64: Peer Alpha badge
const peerAlphaColor = computed(() => {
  const c = sc.value?.peer_alpha?.classification
  if (c === 'Leader') return '#22c55e'
  if (c === 'Laggard') return '#ef4444'
  return '#94a3b8'  // Rider
})

const peerAlphaIcon = computed(() => {
  const c = sc.value?.peer_alpha?.classification
  if (c === 'Leader') return '\u2191'   // ↑
  if (c === 'Laggard') return '\u2193'  // ↓
  return '\u2194'                        // ↔
})

// R64: Cluster Risk styling
const clusterRiskColor = computed(() => {
  const level = sc.value?.cluster_risk?.level
  if (level === 'danger') return '#ef4444'
  if (level === 'caution') return '#f59e0b'
  return '#22c55e'
})

const clusterRiskIcon = computed(() => {
  const level = sc.value?.cluster_risk?.level
  if (level === 'danger') return '\uD83D\uDED1'   // 🛑
  if (level === 'caution') return '\u26A0\uFE0F'   // ⚠️
  if (level === 'unknown') return '\u26AA'          // ⚪
  return '\u2705'                                    // ✅
})

// R85: VCP styling
const vcpColor = computed(() => {
  const score = vcp.value?.vcp_score ?? 0
  if (score >= 70) return '#a855f7'   // Diamond purple — Rocket Launch
  if (score >= 50) return '#22c55e'   // Green — forming
  if (score >= 30) return '#f59e0b'   // Amber — weak
  return '#6b7280'                     // Grey
})

const vcpLabel = computed(() => {
  if (!vcp.value?.has_vcp) return '--'
  const score = vcp.value.vcp_score
  const bases = vcp.value.base_count
  const label = `T${bases} (${score})`
  if (vcp.value.has_coiled_spring) return `${label} \uD83C\uDFAF`  // 🎯 Coiled Spring
  return label
})
</script>

<template>
  <NCard size="small" style="margin-bottom: 16px">
    <template #header>
      <NSpace align="center" :size="8">
        <span style="font-weight: 700">Bold Status Panel</span>
        <NTag size="small" :bordered="false" type="warning">R85</NTag>
        <NTag
          v-if="rs?.grade && rs.grade !== 'unknown'"
          size="small"
          :bordered="false"
          :style="{ color: rsGradeColor, fontWeight: 700 }"
        >
          {{ rsGradeIcon }} RS {{ rs.grade }}
        </NTag>
        <!-- R64: Peer Alpha badge -->
        <NTag
          v-if="sc?.peer_alpha?.peer_alpha != null"
          size="small"
          :bordered="false"
          :style="{ color: peerAlphaColor, fontWeight: 600 }"
        >
          {{ peerAlphaIcon }} {{ sc.peer_alpha.classification }}
          ({{ sc.peer_alpha.peer_alpha.toFixed(2) }})
        </NTag>
        <!-- R64: Cluster Risk -->
        <NTag
          v-if="sc?.cluster_risk && sc.cluster_risk.level !== 'normal'"
          size="small"
          :bordered="false"
          :style="{ color: clusterRiskColor, fontWeight: 600 }"
        >
          {{ clusterRiskIcon }} {{ sc.cluster_risk.label }}
        </NTag>
        <!-- R64: Blind Spot -->
        <NTag
          v-if="sc?.blind_spot"
          size="small"
          :bordered="false"
          :style="{ color: '#9ca3af', fontWeight: 600 }"
        >
          &#x26AA; Sector Blind Spot
        </NTag>
        <!-- R85: VCP badge -->
        <NTag
          v-if="vcp?.has_vcp && vcp.vcp_score >= 70"
          size="small"
          :bordered="false"
          :style="{ color: '#a855f7', fontWeight: 700 }"
        >
          &#x1F680; VCP Rocket
        </NTag>
        <NTag
          v-else-if="vcp?.has_vcp && vcp.vcp_score < 30"
          size="small"
          :bordered="false"
          :style="{ color: '#f59e0b', fontWeight: 600 }"
        >
          &#x26A0;&#xFE0F; Thin Base
        </NTag>
        <NTag
          v-if="bold?.signal === 'BUY'"
          size="small"
          type="error"
          :bordered="false"
        >
          Entry D
        </NTag>
      </NSpace>
    </template>

    <NGrid :cols="6" :x-gap="12" :y-gap="12">
      <!-- RS Rating -->
      <NGi>
        <MetricCard title="RS Rating">
          <template #default>
            <span :style="{ color: rsGradeColor, fontSize: '20px', fontWeight: 700 }">
              {{ rs?.rs_rating != null ? rs.rs_rating.toFixed(1) : '--' }}
            </span>
          </template>
        </MetricCard>
      </NGi>

      <!-- Bold Signal -->
      <NGi>
        <MetricCard title="Bold Signal">
          <template #default>
            <SignalBadge :signal="bold?.signal || 'HOLD'" size="large" />
          </template>
        </MetricCard>
      </NGi>

      <!-- Entry Type -->
      <NGi>
        <MetricCard
          title="Entry Type"
          :value="entryTypeLabel"
        />
      </NGi>

      <!-- Peer Alpha (R64) -->
      <NGi>
        <NTooltip>
          <template #trigger>
            <MetricCard title="Peer Alpha">
              <template #default>
                <span
                  v-if="sc?.peer_alpha?.peer_alpha != null"
                  :style="{ color: peerAlphaColor, fontSize: '18px', fontWeight: 700 }"
                >
                  {{ sc.peer_alpha.peer_alpha.toFixed(2) }}
                </span>
                <span v-else style="color: #6b7280; fontSize: 14px">--</span>
                <div style="font-size: 11px; color: var(--text-muted); margin-top: 2px">
                  {{ sc?.peer_alpha?.classification || 'N/A' }}
                  <span v-if="sc?.peer_alpha?.downgrade" style="color: #ef4444"> (Downgraded)</span>
                </div>
              </template>
            </MetricCard>
          </template>
          <div v-if="sc?.sector_rs">
            Sector: {{ sc.sector_l1 }} ({{ sc.sector_l2 }})
            <br>Sector Median RS: {{ sc.sector_rs.median_rs }}
            <br>Peer Rank: #{{ sc.peer_rank || '--' }}/{{ sc.peer_total || '--' }}
            <br>Sector Diamonds: {{ sc.sector_rs.diamond_count }}/{{ sc.sector_rs.count }}
            ({{ (sc.sector_rs.diamond_pct * 100).toFixed(0) }}%)
          </div>
          <div v-else-if="sc?.blind_spot">
            Sector Blind Spot: No sector mapping for this stock.
            <br>RS rating is market-wide only.
          </div>
          <div v-else>No sector data available</div>
        </NTooltip>
      </NGi>

      <!-- Cluster Risk (R64) -->
      <NGi>
        <NTooltip>
          <template #trigger>
            <MetricCard title="Sector Risk">
              <template #default>
                <span :style="{ color: clusterRiskColor, fontSize: '14px', fontWeight: 600 }">
                  {{ sc?.cluster_risk?.label || '--' }}
                </span>
              </template>
            </MetricCard>
          </template>
          <div v-if="sc?.cluster_risk?.advice">{{ sc.cluster_risk.advice }}</div>
          <div v-else>Sector cluster risk assessment</div>
        </NTooltip>
      </NGi>

      <!-- VCP (R85) -->
      <NGi>
        <NTooltip>
          <template #trigger>
            <MetricCard title="VCP">
              <template #default>
                <span
                  :style="{ color: vcpColor, fontSize: '16px', fontWeight: 700 }"
                >
                  {{ vcpLabel }}
                </span>
                <div v-if="vcp?.has_vcp" style="font-size: 11px; color: var(--text-muted); margin-top: 2px">
                  {{ vcp.ghost_day_count }} ghost{{ vcp.ghost_day_count !== 1 ? 's' : '' }}
                  <span v-if="vcp.is_breakout" style="color: #ef4444; font-weight: 600"> BREAKOUT!</span>
                </div>
                <div v-else-if="vcp?.disqualify_reason" style="font-size: 10px; color: #6b7280; margin-top: 2px">
                  {{ vcp.volume_floor_fail ? 'Low volume' : 'No pattern' }}
                </div>
              </template>
            </MetricCard>
          </template>
          <div v-if="vcp?.has_vcp">
            VCP Score: {{ vcp.vcp_score }}/100
            <br>Bases: {{ vcp.base_count }} ({{ vcp.base_count >= 3 ? 'Gold Standard T3' : 'T2' }})
            <br>Ghost Days: {{ vcp.ghost_day_count }}
            <br>Pivot: {{ vcp.pivot_price ? '$' + vcp.pivot_price.toFixed(1) : '--' }}
            <br v-if="vcp.has_coiled_spring">Coiled Spring: {{ vcp.coiled_spring_days }}d
            <br>Signal: {{ vcp.signal_action_label }}
            <div v-if="vcp.contractions?.length" style="margin-top: 4px; font-size: 11px">
              <div v-for="c in vcp.contractions" :key="c.base">
                T{{ c.base }}: {{ (c.depth * 100).toFixed(1) }}% depth, {{ c.duration }}d
              </div>
            </div>
          </div>
          <div v-else>{{ vcp?.disqualify_reason || 'VCP not detected' }}</div>
        </NTooltip>
      </NGi>
    </NGrid>

    <!-- Bottom summary line -->
    <NText depth="3" style="font-size: 11px; margin-top: 8px; display: block">
      RS Ratio: {{ rs?.rs_ratio ?? '--' }}
      | Vol: {{ bold?.vol_ratio ? bold.vol_ratio.toFixed(1) + 'x' : '--' }}
      | ATR%: {{ bold?.atr_pct ? (bold.atr_pct * 100).toFixed(1) + '%' : '--' }}
      | Squeeze: {{ bold?.squeeze_days_in_10 ?? 0 }}/10d
      <template v-if="params?.rs_filter_enabled">
        | RS Filter:
        <span :style="{ color: rsQualified ? '#22c55e' : '#ef4444', fontWeight: 600 }">
          {{ rsQualified ? 'PASS' : 'FAIL' }}
        </span>
        (min {{ params?.rs_min_rating ?? 80 }})
      </template>
      <template v-if="sc?.sector_l1 && sc.sector_l1 !== '\u672A\u5206\u985E'">
        | Sector: {{ sc.sector_l1 }}
      </template>
      <template v-if="rs?.scan_date">
        | Scan: {{ rs.scan_date }}
      </template>
    </NText>
  </NCard>
</template>
