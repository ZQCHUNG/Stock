import { defineStore } from 'pinia'
import { ref } from 'vue'
import { recommendApi } from '../api/recommend'

export const useRecommendStore = defineStore('recommend', () => {
  const scanResults = ref<any[]>([])
  const isScanning = ref(false)

  async function scan(stockCodes?: string[]) {
    isScanning.value = true
    try {
      scanResults.value = await recommendApi.scanV4(stockCodes)
    } catch { /* ignore */ }
    finally { isScanning.value = false }
  }

  return { scanResults, isScanning, scan }
})
