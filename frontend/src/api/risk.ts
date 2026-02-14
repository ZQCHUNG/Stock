import client from './client'

export const riskApi = {
  getSummary: () => client.get<any, any>('/risk/summary', { timeout: 60000 }),
}
