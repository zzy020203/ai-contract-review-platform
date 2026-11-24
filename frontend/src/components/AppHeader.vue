<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '../stores/user'

const router = useRouter()
const store = useUserStore()

const NAVS = [
  { path: '/', text: '审查任务', perm: '' },
  { path: '/dashboard', text: '数据看板', perm: 'dashboard:view' },
  { path: '/queue', text: '复核队列', perm: 'review:audit' },
  { path: '/rules', text: '规则管理', perm: 'rule:manage' },
  { path: '/knowledge', text: '知识库', perm: 'knowledge:view' },
  { path: '/audit', text: '审计日志', perm: 'audit:view' },
  { path: '/monitor', text: '系统监控', perm: 'system:manage' },
]

const navs = computed(() => NAVS.filter((n) => !n.perm || store.hasPerm(n.perm)))

function logout() {
  store.logout()
  router.push('/login')
}
</script>

<template>
  <el-header class="header">
    <span class="title" @click="router.push('/')">企业智能合同审查平台</span>
    <div class="right">
      <el-button
        v-for="n in navs" :key="n.path" link type="primary" class="nav"
        @click="router.push(n.path)"
      >{{ n.text }}</el-button>
      <span class="user">{{ store.realName || store.username }}</span>
      <el-button link type="primary" @click="logout">退出</el-button>
    </div>
  </el-header>
</template>

<style scoped>
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #001529;
  color: #fff;
}
.title {
  font-size: 18px;
  font-weight: 600;
  cursor: pointer;
}
.right {
  display: flex;
  align-items: center;
}
.nav {
  color: #a6c8ff;
  margin-right: 12px;
}
.user {
  margin: 0 12px;
}
</style>
