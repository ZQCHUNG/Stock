<script setup lang="ts">
import { computed } from 'vue'
import { priceColor, fmtPct, fmtNum } from '../utils/format'

const props = defineProps<{
  value: number | null | undefined
  format?: 'pct' | 'num' | 'price'
  digits?: number
}>()

const color = computed(() => priceColor(props.value))
const display = computed(() => {
  const v = props.value
  if (v == null) return '-'
  if (props.format === 'pct') return fmtPct(v, props.digits ?? 2)
  if (props.format === 'num') return fmtNum(v, props.digits ?? 0)
  return v.toFixed(props.digits ?? 2)
})
</script>

<template>
  <span :style="{ color, fontWeight: 600 }">{{ display }}</span>
</template>
