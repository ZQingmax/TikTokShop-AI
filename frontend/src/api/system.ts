import request from './request'

// 拦截器返回的已经是响应体
const get = <T>(url: string, params?: Record<string, unknown>) => request.get(url, { params }) as unknown as Promise<T>

export interface RoleInfo {
  name: string
  display_name: string
  description: string | null
  summary: string
  permissions: string[]
  restrictions: string[]
  user_count: number
}

export interface SystemUser {
  id: string
  username: string
  nickname: string
  role: string
  is_active: boolean
  created_at: string | null
  is_self: boolean
}

export interface ModelCandidate { id: string; tier: string; note: string; price: string }

export interface ModelScenario {
  key: string
  label: string
  used_in: string
  unit: 'tokens' | 'images'
  candidates: ModelCandidate[]
  default_model: string
  selected_model: string | null
  effective_model: string
  updated_by: string | null
  updated_at: string | null
}

/** 汇总值：null 表示该范围内没有任何调用返回这一项用量 */
export interface UsageGroup {
  calls: number
  missing_usage: number
  input_tokens: number | null
  output_tokens: number | null
  total_tokens: number | null
  input_images: number | null
  output_images: number | null
  scenario?: string
  label?: string
  provider?: string
  model?: string
  day?: string
}

export interface UsageRecord {
  id: string
  called_at: string
  provider: string
  scenario: string
  label: string
  model: string
  status: string
  input_tokens: number | null
  output_tokens: number | null
  total_tokens: number | null
  input_images: number | null
  output_images: number | null
  has_usage: boolean
  user: string | null
}

export interface UsageSummary {
  start: string
  end: string
  totals: UsageGroup
  by_scenario: UsageGroup[]
  by_model: UsageGroup[]
  by_date: UsageGroup[]
  recent: UsageRecord[]
}

export const system = {
  changePassword: (current_password: string, new_password: string) =>
    request.post('/v1/auth/change-password', { current_password, new_password }),
  roles: () => get<{ roles: RoleInfo[]; current_role: string; can_manage: boolean }>('/v1/system/roles'),
  users: () => get<SystemUser[]>('/v1/system/users'),
  setRole: (id: string, role: string) => request.patch(`/v1/system/users/${id}/role`, { role }) as unknown as Promise<SystemUser>,
  models: () => get<{ scenarios: ModelScenario[]; can_edit: boolean }>('/v1/system/models'),
  /** model 为 null 时恢复默认模型 */
  setModel: (scenario: string, model: string | null) =>
    request.put(`/v1/system/models/${scenario}`, { model }) as unknown as Promise<ModelScenario>,
  usage: (start?: string, end?: string) => get<UsageSummary>('/v1/system/model-usage', { start, end }),
}
