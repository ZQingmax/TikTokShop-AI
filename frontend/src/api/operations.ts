import request from './request'
import type { Page } from './sourcing'

export interface SyncState { status: 'never' | 'running' | 'succeeded' | 'failed'; succeeded_at: string | null; finished_at: string | null; counts: Record<string, number>; error: string | null }
export type SyncStates = { orders: SyncState; purchase_orders: SyncState }

export interface OrderRow {
  id: string; tiktok_order_id: string; miaoshou_package_id: string | null; status: string
  app_package_status: string | null; status_text: string | null; platform_status: string | null
  total_amount: string | null; product_amount: string | null; commission_fee: string | null; escrow_amount: string | null
  shipping_fee: string | null; currency: string; shop_id: string | null; shop_name: string | null; site: string | null
  shipping_address: Record<string, string>; tracking_number: string; fulfillment_type: string | null; remark: string
  ordered_at: string | null; ship_by_at: string | null; shipped_at: string | null; synced_at: string | null; created_at: string
  item_count?: number; first_item?: { name: string; image_url: string | null } | null
}
export interface OrderDetail extends OrderRow {
  logistics: Record<string, unknown>
  items: Array<{ id: string; product_id: string | null; product_name: string; sku_code: string | null; quantity: number; unit_price: string; subtotal: string; image_url: string | null }>
  finance: Array<{ type: string; amount: string; currency: string; cny_amount: string | null; description: string }>
}
export interface OutboundRow {
  id: string; tiktok_order_id: string; miaoshou_package_id: string | null; status_text: string | null; shop_name: string | null; site: string | null
  items: Array<{ name: string; sku: string | null; quantity: number; image_url: string | null }>
  ship_by_at: string | null; shipped_at: string | null; tracking_number: string; carrier: string; fulfillment_type: string | null
}
export interface PurchaseOrderRow {
  id: string; po_sn: string; alibaba_order_id: string; supplier_name: string; status: string; total_amount: string; currency: string
  items: Array<{ name: string | null; spec: string | null; sku: string | null; image: string | null; quantity: string | null; received: string | null; price: string | null }>
  tracking_number: string; remark: string; ordered_at: string | null; synced_at: string | null; created_at: string
}
export interface ShipmentRow { id: string; tracking_number: string; status: string; carrier: string; origin: string; destination: string; po_sn: string; alibaba_order_id: string; created_at: string }

export const orders = {
  list: (params: Record<string, unknown>) => request.get<unknown, Page<OrderRow>>('/v1/orders', { params }),
  get: (id: string) => request.get<unknown, OrderDetail>(`/v1/orders/${id}`),
  summary: () => request.get<unknown, { counts: Record<string, number> }>('/v1/orders/summary'),
  sync: () => request.post<unknown, SyncStates>('/v1/orders/sync', undefined, { timeout: 300000 }),
  syncState: () => request.get<unknown, SyncStates>('/v1/orders/sync-state'),
}
export const fulfillment = {
  summary: () => request.get<unknown, { to_ship: number; overdue: number; shipped: number; purchase_orders: Record<string, number> }>('/v1/fulfillment/summary'),
  outbound: (state: 'to_ship' | 'shipped', page: number) => request.get<unknown, Page<OutboundRow>>('/v1/fulfillment/outbound', { params: { state, page, page_size: 20 } }),
  purchaseOrders: (page: number) => request.get<unknown, Page<PurchaseOrderRow>>('/v1/fulfillment/purchase-orders', { params: { page, page_size: 20 } }),
  shipments: (page: number) => request.get<unknown, Page<ShipmentRow>>('/v1/fulfillment/shipments', { params: { page, page_size: 20 } }),
}

/** 妙手包裹状态（#150 appPackageStatus）。 */
export const packageStatus: Record<string, { label: string; type: 'success' | 'warning' | 'info' | 'danger' | 'primary' }> = {
  unpaid: { label: '未付款', type: 'info' },
  wait_confirmed: { label: '待审核', type: 'warning' },
  wait_seller_send: { label: '待发货', type: 'warning' },
  wait_receiver_confirm: { label: '已发货', type: 'primary' },
  finished: { label: '已完成', type: 'success' },
  cancelled: { label: '已取消', type: 'info' },
  returned: { label: '已退款', type: 'danger' },
  refunding: { label: '售后中', type: 'danger' },
}

export function formatTime(value: string | null | undefined) {
  if (!value) return '—'
  const d = new Date(value)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}
export function money(value: string | number | null | undefined, currency?: string | null) {
  if (value === null || value === undefined || value === '') return '—'
  return `${Number(value).toFixed(2)}${currency ? ` ${currency}` : ''}`
}
export function errorText(e: unknown, fallback: string) {
  const detail = (e as { response?: { data?: { detail?: unknown } } }).response?.data?.detail
  return typeof detail === 'string' ? detail : fallback
}
export function syncLabel(state: SyncState | undefined) {
  if (!state || state.status === 'never') return '尚未从妙手同步'
  if (state.status === 'running') return '正在从妙手同步…'
  const last = state.succeeded_at ? `上次成功同步 ${formatTime(state.succeeded_at)}` : '尚未成功同步'
  return state.status === 'failed' ? `${last}；最近一次失败：${state.error || '未知错误'}` : last
}
