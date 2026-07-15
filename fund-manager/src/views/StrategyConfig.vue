<template>
  <div>
    <div class="page-header">
      <h2>量化策略配置</h2>
      <p>选择基金标的，配置均线/网格交易策略参数</p>
    </div>

    <div class="action-bar">
      <button class="btn btn-primary" @click="openAdd">+ 新建策略</button>
      <button class="btn btn-default" @click="loadStrategies">刷新</button>
    </div>

    <div class="card">
      <div v-if="!list.length" class="empty-state">
        <div class="icon">⚙️</div>
        <p>暂无策略配置，点击上方按钮新建</p>
      </div>
      <div v-for="s in list" :key="s.id" class="strategy-card">
        <div class="sc-header">
          <div class="sc-title">
            <strong>{{ s.name }}</strong>
            <span class="tag" :class="s.enabled ? 'tag-green' : 'tag-orange'">
              {{ s.enabled ? '已启用' : '已停用' }}
            </span>
            <span class="tag tag-blue">{{ typeLabel(s.type) }}</span>
          </div>
          <div class="sc-actions">
            <button class="btn btn-sm btn-default" @click="openEdit(s)">编辑</button>
            <button
              class="btn btn-sm"
              :class="s.enabled ? 'btn-warning' : 'btn-success'"
              @click="toggleStrategy(s)"
            >
              {{ s.enabled ? '停用' : '启用' }}
            </button>
            <button class="btn btn-sm btn-danger" @click="removeStrategy(s)">删除</button>
          </div>
        </div>
        <div class="sc-body">
          <div class="sc-info">
            <span class="sc-info-item">
              <label>关联基金：</label>
              {{ fundLabel(s.fundId) }}
            </span>
          </div>
          <div class="sc-params">
            <template v-if="s.type === 'ma'">
              <span class="sc-info-item"><label>均线周期：</label>{{ s.params.period }} 日</span>
              <span class="sc-info-item"><label>上界(%)：</label>{{ s.params.upper }}</span>
              <span class="sc-info-item"><label>下界(%)：</label>{{ s.params.lower }}</span>
            </template>
            <template v-else-if="s.type === 'grid'">
              <span class="sc-info-item"><label>上界价：</label>{{ s.params.upperPrice }}</span>
              <span class="sc-info-item"><label>下界价：</label>{{ s.params.lowerPrice }}</span>
              <span class="sc-info-item"><label>网格层数：</label>{{ s.params.stepCount }}</span>
              <span class="sc-info-item"><label>步长：</label>{{ s.params.stepSize }}</span>
            </template>
          </div>
        </div>
      </div>
    </div>

    <!-- 策略弹窗 -->
    <div v-if="showModal" class="modal-overlay" @click.self="closeModal">
      <div class="modal">
        <div class="modal-header">
          <h3>{{ isEdit ? '编辑策略' : '新建策略' }}</h3>
          <button class="modal-close" @click="closeModal">&times;</button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label>策略名称</label>
            <input v-model="form.name" placeholder="如 均线趋势策略" />
          </div>
          <div class="form-group">
            <label>关联基金</label>
            <select v-model.number="form.fundId">
              <option value="" disabled>-- 选择基金 --</option>
              <option v-for="f in fundStore.list" :key="f.id" :value="f.id">
                {{ f.code }} - {{ f.name }}
              </option>
            </select>
          </div>
          <div class="form-group">
            <label>策略类型</label>
            <select v-model="form.type">
              <option value="ma">均线策略 (MA)</option>
              <option value="grid">网格交易策略 (Grid)</option>
            </select>
          </div>

          <!-- 均线参数 -->
          <template v-if="form.type === 'ma'">
            <div class="form-row">
              <div class="form-group">
                <label>均线周期（日）</label>
                <input v-model.number="form.params.period" type="number" min="1" />
              </div>
              <div class="form-group">
                <label>上界触发 (%)</label>
                <input v-model.number="form.params.upper" type="number" step="0.1" placeholder="如 105" />
              </div>
            </div>
            <div class="form-group">
              <label>下界触发 (%)</label>
              <input v-model.number="form.params.lower" type="number" step="0.1" placeholder="如 95" />
            </div>
          </template>

          <!-- 网格参数 -->
          <template v-if="form.type === 'grid'">
            <div class="form-row">
              <div class="form-group">
                <label>上界价格</label>
                <input v-model.number="form.params.upperPrice" type="number" step="0.01" />
              </div>
              <div class="form-group">
                <label>下界价格</label>
                <input v-model.number="form.params.lowerPrice" type="number" step="0.01" />
              </div>
            </div>
            <div class="form-row">
              <div class="form-group">
                <label>网格层数</label>
                <input v-model.number="form.params.stepCount" type="number" min="2" max="20" />
              </div>
              <div class="form-group">
                <label>步长</label>
                <input v-model.number="form.params.stepSize" type="number" step="0.01" />
              </div>
            </div>
          </template>
        </div>
        <div class="modal-footer">
          <button class="btn btn-default" @click="closeModal">取消</button>
          <button class="btn btn-primary" @click="saveStrategy">保存</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useStrategyStore } from '../stores/strategy'
import { useFundStore } from '../stores/fund'
import { useToast } from '../composables/useToast'

const strategyStore = useStrategyStore()
const fundStore = useFundStore()
const { showToast } = useToast()
const list = computed(() => strategyStore.list)
const showModal = ref(false)
const isEdit = ref(false)
const editingId = ref(null)
const form = ref({
  name: '', fundId: '', type: 'ma',
  params: { period: 20, upper: 105, lower: 95 }
})

function typeLabel(t) {
  return { ma: '均线策略', grid: '网格交易' }[t] || t
}

function fundLabel(id) {
  const f = fundStore.list.find(f => f.id === id)
  return f ? `${f.code} - ${f.name}` : `ID:${id}`
}

function resetForm() {
  form.value = {
    name: '', fundId: '', type: 'ma',
    params: { period: 20, upper: 105, lower: 95 }
  }
  editingId.value = null
  isEdit.value = false
}

function openAdd() {
  resetForm()
  showModal.value = true
}

function openEdit(s) {
  isEdit.value = true
  editingId.value = s.id
  form.value = {
    name: s.name,
    fundId: s.fundId,
    type: s.type,
    params: { ...s.params }
  }
  showModal.value = true
}

function closeModal() {
  showModal.value = false
  resetForm()
}

async function saveStrategy() {
  try {
    if (isEdit.value) {
      await strategyStore.updateStrategy(editingId.value, form.value)
    } else {
      await strategyStore.createStrategy(form.value)
    }
    closeModal()
  } catch (e) {
    showToast(e.message, 'error')
  }
}

async function toggleStrategy(s) {
  try {
    await strategyStore.toggleStrategy(s.id, !s.enabled)
  } catch (e) {
    showToast(e.message, 'error')
  }
}

async function removeStrategy(s) {
  if (!confirm(`确定删除策略 "${s.name}"？`)) return
  try {
    await strategyStore.removeStrategy(s.id)
  } catch (e) {
    showToast(e.message, 'error')
  }
}

function loadStrategies() {
  strategyStore.fetchList()
}

onMounted(() => {
  fundStore.seedMock()
  strategyStore.seedMock(fundStore.list)
})
</script>

<style scoped>
.strategy-card {
  border: 1px solid #e8e8e8;
  border-radius: 8px;
  padding: 16px 20px;
  margin-bottom: 12px;
  transition: box-shadow 0.2s;
}
.strategy-card:hover {
  box-shadow: 0 2px 8px rgba(0,0,0,0.08);
}
.sc-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.sc-title {
  display: flex;
  align-items: center;
  gap: 8px;
}
.sc-title strong { font-size: 16px; }
.sc-actions { display: flex; gap: 6px; }
.sc-body { }
.sc-info {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  margin-bottom: 8px;
}
.sc-params {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
}
.sc-info-item label {
  color: #888;
  font-size: 13px;
}
.sc-info-item {
  font-size: 14px;
}
</style>
