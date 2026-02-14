/** 格式化百分比 */
export function fmtPct(v: number | null | undefined, digits = 2): string {
  if (v == null) return '-'
  return (v * 100).toFixed(digits) + '%'
}

/** 格式化數字（千分位） */
export function fmtNum(v: number | null | undefined, digits = 0): string {
  if (v == null) return '-'
  return v.toLocaleString('zh-TW', { maximumFractionDigits: digits })
}

/** 格式化金額 */
export function fmtMoney(v: number | null | undefined): string {
  if (v == null) return '-'
  if (Math.abs(v) >= 1e8) return (v / 1e8).toFixed(2) + '億'
  if (Math.abs(v) >= 1e4) return (v / 1e4).toFixed(0) + '萬'
  return fmtNum(v, 0)
}

/** 顏色: 漲紅跌綠 (台股慣例) */
export function priceColor(v: number | null | undefined): string {
  if (v == null || v === 0) return ''
  return v > 0 ? '#e53e3e' : '#38a169'
}

/** 訊號顏色 */
export function signalColor(signal: string): string {
  if (signal === 'BUY') return '#e53e3e'
  if (signal === 'SELL') return '#38a169'
  return '#718096'
}

/** 訊號文字 */
export function signalText(signal: string): string {
  if (signal === 'BUY') return '買進'
  if (signal === 'SELL') return '賣出'
  return '觀望'
}

/** 格式化價格（固定 2 位小數） */
export function fmtPrice(v: number | null | undefined): string {
  if (v == null) return '-'
  return v.toFixed(2)
}

/** 格式化成交量（張） */
export function fmtVol(v: number | null | undefined): string {
  if (v == null) return '-'
  const lots = v / 1000
  if (lots >= 10000) return (lots / 10000).toFixed(1) + '萬張'
  return lots.toFixed(0) + '張'
}

/** 匯出 CSV 下載 */
export function downloadCsv(rows: Record<string, any>[], headers: { key: string; label: string }[], filename: string) {
  const headerLine = headers.map((h) => h.label).join(',')
  const lines = rows.map((row) =>
    headers.map((h) => {
      const v = row[h.key]
      if (v == null) return ''
      const s = String(v)
      return s.includes(',') || s.includes('"') ? `"${s.replace(/"/g, '""')}"` : s
    }).join(','),
  )
  const csv = '\uFEFF' + [headerLine, ...lines].join('\n')
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}
