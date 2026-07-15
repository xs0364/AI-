<template>
  <div>
    <div class="page-header">
      <h2>基金持仓管理</h2>
      <p>管理所有基金标的，查看持仓盈亏与实时估值</p>
    </div>

    <!-- 汇总卡片 -->
    <div class="summary-cards">
      <div class="summary-card">
        <div class="sc-label">持仓市值</div>
        <div class="sc-value">{{ fundStore.totalValue.toFixed(2) }}</div>
      </div>
      <div class="summary-card">
        <div class="sc-label">累计成本</div>
        <div class="sc-value">{{ fundStore.totalCost.toFixed(2) }}</div>
      </div>
      <div class="summary-card" :class="fundStore.totalProfit >= 0 ? 'profit' : 'loss'">
        <div class="sc-label">累计盈亏</div>
        <div class="sc-value">{{ fundStore.totalProfit >= 0 ? '+' : '' }}{{ fundStore.totalProfit.toFixed(2) }}</div>
      </div>
      <div class="summary-card" :class="fundStore.totalProfit >= 0 ? 'profit' : 'loss'">
        <div class="sc-label">盈亏率</div>
        <div class="sc-value">{{ fundStore.totalProfitRate }}%</div>
      </div>
    </div>

    <!-- 操作栏 -->
    <div class="card">
      <div class="action-bar">
        <button class="btn btn-primary" @click="openAdd">+ 新增基金</button>
        <button class="btn btn-default" @click="loadData" :disabled="fundStore.loading">刷新数据</button>
        <button class="btn btn-warning" @click="refreshRealtime" :disabled="loadingRealTime">
          {{ loadingRealTime ? '估值更新中...' : '⚡ 更新实时估值' }}
        </button>
        <span v-if="estimateTime" class="est-time">估值时间: {{ estimateTime }}</span>
        <span v-if="fundStore.loading" class="loading-text">加载中...</span>
      </div>

      <!-- 表格 -->
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>基金代码</th>
              <th>基金名称</th>
              <th>持仓份额</th>
              <th>成本价</th>
              <th>持仓价</th>
              <th>实时估值</th>
              <th>估算涨跌</th>
              <th>市值</th>
              <th>盈亏</th>
              <th>盈亏率</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!fundStore.list.length && !fundStore.loading">
              <td colspan="11" style="text-align:center;color:#999;padding:40px;">
                暂无数据，请新增基金
              </td>
            </tr>
            <tr v-for="f in fundStore.list" :key="f.id">
              <td><strong>{{ f.code }}</strong></td>
              <td>{{ f.name }}</td>
              <td>{{ f.shares }}</td>
              <td>{{ f.costPrice?.toFixed(4) }}</td>
              <td>{{ f.currentPrice?.toFixed(4) }}</td>
              <td>
                <span v-if="realtimeMap[f.code]" :class="rtCls(realtimeMap[f.code])">
                  {{ realtimeMap[f.code].gsz }}
                </span>
                <span v-else class="rt-na">-</span>
              </td>
              <td>
                <span v-if="realtimeMap[f.code]" class="tag" :class="rtTagCls(realtimeMap[f.code])">
                  {{ realtimeMap[f.code].gszzl >= 0 ? '+' : '' }}{{ realtimeMap[f.code].gszzl }}%
                </span>
                <span v-else class="tag tag-blue">等待</span>
              </td>
              <td>
                {{ calcMarketValue(f) }}
                <span v-if="realtimeMap[f.code]" class="diff-hint" :class="rtDeltaCls(f, realtimeMap[f.code])">
                  {{ calcDelta(f, realtimeMap[f.code]) }}
                </span>
              </td>
              <td>
                <span :class="profitCls(f)">{{ profit(f) >= 0 ? '+' : '' }}{{ profit(f).toFixed(2) }}</span>
              </td>
              <td>
                <span class="tag" :class="profit(f) >= 0 ? 'tag-green' : 'tag-red'">
                  {{ profitRate(f) >= 0 ? '+' : '' }}{{ profitRate(f) }}%
                </span>
              </td>
              <td>
                <button class="btn btn-sm btn-default" @click="openEdit(f)" style="margin-right:4px;">编辑</button>
                <button class="btn btn-sm btn-danger" @click="confirmRemove(f)">删除</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 弹窗 -->
    <div v-if="showModal" class="modal-overlay" @click.self="closeModal">
      <div class="modal">
        <div class="modal-header">
          <h3>{{ isEdit ? '编辑基金' : '新增基金' }}</h3>
          <button class="modal-close" @click="closeModal">&times;</button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label>基金代码</label>
            <input v-model="form.code" placeholder="如 110011" maxlength="10" />
          </div>
          <div class="form-group">
            <label>基金名称</label>
            <input v-model="form.name" placeholder="如 易方达中小盘混合" />
          </div>
          <div class="form-row">
            <div class="form-group">
              <label>持仓份额</label>
              <input v-model.number="form.shares" type="number" min="0" placeholder="0" />
            </div>
            <div class="form-group">
              <label>成本价</label>
              <input v-model.number="form.costPrice" type="number" step="0.0001" min="0" placeholder="0.0000" />
            </div>
          </div>
          <div class="form-group">
            <label>现价</label>
            <input v-model.number="form.currentPrice" type="number" step="0.0001" min="0" placeholder="0.0000" />
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-default" @click="closeModal">取消</button>
          <button class="btn btn-primary" @click="saveFund" :disabled="!validForm">
            {{ isEdit ? '保存' : '新增' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useFundStore } from '../stores/fund'
import { marketApi } from '../api'

const fundStore = useFundStore()
const showModal = ref(false)
const isEdit = ref(false)
const editingId = ref(null)
const form = ref({ code: '', name: '', shares: 0, costPrice: 0, currentPrice: 0 })

// 实时估值数据
const realtimeMap = reactive({})
const loadingRealTime = ref(false)
const estimateTime = ref('')

const validForm = computed(() =>
  form.value.code && form.value.name && form.value.shares > 0 && form.value.costPrice > 0 && form.value.currentPrice > 0
)

function profit(f) {
  return (f.currentPrice - f.costPrice) * f.shares
}
function profitRate(f) {
  return f.costPrice ? (((f.currentPrice - f.costPrice) / f.costPrice) * 100).toFixed(2) : '0.00'
}
function profitCls(f) {
  return profit(f) >= 0 ? 'tag-green' : 'tag-red'
}

// 实时估值相关
function calcMarketValue(f) {
  if (realtimeMap[f.code]) {
    return (f.shares * parseFloat(realtimeMap[f.code].gsz)).toFixed(2)
  }
  return (f.shares * f.currentPrice).toFixed(2)
}
function calcDelta(f, rt) {
  const estVal = f.shares * parseFloat(rt.gsz)
  const curVal = f.shares * f.currentPrice
  const d = estVal - curVal
  return d >= 0 ? `+${d.toFixed(2)}` : d.toFixed(2)
}
function rtCls(rt) {
  const v = parseFloat(rt.gszzl)
  if (v > 0) return 'rt-up'
  if (v < 0) return 'rt-down'
  return ''
}
function rtTagCls(rt) {
  const v = parseFloat(rt.gszzl)
  if (v > 0) return 'tag-green'
  if (v < 0) return 'tag-red'
  return 'tag-blue'
}
function rtDeltaCls(f, rt) {
  const d = f.shares * parseFloat(rt.gsz) - f.shares * f.currentPrice
  return d >= 0 ? 'delta-up' : 'delta-down'
}

async function refreshRealtime() {
  const codes = fundStore.list.map(f => f.code)
  if (!codes.length) return
  loadingRealTime.value = true
  try {
    const res = await marketApi.batchRealtime(codes.join(','))
    const data = res.data || []
    for (const item of data) {
      if (item.code && !item.error) {
        realtimeMap[item.code] = item
      }
    }
    // 取第一个有效估值时间
    for (const item of data) {
      if (item.gztime) {
        estimateTime.value = item.gztime
        break
      }
    }
  } catch (e) {
    // 后端不可用时静默降级
  } finally {
    loadingRealTime.value = false
  }
}

function resetForm() {
  form.value = { code: '', name: '', shares: 0, costPrice: 0, currentPrice: 0 }
  editingId.value = null
  isEdit.value = false
}

function openAdd() {
  resetForm()
  showModal.value = true
}

function openEdit(f) {
  isEdit.value = true
  editingId.value = f.id
  form.value = { ...f }
  showModal.value = true
}

function closeModal() {
  showModal.value = false
  resetForm()
}

async function saveFund() {
  if (!validForm.value) return
  if (isEdit.value) {
    await fundStore.updateFund(editingId.value, form.value)
  } else {
    await fundStore.createFund(form.value)
  }
  closeModal()
}

async function confirmRemove(f) {
  if (!confirm(`确定删除基金 "${f.name}" (${f.code}) ？`)) return
  await fundStore.removeFund(f.id)
  // 清除对应的实时估值缓存
  delete realtimeMap[f.code]
}

function loadData() {
  fundStore.fetchList()
}

onMounted(() => {
  fundStore.seedMock()
  // 自动拉取实时估值
  setTimeout(() => refreshRealtime(), 500)
})
</script>

<style scoped>
.summary-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 20px;
}
.summary-card {
  background: #fff;
  border-radius: 8px;
  padding: 20px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}
.summary-card .sc-label {
  font-size: 13px;
  color: #888;
  margin-bottom: 8px;
}
.summary-card .sc-value {
  font-size: 24px;
  font-weight: 700;
  font-family: 'Courier New', monospace;
}
.summary-card.profit .sc-value { color: #52c41a; }
.summary-card.loss .sc-value { color: #ff4d4f; }
.loading-text { color: #888; font-size: 13px; margin-left: 8px; }
.est-time { color: #888; font-size: 12px; margin-left: 8px; }

/* 实时估值颜色 */
.rt-up { color: #52c41a; font-weight: 600; }
.rt-down { color: #ff4d4f; font-weight: 600; }
.rt-na { color: #bbb; }
.diff-hint { font-size: 11px; margin-left: 4px; }
.delta-up { color: #52c41a; }
.delta-down { color: #ff4d4f; }

@media (max-width: 1200px) {
  .summary-cards { grid-template-columns: repeat(2, 1fr); }
}
</style>
