import request from './request'
import type { Market, Page } from './sourcing'

export interface ListingIssue { field: string; message: string }
export interface ListingItem {
  detail_id: string; shop_id: string; title?: string; state: string
  errors?: ListingIssue[]; warnings?: ListingIssue[]; error?: string; record?: Record<string, unknown>
}
export interface ListingTask {
  id: string; kind: 'check' | 'publish'; market: Market; status: string; stage: string; poll_count: number
  error_code: string | null; error_message: string | null; created_at: string; finished_at: string | null
  items: ListingItem[]; counts: Record<string, number>; total: number; reused?: boolean
}
const root = '/v1/listing'
export const listing = {
  create: (data: { request_key: string; kind: 'check' | 'publish'; market: Market; items: Array<{ detail_id: string; shop_id: string }> }) =>
    request.post<unknown, ListingTask>(`${root}/tasks`, data),
  tasks: (page: number) => request.get<unknown, Page<ListingTask>>(`${root}/tasks`, { params: { page, page_size: 10 } }),
  task: (id: string) => request.get<unknown, ListingTask>(`${root}/tasks/${id}`),
  reconcile: (id: string) => request.post<unknown, ListingTask>(`${root}/tasks/${id}/reconcile`),
  records: (page: number) => request.get<unknown, { items: Array<Record<string, unknown>>; total: number | null }>(`${root}/records`, { params: { page, page_size: 20 } }),
}
export const listingStatus: Record<string, string> = {
  queued: '排队', running: '执行中', waiting: '等待妙手结果', succeeded: '完成', partial: '部分完成', failed: '未通过 / 失败', uncertain: '结果未确认',
}
export const itemState: Record<string, { label: string; type: 'success' | 'warning' | 'danger' | 'info' | 'primary' }> = {
  pending: { label: '待检查', type: 'info' }, ready: { label: '预检通过', type: 'success' }, blocked: { label: '预检未通过', type: 'danger' },
  submitting: { label: '提交中', type: 'primary' }, submitted: { label: '已提交，等待结果', type: 'primary' },
  uncertain: { label: '结果未确认', type: 'warning' }, published: { label: '已发布', type: 'success' }, failed: { label: '发布失败', type: 'danger' },
}
