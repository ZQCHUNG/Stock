import { describe, it, expect } from 'vitest'
import { encodeConfig, decodeConfig } from './urlConfig'

describe('encodeConfig / decodeConfig', () => {
  it('round-trips a config object', () => {
    const config = { stockCode: '2330', periodDays: 1095, capital: 1000000 }
    const encoded = encodeConfig(config)
    const decoded = decodeConfig(encoded)
    expect(decoded).toEqual(config)
  })

  it('strips null/undefined/empty/false values', () => {
    const config = { a: 1, b: null, c: undefined, d: '', e: false, f: 'ok' }
    const encoded = encodeConfig(config)
    const decoded = decodeConfig(encoded)
    expect(decoded).toEqual({ a: 1, f: 'ok' })
  })

  it('returns null for invalid base64', () => {
    expect(decodeConfig('invalid!!!')).toBeNull()
  })

  it('returns null for non-JSON base64', () => {
    expect(decodeConfig(btoa('not json'))).toBeNull()
  })
})
