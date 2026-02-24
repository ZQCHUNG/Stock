<script setup lang="ts">
import { NCard } from 'naive-ui'
import PatternSimulator from '../components/PatternSimulator.vue'
import { useAppStore } from '../stores/app'

const app = useAppStore()
</script>

<template>
  <div>
    <h2 style="margin: 0 0 12px">Pattern 模擬</h2>
    <PatternSimulator :stock-code="app.currentStockCode" />
  </div>
</template>
