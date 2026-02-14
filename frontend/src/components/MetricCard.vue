<script setup lang="ts">
defineProps<{
  title: string
  value?: string | number
  subtitle?: string
  color?: string
  bgColor?: string
}>()
</script>

<template>
  <div class="metric-card" :style="bgColor ? { background: bgColor, borderColor: bgColor } : undefined">
    <div class="metric-title">{{ title }}</div>
    <div class="metric-value" :style="{ color: color || 'inherit' }">
      <slot>{{ value }}</slot>
    </div>
    <div v-if="subtitle" class="metric-subtitle">{{ subtitle }}</div>
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
