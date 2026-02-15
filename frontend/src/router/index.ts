import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/dashboard' },
    {
      path: '/dashboard',
      name: 'dashboard',
      component: () => import('../views/DashboardView.vue'),
      meta: { title: 'Dashboard' },
    },
    {
      path: '/technical',
      name: 'technical',
      component: () => import('../views/TechnicalView.vue'),
      meta: { title: '技術分析' },
    },
    {
      path: '/watchlist',
      name: 'watchlist',
      component: () => import('../views/WatchlistView.vue'),
      meta: { title: '自選股總覽' },
    },
    { path: '/backtest', redirect: '/strategies' },
    {
      path: '/recommend',
      name: 'recommend',
      component: () => import('../views/RecommendView.vue'),
      meta: { title: '推薦股票' },
    },
    {
      path: '/report',
      name: 'report',
      component: () => import('../views/ReportView.vue'),
      meta: { title: '分析報告' },
    },
    {
      path: '/screener',
      name: 'screener',
      component: () => import('../views/ScreenerView.vue'),
      meta: { title: '條件選股' },
    },
    {
      path: '/portfolio',
      name: 'portfolio',
      component: () => import('../views/PortfolioView.vue'),
      meta: { title: '模擬倉位' },
    },
    // Redirects for consolidated pages
    { path: '/fitness', redirect: '/strategies' },
    { path: '/alerts', redirect: '/risk' },
    { path: '/sqs-performance', redirect: '/risk' },
    {
      path: '/risk',
      name: 'risk',
      component: () => import('../views/RiskDashboardView.vue'),
      meta: { title: '風險監控' },
    },
    {
      path: '/strategies',
      name: 'strategies',
      component: () => import('../views/StrategyWorkbenchView.vue'),
      meta: { title: '策略工作台' },
    },
  ],
})

export default router
