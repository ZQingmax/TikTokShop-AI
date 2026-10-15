import request from './request'
import type { Market, Page } from './sourcing'

export interface MiaoshouConnection {
  configured: boolean; connected: boolean | null; reason?: string; verified_at?: string
  site?: string; shop_count?: number; error_code?: string; error_category?: string
  shops?: Array<Record<string, unknown>>
}
export interface SourceDetail {
  commonCollectBoxDetailId?: number; title?: string; imgUrls?: string[]; price?: number | null
  skuMap?: Record<string, Record<string, unknown>>; stock?: number | null; weight?: number | null
  sourceSupplierInfo?: unknown; sourceMataInfo?: unknown; sourceList?: unknown[]
  [key: string]: unknown
}
export interface SourceJobItem {
  source_item_id?: string; url?: string; common_detail_id?: string; candidate_id?: string; analysis_task_id?: string
  state: string; error_code?: string; error?: string; updated?: boolean; completeness?: string; reused_platform?: boolean
  claim_platform?: string; platform_detail_id?: string
}
export interface SourceJob {
  id: string; kind: string; status: string; stage: string; completed: number; total: number; items: SourceJobItem[]
  error_code: string | null; error_message: string | null; target_market: Market; currency: string; reused?: boolean
  created_at?: string
}
export interface CommonProduct {
  id: string; commonCollectBoxDetailId: number; title: string | null; thumbnail: string | null
  sources: Array<{ sourceItemId?: string; sourceItemUrl?: string }>; price: number | null; minSkuPrice: number | null
  maxSkuPrice: number | null; stock: number | null; weight: number | null; status: string | null; reason: string | null
}
const root = '/v1/sourcing/miaoshou'
export const miaoshou = {
  status: () => request.get<unknown, MiaoshouConnection>(`${root}/status`),
  check: (site: string) => request.post<unknown, MiaoshouConnection>(`${root}/connection-check`, { platform: 'tiktok', site }),
  products: (page: number, source_id: string, tab: string) => request.get<unknown, Page<CommonProduct>>('/v1/sourcing/sources/miaoshou/products', { params: { page, page_size: 20, source_id: source_id || undefined, tab } }),
  detail: (id: string) => request.get<unknown, { data: { editCommonCollectBoxDetail: SourceDetail; ossMd5?: string }; units: Record<string, string>; price_meanings: Record<string, string> }>(`${root}/common-products/${id}`),
  collect: (data: { request_key: string; links: string[]; target_market: Market; currency: string; analyze_after_sync: boolean }) => request.post<unknown, SourceJob>(`${root}/collect`, data),
  sync: (data: { request_key: string; common_detail_ids: string[]; target_market: Market; currency: string; analyze_after_sync: boolean }) => request.post<unknown, SourceJob>(`${root}/sync`, data),
  jobs: (page: number) => request.get<unknown, Page<SourceJob>>(`${root}/tasks`, { params: { page, page_size: 10 } }),
  job: (id: string) => request.get<unknown, SourceJob>(`${root}/tasks/${id}`),
  reconcile: (id: string) => request.post<unknown, SourceJob>(`${root}/tasks/${id}/reconcile`),
}
export const sourceStatus: Record<string, string> = { queued: '排队', running: '执行中', waiting: '等待平台详情', succeeded: '同步完成', failed: '失败', uncertain: '结果不确定，需查询' }
export interface TiktokBoxProduct {
  id: string; title: string | null; thumbnail: string | null; price: string | number | null; stock: string | number | null
  item_num: string | null; common_detail_id: string | number | null; group: string | null; shop_ids: Array<string | number>
  created_at: string | null; remark: string | null
}
export const miaoshouBoxes = {
  tiktok: (page: number, source_id: string, status: string) =>
    request.get<unknown, { items: TiktokBoxProduct[]; page: number; has_more: boolean; total: number | null }>(`${root}/tiktok-products`, { params: { page, page_size: 20, source_id: source_id || undefined, status: status || undefined } }),
  detail: (id: string, shop_id: string | number) =>
    request.get<unknown, { detail_id: string; shop_id: string; data: TiktokBoxDetail }>(`${root}/tiktok-products/${id}`, { params: { shop_id } }),
}
export interface TiktokBoxDetail {
  title?: string; notes?: string; imgUrls?: string[]; cid?: string | number | null; brandId?: string | number | null
  weight?: number | null; packageLength?: number | null; packageWidth?: number | null; packageHeight?: number | null
  skuMap?: Record<string, Record<string, unknown>>
  skuPropertyList?: Array<{ attrId?: string; attrName?: string; attrValueList?: Array<{ attrValueId?: string; attrValue?: string; imgUrl?: string }> }>
  productAttributes?: Array<{ attributeId?: string; attributeName?: string; attributeValues?: Array<{ valueId?: string; valueName?: string }> }>
  [key: string]: unknown
}
export const tiktokStatus: Record<string, string> = { notPublished: '未发布', timingPublish: '定时发布', published: '已发布' }
export const commonStatus: Record<string, string> = { all: '全部', noClaimed: '未认领', claimed: '已认领', collectFail: '采集失败', collectSuccess: '采集成功' }
