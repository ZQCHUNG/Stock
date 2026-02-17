import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  clusterApi,
  type SimilarResult,
  type DimensionInfo,
  type FeatureStatus,
} from '../api/cluster'

export const useClusterStore = defineStore('cluster', () => {
  // --- State ---
  const selectedDimensions = ref<string[]>(['technical', 'institutional'])
  const window = ref(20)
  const topK = ref(30)
  const excludeSelf = ref(true)
  const minDate = ref<string | null>('2020-01-01')
  const regimeMatch = ref(true)

  const result = ref<SimilarResult | null>(null)
  const dimensions = ref<DimensionInfo[]>([])
  const featureStatus = ref<FeatureStatus | null>(null)
  const isLoading = ref(false)
  const error = ref('')

  // --- Actions ---

  async function loadDimensions() {
    try {
      const res = await clusterApi.dimensions()
      dimensions.value = res.dimensions
    } catch (e) {
      console.error('Failed to load dimensions:', e)
    }
  }

  async function loadFeatureStatus() {
    try {
      featureStatus.value = await clusterApi.featureStatus()
    } catch (e) {
      console.error('Failed to load feature status:', e)
    }
  }

  async function loadSimilar(stockCode: string) {
    if (!stockCode || selectedDimensions.value.length === 0) return

    isLoading.value = true
    error.value = ''
    result.value = null

    try {
      result.value = await clusterApi.similar({
        stock_code: stockCode,
        dimensions: selectedDimensions.value,
        window: window.value,
        top_k: topK.value,
        exclude_self: excludeSelf.value,
        min_date: minDate.value,
        regime_match: regimeMatch.value,
      })
    } catch (e: any) {
      error.value = e.message || String(e)
    } finally {
      isLoading.value = false
    }
  }

  return {
    // State
    selectedDimensions,
    window,
    topK,
    excludeSelf,
    minDate,
    regimeMatch,
    result,
    dimensions,
    featureStatus,
    isLoading,
    error,
    // Actions
    loadDimensions,
    loadFeatureStatus,
    loadSimilar,
  }
})
