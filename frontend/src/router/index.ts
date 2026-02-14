import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/technical' },
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
    {
      path: '/backtest',
      name: 'backtest',
      component: () => import('../views/BacktestView.vue'),
      meta: { title: '回測報告' },
    },
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
    {
      path: '/fitness',
      name: 'fitness',
      component: () => import('../views/FitnessView.vue'),
      meta: { title: '策略適配' },
    },
    {
      path: '/alerts',
      name: 'alerts',
      component: () => import('../views/AlertsView.vue'),
      meta: { title: 'SQS 警報' },
    },
    {
      path: '/sqs-performance',
      name: 'sqs-performance',
      component: () => import('../views/SqsPerformanceView.vue'),
      meta: { title: 'SQS 績效' },
    },
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
