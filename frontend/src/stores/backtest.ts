import { defineStore } from 'pinia'
import { ref } from 'vue'
import { backtestApi, type BacktestParams } from '../api/backtest'

export const useBacktestStore = defineStore('backtest', () => {
  const singleResult = ref<any>(null)
  const portfolioResult = ref<any>(null)
  const simulationResult = ref<any>(null)
  const rollingResult = ref<any>(null)
  const sensitivityResult = ref<any>(null)
  const alphaBetaResult = ref<any>(null)
  const isLoading = ref(false)
  const error = ref('')

  async function runSingle(code: string, req?: BacktestParams) {
    isLoading.value = true
    error.value = ''
    try {
      singleResult.value = await backtestApi.v4(code, req)
    } catch (e: any) {
      error.value = e.message
    } finally {
      isLoading.value = false
    }
  }

  async function runPortfolio(codes: string[], req?: BacktestParams) {
    isLoading.value = true
    error.value = ''
    try {
      portfolioResult.value = await backtestApi.portfolio(codes, req)
    } catch (e: any) {
      error.value = e.message
    } finally {
      isLoading.value = false
    }
  }

  async function runSimulation(code: string, days = 30, req?: BacktestParams) {
    isLoading.value = true
    error.value = ''
    try {
      simulationResult.value = await backtestApi.simulation(code, days, req)
    } catch (e: any) {
      error.value = e.message
    } finally {
      isLoading.value = false
    }
  }

  async function runRolling(code: string, windowMonths = 6, req?: BacktestParams) {
    isLoading.value = true
    error.value = ''
    try {
      rollingResult.value = await backtestApi.rolling(code, windowMonths, req)
    } catch (e: any) {
      error.value = e.message
    } finally {
      isLoading.value = false
    }
  }

  async function runSensitivity(code: string, req?: BacktestParams) {
    isLoading.value = true
    error.value = ''
    try {
      sensitivityResult.value = await backtestApi.sensitivity(code, req)
    } catch (e: any) {
      error.value = e.message
    } finally {
      isLoading.value = false
    }
  }

  async function runAlphaBeta(code: string, req?: BacktestParams) {
    isLoading.value = true
    error.value = ''
    try {
      alphaBetaResult.value = await backtestApi.alphaBeta(code, req)
    } catch (e: any) {
      error.value = e.message
    } finally {
      isLoading.value = false
    }
  }

  return {
    singleResult, portfolioResult, simulationResult,
    rollingResult, sensitivityResult, alphaBetaResult,
    isLoading, error,
    runSingle, runPortfolio, runSimulation,
    runRolling, runSensitivity, runAlphaBeta,
  }
})
