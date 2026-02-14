import { defineStore } from 'pinia'
import { ref } from 'vue'
import { watchlistApi } from '../api/watchlist'
import { fetchSSE, type SSEProgress } from '../composables/useSSE'
import { message } from '../utils/discrete'

export const useWatchlistStore = defineStore('watchlist', () => {
  const watchlist = ref<{ code: string; name: string }[]>([])
  const overview = ref<any[]>([])
  const batchResults = ref<any[]>([])
  const isLoading = ref(false)
  const batchProgress = ref<SSEProgress>({ current: 0, total: 0, message: '' })

  async function load() {
    try {
      watchlist.value = await watchlistApi.get()
    } catch { /* interceptor handles toast */ }
  }

  async function add(code: string) {
    try {
      await watchlistApi.add(code)
      await load()
      message.success(`已加入自選股: ${code}`)
    } catch { /* interceptor handles toast */ }
  }

  async function remove(code: string) {
    try {
      await watchlistApi.remove(code)
      await load()
      message.success(`已移除自選股: ${code}`)
    } catch { /* interceptor handles toast */ }
  }

  async function loadOverview() {
    isLoading.value = true
    try {
      overview.value = await watchlistApi.overview()
    } catch { /* interceptor handles toast */ }
    finally { isLoading.value = false }
  }

  async function runBatchBacktest(req?: any) {
    isLoading.value = true
    batchProgress.value = { current: 0, total: 0, message: '' }
    try {
      const result = await fetchSSE<any[]>(
        '/api/watchlist/batch-backtest-stream',
        req || {},
        {
          onProgress: (p) => { batchProgress.value = p },
          onDone: (r) => { batchResults.value = r },
          onError: (msg) => { message.error(`批次回測失敗: ${msg}`) },
        },
      )
      if (result) {
        batchResults.value = result
        message.success(`批次回測完成：${result.length} 隻`)
      }
    } catch (e: any) {
      message.error(`批次回測失敗: ${e.message}`)
    } finally {
      isLoading.value = false
      batchProgress.value = { current: 0, total: 0, message: '' }
    }
  }

  const isExporting = ref(false)

  async function exportRiskAudit(capital = 1_000_000, riskPct = 2.0) {
    isExporting.value = true
    try {
      const data = await watchlistApi.riskAudit(capital, riskPct)
      const stocks: any[] = data.stocks || []
      const summary = data.summary || {}

      // Build CSV
      const BOM = '\uFEFF'
      const headers = [
        '代碼', '名稱', '收盤價', 'V4訊號', '進場類型', '訊號成熟度', 'RSI', 'ADX', '趨勢天數',
        '產業', '生技?', '法人能見度', '法人分數',
        '營業跑道(季)', '總跑道(季)', '有效跑道(季)',
        'Liquidity Factor', '建議張數', '停損價', '最大虧損',
        '均量(張/日)', '風險警告',
      ]
      const rows = stocks.map((s: any) => {
        if (s.error) return [s.code, s.name, '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', `ERROR: ${s.error}`]
        return [
          s.code, s.name, s.price?.toFixed(2) ?? '',
          s.signal ?? '', s.entry_type ?? '', s.signal_maturity ?? 'N/A',
          s.rsi?.toFixed(1) ?? '', s.adx?.toFixed(1) ?? '', s.uptrend_days ?? '',
          s.sector ?? '', s.is_biotech ? 'Y' : 'N',
          s.visibility ?? '', s.inst_score ?? '',
          s.op_runway ?? '', s.total_runway ?? '', s.eff_runway ?? '',
          s.liquidity_factor ?? '', s.suggested_lots ?? '',
          s.stop_loss_price ?? '', s.max_loss ?? '',
          s.avg_volume_lots ?? '',
          (s.warnings || []).join('; '),
        ]
      })

      // Summary rows
      const blankRow: string[] = []
      const summaryRows = [
        blankRow,
        ['=== 組合風險摘要 ==='],
        [`自選股數: ${summary.total_stocks}`, `有效: ${summary.valid_stocks}`, `BUY訊號: ${summary.buy_signal_count}`],
        [`最大產業: ${summary.top_sector} (${summary.top_sector_pct}%)`, `生技佔比: ${summary.biotech_pct}%`, `Ghost Town: ${summary.ghost_town_count}`],
        [`平均LF: ${summary.avg_liquidity_factor}`, `資金: ${(summary.capital / 10000).toFixed(0)}萬`, `風險比: ${summary.risk_pct}%`],
        ...(summary.portfolio_warnings || []).map((w: string) => [`!!! ${w}`]),
        [`審計時間: ${summary.audit_time}`],
      ]

      const csvContent = BOM + [
        headers.join(','),
        ...rows.map((r: any[]) => r.map((v: any) => `"${String(v).replace(/"/g, '""')}"`).join(',')),
        ...summaryRows.map((r: string[]) => r.join(',')),
      ].join('\n')

      // Download
      const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      const date = new Date().toISOString().slice(0, 10)
      a.download = `風險審計_${date}.csv`
      a.click()
      URL.revokeObjectURL(url)
      message.success(`風險審計報告已匯出（${stocks.length} 檔）`)
    } catch (e: any) {
      message.error(`匯出失敗: ${e.message}`)
    } finally {
      isExporting.value = false
    }
  }

  return { watchlist, overview, batchResults, isLoading, isExporting, batchProgress, load, add, remove, loadOverview, runBatchBacktest, exportRiskAudit }
})
