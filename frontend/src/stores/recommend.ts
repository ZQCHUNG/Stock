import { defineStore } from 'pinia'
import { ref } from 'vue'
import { fetchSSE, type SSEProgress } from '../composables/useSSE'

export const useRecommendStore = defineStore('recommend', () => {
  const scanResults = ref<any[]>([])
  const isScanning = ref(false)
  const progress = ref<SSEProgress>({ current: 0, total: 0, message: '' })

  async function scan(stockCodes?: string[]) {
    isScanning.value = true
    progress.value = { current: 0, total: 0, message: '' }
    try {
      const result = await fetchSSE<any[]>(
        '/api/recommend/scan-v4-stream',
        { stock_codes: stockCodes || null },
        {
          onProgress: (p) => { progress.value = p },
          onDone: (r) => { scanResults.value = r },
        },
      )
      if (result) scanResults.value = result
    } catch { /* ignore */ }
    finally {
      isScanning.value = false
      progress.value = { current: 0, total: 0, message: '' }
    }
  }

  return { scanResults, isScanning, progress, scan }
})
