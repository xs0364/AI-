import { defineStore } from 'pinia'
import { ref } from 'vue'
import { strategyApi } from '../api'
import { useToast } from '../composables/useToast'

export const useStrategyStore = defineStore('strategy', () => {
  const list = ref([])
  const loading = ref(false)
  const { showToast } = useToast()

  async function fetchList() {
    loading.value = true
    try {
      const res = await strategyApi.list()
      list.value = res.data || res
    } catch (e) {
      showToast(e.message || '加载策略失败', 'error')
    } finally {
      loading.value = false
    }
  }

  async function createStrategy(data) {
    try {
      const res = await strategyApi.create(data)
      list.value.push(res.data || res)
      showToast('策略创建成功', 'success')
      return res
    } catch (e) {
      showToast(e.message || '创建策略失败', 'error')
      throw e
    }
  }

  async function updateStrategy(id, data) {
    try {
      const res = await strategyApi.update(id, data)
      const idx = list.value.findIndex(s => s.id === id)
      if (idx !== -1) list.value[idx] = res.data || res
      showToast('策略更新成功', 'success')
      return res
    } catch (e) {
      showToast(e.message || '更新策略失败', 'error')
      throw e
    }
  }

  async function removeStrategy(id) {
    try {
      await strategyApi.remove(id)
      list.value = list.value.filter(s => s.id !== id)
      showToast('策略已删除', 'success')
    } catch (e) {
      showToast(e.message || '删除策略失败', 'error')
      throw e
    }
  }

  async function toggleStrategy(id, enabled) {
    try {
      const res = await strategyApi.toggle(id, enabled)
      const idx = list.value.findIndex(s => s.id === id)
      if (idx !== -1) list.value[idx].enabled = enabled
      showToast(enabled ? '策略已启用' : '策略已停用', 'success')
      return res
    } catch (e) {
      showToast(e.message || '操作失败', 'error')
      throw e
    }
  }

  function seedMock(funds) {
    if (list.value.length) return
    list.value = [
      {
        id: 1, fundId: 1, name: '均线趋势策略',
        type: 'ma', params: { period: 20, upper: 105, lower: 95 },
        enabled: true
      },
      {
        id: 2, fundId: 3, name: '网格交易策略',
        type: 'grid', params: { upperPrice: 1.50, lowerPrice: 1.00, stepCount: 5, stepSize: 0.10 },
        enabled: false
      },
      {
        id: 3, fundId: 5, name: '均线网格混合',
        type: 'ma', params: { period: 10, upper: 103, lower: 97 },
        enabled: true
      }
    ]
  }

  return { list, loading, fetchList, createStrategy, updateStrategy, removeStrategy, toggleStrategy, seedMock }
})
