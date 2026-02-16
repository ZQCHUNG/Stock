import client from './client'

export const riskApi = {
  getSummary: () => client.get<any, any>('/risk/summary', { timeout: 60000 }),
  getPositionSize: (params: {
    code: string
    entry_price: number
    confidence?: number
    account_value?: number
    var_limit_pct?: number
  }) => client.post<any, any>('/risk/position-size', params, { timeout: 30000 }),
  getScenario: (account_value?: number) =>
    client.post<any, any>('/risk/scenario', { account_value: account_value || 1000000 }, { timeout: 30000 }),
  validateVar: () =>
    client.post<any, any>('/risk/validate-var', {}, { timeout: 120000 }),
  // R86: R-Multiple + Portfolio Heat
  getRMultiples: () => client.get<any, any>('/risk/r-multiples', { timeout: 30000 }),
  getPortfolioHeat: () => client.get<any, any>('/risk/portfolio-heat', { timeout: 60000 }),
  // R87: Sector Correlation Monitor
  getSectorCorrelation: () => client.get<any, any>('/risk/sector-correlation', { timeout: 120000 }),
}
