<template>
  <div>
    <div class="page-header">
      <h2>
        <span style="margin-right:8px;">⏰</span>
        交易时间知识库
      </h2>
      <p>基金买卖盈利必须卡死的所有时间节点 — 场外/场内/QDII/节假日/操作窗口</p>
    </div>

    <!-- 实时交易状态 -->
    <div class="card status-card" :class="statusClass">
      <div class="status-header">
        <div class="status-icon-wrapper">
          <span class="status-icon">{{ statusIcon }}</span>
        </div>
        <div class="status-meta">
          <div class="status-label">{{ statusLabel }}</div>
          <div class="status-time">{{ currentTime }}</div>
          <div class="status-detail">{{ statusDetail }}</div>
        </div>
        <div class="status-badges">
          <span class="status-badge" :class="tradingDay ? 'badge-green' : 'badge-red'">
            {{ tradingDay ? '交易日' : '休市' }}
          </span>
          <span class="status-badge" :class="before1500 ? 'badge-blue' : 'badge-red'">
            {{ before1500 ? '15:00前' : '15:00后' }}
          </span>
        </div>
      </div>
      <div class="status-warnings" v-if="warnings.length">
        <div class="warning-item" v-for="(w, i) in warnings" :key="i">{{ w }}</div>
      </div>
    </div>

    <!-- 黄金4条 (顶部置顶) -->
    <div class="card golden-card">
      <div class="golden-header">🏆 极简盈利 4 条</div>
      <div class="golden-rules">
        <div class="golden-rule" v-for="(rule, i) in goldenRules" :key="i">
          <span class="golden-num">{{ i + 1 }}</span>
          <span class="golden-text">{{ rule }}</span>
        </div>
      </div>
    </div>

    <!-- 知识库分类 -->
    <div v-for="section in sections" :key="section.id" class="card">
      <div class="section-header">
        <span class="section-icon">{{ section.icon }}</span>
        <h3>{{ section.title }}</h3>
      </div>

      <div v-for="(rule, ri) in section.rules" :key="ri" class="rule-block">
        <div class="rule-title">{{ rule.title }}</div>
        <ul class="rule-items">
          <li v-for="(item, ii) in rule.items" :key="ii" v-html="renderItem(item)"></li>
        </ul>
        <div v-if="rule.warning" class="rule-warning">{{ rule.warning }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { timeApi } from '../api'

const status = ref(null)
const knowledge = ref(null)
const loading = ref(true)

const goldenRules = computed(() => {
  if (!knowledge.value) return []
  const gs = knowledge.value.sections.find(s => s.id === 'golden_rules')
  return gs?.rules[0]?.items || []
})

const sections = computed(() => {
  if (!knowledge.value) return []
  return knowledge.value.sections.filter(s => s.id !== 'golden_rules')
})

const tradingDay = computed(() => status.value?.isTradingDay ?? false)
const before1500 = computed(() => status.value?.isBefore1500 ?? false)
const currentTime = computed(() => {
  const t = status.value?.currentTime
  if (!t) return ''
  const d = new Date(t)
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}:${String(d.getSeconds()).padStart(2,'0')}`
})

const statusLabel = computed(() => status.value?.statusLabel || '加载中...')
const statusDetail = computed(() => {
  if (!status.value) return ''
  if (status.value.inOptimalBuyWindow) return '最佳买入窗口已开启，抓紧操作'
  if (status.value.inOptimalSellWindow) return '最佳止盈窗口已开启，锁定利润'
  if (status.value.inMorningNewsWindow) return '早盘利好窗口，隔夜消息可操作'
  if (status.value.isCallAuction) return '尾盘集合竞价时段，不可撤单'
  if (status.value.isTradingDay && status.value.isBefore1500) return '场内交易中，场外15点前可操作'
  if (!status.value.isTradingDay) return '今日休市，可提前规划明日操作'
  return ''
})

const warnings = computed(() => {
  const ws = []
  if (status.value?.holidayStrategy?.warnings) {
    ws.push(...status.value.holidayStrategy.warnings)
  }
  if (status.value?.tradeInfo?.warnings) {
    ws.push(...status.value.tradeInfo.warnings)
  }
  return ws
})

const statusIcon = computed(() => {
  if (status.value?.inOptimalSellWindow) return '🔔'
  if (status.value?.inOptimalBuyWindow) return '🟢'
  if (status.value?.isCallAuction) return '⚠️'
  if (status.value?.isTradingDay && status.value?.isBefore1500) return '✅'
  return '⏸️'
})

const statusClass = computed(() => {
  if (status.value?.inOptimalSellWindow || status.value?.inOptimalBuyWindow) return 'status-urgent'
  if (status.value?.isTradingDay) return 'status-normal'
  return 'status-closed'
})

function renderItem(text) {
  return text
    .replace(/🚨/g, '<span class="emoji-em">🚨</span>')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
}

async function loadData() {
  loading.value = true
  try {
    const [s, kb] = await Promise.all([
      timeApi.status(),
      timeApi.knowledge()
    ])
    status.value = s
    knowledge.value = kb
  } catch (e) {
    console.error('加载交易时间知识库失败', e)
  } finally {
    loading.value = false
  }
}

onMounted(loadData)
</script>

<style scoped>
.status-card {
  transition: all 0.3s;
  border-left: 4px solid #999;
}
.status-normal { border-left-color: #52c41a; }
.status-urgent { border-left-color: #faad14; background: #fffbe6; }
.status-closed { border-left-color: #d9d9d9; }

.status-header {
  display: flex;
  align-items: center;
  gap: 16px;
}
.status-icon-wrapper {
  width: 48px;
  height: 48px;
  border-radius: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
  background: #f5f5f5;
}
.status-meta { flex: 1; }
.status-label { font-size: 18px; font-weight: 700; margin-bottom: 4px; }
.status-time { font-size: 13px; color: #888; font-family: 'Courier New', monospace; }
.status-detail { font-size: 13px; color: #666; margin-top: 2px; }
.status-badges { display: flex; gap: 8px; flex-shrink: 0; }
.status-badge {
  display: inline-block;
  padding: 4px 12px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 600;
}
.badge-green { background: #f6ffed; color: #52c41a; border: 1px solid #b7eb8f; }
.badge-red { background: #fff2f0; color: #ff4d4f; border: 1px solid #ffccc7; }
.badge-blue { background: #e6f7ff; color: #1890ff; border: 1px solid #91d5ff; }

.status-warnings {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #f0f0f0;
}
.warning-item {
  padding: 8px 12px;
  margin-bottom: 4px;
  background: #fff7e6;
  border-radius: 4px;
  font-size: 13px;
  color: #d46b08;
  border-left: 3px solid #faad14;
}

/* 黄金四法则 */
.golden-card {
  background: linear-gradient(135deg, #fff7e6 0%, #fffbe6 100%);
  border: 1px solid #ffe58f;
}
.golden-header {
  font-size: 18px;
  font-weight: 700;
  margin-bottom: 16px;
  color: #d48806;
}
.golden-rules {
  display: grid;
  gap: 12px;
}
.golden-rule {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 10px 14px;
  background: rgba(255,255,255,0.7);
  border-radius: 6px;
}
.golden-num {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 12px;
  background: #faad14;
  color: #fff;
  font-size: 13px;
  font-weight: 700;
  flex-shrink: 0;
}
.golden-text {
  font-size: 15px;
  font-weight: 500;
  color: #333;
  line-height: 1.6;
}

/* 知识库区域 */
.section-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
  padding-bottom: 10px;
  border-bottom: 2px solid #f0f0f0;
}
.section-header h3 {
  font-size: 17px;
  font-weight: 600;
  color: #1a1a1a;
}
.section-icon { font-size: 22px; }

.rule-block {
  margin-bottom: 16px;
  padding: 14px;
  background: #fafafa;
  border-radius: 6px;
}
.rule-title {
  font-size: 14px;
  font-weight: 600;
  color: #333;
  margin-bottom: 8px;
}
.rule-items {
  margin: 0;
  padding-left: 18px;
  list-style: disc;
}
.rule-items li {
  font-size: 13px;
  color: #555;
  line-height: 1.7;
  margin-bottom: 4px;
}
.rule-warning {
  margin-top: 8px;
  padding: 8px 12px;
  background: #fff2f0;
  border-radius: 4px;
  font-size: 13px;
  color: #cf1322;
  border-left: 3px solid #ff4d4f;
}
.rule-warning::before {
  content: '⚠️ ';
}

:deep(.emoji-em) { font-size: 16px; }
</style>
