import client from './client'

// --- Report Types ---

export interface OutlookData {
  timeframe: string
  bull_case: string
  bull_target: number
  bull_probability: number
  base_case: string
  base_target: number
  base_probability: number
  bear_case: string
  bear_target: number
  bear_probability: number
}

export interface PriceLevel {
  price: number
  source: string
  strength: number
}

export interface FibonacciData {
  swing_high: number
  swing_low: number
  direction: string
  retracement: Record<string, number>
  extension: Record<string, number>
}

export interface PriceTarget {
  scenario: string
  target_price: number
  upside_pct: number
  rationale: string
  timeframe: string
  confidence: number
}

export interface ReportResult {
  stock_code: string
  stock_name: string
  report_date: string
  current_price: number
  // Price performance
  price_change_1w: number | null
  price_change_1m: number | null
  price_change_3m: number | null
  price_change_6m: number | null
  price_change_1y: number | null
  high_52w: number | null
  low_52w: number | null
  pct_from_52w_high: number | null
  pct_from_52w_low: number | null
  // Trend
  trend_direction: string
  trend_strength: string
  momentum_status: string
  volatility_level: string
  overall_rating: string
  ma_alignment: string
  // Support / Resistance
  support_levels: PriceLevel[]
  resistance_levels: PriceLevel[]
  fibonacci: FibonacciData | null
  price_targets: PriceTarget[]
  // Momentum indicators
  adx_value: number | null
  adx_interpretation: string
  rsi_value: number | null
  rsi_interpretation: string
  macd_value: number | null
  macd_signal_value: number | null
  macd_histogram: number | null
  macd_interpretation: string
  k_value: number | null
  d_value: number | null
  kd_interpretation: string
  // Volume
  volume_trend: string
  volume_ratio: number | null
  volume_interpretation: string
  // Volatility
  atr_value: number | null
  atr_pct: number | null
  bollinger_width: number | null
  bollinger_position: number | null
  volatility_interpretation: string
  // Risk
  max_drawdown_1y: number | null
  current_drawdown: number | null
  risk_reward_ratio: number | null
  risk_interpretation: string
  // Outlook
  outlook_3m: OutlookData | null
  outlook_6m: OutlookData | null
  outlook_1y: OutlookData | null
  // Summary
  summary_text: string
  // Strategy
  v4_analysis: Record<string, unknown> | null
  v2_analysis: Record<string, unknown> | null
  // Fundamentals
  fundamentals: Record<string, unknown> | null
  fundamental_interpretation: string | null
  fundamental_score: number | null
  analyst_data: Record<string, unknown> | null
  // News
  news_items: Record<string, unknown>[] | null
  news_sentiment_score: number | null
  news_sentiment_label: string | null
  news_insights: string | null
  news_themes: string[] | null
  // Actionable
  actionable_recommendation: string | null
  industry_risks: string[] | null
  technical_conflicts: string[] | null
  technical_bias: string | null
  peer_context: Record<string, unknown> | null
  valuation: Record<string, unknown> | null
  // Institutional
  institutional_score: number | null
  is_biotech: boolean
  rating_weights: Record<string, number> | null
  cash_runway: Record<string, unknown> | null
  rating_decision: Record<string, unknown> | null
}

export const reportApi = {
  generate: (code: string, periodDays = 730, marketRegime?: string) =>
    client.post<any, ReportResult>(`/report/${code}/generate`, {
      period_days: periodDays,
      market_regime: marketRegime,
    }),
}
