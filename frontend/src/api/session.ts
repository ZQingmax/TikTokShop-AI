import axios from 'axios'

/**
 * 登录会话存储。
 * - token：访问令牌（30 分钟有效）
 * - refresh_token：仅在勾选“记住我”时保存（7 天有效，每次刷新顺延），用于免登录
 * - remembered_username：记住的用户名，用于预填登录框
 * 出于安全考虑，任何情况下都不在浏览器中保存密码。
 */
const TOKEN = 'token'
const REFRESH = 'refresh_token'
const USERNAME = 'remembered_username'
let sessionVersion = 0

export const session = {
  token: () => localStorage.getItem(TOKEN) || '',
  refreshToken: () => localStorage.getItem(REFRESH) || '',
  rememberedUsername: () => localStorage.getItem(USERNAME) || '',
  save(accessToken: string, refreshToken: string | null, username?: string) {
    sessionVersion++
    localStorage.setItem(TOKEN, accessToken)
    if (refreshToken) localStorage.setItem(REFRESH, refreshToken)
    else localStorage.removeItem(REFRESH)
    if (username !== undefined) {
      if (refreshToken) localStorage.setItem(USERNAME, username)
      else localStorage.removeItem(USERNAME)
    }
  },
  /** 退出或会话失效：清除令牌，保留记住的用户名以便预填 */
  clear() {
    sessionVersion++
    localStorage.removeItem(TOKEN)
    localStorage.removeItem(REFRESH)
    localStorage.removeItem('userInfo')
  },
}

let pending: Promise<boolean> | null = null

/** 用记住的 refresh_token 换取新令牌；并发调用共享同一次刷新。返回是否成功。 */
export function refreshSession(): Promise<boolean> {
  const refreshToken = session.refreshToken()
  if (!refreshToken) return Promise.resolve(false)
  if (!pending) {
    const version = sessionVersion
    pending = axios
      .post(`${import.meta.env.VITE_API_BASE_URL || '/api'}/v1/auth/refresh`, { refresh_token: refreshToken }, { timeout: 15000 })
      .then((res) => {
        // 退出或重新登录后，旧刷新请求不得覆盖当前会话。
        if (version !== sessionVersion) return false
        const data = res.data
        if (!data?.access_token) return false
        session.save(data.access_token, data.refresh_token || refreshToken)
        return true
      })
      .catch((error) => {
        // 只有令牌被拒绝时才清除；网络错误保留，下次仍可重试
        if (error?.response?.status === 401 && version === sessionVersion) session.clear()
        return false
      })
      .finally(() => {
        pending = null
      })
  }
  return pending
}
