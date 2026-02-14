import { defineStore } from 'pinia'
import { ref } from 'vue'
import { backtestApi, type BacktestParams } from '../api/backtest'
import { message } from '../utils/discrete'

export const useBacktestStore = defineStore('backtest', () => {
  const singleResult = ref<any>(null)
  const portfolioResult = ref<any>(null)
  const simulationResult = ref<any>(null)
  const rollingResult = ref<any>(null)
  const sensitivityResult = ref<any>(null)
  const alphaBetaResult = ref<any>(null)
  const strategyComparison = ref<any>(null)
  const isLoading = ref(false)
  const error = ref('')

  async function runSingle(code: string, req?: BacktestParams) {
    isLoading.value = true
    error.value = ''
    try {
      singleResult.value = await backtestApi.v4(code, req)
      message.success(`回測完成：${singleResult.value.total_trades || 0} 筆交易`)
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
      message.success(`組合回測完成：${codes.length} 隻股票`)
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
      message.success('模擬交易完成')
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
      message.success('滾動回測完成')
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
      message.success('參數敏感度分析完成')
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
      message.success('Alpha/Beta 分析完成')
    } catch (e: any) {
      error.value = e.message
    } finally {
      isLoading.value = false
    }
  }

  async function runStrategyComparison(code: string, req?: { period_days?: number; initial_capital?: number }) {
    isLoading.value = true
    error.value = ''
    try {
      strategyComparison.value = await backtestApi.strategyComparison(code, req)
      message.success('策略比較完成')
    } catch (e: any) {
      error.value = e.message
    } finally {
      isLoading.value = false
    }
  }

  return {
    singleResult, portfolioResult, simulationResult,
    rollingResult, sensitivityResult, alphaBetaResult, strategyComparison,
    isLoading, error,
    runSingle, runPortfolio, runSimulation,
    runRolling, runSensitivity, runAlphaBeta, runStrategyComparison,
  }
})
