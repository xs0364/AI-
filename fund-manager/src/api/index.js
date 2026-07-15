import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 10000,
  headers: { 'Content-Type': 'application/json' }
})

api.interceptors.response.use(
  res => res.data,
  err => {
    const msg = err.response?.data?.message || err.message || '请求失败'
    console.error('[API Error]', msg)
    return Promise.reject(new Error(msg))
  }
)

/* ---- 基金 ---- */
export const fundApi = {
  list: () => api.get('/funds'),
  get: id => api.get(`/funds/${id}`),
  create: data => api.post('/funds', data),
  update: (id, data) => api.put(`/funds/${id}`, data),
  remove: id => api.delete(`/funds/${id}`)
}

/* ---- 策略 ---- */
export const strategyApi = {
  list: () => api.get('/strategies'),
  create: data => api.post('/strategies', data),
  update: (id, data) => api.put(`/strategies/${id}`, data),
  remove: id => api.delete(`/strategies/${id}`),
  toggle: (id, enabled) => api.patch(`/strategies/${id}/toggle`, { enabled })
}

/* ---- 交易 ---- */
export const tradeApi = {
  list: (params) => api.get('/trades', { params }),
  scan: () => api.post('/trades/scan')
}

/* ---- 收益/持仓走势 ---- */
export const analyticsApi = {
  portfolio: (params) => api.get('/analytics/portfolio', { params }),
  trades: (params) => api.get('/analytics/trades', { params }),
  summary: () => api.get('/analytics/summary')
}

/* ---- 交易时间引擎 ---- */
export const timeApi = {
  status: () => api.get('/time/status'),
  knowledge: () => api.get('/time/knowledge'),
  tradeInfo: (params) => api.get('/time/trade-info', { params }),
  redemptionFee: (params) => api.get('/time/redemption-fee', { params }),
  qdii: (params) => api.get('/time/qdii', { params }),
  newsWindow: (params) => api.get('/time/news-window', { params })
}

/* ---- 实时行情 ---- */
export const marketApi = {
  fundRealtime: code => api.get(`/market/fund/${code}/realtime`),
  fundHistory: (code, params) => api.get(`/market/fund/${code}/history`, { params }),
  etfTrend: (etfCode, params) => api.get(`/market/etf/${etfCode}/trend`, { params }),
  holdings: code => api.get(`/market/fund/${code}/holdings`),
  fundList: () => api.get('/market/fund-list'),
  batchRealtime: (codes) => api.get('/market/batch-realtime', { params: { codes } })
}

/* ---- 新闻舆情 ---- */
export const newsApi = {
  latest: () => api.get('/news/latest'),
  portfolio: () => api.get('/news/portfolio'),
  holdingsKeywords: () => api.get('/news/holdings-keywords')
}

export default api
