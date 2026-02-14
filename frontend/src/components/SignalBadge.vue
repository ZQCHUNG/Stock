<script setup lang="ts">
import { NTag } from 'naive-ui'
import { signalText } from '../utils/format'

defineProps<{ signal: string; size?: 'small' | 'medium' | 'large' }>()
</script>

<template>
  <NTag
    :type="signal === 'BUY' ? 'error' : signal === 'SELL' ? 'success' : 'default'"
    :size="size || 'medium'"
    round
  >
    {{ signalText(signal) }}
  </NTag>
</template>
