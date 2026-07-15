import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { fundApi } from '../api'
import { useToast } from '../composables/useToast'

export const useFundStore = defineStore('fund', () => {
  const list = ref([])
  const loading = ref(false)
  const error = ref(null)
  const { showToast } = useToast()

  const totalValue = computed(() =>
    list.value.reduce((s, f) => s + (f.shares || 0) * (f.currentPrice || 0), 0)
  )
  const totalCost = computed(() =>
    list.value.reduce((s, f) => s + (f.shares || 0) * (f.costPrice || 0), 0)
  )
  const totalProfit = computed(() => totalValue.value - totalCost.value)
  const totalProfitRate = computed(() =>
    totalCost.value ? ((totalProfit.value / totalCost.value) * 100).toFixed(2) : '0.00'
  )

  async function fetchList() {
    loading.value = true
    error.value = null
    try {
      const res = await fundApi.list()
      list.value = res.data || res
    } catch (e) {
      const msg = e.message || '加载基金列表失败'
      error.value = msg
      showToast(msg, 'error')
    } finally {
      loading.value = false
    }
  }

  async function createFund(data) {
    try {
      const res = await fundApi.create(data)
      list.value.push(res.data || res)
      showToast('新增基金成功', 'success')
      return res
    } catch (e) {
      showToast(e.message || '新增失败', 'error')
      throw e
    }
  }

  async function updateFund(id, data) {
    try {
      const res = await fundApi.update(id, data)
      const idx = list.value.findIndex(f => f.id === id)
      if (idx !== -1) list.value[idx] = res.data || res
      showToast('更新成功', 'success')
      return res
    } catch (e) {
      showToast(e.message || '更新失败', 'error')
      throw e
    }
  }

  async function removeFund(id) {
    try {
      await fundApi.remove(id)
      list.value = list.value.filter(f => f.id !== id)
      showToast('删除成功', 'success')
    } catch (e) {
      showToast(e.message || '删除失败', 'error')
      throw e
    }
  }

  // 模拟数据（开发阶段使用）
  function seedMock() {
    if (list.value.length) return
    list.value = [
      { id: 1, code: '110011', name: '易方达中小盘混合', shares: 5000, costPrice: 1.85, currentPrice: 2.12 },
      { id: 2, code: '005827', name: '中欧医疗健康混合C', shares: 3000, costPrice: 0.82, currentPrice: 0.68 },
      { id: 3, code: '001938', name: '中欧时代先锋股票A', shares: 4000, costPrice: 1.22, currentPrice: 1.35 },
      { id: 4, code: '260108', name: '景顺长城新兴成长混合', shares: 2000, costPrice: 2.05, currentPrice: 1.96 },
      { id: 5, code: '003095', name: '中欧医疗健康混合A', shares: 6000, costPrice: 0.55, currentPrice: 0.72 }
    ]
  }

  return { list, loading, error, totalValue, totalCost, totalProfit, totalProfitRate, fetchList, createFund, updateFund, removeFund, seedMock }
})
