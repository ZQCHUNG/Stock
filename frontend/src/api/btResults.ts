import client from './client'

export interface SavedBtResult {
  name: string
  stockCode: string
  stockName: string
  config: Record<string, any>
  metrics: Record<string, any>
  savedAt: string
}

export const btResultsApi = {
  list(): Promise<SavedBtResult[]> {
    return client.get('/backtest-results') as any
  },
  save(data: { name: string; stockCode: string; stockName: string; config: Record<string, any>; metrics: Record<string, any> }) {
    return client.post('/backtest-results', data) as any
  },
  remove(index: number) {
    return client.delete(`/backtest-results/${index}`) as any
  },
}
