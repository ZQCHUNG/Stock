import { defineStore } from 'pinia'
import { ref } from 'vue'
import { fetchSSE, type SSEProgress } from '../composables/useSSE'
import { message } from '../utils/discrete'

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
          onError: (msg) => { message.error(`掃描失敗: ${msg}`) },
        },
      )
      if (result) {
        scanResults.value = result
        const buyCount = result.filter((r: any) => r.signal === 'BUY').length
        message.success(`掃描完成：${result.length} 隻，BUY ${buyCount} 隻`)
      }
    } catch (e: any) {
      message.error(`掃描失敗: ${e.message}`)
    } finally {
      isScanning.value = false
      progress.value = { current: 0, total: 0, message: '' }
    }
  }

  return { scanResults, isScanning, progress, scan }
})
