<script setup lang="ts">
import { onMounted } from 'vue'
import { NLayout, NLayoutSider, NLayoutContent } from 'naive-ui'
import { useAppStore } from './stores/app'
import AppSidebar from './components/AppSidebar.vue'

const app = useAppStore()

onMounted(async () => {
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
</style>
