import { defineStore } from 'pinia'
import { ref } from 'vue'
import { type ScreenerFilters } from '../api/screener'
import { fetchSSE, type SSEProgress } from '../composables/useSSE'
import { message } from '../utils/discrete'

export const useScreenerStore = defineStore('screener', () => {
  const results = ref<any[]>([])
  const isLoading = ref(false)
  const filterConfig = ref<ScreenerFilters>({})
  const progress = ref<SSEProgress>({ current: 0, total: 0, message: '' })

  async function run(filters?: ScreenerFilters) {
    isLoading.value = true
    progress.value = { current: 0, total: 0, message: '' }
    const f = filters || filterConfig.value
    try {
      const result = await fetchSSE<any[]>(
        '/api/screener/run-stream',
        f,
        {
          onProgress: (p) => { progress.value = p },
          onDone: (r) => { results.value = r },
          onError: (msg) => { message.error(`篩選失敗: ${msg}`) },
        },
      )
      if (result) {
        results.value = result
        message.success(`篩選完成：共 ${result.length} 隻符合條件`)
      }
    } catch (e: any) {
      message.error(`篩選失敗: ${e.message}`)
    } finally {
      isLoading.value = false
      progress.value = { current: 0, total: 0, message: '' }
    }
  }

  return { results, isLoading, filterConfig, progress, run }
})
