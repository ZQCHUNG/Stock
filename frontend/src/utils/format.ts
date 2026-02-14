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
