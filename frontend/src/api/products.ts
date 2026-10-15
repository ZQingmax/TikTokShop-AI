import request from './request'
import type { Market, Page } from './sourcing'

export interface SyncedProduct {
  id: string; name: string; status: string; miaoshou_status: string | null
  cost_price: string | null; cost_currency: string | null; cost_source: 'sourcing' | 'miaoshou' | null
  sale_price: string | null; sale_price_max: string | null; sale_currency: string | null; sku_count: number | null
  miaoshou_detail_id: string | null; common_detail_id: string | null; market: Market | null; shop_ids: string[]
  thumbnail: string | null; item_num: string | null; stock: number | null
  sourcing_candidate_id: string | null; source_url: string; source_product_id: string | null
  synced_at: string | null; created_at: string
}
export const products = {
  list: (params: { page: number; page_size: number; keyword?: string; miaoshou_status?: string; market?: string }) =>
    request.get<unknown, Page<SyncedProduct>>('/v1/products', { params }),
  summary: () => request.get<unknown, { counts: Record<string, number>; synced_at: string | null }>('/v1/products/summary'),
  sync: () => request.post<unknown, { created: number; updated: number; removed: number; detail_failed: number; total: number; synced_at: string }>('/v1/products/sync', undefined, { timeout: 300000 }),
}
export const productStatus: Record<string, { label: string; type: 'success' | 'warning' | 'info' | 'danger' | 'primary' }> = {
  notPublished: { label: '未发布', type: 'info' },
  timingPublish: { label: '定时发布', type: 'warning' },
  published: { label: '已发布', type: 'success' },
  removed: { label: '已移出妙手', type: 'danger' },
}
