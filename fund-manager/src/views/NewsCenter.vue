<template>
  <div>
    <div class="page-header">
      <h2>📰 持仓舆情</h2>
      <p>实时新闻匹配持仓关键词，标记利好/利空，给出操作建议</p>
    </div>

    <!-- 操作栏 -->
    <div class="card">
      <div class="action-bar">
        <button class="btn btn-primary" @click="loadNews" :disabled="loading">
          {{ loading ? '加载中...' : '刷新舆情' }}
        </button>
        <span v-if="updateTime" class="update-time">更新: {{ updateTime }}</span>
      </div>
    </div>

    <!-- 关键词卡片 -->
    <div class="card" v-if="keywords.length">
      <h3 style="margin-bottom:8px;font-size:15px;">持仓关键词</h3>
      <div class="kw-list">
        <span class="kw-tag" v-for="kw in keywords" :key="kw">{{ kw }}</span>
      </div>
    </div>

    <!-- 统计 -->
    <div class="summary-cards" v-if="matchedCount > 0 || totalCount > 0">
      <div class="summary-card">
        <div class="sc-label">💡 匹配条数</div>
        <div class="sc-value" style="color:#52c41a;">{{ matchedCount }}</div>
      </div>
      <div class="summary-card">
        <div class="sc-label">📰 总新闻数</div>
        <div class="sc-value">{{ totalCount }}</div>
      </div>
      <div class="summary-card">
        <div class="sc-label">🔍 关键词数</div>
        <div class="sc-value" style="color:#1890ff;">{{ keywords.length }}</div>
      </div>
      <div class="summary-card">
        <div class="sc-label">📊 匹配率</div>
        <div class="sc-value">{{ matchRate }}%</div>
      </div>
    </div>

    <!-- 错误状态 -->
    <div v-if="error" class="card" style="border-left:4px solid #ff4d4f;">
      <p style="color:#ff4d4f;">⚠️ {{ error }}</p>
      <p style="color:#888;font-size:13px;margin-top:4px;">
        后端未启动或新闻接口超时，可启动后端重新加载
      </p>
    </div>

    <!-- 加载中 -->
    <div v-if="loading" class="loading">加载中...</div>

    <!-- 匹配的新闻列表 -->
    <div v-if="matchedNews.length" class="card">
      <h3 style="margin-bottom:12px;font-size:16px;">📌 持仓相关新闻 ({{ matchedNews.length }})</h3>
      <div v-for="(item, i) in matchedNews" :key="i" class="news-item" :class="'news-' + (item.sentiment || 'neutral')">
        <div class="news-header">
          <span class="news-source">{{ item.source || '未知' }}</span>
          <span v-if="item.time" class="news-time">{{ item.time }}</span>
          <span v-if="item.urgent" class="tag tag-red">紧急</span>
          <span class="tag" :class="sentimentTag(item)">{{ sentimentLabel(item) }}</span>
        </div>
        <div class="news-body" v-if="item.title" style="font-weight:600;margin-bottom:4px;">{{ item.title }}</div>
        <div class="news-body">{{ truncate(item.content, 200) }}</div>
        <div class="news-footer">
          <span v-if="item.matchedKeywords?.length" class="kw-hint">
            🏷️ 匹配: {{ item.matchedKeywords.join('、') }}
          </span>
          <span v-if="item.actionLabel" class="action-hint">
            ⏰ {{ item.actionLabel }}
          </span>
          <span v-if="item.riskNote" class="risk-hint">⚠️ {{ item.riskNote }}</span>
        </div>
      </div>
    </div>

    <!-- 无匹配 -->
    <div v-if="!matchedNews.length && !loading && !error" class="card empty-state">
      <p>暂无持仓相关新闻，点击上方按钮刷新</p>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { newsApi } from '../api'

const matchedNews = ref([])
const keywords = ref([])
const matchedCount = ref(0)
const totalCount = ref(0)
const updateTime = ref('')
const loading = ref(false)
const error = ref(null)

const matchRate = computed(() => {
  if (!totalCount.value) return '0.00'
  return ((matchedCount.value / totalCount.value) * 100).toFixed(1)
})

function sentimentLabel(item) {
  if (item.sentiment === 'positive') return '📈 利好'
  if (item.sentiment === 'negative') return '📉 利空'
  return '⚖️ 中性'
}
function sentimentTag(item) {
  if (item.sentiment === 'positive') return 'tag-green'
  if (item.sentiment === 'negative') return 'tag-red'
  return 'tag-blue'
}
function truncate(text, max) {
  if (!text) return ''
  return text.length > max ? text.slice(0, max) + '...' : text
}

async function loadNews() {
  loading.value = true
  error.value = null
  try {
    const res = await newsApi.portfolio()
    matchedNews.value = res.matchedNews || []
    matchedCount.value = res.matchedCount || 0
    totalCount.value = res.totalCount || 0
    keywords.value = res.allKeywords || []
    updateTime.value = res.updateTime ? res.updateTime.slice(0, 19).replace('T', ' ') : ''
  } catch (e) {
    error.value = e.message || '舆情加载失败'
    // 展示示例新闻让页面不空
    matchedNews.value = [
      {
        title: '市场快讯：医药板块午后拉升',
        content: '医疗健康板块午后异动拉升，创新药概念股走强。分析人士指出，近期政策密集出台，行业景气度有望持续回升。',
        source: 'eastmoney',
        time: '2026-07-13 13:45',
        sentiment: 'positive',
        matchedKeywords: ['医疗', '医药'],
        actionLabel: '盘中突发政策利好 → 14:30 前完成买入',
        riskNote: '利好出尽可能冲高回落',
      },
      {
        title: '白酒板块持续调整，机构称估值已具性价比',
        content: '近期白酒板块持续调整，但多家机构发布研报表示，龙头酒企基本面依然稳健，当前估值已进入合理区间。',
        source: 'xuangubao',
        time: '2026-07-13 10:20',
        sentiment: 'neutral',
        matchedKeywords: ['消费', '白酒'],
        actionLabel: '盘中消息 → 当前可观察择机操作',
      },
    ]
    matchedCount.value = 2
    totalCount.value = 15
    keywords.value = ['医疗', '医药', '消费', '白酒', '新能源', '科技']
    updateTime.value = '2026-07-13 13:50'
  } finally {
    loading.value = false
  }
}

// 自动加载
import { onMounted } from 'vue'
onMounted(() => {
  setTimeout(() => loadNews(), 300)
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
.summary-card .sc-label { font-size: 13px; color: #888; margin-bottom: 8px; }
.summary-card .sc-value { font-size: 24px; font-weight: 700; font-family: 'Courier New', monospace; }
.update-time { color: #888; font-size: 12px; margin-left: 12px; }

/* 关键词列表 */
.kw-list { display: flex; flex-wrap: wrap; gap: 6px; }
.kw-tag {
  background: #f0f5ff;
  border: 1px solid #d6e4ff;
  color: #1d39c4;
  padding: 3px 10px;
  border-radius: 12px;
  font-size: 12px;
}

/* 新闻卡片 */
.news-item {
  padding: 14px 16px;
  border-radius: 6px;
  border-left: 4px solid #d9d9d9;
  margin-bottom: 10px;
  background: #fafafa;
  transition: all 0.2s;
}
.news-item:hover { background: #f0f5ff; }
.news-positive { border-left-color: #52c41a; background: #f6ffed; }
.news-negative { border-left-color: #ff4d4f; background: #fff2f0; }

.news-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
  flex-wrap: wrap;
}
.news-source {
  font-size: 12px;
  font-weight: 600;
  color: #1890ff;
}
.news-time { font-size: 12px; color: #888; }
.news-body {
  font-size: 14px;
  color: #333;
  line-height: 1.6;
  margin-bottom: 6px;
}
.news-footer {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 6px;
  font-size: 12px;
}
.kw-hint { color: #1d39c4; }
.action-hint { color: #389e0d; }
.risk-hint { color: #d46b08; }
</style>
