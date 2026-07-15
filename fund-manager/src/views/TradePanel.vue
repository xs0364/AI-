<template>
  <div>
    <div class="page-header">
      <h2>模拟交易面板</h2>
      <p>实时展示策略生成的买卖信号，支持手动触发一次策略扫描</p>
    </div>

    <!-- 时间提示条 -->
    <div class="time-hint" :class="timeHintClass" v-if="timeHint">
      <span class="th-icon">{{ timeHintIcon }}</span>
      <span class="th-text">{{ timeHint }}</span>
    </div>

    <!-- 操作栏 -->
    <div class="card">
      <div class="action-bar">
        <button class="btn btn-primary" @click="triggerScan" :disabled="tradeStore.scanning">
          {{ tradeStore.scanning ? '扫描中...' : '触发策略扫描' }}
        </button>
        <button class="btn btn-default" @click="loadTrades">刷新</button>

        <div style="margin-left:auto;display:flex;gap:8px;align-items:center;">
          <label style="font-size:13px;color:#888;">方向：</label>
          <select v-model="tradeStore.filter.direction" style="padding:4px 8px;border:1px solid #d9d9d9;border-radius:4px;">
            <option value="">全部</option>
            <option value="buy">买入</option>
            <option value="sell">卖出</option>
          </select>

          <label style="font-size:13px;color:#888;">策略：</label>
          <select v-model="tradeStore.filter.strategyId" style="padding:4px 8px;border:1px solid #d9d9d9;border-radius:4px;">
            <option value="">全部</option>
            <option v-for="s in strategyList" :key="s.id" :value="s.id">{{ s.name }}</option>
          </select>
        </div>
      </div>
    </div>

    <!-- 交易统计 -->
    <div class="summary-cards">
      <div class="summary-card">
        <div class="sc-label">总交易次数</div>
        <div class="sc-value">{{ tradeStore.trades.length }}</div>
      </div>
      <div class="summary-card">
        <div class="sc-label">买入次数</div>
        <div class="sc-value" style="color:#52c41a;">{{ buyCount }}</div>
      </div>
      <div class="summary-card">
        <div class="sc-label">卖出次数</div>
        <div class="sc-value" style="color:#ff4d4f;">{{ sellCount }}</div>
      </div>
      <div class="summary-card">
        <div class="sc-label">最后更新</div>
        <div class="sc-value" style="font-size:14px;">{{ latestTime }}</div>
      </div>
    </div>

    <!-- 交易列表 -->
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
              <th>策略来源</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!displayList.length">
              <td colspan="8" style="text-align:center;color:#999;padding:40px;">
                {{ tradeStore.trades.length ? '无匹配筛选条件' : '暂无交易记录' }}
              </td>
            </tr>
            <tr v-for="t in displayList" :key="t.id">
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
              <td><span class="tag tag-blue">已成交</span></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { useTradeStore } from '../stores/trade'
import { useFundStore } from '../stores/fund'
import { useStrategyStore } from '../stores/strategy'
import { useToast } from '../composables/useToast'
import { timeApi } from '../api'

const tradeStore = useTradeStore()
const fundStore = useFundStore()
const strategyStore = useStrategyStore()
const { showToast } = useToast()

// ── 交易时间状态 ──
import { ref } from 'vue'
const timeStatus = ref(null)
const timeHint = ref('')
const timeHintIcon = ref('')
const timeHintClass = ref('')

async function loadTimeStatus() {
  try {
    const s = await timeApi.status()
    timeStatus.value = s
    if (s.inOptimalSellWindow) {
      timeHint.value = '当前为最佳止盈窗口 14:40-14:55，可锁定当日高点净值'
      timeHintIcon.value = '🔔'
      timeHintClass.value = 'hint-sell'
    } else if (s.inOptimalBuyWindow) {
      timeHint.value = '当前为最佳买入窗口 14:30-14:55，抓紧操作卡死15点'
      timeHintIcon.value = '🟢'
      timeHintClass.value = 'hint-buy'
    } else if (s.inMorningNewsWindow) {
      timeHint.value = '早盘利好窗口 9:30-10:00，隔夜消息可操作'
      timeHintIcon.value = '🌅'
      timeHintClass.value = 'hint-buy'
    } else if (!s.isTradingDay) {
      timeHint.value = '今日休市，可提前规划明日操作'
      timeHintIcon.value = '⏸️'
      timeHintClass.value = 'hint-closed'
    } else if (s.isCallAuction) {
      timeHint.value = '尾盘集合竞价时段 14:57-15:00，不可撤单'
      timeHintIcon.value = '⚠️'
      timeHintClass.value = 'hint-warn'
    } else if (s.isTradingDay && s.isBefore1500) {
      timeHint.value = ''
      timeHintIcon.value = ''
    } else {
      timeHint.value = '15:00 后操作将顺延至下一交易日，注意净值差异'
      timeHintIcon.value = '⏰'
      timeHintClass.value = 'hint-warn'
    }
  } catch (_) {}
}

const displayList = computed(() => tradeStore.filteredTrades)
const strategyList = computed(() => strategyStore.list)

const buyCount = computed(() => tradeStore.trades.filter(t => t.direction === 'buy').length)
const sellCount = computed(() => tradeStore.trades.filter(t => t.direction === 'sell').length)
const latestTime = computed(() => {
  if (!tradeStore.trades.length) return '-'
  const t = tradeStore.trades[0].time
  return formatTime(t)
})

function fundLabel(id) {
  const f = fundStore.list.find(f => f.id === id)
  return f ? `${f.code}` : `ID:${id}`
}

function formatTime(iso) {
  if (!iso) return '-'
  const d = new Date(iso)
  const pad = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

async function triggerScan() {
  try {
    await tradeStore.triggerScan()
  } catch (e) {
    showToast(e.message, 'error')
  }
}

function loadTrades() {
  tradeStore.fetchTrades()
}

onMounted(() => {
  fundStore.seedMock()
  strategyStore.seedMock()
  tradeStore.seedMock()
  loadTimeStatus()
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

/* 时间提示条 */
.time-hint {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  margin-bottom: 16px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
}
.hint-buy {
  background: #f6ffed;
  border: 1px solid #b7eb8f;
  color: #389e0d;
}
.hint-sell {
  background: #fffbe6;
  border: 1px solid #ffe58f;
  color: #d48806;
}
.hint-warn {
  background: #fff2f0;
  border: 1px solid #ffccc7;
  color: #cf1322;
}
.hint-closed {
  background: #f5f5f5;
  border: 1px solid #d9d9d9;
  color: #888;
}
.th-icon { font-size: 18px; }
.th-text { line-height: 1.5; }
</style>
