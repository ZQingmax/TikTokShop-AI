import request from './request'
import type { Candidate, Market, Page } from './sourcing'

// 1688 CLI 调用可能需要启动浏览器，单独放宽超时
const SLOW = { timeout: 150000 }
const root = '/v1/sourcing/1688'

export interface Price { text: string | null; min: number | null; max: number | null; currency: string }
export interface OfferItem {
  offer_id: string; title: string | null; main_image: string | null; images: string[]; product_url: string
  price: Price; min_order_quantity: number | null; sales: { text: string | null; count: number | null }
  repurchase_rate: number | null
  supplier: { name: string | null; id: string | null; shop_url: string | null; years: number | null }
  location: { province: string | null; city: string | null }; biz_type: string | null
  verified: { factory: boolean; business: boolean; super_factory: boolean }; is_ad: boolean; tags: string[]
  source: string; fetched_at: string
}
export interface SearchResult {
  keyword: string | null; total: number; total_before_filter: number | null; items: OfferItem[]
  cached: boolean; fetched_at: string; notice: string
}
export interface OfferDetail {
  offer_id: string; title: string | null; product_url: string; main_image: string | null; images: string[]
  price: Price; price_tiers: Array<{ min_qty: number | null; price: number | null }>; unit: string | null
  min_order_quantity: number | null; mix_order_quantity: number | null
  attributes: Array<{ name: string | null; value: string | null }>
  options: Array<{ prop: string | null; values: Array<{ name: string | null; image: string | null }> }>
  skus: Array<{ sku_id: string | null; specs: string | null; price: number | null; multi_price: number | null; stock: number | null; sale_count: number | null; image: string | null }>
  package_info: Array<{ sku_id: string | null; spec: string | null; length: number | null; width: number | null; height: number | null; weight: number | null; volume: number | null }>
  supplier: { name: string | null; login_id: string | null; member_id: string | null; user_id: string | null }
  shipping: { send_area: string | null; province: string | null; city: string | null; unit_weight: number | null }
  sold_count: number | null; category_id: string | null; fetched_at: string; cached: boolean
}
export interface SupplierItem {
  supplier_id: string | null; company_name: string | null; login_id: string | null; member_id: string | null
  shop_url: string | null; factory_card_url: string | null
  location: { province: string | null; city: string | null; address: string | null }
  business_mode: string | null; production_service: string | null; service_years: number | null; member_level: string | null
  factory: Record<string, boolean | string | null>
  platform_metrics: Record<string, number | string | null>
  cli_score: { score: number | null; breakdown: Array<{ name: string; points: number; reason: string }>; note: string } | null
  tags: string[]
  offers_preview: Array<{ offer_id: string | null; title: string | null; url: string | null; price_text: string | null; image: string | null; sale_quantity: number | null }>
}
export interface SupplierDetail {
  supplier_id: string | null; company_name: string | null; login_id: string | null; member_id: string | null
  shop_url: string | null; identity: string | null
  factory: Record<string, unknown> & { tags: string[] }
  platform_metrics: { retention_rate: number | null; company_label: string | null; shop_tags: string[]
    service_scores: Array<{ key: string | null; label: string | null; score: number | null }> }
  offers_available_count: number | null; source_offer_url: string | null; warnings: string[]; fetched_at: string
}
export interface CliStatus {
  state: string; label: string; installed: boolean; version: string | null; browser_ok: boolean | null
  logged_in: boolean | null; last_verified_at?: string | null; hint: string | null; transport: string
  checks: Array<{ name: string; status: string; fix: string | null }>
  daemon: { running: boolean; paused_until: string | null; last_failure_kind: string | null } | null
  last_query: { command: string; state: string; label: string; at: string; duration_ms?: number } | null
  limits: { max_results: number; image_max_bytes: number; search_cache_seconds: number }
}
export interface CliError { state: string; code: string; message: string; label: string; hint: string | null; retryable: boolean }
export interface SearchParams {
  keyword: string; max?: number; sort?: string; price_min?: number | null; price_max?: number | null
  exclude_ads?: boolean; factory_only?: boolean
}

export function cliError(error: unknown): CliError | null {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  return detail && typeof detail === 'object' && 'state' in detail ? detail as CliError : null
}

export const operationsLabels: Record<string, string> = { saved: '已保存', to_analyze: '待分析', to_review: '待审核' }

export const alibaba1688 = {
  status: (refresh = false) => request.get<unknown, CliStatus>(`${root}/status`, { params: { refresh }, ...SLOW }),
  search: (params: SearchParams) => request.get<unknown, SearchResult>(`${root}/search`, { params, ...SLOW }),
  imageSearch: (file: File, max = 20) => {
    const form = new FormData()
    form.append('image', file)
    form.append('max', String(max))
    return request.post<unknown, SearchResult>(`${root}/image-search`, form, { ...SLOW, headers: { 'Content-Type': 'multipart/form-data' } })
  },
  product: (offerId: string, refresh = false) => request.get<unknown, OfferDetail>(`${root}/products/${offerId}`, { params: { refresh }, ...SLOW }),
  supplierSearch: (params: { keyword: string; max?: number; factory_only?: boolean; province?: string | null }) =>
    request.get<unknown, { items: SupplierItem[]; total: number; notice: string; cached: boolean }>(`${root}/suppliers/search`, { params, ...SLOW }),
  supplier: (id: string) => request.get<unknown, SupplierDetail>(`${root}/suppliers/${id}`, SLOW),
  save: (offer_id: string, target_market: Market, use_detail = true) =>
    request.post<unknown, { id: string; status: string; detail_fetched: boolean; detail_error: string | null }>(`${root}/candidates`, { offer_id, target_market, use_detail }, SLOW),
  candidates: (params: Record<string, unknown>) => request.get<unknown, Page<Candidate & CliCandidateFields>>('/v1/sourcing/candidates', { params: { data_source: '1688_cli', ...params } }),
  operations: (id: string, data: { favorite?: boolean; operator_note?: string; sourcing_status?: string }) =>
    request.patch<unknown, Candidate & CliCandidateFields>(`/v1/sourcing/candidates/${id}/operations`, data),
}

export interface CliCandidateFields {
  source_price_min: string | null; source_price_max: string | null; min_order_quantity: number | null
  fetched_at: string | null; supplier_ref_id: string | null; sourcing_status: string; operator_note: string
  source_record?: { detail_fetched?: boolean; detail_error?: string | null } | null
}
