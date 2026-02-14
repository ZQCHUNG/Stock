import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import ChartContainer from './ChartContainer.vue'

// Mock vue-echarts since it needs canvas
vi.mock('vue-echarts', () => ({
  default: { name: 'VChart', template: '<div class="mock-vchart" />', props: ['option', 'group', 'autoresize'] },
}))

describe('ChartContainer', () => {
  it('shows empty state when option is empty object', () => {
    const w = mount(ChartContainer, { props: { option: {} } })
    expect(w.text()).toContain('暫無數據')
  })

  it('shows chart when option has data', () => {
    const w = mount(ChartContainer, {
      props: { option: { series: [{ data: [1, 2, 3] }] } },
    })
    expect(w.find('.mock-vchart').exists()).toBe(true)
  })

  it('applies custom height', () => {
    const w = mount(ChartContainer, { props: { option: {}, height: '500px' } })
    expect(w.find('.chart-container').attributes('style')).toContain('height: 500px')
  })

  it('renders aria-label', () => {
    const w = mount(ChartContainer, { props: { option: {}, ariaLabel: 'K線圖' } })
    expect(w.find('.chart-container').attributes('aria-label')).toBe('K線圖')
  })

  it('uses default aria-label', () => {
    const w = mount(ChartContainer, { props: { option: {} } })
    expect(w.find('.chart-container').attributes('aria-label')).toBe('圖表')
  })

  it('shows skeleton when loading', () => {
    const w = mount(ChartContainer, { props: { option: { series: [] }, loading: true } })
    // When loading, chart should not render
    expect(w.find('.mock-vchart').exists()).toBe(false)
  })
})
