import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { tradeApi } from '../api'
import { useToast } from '../composables/useToast'

export const useTradeStore = defineStore('trade', () => {
  const trades = ref([])
  const loading = ref(false)
  const scanning = ref(false)
  const filter = ref({ direction: '', strategyId: '' })
  const { showToast } = useToast()

  const filteredTrades = computed(() =>
    trades.value.filter(t => {
      if (filter.value.direction && t.direction !== filter.value.direction) return false
      if (filter.value.strategyId && t.strategyId !== Number(filter.value.strategyId)) return false
      return true
    })
  )

  async function fetchTrades(params) {
    loading.value = true
    try {
      const res = await tradeApi.list(params)
      trades.value = res.data || res
    } catch (e) {
      showToast(e.message || '加载交易记录失败', 'error')
    } finally {
      loading.value = false
    }
  }

  async function triggerScan() {
    scanning.value = true
    try {
      const res = await tradeApi.scan()
      await fetchTrades()
      showToast('策略扫描完成，已生成交易信号', 'success')
      return res
    } catch (e) {
      showToast(e.message || '策略扫描失败', 'error')
    } finally {
      scanning.value = false
    }
  }

  function addTrade(trade) {
    trades.value.unshift(trade)
  }

  function seedMock() {
    if (trades.value.length) return
    const now = Date.now()
    const signals = [
      { time: now - 3600000 * 2, fundId: 1, direction: 'buy', price: 2.10, shares: 200, strategy: '均线趋势策略', strategyId: 1 },
      { time: now - 3600000 * 5, fundId: 3, direction: 'sell', price: 1.36, shares: 300, strategy: '均线趋势策略', strategyId: 1 },
      { time: now - 86400000, fundId: 5, direction: 'buy', price: 0.71, shares: 500, strategy: '均线网格混合', strategyId: 3 },
      { time: now - 86400000 * 2, fundId: 1, direction: 'sell', price: 2.08, shares: 150, strategy: '均线趋势策略', strategyId: 1 },
      { time: now - 86400000 * 3, fundId: 3, direction: 'buy', price: 1.32, shares: 400, strategy: '网格交易策略', strategyId: 2 }
    ]
    trades.value = signals.map((s, i) => ({
      id: i + 1,
      ...s,
      status: 'executed',
      time: new Date(s.time).toISOString()
    }))
  }

  return { trades, filteredTrades, loading, scanning, filter, fetchTrades, triggerScan, addTrade, seedMock }
})
