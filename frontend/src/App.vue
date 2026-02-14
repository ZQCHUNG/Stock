<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { NLayout, NLayoutSider, NLayoutContent } from 'naive-ui'
import { useAppStore } from './stores/app'
import { useResponsive } from './composables/useResponsive'
import AppSidebar from './components/AppSidebar.vue'

const app = useAppStore()
const { isMobile } = useResponsive()
const collapsed = ref(false)

// Auto-collapse sidebar on mobile
watch(isMobile, (mobile) => { if (mobile) collapsed.value = true })

onMounted(async () => {
  collapsed.value = isMobile.value
  await Promise.all([
    app.loadAllStocks(),
    app.loadRecentStocks(),
    app.loadV4Params(),
    app.loadMarketRegime(),
  ])
})
</script>

<template>
  <NLayout has-sider style="height: 100vh">
    <NLayoutSider
      bordered
      :width="280"
      :collapsed-width="0"
      v-model:collapsed="collapsed"
      show-trigger="bar"
      collapse-mode="width"
      content-style="padding: 12px;"
    >
      <AppSidebar />
    </NLayoutSider>
    <NLayoutContent content-style="padding: 16px 24px; overflow-y: auto;">
      <router-view />
    </NLayoutContent>
  </NLayout>
</template>

<style>
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}
@media (max-width: 768px) {
  .n-layout-content { padding: 8px 12px !important; }
}
</style>
