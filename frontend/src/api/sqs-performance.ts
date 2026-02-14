import client from './client'

export const sqsPerformanceApi = {
  getSummary: (params?: { date_from?: string; date_to?: string; min_sqs?: number; source?: string }) =>
    client.get<any, any>('/sqs-performance/summary', { params }),
  getSignals: (params?: { limit?: number; offset?: number; source?: string }) =>
    client.get<any, any>('/sqs-performance/signals', { params }),
  updateReturns: (maxRecords = 50) =>
    client.post<any, any>('/sqs-performance/update-returns', null, { params: { max_records: maxRecords } }),
  backfill: (periodDays = 730) =>
    client.post<any, any>('/sqs-performance/backfill', null, {
      params: { period_days: periodDays },
      timeout: 600000,  // 10 min for heavy operation
    }),
}
