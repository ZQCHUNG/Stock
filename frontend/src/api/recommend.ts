import client from './client'

// --- Scan V4 Types ---

export interface ScanV4Item {
  code: string
  name: string
  price: number
  price_change: number
  signal: 'BUY' | 'HOLD' | 'SELL'
  entry_type: string
  uptrend_days: number
  dist_ma20: number
  indicators: Record<string, number | null>
  filter_reason?: string
  roe?: number | null
  pe?: number | null
  market_cap?: number | null
}

// --- Alpha Hunter Types ---

export interface AlphaHunterStock {
  code: string
  name: string
  maturity: string
  maturity_rank: number
  is_leader: boolean
  leader_score: number
  confidence: number
  sector: string
  momentum: string
  weighted_heat: number
}

export interface AlphaHunterSector {
  sector: string
  momentum: string
  weighted_heat: number
  momentum_rank: number
  leader: { code: string; name: string; leader_score: number } | null
  buy_count: number
  total: number
  stocks: AlphaHunterStock[]
  is_crowded: boolean
}

export interface TransitionEvent {
  code: string
  name: string
  from: string
  to: string
  timestamp: string
  [key: string]: unknown
}

export interface AlphaHunterResult {
  sectors: AlphaHunterSector[]
  high_confidence: AlphaHunterStock[]
  transitions: TransitionEvent[]
  total_buy: number
  updated_at?: string
}

export const recommendApi = {
  scanV4: (stockCodes?: string[]) =>
    client.post<any, ScanV4Item[]>('/recommend/scan-v4', { stock_codes: stockCodes }),
  alphaHunter: () =>
    client.get<any, AlphaHunterResult>('/recommend/alpha-hunter'),
}
