import request from './request'

// ========== Auth ==========
export function login(data: { username: string; password: string }) {
  return request.post('/v1/auth/login', data)
}

export function refreshToken(data: { refresh_token: string }) {
  return request.post('/v1/auth/refresh', data)
}

export function getMe() {
  return request.get('/v1/auth/me')
}

// ========== Products ==========
export function getProducts(params?: Record<string, unknown>) {
  return request.get('/v1/products', { params })
}

export function getProduct(id: string) {
  return request.get(`/v1/products/${id}`)
}

export function createProduct(data: Record<string, unknown>) {
  return request.post('/v1/products', data)
}

export function updateProduct(id: string, data: Record<string, unknown>) {
  return request.put(`/v1/products/${id}`, data)
}

export function generateMaterials(id: string) {
  return request.post(`/v1/products/${id}/materials`)
}

export function listingProduct(id: string, data: Record<string, unknown>) {
  return request.post(`/v1/products/${id}/listing`, data)
}

// ========== Orders ==========
export function getOrders(params?: Record<string, unknown>) {
  return request.get('/v1/orders', { params })
}

export function getOrder(id: string) {
  return request.get(`/v1/orders/${id}`)
}

export function updateOrderStatus(id: string, data: Record<string, unknown>) {
  return request.put(`/v1/orders/${id}/status`, data)
}

// ========== Pricing ==========
export function calculatePricing(data: Record<string, unknown>) {
  return request.post('/v1/pricing/calculate', data)
}

export function getPricingSuggestions(params?: Record<string, unknown>) {
  return request.get('/v1/pricing/suggestions', { params })
}

// ========== Fulfillment ==========
export function getPurchaseOrders(params?: Record<string, unknown>) {
  return request.get('/v1/fulfillment/purchase-orders', { params })
}


export function getShipments(params?: Record<string, unknown>) {
  return request.get('/v1/fulfillment/shipments', { params })
}

// ========== Customer Service ==========
export function getCsSessions(params?: Record<string, unknown>) {
  return request.get('/v1/customer-service/sessions', { params })
}

export function getCsSession(id: string) {
  return request.get(`/v1/customer-service/sessions/${id}`)
}

export function sendCsMessage(data: Record<string, unknown>) {
  return request.post('/v1/customer-service/messages', data)
}

export function createCsSession(data: Record<string, unknown>) {
  return request.post('/v1/customer-service/sessions', data)
}

export function endCsSession(id: string) {
  return request.post(`/v1/customer-service/sessions/${id}/end`)
}

export function transferCsSession(id: string, reason?: string) {
  return request.post(`/v1/customer-service/sessions/${id}/transfer`, null, { params: { reason } })
}

export function searchFaqs(params?: Record<string, unknown>) {
  return request.get('/v1/customer-service/faqs', { params })
}

// ========== Finance ==========
export function getFinanceSummary(params?: Record<string, unknown>) {
  return request.get('/v1/finance/summary', { params })
}

export function getTransactions(params?: Record<string, unknown>) {
  return request.get('/v1/finance/transactions', { params })
}

export interface ExchangeRateItem {
  currency: string
  base_currency: 'CNY'
  rate: string | null
  source: string | null
  updated_by: string | null
  updated_by_name: string | null
  updated_at: string | null
  unconverted_records: number
  recomputed_records?: number
}

export function getExchangeRates() {
  return request.get<any, { items: ExchangeRateItem[] }>('/v1/finance/exchange-rates')
}

// rate: 1 CNY = rate × currency. recompute_all re-derives every record in that currency, not just unconverted ones.
export function saveExchangeRate(currency: string, rate: string, recomputeAll = false) {
  return request.put<any, ExchangeRateItem>(`/v1/finance/exchange-rates/${currency}`, { rate, recompute_all: recomputeAll })
}

// ========== Dashboard ==========
interface DashboardStats {
  today_orders: number
  today_sales: string
  pending_orders: number
  total_products: number
  order_trend: number
  sales_trend: number
  pending_trend: number
  product_trend: number
}

export function getDashboardStats() {
  return request.get<DashboardStats, DashboardStats>('/v1/dashboard/stats')
}

export function getDashboardRecentOrders() {
  return request.get('/v1/dashboard/recent-orders')
}

export function getDashboardSalesTrend() {
  return request.get<unknown, { dates: string[]; sales: number[] }>('/v1/dashboard/sales-trend')
}

export function getDashboardOrderDistribution() {
  return request.get('/v1/dashboard/order-status-distribution')
}

export function healthCheck() {
  return request.get('/v1/health')
}
