<template>
  <div class="app-layout">
    <Sidebar />
    <main class="main-content">
      <TimeStatusBar />
      <router-view />
    </main>
    <!-- 全局 Toast -->
    <div class="toast-container">
      <div v-for="t in toasts" :key="t.id"
           class="toast" :class="'toast-' + t.type">
        {{ t.msg }}
      </div>
    </div>
  </div>
</template>

<script setup>
import Sidebar from './components/Sidebar.vue'
import TimeStatusBar from './components/TimeStatusBar.vue'
import { useToast } from './composables/useToast'

const { toasts } = useToast()
</script>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  background: #f0f2f5;
  color: #333;
}

.app-layout {
  display: flex;
  min-height: 100vh;
}

.main-content {
  flex: 1;
  margin-left: 220px;
  padding: 24px;
  background: #f0f2f5;
}

.card {
  background: #fff;
  border-radius: 8px;
  padding: 20px;
  margin-bottom: 20px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}

.btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 8px 16px;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
  transition: all 0.2s;
}
.btn-primary { background: #1890ff; color: #fff; }
.btn-primary:hover { background: #40a9ff; }
.btn-danger { background: #ff4d4f; color: #fff; }
.btn-danger:hover { background: #ff7875; }
.btn-success { background: #52c41a; color: #fff; }
.btn-success:hover { background: #73d13d; }
.btn-warning { background: #faad14; color: #fff; }
.btn-warning:hover { background: #ffc53d; }
.btn-default { background: #fff; color: #333; border: 1px solid #d9d9d9; }
.btn-default:hover { border-color: #1890ff; color: #1890ff; }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-sm { padding: 4px 10px; font-size: 12px; }

.table-wrap {
  overflow-x: auto;
}
table {
  width: 100%;
  border-collapse: collapse;
}
th, td {
  padding: 10px 12px;
  text-align: left;
  border-bottom: 1px solid #f0f0f0;
  font-size: 14px;
}
th {
  background: #fafafa;
  font-weight: 600;
  color: #555;
  white-space: nowrap;
}
tr:hover td { background: #f5f9ff; }

.form-group {
  margin-bottom: 14px;
}
.form-group label {
  display: block;
  margin-bottom: 4px;
  font-size: 13px;
  color: #555;
  font-weight: 500;
}
.form-group input, .form-group select {
  width: 100%;
  padding: 8px 10px;
  border: 1px solid #d9d9d9;
  border-radius: 4px;
  font-size: 14px;
  outline: none;
  transition: border 0.2s;
}
.form-group input:focus, .form-group select:focus {
  border-color: #1890ff;
  box-shadow: 0 0 0 2px rgba(24,144,255,0.15);
}
.form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 3px;
  font-size: 12px;
  font-weight: 500;
}
.tag-green { background: #f6ffed; color: #52c41a; border: 1px solid #b7eb8f; }
.tag-red { background: #fff2f0; color: #ff4d4f; border: 1px solid #ffccc7; }
.tag-blue { background: #e6f7ff; color: #1890ff; border: 1px solid #91d5ff; }
.tag-orange { background: #fff7e6; color: #fa8c16; border: 1px solid #ffd591; }

.badge {
  display: inline-block;
  min-width: 20px;
  padding: 1px 6px;
  border-radius: 10px;
  font-size: 12px;
  text-align: center;
}
.badge-green { background: #52c41a; color: #fff; }
.badge-red { background: #ff4d4f; color: #fff; }
.badge-blue { background: #1890ff; color: #fff; }

.page-header {
  margin-bottom: 20px;
}
.page-header h2 {
  font-size: 22px;
  font-weight: 600;
  color: #1a1a1a;
}
.page-header p {
  margin-top: 4px;
  color: #888;
  font-size: 14px;
}

.action-bar {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
  flex-wrap: wrap;
  align-items: center;
}

.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}
.modal {
  background: #fff;
  border-radius: 8px;
  width: 520px;
  max-width: 90vw;
  max-height: 85vh;
  overflow-y: auto;
  box-shadow: 0 6px 30px rgba(0,0,0,0.15);
}
.modal-header {
  padding: 16px 20px;
  border-bottom: 1px solid #f0f0f0;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.modal-header h3 { font-size: 16px; font-weight: 600; }
.modal-close {
  background: none;
  border: none;
  font-size: 20px;
  cursor: pointer;
  color: #999;
}
.modal-body { padding: 20px; }
.modal-footer {
  padding: 12px 20px;
  border-top: 1px solid #f0f0f0;
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.empty-state {
  text-align: center;
  padding: 60px 20px;
  color: #999;
}
.empty-state .icon { font-size: 48px; margin-bottom: 12px; }
.empty-state p { font-size: 14px; }

.loading {
  text-align: center;
  padding: 40px;
  color: #999;
}

.toast {
  position: fixed;
  top: 20px;
  right: 20px;
  z-index: 2000;
  padding: 12px 20px;
  border-radius: 6px;
  color: #fff;
  font-size: 14px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.15);
  animation: slideIn 0.3s ease;
}
.toast-success { background: #52c41a; }
.toast-error { background: #ff4d4f; }
.toast-info { background: #1890ff; }

@keyframes slideIn {
  from { transform: translateX(100%); opacity: 0; }
  to { transform: translateX(0); opacity: 1; }
}
.toast-container {
  position: fixed;
  top: 20px;
  right: 20px;
  z-index: 2000;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
</style>
