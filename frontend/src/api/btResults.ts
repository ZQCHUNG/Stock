import client from './client'

export interface EquityCurveData {
  dates: string[]
  values: number[]
}

export interface SavedBtResult {
  name: string
  stockCode: string
  stockName: string
  config: Record<string, any>
  metrics: Record<string, any>
  savedAt: string
  equityCurve?: EquityCurveData
}

export const btResultsApi = {
  list(): Promise<SavedBtResult[]> {
    return client.get('/backtest-results') as any
  },
  listWithEquity(): Promise<SavedBtResult[]> {
    return client.get('/backtest-results', { params: { include_equity: true } }) as any
  },
  save(data: {
    name: string; stockCode: string; stockName: string;
    config: Record<string, any>; metrics: Record<string, any>;
    equityCurve?: EquityCurveData;
  }) {
    return client.post('/backtest-results', data) as any
  },
  remove(index: number) {
    return client.delete(`/backtest-results/${index}`) as any
  },
}
