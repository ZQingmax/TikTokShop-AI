import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { refreshSession, session } from '@/api/session'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/LoginView.vue'),
    meta: { requiresAuth: false },
  },
  {
    path: '/',
    component: () => import('@/layouts/DefaultLayout.vue'),
    meta: { requiresAuth: true },
    redirect: '/dashboard',
    children: [
      {
        path: 'sourcing',
        name: 'Sourcing',
        component: () => import('@/views/SourcingView.vue'),
        meta: { title: '选品中心', requiresAuth: true },
      },
      {
        path: 'sourcing/1688',
        name: 'Sourcing1688',
        component: () => import('@/views/Alibaba1688View.vue'),
        meta: { title: '1688 货源中心', requiresAuth: true },
      },
      {
        path: 'sourcing/review',
        name: 'SourcingReview',
        redirect: { path: '/sourcing', query: { tab: 'candidates' } },
        meta: { title: '选品审核', requiresAuth: true },
      },
      {
        path: 'sourcing/discovery',
        name: 'SourcingDiscovery',
        redirect: { path: '/sourcing', query: { tab: 'ai' } },
        meta: { title: '自动发现', requiresAuth: true },
      },
      {
        path: 'collect',
        name: 'Collect',
        component: () => import('@/views/CollectView.vue'),
        meta: { title: '采集上架', requiresAuth: true },
      },
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: () => import('@/views/DashboardView.vue'),
        meta: { title: '仪表盘', requiresAuth: true },
      },
      {
        path: 'products',
        name: 'Products',
        component: () => import('@/views/ProductsView.vue'),
        meta: { title: '商品管理', requiresAuth: true },
      },
      {
        path: 'orders',
        name: 'Orders',
        component: () => import('@/views/OrdersView.vue'),
        meta: { title: '订单管理', requiresAuth: true },
      },
      {
        path: 'fulfillment',
        name: 'Fulfillment',
        component: () => import('@/views/FulfillmentView.vue'),
        meta: { title: '履约管理', requiresAuth: true },
      },
      {
        path: 'customer-service',
        name: 'CustomerService',
        component: () => import('@/views/CustomerServiceView.vue'),
        meta: { title: '客服管理', requiresAuth: true },
      },
      {
        path: 'finance',
        name: 'Finance',
        component: () => import('@/views/FinanceView.vue'),
        meta: { title: '财务管理', requiresAuth: true },
      },
      {
        path: 'settings',
        name: 'Settings',
        component: () => import('@/views/SettingsView.vue'),
        meta: { title: '系统设置', requiresAuth: true },
      },
    ],
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to, _from, next) => {
  let token = session.token()
  // 勾选过“记住我”：没有访问令牌时先用 refresh_token 恢复会话，再决定是否去登录页
  if (!token && session.refreshToken() && (await refreshSession())) token = session.token()

  if (to.meta.requiresAuth !== false && !token) {
    next({ name: 'Login', query: { redirect: to.fullPath } })
  } else if (to.name === 'Login' && token) {
    next({ name: 'Dashboard' })
  } else {
    next()
  }
})

export default router
