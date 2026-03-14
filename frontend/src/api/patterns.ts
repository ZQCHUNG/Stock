import client from './client'

// --- Pattern Matching Types ---

export interface SimilarStockMatch {
  code: string
  name: string
  similarity: number
  distance: number
  [key: string]: unknown
}

export interface SimilarStocksResult {
  code: string
  window: number
  results: SimilarStockMatch[]
}

export interface HistoryMatch {
  start_date: string
  end_date: string
  similarity: number
  distance: number
  forward_returns: Record<string, number | null>
  [key: string]: unknown
}

export interface SimilarHistoryResult {
  code: string
  window: number
  search_code: string
  results: HistoryMatch[]
}

export const patternApi = {
  /** Find stocks with similar recent price patterns (DTW) */
  similarStocks: (code: string, window = 20, topN = 10, candidateCodes?: string) =>
    client.get<any, SimilarStocksResult>(`/analysis/${code}/similar-stocks`, {
      params: { window, top_n: topN, candidate_codes: candidateCodes },
      timeout: 300_000,
    }),

  /** Find similar historical pattern segments + forward returns */
  similarHistory: (code: string, window = 20, searchCode?: string, lookbackDays = 365) =>
    client.get<any, SimilarHistoryResult>(`/analysis/${code}/similar-history`, {
      params: { window, search_code: searchCode, lookback_days: lookbackDays },
      timeout: 120_000,
    }),
}
