import client from './client'

export interface ScreenerFilters {
  min_price?: number
  max_price?: number
  min_change_pct?: number
  max_change_pct?: number
  min_volume?: number
  min_rsi?: number
  max_rsi?: number
  min_adx?: number
  ma20_above_ma60?: boolean
  min_uptrend_days?: number
  signal_filter?: string
  min_pe?: number
  max_pe?: number
  min_dividend_yield?: number
  min_roe?: number
  market_filter?: string
  stock_codes?: string[]
}

export const screenerApi = {
  run: (filters: ScreenerFilters) => client.post<any, any[]>('/screener/run', filters),
}
