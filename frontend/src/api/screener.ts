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
  predicted_slippage_pct: number
  liquidity_stress: boolean
}

export interface BoldScanResponse {
  scan_date: string
  total_scanned: number
  results_count: number
  error_count: number
  results: BoldScanResult[]
}

// ─── V2 Snapshot-based Screener (instant queries) ───────────────

export interface ScreenerV2Filter {
  filters: Record<string, { op?: string; value?: number; min?: number; max?: number } | { op: string; value: number }[]>
  sort_by?: string
  sort_desc?: boolean
  limit?: number
  offset?: number
}

export interface ScreenerV2Response {
  count: number
  results: Record<string, any>[]
}

export interface RankingsResponse {
  metric: string
  ascending: boolean
  count: number
  results: Record<string, any>[]
}

export interface FilterCategory {
  label: string
  filters: { key: string; label: string; type: string }[]
}

export interface ScreenerStats {
  stock_count: number
  last_updated: string | null
  status: string
}

export const screenerApi = {
  // V1 Legacy
  run: (filters: ScreenerFilters) => client.post<any, any[]>('/screener/run', filters),
  boldScan: (req?: BoldScanRequest) => client.post<any, BoldScanResponse>('/screener/bold-scan', req || {}),

  // V2 Snapshot-based
  filterV2: (req: ScreenerV2Filter) => client.post<any, ScreenerV2Response>('/screener/v2/filter', req),
  rankingsV2: (metric: string, topN = 50, ascending = false) =>
    client.get<any, RankingsResponse>(`/screener/v2/rankings/${metric}`, { params: { top_n: topN, ascending } }),
  stockSnapshotV2: (code: string) => client.get<any, Record<string, any>>(`/screener/v2/stock/${code}`),
  indicatorsV2: () => client.get<any, Record<string, FilterCategory>>('/screener/v2/indicators'),
  statsV2: () => client.get<any, ScreenerStats>('/screener/v2/stats'),
  refreshV2: () => client.post<any, { status: string; rows: number }>('/screener/v2/refresh'),
}
