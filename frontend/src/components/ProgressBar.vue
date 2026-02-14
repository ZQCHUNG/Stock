<script setup lang="ts">
import { computed } from 'vue'
import { NProgress, NText } from 'naive-ui'

const props = defineProps<{
  current: number
  total: number
  message?: string
}>()

const percentage = computed(() =>
  props.total > 0 ? Math.round((props.current / props.total) * 100) : 0,
)
</script>

<template>
  <div v-if="total > 0" style="margin-bottom: 12px">
    <NProgress type="line" :percentage="percentage" :show-indicator="true" />
    <NText v-if="message" depth="3" style="font-size: 12px; margin-top: 4px; display: block">
      {{ message }} ({{ current }}/{{ total }})
    </NText>
  </div>
</template>
