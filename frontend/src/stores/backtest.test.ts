import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useBacktestStore } from './backtest'

// Mock API module
vi.mock('../api/backtest', () => ({
  backtestApi: {
    v4: vi.fn().mockResolvedValue({ total_trades: 15, total_return: 0.25 }),
    portfolio: vi.fn().mockResolvedValue({ total_return: 0.18, stocks: [] }),
    simulation: vi.fn().mockResolvedValue({ total_return: 0.10, daily_records: [] }),
    rolling: vi.fn().mockResolvedValue({ windows: [] }),
    sensitivity: vi.fn().mockResolvedValue({ results: [] }),
    alphaBeta: vi.fn().mockResolvedValue({ alpha: 0.05, beta: 0.8 }),
  },
}))

// Mock discrete message
vi.mock('../utils/discrete', () => ({
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}))

describe('useBacktestStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('has correct initial state', () => {
    const store = useBacktestStore()
    expect(store.singleResult).toBeNull()
    expect(store.portfolioResult).toBeNull()
    expect(store.isLoading).toBe(false)
    expect(store.error).toBe('')
  })

  it('runSingle sets loading and stores result', async () => {
    const store = useBacktestStore()
    const promise = store.runSingle('2330')
    expect(store.isLoading).toBe(true)
    await promise
    expect(store.isLoading).toBe(false)
    expect(store.singleResult).toEqual({ total_trades: 15, total_return: 0.25 })
    expect(store.error).toBe('')
  })

  it('runSingle handles errors', async () => {
    const { backtestApi } = await import('../api/backtest')
    vi.mocked(backtestApi.v4).mockRejectedValueOnce(new Error('Network error'))

    const store = useBacktestStore()
    await store.runSingle('2330')
    expect(store.isLoading).toBe(false)
    expect(store.error).toBe('Network error')
  })

  it('runPortfolio stores result', async () => {
    const store = useBacktestStore()
    await store.runPortfolio(['2330', '2317'])
    expect(store.portfolioResult).toEqual({ total_return: 0.18, stocks: [] })
  })

  it('runSimulation stores result', async () => {
    const store = useBacktestStore()
    await store.runSimulation('2330', 30)
    expect(store.simulationResult).toEqual({ total_return: 0.10, daily_records: [] })
  })

  it('runRolling stores result', async () => {
    const store = useBacktestStore()
    await store.runRolling('2330', 6)
    expect(store.rollingResult).toEqual({ windows: [] })
  })

  it('runAlphaBeta stores result', async () => {
    const store = useBacktestStore()
    await store.runAlphaBeta('2330')
    expect(store.alphaBetaResult).toEqual({ alpha: 0.05, beta: 0.8 })
  })

  it('clears error on new run', async () => {
    const store = useBacktestStore()
    store.error = 'previous error'
    await store.runSingle('2330')
    expect(store.error).toBe('')
  })
})
