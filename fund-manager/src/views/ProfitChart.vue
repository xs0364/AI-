<template>
  <div>
    <div class="page-header">
      <h2>收益可视化</h2>
      <p>持仓市值曲线、累计收益曲线、交易记录</p>
    </div>

    <!-- 时间范围选择 -->
    <div class="card">
      <div class="action-bar">
        <label style="font-size:13px;color:#888;">时间范围：</label>
        <select v-model="range" style="padding:4px 12px;border:1px solid #d9d9d9;border-radius:4px;font-size:14px;" @change="regenerateData">
          <option value="7d">近 7 天</option>
          <option value="1m">近 1 个月</option>
          <option value="3m">近 3 个月</option>
          <option value="6m">近 6 个月</option>
          <option value="1y">近 1 年</option>
        </select>
        <span style="margin-left:auto;font-size:13px;color:#888;">
          数据区间：{{ dataStart }} ~ {{ dataEnd }}
        </span>
      </div>
    </div>

    <!-- 错误提示 -->
    <div v-if="error" class="card" style="border-left:4px solid #ff4d4f;">
      <p style="color:#ff4d4f;font-size:14px;">⚠️ {{ error }}</p>
      <p style="color:#888;font-size:12px;margin-top:4px;">已使用本地模拟数据展示</p>
    </div>

    <!-- 加载中 -->
    <div v-if="loading" class="loading">加载中...</div>

    <!-- 持仓市值曲线 -->
    <div class="card">
      <h3 style="margin-bottom:12px;font-size:16px;">持仓市值走势</h3>
      <div ref="valueChartRef" style="width:100%;height:380px;"></div>
      <div v-if="!portfolioData.length && !loading" style="text-align:center;padding:40px 0;color:#999;">暂无市值数据</div>
    </div>

    <!-- 累计收益曲线 -->
    <div class="card">
      <h3 style="margin-bottom:12px;font-size:16px;">累计收益走势</h3>
      <div ref="profitChartRef" style="width:100%;height:380px;"></div>
      <div v-if="!portfolioData.length && !loading" style="text-align:center;padding:40px 0;color:#999;">暂无收益数据</div>
    </div>

    <!-- 交易记录列表 -->
    <div class="card">
      <h3 style="margin-bottom:12px;font-size:16px;">交易记录</h3>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>时间</th>
              <th>基金</th>
              <th>方向</th>
              <th>价格</th>
              <th>数量</th>
              <th>金额</th>
              <th>策略</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!rangeTrades.length">
              <td colspan="7" style="text-align:center;color:#999;padding:40px;">暂无交易记录</td>
            </tr>
            <tr v-for="t in rangeTrades" :key="t.id">
              <td>{{ formatTime(t.time) }}</td>
              <td>{{ fundLabel(t.fundId) }}</td>
              <td>
                <span class="tag" :class="t.direction === 'buy' ? 'tag-green' : 'tag-red'">
                  {{ t.direction === 'buy' ? '买入' : '卖出' }}
                </span>
              </td>
              <td>{{ t.price?.toFixed(4) }}</td>
              <td>{{ t.shares }}</td>
              <td>{{ (t.price * t.shares).toFixed(2) }}</td>
              <td>{{ t.strategy }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch, nextTick, onBeforeUnmount } from 'vue'
import * as echarts from 'echarts'
import { analyticsApi, tradeApi } from '../api'
import { useFundStore } from '../stores/fund'

const fundStore = useFundStore()

const range = ref('1m')
const valueChartRef = ref(null)
const profitChartRef = ref(null)
let valueChart = null
let profitChart = null

const loading = ref(true)
const error = ref(null)

const portfolioData = ref([])   // [{date, totalValue}]
const tradeStats = ref([])      // [{date, trade_count, buy_count, sell_count, total_amount}]
const trades = ref([])          // raw trade records

const DAY_MS = 86400000

const rangeDays = computed(() => {
  const map = { '7d': 7, '1m': 30, '3m': 90, '6m': 180, '1y': 365 }
  return map[range.value] || 30
})

const dataStart = computed(() => {
  if (portfolioData.value.length) return portfolioData.value[0]?.date || '-'
  return '-'
})
const dataEnd = computed(() => {
  if (portfolioData.value.length) return portfolioData.value[portfolioData.value.length - 1]?.date || '-'
  return '-'
})

const rangeTrades = computed(() => {
  const cutoff = Date.now() - rangeDays.value * DAY_MS
  return trades.value.filter(t => new Date(t.time).getTime() >= cutoff)
})

function fundLabel(id) {
  const f = fundStore.list.find(f => f.id === id)
  return f ? `${f.code}` : `ID:${id}`
}

function formatTime(iso) {
  if (!iso) return '-'
  const d = new Date(iso)
  const pad = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

async function fetchData() {
  loading.value = true
  error.value = null
  try {
    const days = rangeDays.value
    // 调后端 API
    const [portRes, tradeStatRes, tradeRes] = await Promise.all([
      analyticsApi.portfolio({ days }),
      analyticsApi.trades({ days }),
      tradeApi.list({ limit: 200 }),
    ])
    portfolioData.value = portRes.data || []
    tradeStats.value = tradeStatRes.data || []
    trades.value = tradeRes.data || []

    // 如果后端有数据，实时刷新图表
    if (portfolioData.value.length || tradeStats.value.length) {
      nextTick(() => initCharts())
    }
  } catch (e) {
    error.value = e.message || '数据加载失败'
    // 后端挂了时用 mock 数据兜底
    fallbackMock()
  } finally {
    loading.value = false
  }
}

function fallbackMock() {
  // 后端不可用时的 mock 兜底
  const count = rangeDays.value
  const now = Date.now()
  const dates = []
  for (let i = count - 1; i >= 0; i--) {
    dates.push(new Date(now - i * DAY_MS).toISOString().slice(0, 10))
  }

  function randomWalk(base, steps, volatility = 0.015) {
    const values = [base]
    for (let i = 1; i < steps; i++) {
      const change = values[i - 1] * volatility * (Math.random() - 0.48)
      values.push(Math.max(values[i - 1] + change, base * 0.6))
    }
    return values
  }

  const currentVal = fundStore.totalValue || 100000
  const pv = randomWalk(currentVal, count)
  portfolioData.value = dates.map((d, i) => ({ date: d, totalValue: pv[i] }))

  nextTick(() => initCharts())
}

function initCharts() {
  if (!valueChartRef.value || !profitChartRef.value) return
  if (!portfolioData.value.length) return

  // 市值曲线
  if (valueChart) valueChart.dispose()
  valueChart = echarts.init(valueChartRef.value)
  valueChart.setOption({
    tooltip: { trigger: 'axis', valueFormatter: v => '¥' + Number(v).toFixed(2) },
    grid: { left: 60, right: 20, bottom: 30, top: 20 },
    xAxis: { type: 'category', data: portfolioData.value.map(d => d.date), axisLabel: { rotate: 45, fontSize: 11 } },
    yAxis: { type: 'value', axisLabel: { formatter: '¥{value}' } },
    series: [{
      data: portfolioData.value.map(d => d.totalValue),
      type: 'line',
      smooth: true,
      lineStyle: { color: '#1890ff', width: 2 },
      areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
        { offset: 0, color: 'rgba(24,144,255,0.3)' },
        { offset: 1, color: 'rgba(24,144,255,0.02)' }
      ]) },
      markLine: { data: [{ type: 'average', name: '均值' }], label: { formatter: '均值: ¥{c}' } }
    }]
  })

  // 收益曲线 — 用 portfolio 数据计算收益
  if (profitChart) profitChart.dispose()
  profitChart = echarts.init(profitChartRef.value)
  const pData = portfolioData.value.map(d => d.totalValue)
  const profitVals = pData.map(v => v - pData[0])
  const colors = profitVals.map(v => v >= 0 ? '#52c41a' : '#ff4d4f')
  profitChart.setOption({
    tooltip: { trigger: 'axis', valueFormatter: v => '¥' + Number(v).toFixed(2) },
    grid: { left: 60, right: 20, bottom: 30, top: 20 },
    xAxis: { type: 'category', data: portfolioData.value.map(d => d.date), axisLabel: { rotate: 45, fontSize: 11 } },
    yAxis: { type: 'value', axisLabel: { formatter: '¥{value}' } },
    series: [{
      data: profitVals.map((v, i) => ({ value: v, itemStyle: { color: colors[i] } })),
      type: 'bar',
      barWidth: '60%',
      markLine: { data: [{ type: 'average', name: '均值' }], label: { formatter: '均值: ¥{c}' } }
    }]
  })
}

function regenerateData() {
  fetchData()
}

onMounted(() => {
  fundStore.fetchList()
  fetchData()
})

watch(range, () => {
  fetchData()
})

onBeforeUnmount(() => {
  valueChart?.dispose()
  profitChart?.dispose()
})
</script>
