<script setup lang="ts">
import { computed } from 'vue'
import { NSpace, NTag, NText } from 'naive-ui'

const props = defineProps<{
  data: {
    mode: string
    atr_pct: number
    threshold_pct: number
    trail_description: string
  } | null
}>()

const isMomentum = computed(() => props.data?.mode === 'momentum_scalper')

const modeLabel = computed(() =>
  isMomentum.value ? 'Momentum Scalper' : 'Precision Trender'
)

const modeSubtitle = computed(() =>
  isMomentum.value ? 'High Noise Environment' : 'Stable Trend Environment'
)

const badgeColor = computed(() =>
  isMomentum.value ? '#FF4B2B' : '#1A2980'
)
</script>

<template>
  <div v-if="data" class="trail-badge" :style="{ borderColor: badgeColor }">
    <NSpace align="center" :size="12" :wrap="false">
      <div class="badge-icon" :style="{ background: badgeColor }">
        {{ isMomentum ? 'M' : 'P' }}
      </div>
      <div class="badge-info">
        <div class="badge-mode" :style="{ color: badgeColor }">{{ modeLabel }}</div>
        <NText depth="3" style="font-size: 11px">{{ modeSubtitle }}</NText>
      </div>
      <div class="badge-metric">
        <div class="metric-label">ATR%</div>
        <div class="metric-value" :style="{ color: badgeColor }">{{ data.atr_pct.toFixed(1) }}%</div>
      </div>
      <div class="badge-trail">
        <NTag :bordered="false" size="small" :color="{ color: isMomentum ? '#fff5f5' : '#f0f4ff', textColor: badgeColor }">
          {{ data.trail_description }}
        </NTag>
      </div>
    </NSpace>
  </div>
</template>

<style scoped>
.trail-badge {
  border: 2px solid;
  border-radius: 10px;
  padding: 10px 16px;
  margin-bottom: 16px;
  background: var(--card-bg);
}
.badge-icon {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-weight: 800;
  font-size: 18px;
  flex-shrink: 0;
}
.badge-info {
  flex: 1;
  min-width: 0;
}
.badge-mode {
  font-size: 15px;
  font-weight: 700;
  line-height: 1.2;
}
.badge-metric {
  text-align: center;
  flex-shrink: 0;
}
.metric-label {
  font-size: 10px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.metric-value {
  font-size: 18px;
  font-weight: 700;
}
.badge-trail {
  flex-shrink: 0;
}
</style>
