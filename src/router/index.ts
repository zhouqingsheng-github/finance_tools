import { createRouter, createWebHashHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'Dashboard',
    component: () => import('@/views/Dashboard.vue'),
    meta: { title: '仪表盘', icon: 'Monitor' }
  },
  {
    path: '/merchants',
    name: 'MerchantConfig',
    component: () => import('@/views/MerchantConfig.vue'),
    meta: { title: '商家配置', icon: 'Store' }
  },
  {
    path: '/tasks',
    name: 'TaskCenter',
    component: () => import('@/views/TaskCenter.vue'),
    meta: { title: '任务调度', icon: 'PlayCircle' }
  },
  {
    path: '/data',
    name: 'DataView',
    component: () => import('@/views/DataView.vue'),
    meta: { title: '数据查看', icon: 'Database' }
  }
]

const router = createRouter({
  history: createWebHashHistory(),
  routes
})

export default router
