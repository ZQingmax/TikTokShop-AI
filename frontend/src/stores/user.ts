import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import request from '@/api/request'
import { session } from '@/api/session'
import router from '@/router'

interface UserInfo {
  id: string  // UUID是字符串类型
  username: string
  nickname: string
  avatar?: string  // 可选字段
  role: string
  is_active?: boolean
  created_at?: string
}

interface LoginParams {
  username: string
  password: string
}

export const useUserStore = defineStore('user', () => {
  const token = ref<string>(session.token())
  const userInfo = ref<UserInfo | null>(null)

  const isLoggedIn = computed(() => !!token.value)

  /** remember=true：保存 7 天 refresh_token 实现免登录，并记住用户名；从不保存密码 */
  async function login(username: string, password: string, remember = false) {
    const res = await request.post('/v1/auth/login', { username, password })
    const data = res.data || res
    token.value = data.access_token || data.token
    session.save(token.value, remember ? data.refresh_token || null : null, username)
    await fetchUserInfo()
  }

  async function fetchUserInfo() {
    try {
      const res = await request.get('/v1/auth/me')
      const data = res.data || res
      userInfo.value = data
      localStorage.setItem('userInfo', JSON.stringify(data))
    } catch {
      userInfo.value = null
    }
  }

  async function logout() {
    token.value = ''
    userInfo.value = null
    // 主动退出同时作废本机的“记住我”，下次需重新输入密码
    session.clear()
    // 完整跳转可卸载旧页面和未保存编辑的路由守卫，退出后不再停留在后台。
    window.location.replace(router.resolve({ name: 'Login' }).href)
  }

  function initUserInfo() {
    const stored = localStorage.getItem('userInfo')
    if (stored) {
      try {
        userInfo.value = JSON.parse(stored)
      } catch {
        userInfo.value = null
      }
    }
  }

  if (token.value) {
    initUserInfo()
  }

  return { token, userInfo, isLoggedIn, login, fetchUserInfo, logout }
})
