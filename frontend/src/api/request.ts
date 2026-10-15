import axios from 'axios'
import type { AxiosInstance, InternalAxiosRequestConfig, AxiosResponse } from 'axios'
import { ElMessage } from 'element-plus'
import { refreshSession, session } from './session'

const service: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// 登录、刷新接口的 401 表示凭证错误，不是“会话过期”，不触发自动刷新和跳转
const AUTH_ENDPOINTS = ['/v1/auth/login', '/v1/auth/refresh', '/v1/auth/register']

service.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = session.token()
    if (token && config.headers) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error),
)

service.interceptors.response.use(
  (response: AxiosResponse) => {
    return response.data
  },
  async (error) => {
    const status = error.response?.status
    const rawDetail = error.response?.data?.detail
    // 结构化错误（如 1688 CLI：{state, message, hint}）显示其 message
    const structured = rawDetail && typeof rawDetail === 'object' && !Array.isArray(rawDetail) ? rawDetail.message as string : null
    const message = structured || rawDetail || error.response?.data?.message
    const config = error.config as (InternalAxiosRequestConfig & { _retried?: boolean }) | undefined
    const isAuthEndpoint = AUTH_ENDPOINTS.some((path) => config?.url?.includes(path))

    if (status === 401 && isAuthEndpoint) {
      // 交给调用方显示（如“用户名或密码错误”）
      return Promise.reject(error)
    }
    if (status === 401) {
      // 勾选了“记住我”：静默刷新令牌并重试一次原请求
      if (config && !config._retried && (await refreshSession())) {
        config._retried = true
        config.headers.Authorization = `Bearer ${session.token()}`
        return service(config)
      }
      ElMessage.error('登录已过期，请重新登录')
      session.clear()
      if (window.location.pathname !== '/login') {
        const redirect = encodeURIComponent(window.location.pathname + window.location.search)
        window.location.href = `/login?redirect=${redirect}`
      }
    } else if (status === 403) {
      ElMessage.error('没有权限访问该资源')
    } else if (status === 404) {
      ElMessage.error('请求的资源不存在')
    } else if (status === 422) {
      const errors = error.response?.data?.detail
      if (Array.isArray(errors)) {
        ElMessage.error(errors.map((e: any) => e.msg).join('; '))
      } else {
        ElMessage.error(message || '请求参数错误')
      }
    } else if (status >= 500) {
      ElMessage.error(structured || '服务器内部错误')
    } else {
      ElMessage.error(message || error.message || '网络错误')
    }

    return Promise.reject(error)
  },
)

export default service
