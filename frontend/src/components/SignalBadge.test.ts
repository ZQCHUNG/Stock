import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import SignalBadge from './SignalBadge.vue'

describe('SignalBadge', () => {
  it('renders BUY signal', () => {
    const w = mount(SignalBadge, { props: { signal: 'BUY' } })
    expect(w.text()).toContain('買進')
  })

  it('renders SELL signal', () => {
    const w = mount(SignalBadge, { props: { signal: 'SELL' } })
    expect(w.text()).toContain('賣出')
  })

  it('renders HOLD signal', () => {
    const w = mount(SignalBadge, { props: { signal: 'HOLD' } })
    expect(w.text()).toContain('觀望')
  })

  it('handles unknown signal', () => {
    const w = mount(SignalBadge, { props: { signal: 'UNKNOWN' } })
    expect(w.text()).toBeTruthy()
  })
})
