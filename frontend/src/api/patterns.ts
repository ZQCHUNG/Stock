import client from './client'

export const patternApi = {
  /** 找出與目標股票近期走勢相似的股票 (DTW) */
  similarStocks: (code: string, window = 20, topN = 10, candidateCodes?: string) =>
    client.get<any, any>(`/analysis/${code}/similar-stocks`, {
      params: { window, top_n: topN, candidate_codes: candidateCodes },
      timeout: 300_000,
    }),

  /** 在歷史中找出類似的線型區段 + 之後走勢 */
  similarHistory: (code: string, window = 20, searchCode?: string, lookbackDays = 365) =>
    client.get<any, any>(`/analysis/${code}/similar-history`, {
      params: { window, search_code: searchCode, lookback_days: lookbackDays },
      timeout: 120_000,
    }),
}
