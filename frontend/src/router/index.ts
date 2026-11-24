import { createRouter, createWebHistory } from 'vue-router'
import { useUserStore } from '../stores/user'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('../views/LoginView.vue'), meta: { title: '登录', public: true } },
    { path: '/', name: 'tasks', component: () => import('../views/TaskListView.vue'), meta: { title: '审查任务' } },
    { path: '/dashboard', name: 'dashboard', component: () => import('../views/DashboardView.vue'), meta: { title: '数据看板', perm: 'dashboard:view' } },
    { path: '/queue', name: 'queue', component: () => import('../views/ReviewQueueView.vue'), meta: { title: '复核队列', perm: 'review:audit' } },
    { path: '/rules', name: 'rules', component: () => import('../views/RuleManageView.vue'), meta: { title: '规则管理', perm: 'rule:manage' } },
    { path: '/knowledge', name: 'knowledge', component: () => import('../views/KnowledgeView.vue'), meta: { title: '知识库', perm: 'knowledge:view' } },
    { path: '/audit', name: 'audit', component: () => import('../views/AuditLogView.vue'), meta: { title: '审计日志', perm: 'audit:view' } },
    { path: '/monitor', name: 'monitor', component: () => import('../views/MonitorView.vue'), meta: { title: '系统监控', perm: 'system:manage' } },
    { path: '/review/:id', name: 'detail', component: () => import('../views/ReviewDetailView.vue'), meta: { title: '审查详情' } },
  ],
})

// 导航守卫：未登录跳登录页；按权限码控制页面访问
router.beforeEach((to) => {
  const store = useUserStore()
  if (!to.meta.public && !store.isLoggedIn) {
    return { name: 'login' }
  }
  if (to.name === 'login' && store.isLoggedIn) {
    return { name: 'tasks' }
  }
  if (to.meta.perm && !store.hasPerm(String(to.meta.perm))) {
    return { name: 'tasks' }
  }
})

router.afterEach((to) => {
  document.title = `${String(to.meta.title ?? '')} - 企业智能合同审查平台`
})

export default router
