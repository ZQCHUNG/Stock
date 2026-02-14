import { defineStore } from 'pinia'
import { ref } from 'vue'
import { reportApi } from '../api/report'

export const useReportStore = defineStore('report', () => {
  const currentReport = ref<any>(null)
  const isGenerating = ref(false)
  const error = ref('')

  async function generate(code: string, periodDays = 730, marketRegime?: string) {
    isGenerating.value = true
    error.value = ''
    try {
      currentReport.value = await reportApi.generate(code, periodDays, marketRegime)
    } catch (e: any) {
      error.value = e.message
    } finally {
      isGenerating.value = false
    }
  }

  return { currentReport, isGenerating, error, generate }
})
