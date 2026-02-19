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
  brokerage: number
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

export interface SniperAssessment {
  tier: 'sniper' | 'tactical' | 'avoid'
  mean_similarity: number
  mean_fund_similarity: number
  confidence_label: string
  label: string  // e.g. "[EXPERIMENTAL]"
  validation: {
    rho: number
    pf: number
    n: number
    period: string
  }
}

export interface DualSimilarResult {
  query: {
    stock_code: string
    date: string
    regime: number
  }
  dimensions_used: string[]
  sniper_assessment: SniperAssessment
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
  active_feature_count: number
  features: string[]
  warmup_features: string[]
  has_warmup: boolean
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

export interface MutationResult {
  stock_code: string
  date: string
  score_brokerage: number
  score_technical: number
  delta_div: number
  abs_delta: number
  z_score: number
  mutation_type: string
  mutation_label: string
}

export interface MutationScanResult {
  mutations: MutationResult[]
  total_stocks_scanned: number
  total_mutations: number
  distribution: {
    mean: number
    std: number
    min: number
    max: number
  }
  histogram: {
    counts: number[]
    edges: number[]
    threshold_sigma: number
    threshold_value_upper: number
    threshold_value_lower: number
  }
  circuit_breaker: {
    triggered: boolean
    extreme_count: number
    extreme_pct: number
    threshold_pct: number
    threshold_sigma: number
  }
  config: {
    threshold_sigma: number
    top_n: number
    use_weights: boolean
    brokerage_features_active: number
    brokerage_features_total: number
    technical_features_active: number
  }
}

// --- Daily Summary Types (R88.7 Phase 10-11) ---

export interface NightWatchmanHealth {
  status: string
  latest_date: string | null
  brokerage_nonzero_rate: number
  brokerage_stocks_with_data: number
}

export interface RowCountDrift {
  status: string
  deviation_pct: number | null
  expected_rows?: number
  actual_rows?: number
  history_days?: number
}

export interface PipelineHealth {
  status: string
  swap_result?: string
  new_rows?: number
  row_delta?: number
  size_mb?: number
  timestamp?: string
  night_watchman?: NightWatchmanHealth
  row_count_drift?: RowCountDrift
  error?: string
}

export interface MutationEntry {
  stock_code: string
  date: string
  z_score: number
  score_brokerage: number
  score_technical: number
  sector?: string
}

export interface ActivityPercentile {
  percentile: number | null
  label: string
  history_days: number
  min_required?: number
  avg_20d?: number
}

export interface HotSector {
  sector: string
  stealth_count: number
  distribution_count: number
  total: number
  signal: 'stealth_heavy' | 'distribution_heavy' | 'mixed'
}

export interface MarketPulse {
  total_stocks_scanned: number
  total_mutations: number
  stealth_count: number
  distribution_count: number
  mutation_bias: string
  bias_ratio: number
  activity_percentile?: ActivityPercentile
  circuit_breaker: {
    triggered: boolean
    extreme_count: number
    extreme_pct: number
    threshold_pct: number
    threshold_sigma: number
  }
  distribution_stats: {
    mean: number
    std: number
    min: number
    max: number
  }
  error?: string
}

export interface ConfidenceScore {
  score: number
  label: string
  color: 'green' | 'yellow' | 'red'
  data_health: number
  signal_strength: number
  components?: {
    h1_row_integrity: number
    h2_night_watchman: number
    h3_brokerage_activity: number
    s1_intensity: number
    s2_conviction: number
    s3_concentration: number
  }
}

export interface DailySummary {
  date: string
  generated_at: string
  version: string
  pipeline_health: PipelineHealth
  market_pulse: MarketPulse
  confidence_score?: ConfidenceScore
  hot_sectors: HotSector[]
  top_mutations: {
    stealth: MutationEntry[]
    distribution: MutationEntry[]
  }
  narrative: string
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

  /** 基因突變掃描 (R88.7) */
  mutations: (threshold = 1.5, topN = 10, useWeights = false) =>
    client.get<any, MutationScanResult>('/cluster/mutations', {
      params: { threshold, top_n: topN, use_weights: useWeights },
    }),

  /** 每日自動摘要 (R88.7 Phase 10) */
  dailySummary: (regenerate = false) =>
    client.get<any, DailySummary>('/cluster/daily-summary', {
      params: { regenerate },
    }),
}
