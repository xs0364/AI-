import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', redirect: '/funds' },
  { path: '/funds', name: 'FundList', component: () => import('../views/FundList.vue') },
  { path: '/strategies', name: 'StrategyConfig', component: () => import('../views/StrategyConfig.vue') },
  { path: '/trades', name: 'TradePanel', component: () => import('../views/TradePanel.vue') },
  { path: '/profit', name: 'ProfitChart', component: () => import('../views/ProfitChart.vue') },
  { path: '/time-rules', name: 'TimeRules', component: () => import('../views/TimeRules.vue') },
  { path: '/news', name: 'NewsCenter', component: () => import('../views/NewsCenter.vue') }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router
