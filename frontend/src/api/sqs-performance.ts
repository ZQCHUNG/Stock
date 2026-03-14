import client from './client'

// --- SQS Performance Types ---

export interface SqsPerformanceSummary {
  total_signals: number
  by_grade: Record<string, {
    count: number
    avg_return_d5?: number | null
    avg_return_d10?: number | null
    avg_return_d20?: number | null
    win_rate_d5?: number | null
    win_rate_d10?: number | null
    win_rate_d20?: number | null
    [key: string]: unknown
  }>
  [key: string]: unknown
}

export interface SqsTrackedSignal {
  id: number
  stock_code: string
  signal_date: string
  sqs_score: number
  grade: string
  strategy: string
  source: string
  return_d5?: number | null
  return_d10?: number | null
  return_d20?: number | null
  [key: string]: unknown
}

export interface SqsSignalsResult {
  signals: SqsTrackedSignal[]
  total: number
  [key: string]: unknown
}

export interface SqsUpdateResult {
  updated: number
}

export interface SqsBackfillResult {
  backfilled: number
  source: string
}

export const sqsPerformanceApi = {
  getSummary: (params?: { date_from?: string; date_to?: string; min_sqs?: number; source?: string }) =>
    client.get<any, SqsPerformanceSummary>('/sqs-performance/summary', { params }),
  getSignals: (params?: { limit?: number; offset?: number; source?: string }) =>
    client.get<any, SqsSignalsResult>('/sqs-performance/signals', { params }),
  updateReturns: (maxRecords = 50) =>
    client.post<any, SqsUpdateResult>('/sqs-performance/update-returns', null, { params: { max_records: maxRecords } }),
  backfill: (periodDays = 730) =>
    client.post<any, SqsBackfillResult>('/sqs-performance/backfill', null, {
      params: { period_days: periodDays },
      timeout: 600000,
    }),
}
