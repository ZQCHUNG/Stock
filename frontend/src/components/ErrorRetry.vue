<script setup lang="ts">
import { NResult, NButton } from 'naive-ui'

defineProps<{
  error: string
  description?: string
}>()

const emit = defineEmits<{
  retry: []
}>()
</script>

<template>
  <NResult status="error" :title="error" :description="description" style="padding: 24px 0">
    <template #footer>
      <NButton type="primary" size="small" @click="emit('retry')">重試</NButton>
    </template>
  </NResult>
</template>
