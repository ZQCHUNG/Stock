import client from './client'

// --- Dual Pipeline Types ---

export interface DualSimilarRequest {
  stock_code: string
  query_date?: string | null
  top_k?: number
  exclude_self?: boolean
  dimensions?: string[] | null
}

export interface ForwardReturns {
  d3: number | null
  d7: number | null
  d21: number | null
  d90: number | null
  d180: number | null
}

export interface DimensionSimilarities {
  technical: number
  institutional: number
  industry: number
  fundamental: number
  attention: number
  [key: string]: number
}

export interface SimilarCase {
  stock_code: string
  date: string
  similarity: number
  forward_returns: ForwardReturns
  dimension_similarities?: DimensionSimilarities
  similarity_summary?: string
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

export interface PathPoint {
  day: number
  value: number
}

export interface ForwardPath {
  stock_code: string
  date: string
  similarity: number
  path: PathPoint[]
}

export interface Opinion {
  regime_label: string
  advice_text: string
  confidence: 'high' | 'medium' | 'low'
  filters_applied: string[]
  weight_transparency?: Record<string, number>
}

export interface BlockResult {
  label: string
  description: string
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
  forward_paths: ForwardPath[]
  opinion?: Opinion
}

export interface DualSimilarResult {
  query: {
    stock_code: string
    date: string
    regime: number
  }
  dimensions_used: string[]
  raw: BlockResult
  augmented: BlockResult
  divergence_warning: boolean
  transaction_cost_deducted: number
}

// --- Legacy Types (backward compat) ---

export interface SimilarRequest {
  stock_code: string
  dimensions: string[]
  window?: number
  top_k?: number
  exclude_self?: boolean
  min_date?: string | null
  regime_match?: boolean
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
  /** 雙區塊查詢 (主 API) */
  similarDual: (req: DualSimilarRequest) =>
    client.post<any, DualSimilarResult>('/cluster/similar-dual', req, {
      timeout: 300_000,
    }),

  /** Legacy 查詢 */
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
