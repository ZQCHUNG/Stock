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
}
