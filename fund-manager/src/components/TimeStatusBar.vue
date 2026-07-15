<template>
  <div class="time-status-bar" :class="barClass" v-if="status">
    <div class="ts-flex">
      <span class="ts-icon">{{ icon }}</span>
      <span class="ts-label">{{ label }}</span>
      <span class="ts-tag" :class="tagClass">{{ tagText }}</span>
    </div>
    <div class="ts-warning" v-if="warningLine">{{ warningLine }}</div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { timeApi } from '../api'

const status = ref(null)
let timer = null

const icon = computed(() => {
  if (!status.value) return '⏳'
  if (status.value.inOptimalSellWindow) return '🔔'
  if (status.value.inOptimalBuyWindow) return '🟢'
  if (status.value.isTradingDay && status.value.isBefore1500) return '✅'
  if (status.value.isCallAuction) return '⚠️'
  if (!status.value.isTradingDay) return '⏸️'
  return '💹'
})

const label = computed(() => {
  if (!status.value) return '加载中...'
  if (status.value.inOptimalSellWindow) return '止盈窗口已开启'
  if (status.value.inOptimalBuyWindow) return '买入窗口已开启'
  if (status.value.isTradingDay && status.value.isBefore1500) return '交易时段'
  if (!status.value.isTradingDay) return '休市'
  return '已收盘'
})

const barClass = computed(() => {
  if (!status.value) return ''
  if (status.value.inOptimalSellWindow || status.value.inOptimalBuyWindow) return 'bar-warning'
  if (status.value.isTradingDay) return 'bar-normal'
  return 'bar-closed'
})

const tagText = computed(() => {
  if (!status.value) return ''
  return status.value.isBefore1500 ? '15:00前' : '15:00后'
})

const tagClass = computed(() => {
  return status.value?.isBefore1500 ? 'tag-before' : 'tag-after'
})

const warningLine = computed(() => {
  if (!status.value) return ''
  const ws = []
  if (status.value.holidayStrategy?.warnings) {
    ws.push(...status.value.holidayStrategy.warnings)
  }
  if (status.value.tradeInfo?.warnings) {
    ws.push(...status.value.tradeInfo.warnings)
  }
  return ws.length ? ws[0] : ''
})

async function fetchStatus() {
  try {
    status.value = await timeApi.status()
  } catch (_) {}
}

onMounted(() => {
  fetchStatus()
  timer = setInterval(fetchStatus, 60000)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<style scoped>
.time-status-bar {
  padding: 10px 16px;
  margin-bottom: 12px;
  border-radius: 6px;
  font-size: 13px;
  transition: all 0.3s;
}
.bar-normal {
  background: #f6ffed;
  border: 1px solid #b7eb8f;
}
.bar-warning {
  background: #fffbe6;
  border: 1px solid #ffe58f;
}
.bar-closed {
  background: #f5f5f5;
  border: 1px solid #d9d9d9;
}

.ts-flex {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.ts-icon { font-size: 16px; }
.ts-label { font-weight: 600; font-size: 13px; color: #333; }
.ts-tag {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 8px;
  font-weight: 500;
}
.tag-before { background: #e6f7ff; color: #1890ff; border: 1px solid #91d5ff; }
.tag-after { background: #fff2f0; color: #ff4d4f; border: 1px solid #ffccc7; }

.ts-warning {
  margin-top: 6px;
  font-size: 12px;
  color: #d46b08;
  line-height: 1.5;
  padding: 4px 8px;
  background: rgba(250, 173, 20, 0.08);
  border-radius: 4px;
}
</style>
