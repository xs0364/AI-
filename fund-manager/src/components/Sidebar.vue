<template>
  <aside class="sidebar">
    <div class="sidebar-logo">基金持仓管理</div>
    <nav class="sidebar-nav">
      <router-link
        v-for="item in navItems"
        :key="item.path"
        :to="item.path"
        class="nav-item"
        :class="{ active: $route.path === item.path }"
      >
        <span class="nav-icon">{{ item.icon }}</span>
        <span class="nav-label">{{ item.label }}</span>
      </router-link>
    </nav>
  </aside>
</template>

<script setup>
const navItems = [
  { path: '/funds', label: '基金持仓', icon: '📊' },
  { path: '/strategies', label: '策略配置', icon: '⚙️' },
  { path: '/trades', label: '交易面板', icon: '💹' },
  { path: '/profit', label: '收益可视化', icon: '📈' },
  { path: '/news', label: '持仓舆情', icon: '📰' },
  { path: '/time-rules', label: '时间知识库', icon: '⏰' }
]
</script>

<style scoped>
.sidebar {
  position: fixed;
  left: 0;
  top: 0;
  bottom: 0;
  width: 220px;
  background: #001529;
  color: #fff;
  display: flex;
  flex-direction: column;
  z-index: 100;
}
.sidebar-logo {
  height: 60px;
  line-height: 60px;
  text-align: center;
  font-size: 18px;
  font-weight: 700;
  letter-spacing: 1px;
  background: #002140;
  border-bottom: 1px solid #003a5c;
}
.sidebar-nav {
  flex: 1;
  padding: 12px 0;
  overflow-y: auto;
}
.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 24px;
  color: rgba(255,255,255,0.7);
  text-decoration: none;
  font-size: 14px;
  transition: all 0.2s;
  cursor: pointer;
  border-left: 3px solid transparent;
}
.nav-item:hover {
  color: #fff;
  background: rgba(255,255,255,0.08);
}
.nav-item.active,
.nav-item.router-link-exact-active {
  color: #fff;
  background: #1890ff;
  border-left-color: #69c0ff;
}
.nav-icon { font-size: 16px; width: 20px; text-align: center; }
.nav-label { font-size: 14px; }
</style>
