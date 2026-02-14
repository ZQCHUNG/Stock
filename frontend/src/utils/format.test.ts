import { describe, it, expect } from 'vitest'
import { fmtPct, fmtNum, fmtMoney, priceColor, signalColor, signalText, fmtPrice, fmtVol } from './format'

describe('fmtPct', () => {
  it('formats decimal as percentage', () => {
    expect(fmtPct(0.1234)).toBe('12.34%')
    expect(fmtPct(-0.05)).toBe('-5.00%')
    expect(fmtPct(0)).toBe('0.00%')
  })
  it('handles custom digits', () => {
    expect(fmtPct(0.1234, 1)).toBe('12.3%')
    expect(fmtPct(0.1234, 0)).toBe('12%')
  })
  it('returns dash for null/undefined', () => {
    expect(fmtPct(null)).toBe('-')
    expect(fmtPct(undefined)).toBe('-')
  })
})

describe('fmtNum', () => {
  it('formats with thousands separator', () => {
    expect(fmtNum(1234567)).toBe('1,234,567')
    expect(fmtNum(0)).toBe('0')
  })
  it('handles decimal digits', () => {
    expect(fmtNum(1234.567, 2)).toBe('1,234.57')
  })
  it('returns dash for null/undefined', () => {
    expect(fmtNum(null)).toBe('-')
    expect(fmtNum(undefined)).toBe('-')
  })
})

describe('fmtMoney', () => {
  it('formats billions (億)', () => {
    expect(fmtMoney(1.5e8)).toBe('1.50億')
    expect(fmtMoney(-2e8)).toBe('-2.00億')
  })
  it('formats ten-thousands (萬)', () => {
    expect(fmtMoney(50000)).toBe('5萬')
    expect(fmtMoney(-30000)).toBe('-3萬')
  })
  it('formats small numbers normally', () => {
    expect(fmtMoney(999)).toBe('999')
  })
  it('returns dash for null/undefined', () => {
    expect(fmtMoney(null)).toBe('-')
    expect(fmtMoney(undefined)).toBe('-')
  })
})

describe('priceColor', () => {
  it('returns red for positive (Taiwan convention)', () => {
    expect(priceColor(1)).toBe('#e53e3e')
    expect(priceColor(0.01)).toBe('#e53e3e')
  })
  it('returns green for negative', () => {
    expect(priceColor(-1)).toBe('#38a169')
    expect(priceColor(-0.01)).toBe('#38a169')
  })
  it('returns empty for zero/null/undefined', () => {
    expect(priceColor(0)).toBe('')
    expect(priceColor(null)).toBe('')
    expect(priceColor(undefined)).toBe('')
  })
})

describe('signalColor', () => {
  it('returns correct colors for signals', () => {
    expect(signalColor('BUY')).toBe('#e53e3e')
    expect(signalColor('SELL')).toBe('#38a169')
    expect(signalColor('HOLD')).toBe('#718096')
    expect(signalColor('UNKNOWN')).toBe('#718096')
  })
})

describe('signalText', () => {
  it('returns correct Chinese text', () => {
    expect(signalText('BUY')).toBe('買進')
    expect(signalText('SELL')).toBe('賣出')
    expect(signalText('HOLD')).toBe('觀望')
    expect(signalText('OTHER')).toBe('觀望')
  })
})

describe('fmtPrice', () => {
  it('formats with 2 decimal places', () => {
    expect(fmtPrice(123.4)).toBe('123.40')
    expect(fmtPrice(100)).toBe('100.00')
    expect(fmtPrice(0.5)).toBe('0.50')
  })
  it('returns dash for null/undefined', () => {
    expect(fmtPrice(null)).toBe('-')
    expect(fmtPrice(undefined)).toBe('-')
  })
})

describe('fmtVol', () => {
  it('formats volume in lots (張)', () => {
    expect(fmtVol(5000000)).toBe('5000張')
    expect(fmtVol(1000)).toBe('1張')
    expect(fmtVol(500000)).toBe('500張')
  })
  it('formats large volume in 萬張', () => {
    expect(fmtVol(10000000)).toBe('1.0萬張')
    expect(fmtVol(50000000)).toBe('5.0萬張')
    expect(fmtVol(15000000)).toBe('1.5萬張')
  })
  it('returns dash for null/undefined', () => {
    expect(fmtVol(null)).toBe('-')
    expect(fmtVol(undefined)).toBe('-')
  })
})
