import client from './client'

export const recommendApi = {
  scanV4: (stockCodes?: string[]) =>
    client.post<any, any[]>('/recommend/scan-v4', { stock_codes: stockCodes }),
  alphaHunter: () =>
    client.get<any, any>('/recommend/alpha-hunter'),
}
