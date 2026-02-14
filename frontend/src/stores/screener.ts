import { defineStore } from 'pinia'
import { ref } from 'vue'
import { screenerApi, type ScreenerFilters } from '../api/screener'

export const useScreenerStore = defineStore('screener', () => {
  const results = ref<any[]>([])
  const isLoading = ref(false)
  const filterConfig = ref<ScreenerFilters>({})

  async function run(filters?: ScreenerFilters) {
    isLoading.value = true
    const f = filters || filterConfig.value
    try {
      results.value = await screenerApi.run(f)
    } catch { /* ignore */ }
    finally { isLoading.value = false }
  }

  return { results, isLoading, filterConfig, run }
})
