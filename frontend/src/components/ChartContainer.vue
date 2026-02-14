<script setup lang="ts">
import { computed } from 'vue'
import { NSkeleton, NEmpty } from 'naive-ui'
import VChart from 'vue-echarts'

const props = withDefaults(defineProps<{
  option: Record<string, any>
  height?: string
  loading?: boolean
  group?: string
  ariaLabel?: string
}>(), {
  height: '350px',
  loading: false,
  ariaLabel: '圖表',
})

const hasData = computed(() => {
  const o = props.option
  return o && Object.keys(o).length > 0
})
</script>

<template>
  <div class="chart-container" :style="{ height }" role="img" :aria-label="ariaLabel">
    <NSkeleton v-if="loading" :height="height" :sharp="false" text />
    <div v-else-if="!hasData" class="chart-empty">
      <NEmpty description="暫無數據" />
    </div>
    <VChart v-else :option="option" :group="group" autoresize style="width: 100%; height: 100%" />
  </div>
</template>

<style scoped>
.chart-container {
  position: relative;
  width: 100%;
}
.chart-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
}
</style>
