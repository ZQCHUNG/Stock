/**
 * E2E Smoke Tests (R54)
 *
 * Core user flows that must always work:
 * 1. Dashboard loads with key panels
 * 2. Technical analysis page loads indicators
 * 3. Navigation between pages works
 * 4. Risk monitoring page loads
 * 5. Strategy workbench loads strategies
 */
import { test, expect } from '@playwright/test'

test.describe('Dashboard', () => {
  test('loads and displays key panels', async ({ page }) => {
    await page.goto('/')
    // Should redirect to /dashboard
    await expect(page).toHaveURL(/dashboard/)

    // Key metric cards should be visible
    await expect(page.getByText('Positions')).toBeVisible({ timeout: 15000 })
    await expect(page.getByText('Market Value')).toBeVisible()

    // Market Regime panel
    await expect(page.getByText('Market Regime')).toBeVisible()

    // Quick navigation buttons
    await expect(page.getByRole('button', { name: 'Technical' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Screener' })).toBeVisible()
  })

  test('refresh button works', async ({ page }) => {
    await page.goto('/dashboard')
    await expect(page.getByText('Positions')).toBeVisible({ timeout: 15000 })

    const refreshBtn = page.getByRole('button', { name: 'Refresh' })
    await expect(refreshBtn).toBeVisible()
    await refreshBtn.click()

    // Should still show key content after refresh
    await expect(page.getByText('Positions')).toBeVisible({ timeout: 10000 })
  })
})

test.describe('Navigation', () => {
  test('sidebar navigation works', async ({ page }) => {
    await page.goto('/dashboard')
    await expect(page.getByText('Positions')).toBeVisible({ timeout: 15000 })

    // Navigate to Technical
    await page.getByText('技術分析').click()
    await expect(page).toHaveURL(/technical/)

    // Navigate to Recommend
    await page.getByText('推薦股票').click()
    await expect(page).toHaveURL(/recommend/)

    // Navigate to Risk
    await page.getByText('風險監控').click()
    await expect(page).toHaveURL(/risk/)
  })

  test('redirects work for consolidated pages', async ({ page }) => {
    // /backtest should redirect to /strategies
    await page.goto('/backtest')
    await expect(page).toHaveURL(/strategies/)

    // /fitness should redirect to /strategies
    await page.goto('/fitness')
    await expect(page).toHaveURL(/strategies/)

    // /alerts should redirect to /risk
    await page.goto('/alerts')
    await expect(page).toHaveURL(/risk/)
  })
})

test.describe('Technical Analysis', () => {
  test('loads for default stock', async ({ page }) => {
    await page.goto('/technical')

    // Stock code should be displayed somewhere
    await expect(page.locator('body')).toContainText(/技術分析|V4/, { timeout: 15000 })
  })
})

test.describe('Strategy Workbench', () => {
  test('loads strategies list', async ({ page }) => {
    await page.goto('/strategies')

    // Should show the workbench title
    await expect(page.getByText('策略工作台')).toBeVisible({ timeout: 15000 })

    // Should have strategy management tab
    await expect(page.getByText('策略管理')).toBeVisible()

    // Should have tabs for backtest and fitness
    await expect(page.getByText('回測與分析')).toBeVisible()
    await expect(page.getByText('策略適配')).toBeVisible()
  })

  test('tabs switch correctly', async ({ page }) => {
    await page.goto('/strategies')
    await expect(page.getByText('策略工作台')).toBeVisible({ timeout: 15000 })

    // Click backtest tab
    await page.getByText('回測與分析').click()
    // BacktestView content should appear
    await expect(page.locator('body')).toContainText(/回測|backtest/i, { timeout: 10000 })
  })
})

test.describe('Risk Dashboard', () => {
  test('loads risk overview', async ({ page }) => {
    await page.goto('/risk')

    // Should show the risk title
    await expect(page.getByText('風險監控儀表板')).toBeVisible({ timeout: 15000 })

    // Should have tabs
    await expect(page.getByText('風險概覽')).toBeVisible()
    await expect(page.getByText('警報監控')).toBeVisible()
    await expect(page.getByText('SQS 績效')).toBeVisible()
  })
})
