import client from './client'

export interface BacktestParams {
  period_days?: number
  initial_capital?: number
  params?: Record<string, any>
}

export const backtestApi = {
  v4: (code: string, req: BacktestParams = {}) =>
    client.post<any, any>(`/backtest/${code}/v4`, req),
  portfolio: (stockCodes: string[], req: BacktestParams = {}) =>
    client.post<any, any>('/backtest/portfolio', { stock_codes: stockCodes, ...req }),
  simulation: (code: string, days = 30, req: BacktestParams = {}) =>
    client.post<any, any>(`/backtest/${code}/simulation`, { days, ...req }),
  rolling: (code: string, windowMonths = 6, req: BacktestParams = {}) =>
    client.post<any, any>(`/backtest/${code}/rolling`, { window_months: windowMonths, ...req }),
  sensitivity: (code: string, req: BacktestParams = {}) =>
    client.post<any, any>(`/backtest/${code}/sensitivity`, req),
  alphaBeta: (code: string, req: BacktestParams = {}) =>
    client.post<any, any>(`/backtest/${code}/alpha-beta`, req),
}
