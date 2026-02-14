import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useAppStore } from './app'

// Mock API modules
vi.mock('../api/stocks', () => ({
  stocksApi: {
    list: vi.fn().mockResolvedValue([
      { code: '2330', name: '台積電' },
      { code: '2317', name: '鴻海' },
    ]),
  },
}))

vi.mock('../api/system', () => ({
  systemApi: {
    recentStocks: vi.fn().mockResolvedValue([
      { code: '2330', name: '台積電' },
    ]),
    addRecentStock: vi.fn().mockResolvedValue({ ok: true }),
    v4Params: vi.fn().mockResolvedValue({ adx_threshold: 18 }),
  },
}))

vi.mock('../api/analysis', () => ({
  analysisApi: {
    marketRegime: vi.fn().mockResolvedValue({ regime: 'bull' }),
  },
}))

describe('useAppStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('has correct initial state', () => {
    const store = useAppStore()
    expect(store.currentStockCode).toBe('2330')
    expect(store.currentStockName).toBe('台積電')
    expect(store.allStocks).toEqual([])
    expect(store.recentStocks).toEqual([])
    expect(store.isLoadingStocks).toBe(false)
  })

  it('loadAllStocks fetches and caches stocks', async () => {
    const store = useAppStore()
    await store.loadAllStocks()
    expect(store.allStocks).toHaveLength(2)
    expect(store.allStocks[0]?.code).toBe('2330')
  })

  it('loadAllStocks only fetches once', async () => {
    const store = useAppStore()
    await store.loadAllStocks()
    const count = store.allStocks.length
    await store.loadAllStocks() // second call should not re-fetch
    expect(store.allStocks.length).toBe(count)
  })

  it('getStockName returns name from stockMap', async () => {
    const store = useAppStore()
    await store.loadAllStocks()
    expect(store.getStockName('2330')).toBe('台積電')
    expect(store.getStockName('9999')).toBe('9999') // not found → returns code
  })

  it('selectStock updates state and recent list', async () => {
    const store = useAppStore()
    await store.loadAllStocks()
    await store.selectStock('2317')
    expect(store.currentStockCode).toBe('2317')
    expect(store.recentStocks[0]?.code).toBe('2317')
  })

  it('selectStock deduplicates recent stocks', async () => {
    const store = useAppStore()
    store.recentStocks = [{ code: '2330', name: '台積電' }]
    await store.selectStock('2330')
    // Should not have duplicates
    const codes = store.recentStocks.map((s) => s.code)
    expect(codes.filter((c) => c === '2330')).toHaveLength(1)
  })

  it('loadMarketRegime updates regime', async () => {
    const store = useAppStore()
    await store.loadMarketRegime()
    expect(store.marketRegime).toEqual({ regime: 'bull' })
  })

  it('loadV4Params updates params', async () => {
    const store = useAppStore()
    await store.loadV4Params()
    expect(store.v4Params).toEqual({ adx_threshold: 18 })
  })
})
