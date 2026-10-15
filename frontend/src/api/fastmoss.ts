import request from './request'
import type { Market, Page } from './sourcing'

export interface FastmossCategory {
  id: string
  name: string
  parent_id: string | null
  path: string[]
  household: boolean
  /** 分类接口提供的英文名（仅辅助显示） */
  name_en?: string | null
  level?: number
  source?: string
}
export interface FastmossTask {
  id: string
  target_market: Market
  categories: FastmossCategory[]
  pages: number
  status: 'queued' | 'running' | 'succeeded' | 'partial' | 'failed'
  progress: string
  report_id?: string
  row_count: number
  truncated: boolean
  error?: string
  created_at: string
  category_results: Array<{ category: FastmossCategory; status: string; rows?: number; error?: string }>
}
export const fastmoss = {
  status: () => request.get<unknown, { ready: boolean; message: string }>('/v1/sourcing/fastmoss/status'),
  categories: (market: Market) => request.get<unknown, { items: FastmossCategory[] }>('/v1/sourcing/fastmoss/categories', { params: { target_market: market } }),
  refresh: (market: Market) => request.post<unknown, { items: FastmossCategory[] }>('/v1/sourcing/fastmoss/categories/refresh', null, { params: { target_market: market }, timeout: 180000 }),
  create: (data: { request_key: string; target_market: Market; category_ids: string[]; pages: number }) => request.post<unknown, FastmossTask>('/v1/sourcing/fastmoss/tasks', data),
  tasks: (market: Market, page = 1) => request.get<unknown, Page<FastmossTask>>('/v1/sourcing/fastmoss/tasks', { params: { target_market: market, page } }),
  task: (id: string) => request.get<unknown, FastmossTask>(`/v1/sourcing/fastmoss/tasks/${id}`),
  csv: (id: string) => request.get<unknown, Blob>(`/v1/sourcing/fastmoss/tasks/${id}/csv`, { responseType: 'blob' }),
}
