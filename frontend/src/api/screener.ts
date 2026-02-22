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

export interface BoldScanRequest {
  min_rs?: number
  min_volume_lots?: number
  include_no_signal?: boolean
}

export interface BoldScanResult {
  code: string
  name: string
  sector: string
  price: number
  change_pct: number
  avg_volume_lots: number
  has_signal: boolean
  entry_type: string
  confidence: number
  rs_rating: number | null
  rs_grade: string
  rs_momentum: number | null
  vcp_score: number
  vcp_breakout: boolean
  sqs_score: number | null
  sniper_score: number
}

export interface BoldScanResponse {
  scan_date: string
  total_scanned: number
  results_count: number
  error_count: number
  results: BoldScanResult[]
}

export const screenerApi = {
  run: (filters: ScreenerFilters) => client.post<any, any[]>('/screener/run', filters),
  boldScan: (req?: BoldScanRequest) => client.post<any, BoldScanResponse>('/screener/bold-scan', req || {}),
}
