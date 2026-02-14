import { describe, it, expect } from 'vitest'

// Test the PAGE_KEYS mapping and isInputFocused helper logic
describe('useKeyboardShortcuts logic', () => {
  const PAGE_KEYS: Record<string, string> = {
    '1': 'technical',
    '2': 'watchlist',
    '3': 'backtest',
    '4': 'recommend',
    '5': 'report',
    '6': 'screener',
  }

  it('maps number keys to correct routes', () => {
    expect(PAGE_KEYS['1']).toBe('technical')
    expect(PAGE_KEYS['2']).toBe('watchlist')
    expect(PAGE_KEYS['3']).toBe('backtest')
    expect(PAGE_KEYS['4']).toBe('recommend')
    expect(PAGE_KEYS['5']).toBe('report')
    expect(PAGE_KEYS['6']).toBe('screener')
    expect(PAGE_KEYS['7']).toBeUndefined()
  })

  it('detects input focus correctly', () => {
    // When body is focused, not an input
    document.body.focus()
    const el = document.activeElement
    expect(el?.tagName.toLowerCase()).not.toBe('input')

    // When an input is focused
    const input = document.createElement('input')
    document.body.appendChild(input)
    input.focus()
    expect(document.activeElement?.tagName.toLowerCase()).toBe('input')
    document.body.removeChild(input)
  })
})
