<script setup lang="ts">
import { NSkeleton } from 'naive-ui'

defineProps<{
  title: string
  value?: string | number
  subtitle?: string
  color?: string
  bgColor?: string
  loading?: boolean
}>()
</script>

<template>
  <div class="metric-card" :style="bgColor ? { background: bgColor, borderColor: bgColor } : undefined">
    <div class="metric-title">{{ title }}</div>
    <template v-if="loading">
      <NSkeleton text style="width: 60%; margin: 4px auto 0" :sharp="false" />
    </template>
    <template v-else>
      <div class="metric-value" :style="{ color: color || 'inherit' }">
        <slot>{{ value }}</slot>
      </div>
      <div v-if="subtitle" class="metric-subtitle">{{ subtitle }}</div>
    </template>
  </div>
</template>

<style scoped>
.metric-card {
  background: var(--card-bg);
  border: 1px solid var(--card-border);
  border-radius: 8px;
  padding: 12px 16px;
  text-align: center;
}
.metric-title { font-size: 12px; color: var(--text-muted); margin-bottom: 4px; }
.metric-value { font-size: 20px; font-weight: 700; }
.metric-subtitle { font-size: 11px; color: var(--text-dimmed); margin-top: 2px; }
</style>
