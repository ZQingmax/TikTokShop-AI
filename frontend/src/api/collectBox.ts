import request from './request'
import type { Market, Page } from './sourcing'

export type MiaoshouBox = 'common' | 'tiktok'
export type BoxSyncStatus = 'not_synced' | 'syncing' | 'synced' | 'failed'
export interface CollectBoxItem {
  id: string; candidate_id: string; source_product_id: string | null; product_url: string; name: string | null
  main_image: string | null; purchase_price: string | null; currency: string; category: string | null; supplier: string | null
  target_market: Market; note: string; miaoshou_box: MiaoshouBox | null; miaoshou_detail_id: string | null
  sync_status: BoxSyncStatus; sync_task_id: string | null; sync_error: string | null; synced_at: string | null; created_at: string
}
const root = '/v1/collect-box'
export const collectBox = {
  items: (params: { target_market: Market; page: number; keyword?: string; sync_status?: string }) =>
    request.get<unknown, Page<CollectBoxItem> & { counts: Partial<Record<BoxSyncStatus, number>> }>(`${root}/items`, { params }),
  add: (candidate_ids: string[]) =>
    request.post<unknown, { added: number; skipped: number }>(`${root}/items`, { candidate_ids }),
  note: (id: string, note: string) => request.patch<unknown, CollectBoxItem>(`${root}/items/${id}`, { note }),
  remove: (ids: string[]) => request.post<unknown, { removed: number }>(`${root}/items/remove`, { ids }),
}
export const boxLabels: Record<MiaoshouBox, string> = { common: '公用采集箱', tiktok: 'TikTok 采集箱' }
export const syncLabels: Record<BoxSyncStatus, string> = { not_synced: '未同步', syncing: '同步中', synced: '已同步', failed: '同步失败' }
