import client from './client'

export interface SimilarRequest {
  stock_code: string
  dimensions: string[]
  window?: number
  top_k?: number
  exclude_self?: boolean
  min_date?: string | null
  regime_match?: boolean
}

export interface ForwardReturns {
  d3: number | null
  d7: number | null
  d21: number | null
  d90: number | null
  d180: number | null
}

export interface SimilarCase {
  stock_code: string
  date: string
  similarity: number
  forward_returns: ForwardReturns
}

export interface ReturnStats {
  mean: number | null
  median: number | null
  win_rate: number | null
  hit_rate_2pct: number | null
  std: number | null
  min: number | null
  max: number | null
  p5: number | null
  p95: number | null
  expectancy: number | null
  avg_win: number | null
  avg_loss: number | null
}

export interface SimilarResult {
  query: {
    stock_code: string
    date: string
    window: number
    regime: number
    regime_match: boolean
  }
  dimensions_used: string[]
  feature_count: number
  descriptor_count: number
  similar_cases: SimilarCase[]
  statistics: {
    sample_count: number
    small_sample_warning: boolean
    d3: ReturnStats
    d7: ReturnStats
    d21: ReturnStats
    d90: ReturnStats
    d180: ReturnStats
  }
  transaction_cost_deducted: number
}

export interface DimensionInfo {
  name: string
  label: string
  feature_count: number
  features: string[]
}

export interface FeatureStatus {
  features_exists: boolean
  returns_exists: boolean
  metadata_exists: boolean
  loaded_in_memory: boolean
  rows?: number
  features?: number
  stocks?: number
  dimensions?: string[]
  features_size_mb?: number
  returns_size_mb?: number
}

export const clusterApi = {
  /** 主查詢：找相似案例 */
  similar: (req: SimilarRequest) =>
    client.post<any, SimilarResult>('/cluster/similar', req, {
      timeout: 300_000,
    }),

  /** 取得可用維度清單 */
  dimensions: () =>
    client.get<any, { dimensions: DimensionInfo[] }>('/cluster/dimensions'),

  /** 取得特徵資料狀態 */
  featureStatus: () =>
    client.get<any, FeatureStatus>('/cluster/feature-status'),
}
