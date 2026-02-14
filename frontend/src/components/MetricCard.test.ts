import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import MetricCard from './MetricCard.vue'

describe('MetricCard', () => {
  it('renders title and value', () => {
    const w = mount(MetricCard, { props: { title: '總報酬率', value: '+15.3%' } })
    expect(w.text()).toContain('總報酬率')
    expect(w.text()).toContain('+15.3%')
  })

  it('renders with color prop', () => {
    const w = mount(MetricCard, { props: { title: 'Test', value: '42', color: '#e53e3e' } })
    const valueEl = w.find('.metric-value')
    expect(valueEl.attributes('style')).toContain('color: rgb(229, 62, 62)')
  })

  it('renders subtitle when provided', () => {
    const w = mount(MetricCard, { props: { title: 'Test', value: '10', subtitle: '較昨日+2%' } })
    expect(w.text()).toContain('較昨日+2%')
    expect(w.find('.metric-subtitle').exists()).toBe(true)
  })

  it('hides subtitle when not provided', () => {
    const w = mount(MetricCard, { props: { title: 'Test', value: '10' } })
    expect(w.find('.metric-subtitle').exists()).toBe(false)
  })

  it('shows skeleton when loading', () => {
    const w = mount(MetricCard, { props: { title: 'Test', loading: true } })
    // value should not be visible
    expect(w.find('.metric-value').exists()).toBe(false)
  })

  it('renders slot content instead of value prop', () => {
    const w = mount(MetricCard, {
      props: { title: 'Custom' },
      slots: { default: '<span class="custom">CUSTOM</span>' },
    })
    expect(w.find('.custom').exists()).toBe(true)
    expect(w.text()).toContain('CUSTOM')
  })

  it('renders numeric value', () => {
    const w = mount(MetricCard, { props: { title: 'Trades', value: 42 } })
    expect(w.text()).toContain('42')
  })

  it('applies bgColor as background style', () => {
    const w = mount(MetricCard, { props: { title: 'T', value: '1', bgColor: '#f0f0f0' } })
    const card = w.find('.metric-card')
    expect(card.attributes('style')).toContain('background: rgb(240, 240, 240)')
  })
})
