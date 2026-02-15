<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import {
  NAutoComplete, NMenu, NDivider, NText, NTag, NSpace, NButton, NSwitch,
} from 'naive-ui'
import { useAppStore } from '../stores/app'
import { useCacheStore } from '../stores/cache'
import { useThemeStore } from '../stores/theme'

const router = useRouter()
const route = useRoute()
const app = useAppStore()
const cache = useCacheStore()
const themeStore = useThemeStore()

const searchValue = ref('')

const searchOptions = computed(() => {
  const q = searchValue.value.trim().toLowerCase()
  if (!q) return []
  return app.allStocks
    .filter((s) => s.code.toLowerCase().includes(q) || s.name.toLowerCase().includes(q))
    .slice(0, 15)
    .map((s) => ({ label: `${s.code} ${s.name}`, value: s.code }))
})

function onSearchSelect(code: string) {
  app.selectStock(code)
  searchValue.value = ''
}

const menuItems = [
  { label: '0  Dashboard', key: 'dashboard' },
  { label: '1  技術分析', key: 'technical' },
  { label: '2  自選股總覽', key: 'watchlist' },
  { label: '3  推薦股票', key: 'recommend' },
  { label: '4  分析報告', key: 'report' },
  { label: '5  條件選股', key: 'screener' },
  { label: '6  模擬倉位', key: 'portfolio' },
  { label: '7  風險監控', key: 'risk' },
  { label: '8  策略中心', key: 'strategies' },
]

const activeKey = computed(() => route.name as string)

function onMenuUpdate(key: string) {
  router.push({ name: key })
}
</script>

<template>
  <nav aria-label="側邊欄導航">
    <NAutoComplete
      v-model:value="searchValue"
      :options="searchOptions"
      placeholder="搜尋股票  Ctrl+K"
      :on-select="onSearchSelect"
      clearable
    />

    <div style="margin: 12px 0; text-align: center">
      <NText strong style="font-size: 18px">{{ app.currentStockCode }}</NText>
      <NText depth="3" style="margin-left: 8px">{{ app.currentStockName }}</NText>
    </div>

    <NDivider style="margin: 8px 0" />

    <NMenu
      :value="activeKey"
      :options="menuItems"
      @update:value="onMenuUpdate"
    />

    <NDivider style="margin: 8px 0" />

    <NText depth="3" style="font-size: 12px">最近查看</NText>
    <NSpace vertical size="small" style="margin-top: 4px">
      <NTag
        v-for="s in app.recentStocks.slice(0, 8)"
        :key="s.code"
        size="small"
        style="cursor: pointer"
        @click="app.selectStock(s.code)"
      >
        {{ s.code }} {{ s.name }}
      </NTag>
    </NSpace>

    <NDivider style="margin: 8px 0" />

    <NText depth="3" style="font-size: 12px">大盤環境</NText>
    <div v-if="app.marketRegime" style="margin-top: 4px">
      <NTag
        :type="app.marketRegime.regime === 'bull' ? 'error' : app.marketRegime.regime === 'bear' ? 'success' : 'warning'"
        size="small"
      >
        {{ app.marketRegime.regime === 'bull' ? '多頭' : app.marketRegime.regime === 'bear' ? '空頭' : '盤整' }}
      </NTag>
    </div>

    <NDivider style="margin: 8px 0" />

    <NSpace justify="space-between" align="center">
      <NButton size="tiny" quaternary @click="cache.loadStats()">
        快取 {{ cache.stats?.keys || 0 }} 筆
      </NButton>
      <NSpace align="center" :size="4">
        <NText depth="3" style="font-size: 11px">{{ themeStore.isDark ? '深色' : '淺色' }}</NText>
        <NSwitch :value="themeStore.isDark" @update:value="themeStore.toggle()" size="small" />
      </NSpace>
    </NSpace>
  </nav>
</template>
