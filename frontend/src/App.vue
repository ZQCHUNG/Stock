<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { NLayout, NLayoutSider, NLayoutContent, NConfigProvider, NMessageProvider, NDialogProvider, NNotificationProvider } from 'naive-ui'
import { useAppStore } from './stores/app'
import { useThemeStore } from './stores/theme'
import { useResponsive } from './composables/useResponsive'
import { useKeyboardShortcuts } from './composables/useKeyboardShortcuts'
import AppSidebar from './components/AppSidebar.vue'

const app = useAppStore()
const theme = useThemeStore()
const { isMobile } = useResponsive()
const collapsed = ref(false)
useKeyboardShortcuts()

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
  <NConfigProvider :theme="theme.naiveTheme">
    <NMessageProvider>
    <NDialogProvider>
    <NNotificationProvider>
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
      <NLayoutContent content-style="padding: 16px 24px; overflow-y: auto;" role="main">
        <router-view v-slot="{ Component }">
          <Transition name="page" mode="out-in">
            <component :is="Component" />
          </Transition>
        </router-view>
      </NLayoutContent>
    </NLayout>
    </NNotificationProvider>
    </NDialogProvider>
    </NMessageProvider>
  </NConfigProvider>
</template>

<style>
:root {
  --card-bg: #fff;
  --card-border: #e2e8f0;
  --text-muted: #718096;
  --text-dimmed: #a0aec0;
  --border-light: #f0f0f0;
}
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  transition: background-color 0.3s, color 0.3s;
}
body.dark {
  --card-bg: #2c2c32;
  --card-border: #3a3a42;
  --text-muted: #a0a0b0;
  --text-dimmed: #78788a;
  --border-light: #3a3a42;
  background-color: #18181c;
  color: #e0e0e0;
}
@media (max-width: 768px) {
  .n-layout-content { padding: 8px 10px !important; }
  .n-card { margin-bottom: 8px; }
  .n-data-table { font-size: 12px; }
  .n-statistic .n-statistic-value { font-size: 18px !important; }
  h2 { font-size: 18px; }
}
.page-enter-active,
.page-leave-active {
  transition: opacity 0.15s ease;
}
.page-enter-from,
.page-leave-to {
  opacity: 0;
}
</style>
