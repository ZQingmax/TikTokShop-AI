import request from './request'

export type Market = 'TH' | 'VN' | 'MY' | 'SG' | 'PH' | 'ID'
export const markets: Market[] = ['MY', 'TH', 'VN', 'SG', 'PH', 'ID']
export interface CandidateInput {
  source_platform: '1688' | 'manual'; source_product_id: string | null; product_url: string
  name: string | null; description: string; main_image: string | null; images: string[]
  purchase_price: string | number | null; currency: string; skus: Array<{ sku_id: string; name: string; specs: Record<string, string>; purchase_price?: number | string | null }>
  category: string | null; supplier: string | null; target_market: Market; source_note: string
}
export interface Vision {
  visual_score: number; product_type: string; visual_selling_points: string[]; presentation_quality: string
  potential_risks: Array<{ kind: string; detail: string }>; score_basis: string[]; limitations: string[]
}
export interface TextAnalysis {
  advantages: string[]; disadvantages: string[]; differentiation: string[]; cost_risks: string[]
  english_title_suggestion: string; worth_review: boolean; recommendation_reasons: string[]; limitations: string[]
  market_fit_suggestions: Array<{ target_market: string; suggestion: string; basis: string; limitation: string }>
}
export interface Evaluation {
  id: string; task_id: string; input_version: number; stale: boolean; visual_score: number
  vision: Vision; text_analysis: TextAnalysis | null; text_status: string; rule_score: number
  rule_basis: Array<{ check: string; passed: boolean }>; market_metrics: null; evidence: Record<string, unknown>
}
export interface Candidate extends CandidateInput {
  id: string; version: number; completeness: string; data_source: string; trust_status: string
  review_status: string; favorite: boolean; evaluation: Evaluation | null; created_at: string
  miaoshou_detail_id?: string | null; original_source_id?: string | null; original_url?: string | null
  sync_status?: string; source_stock?: number | null; source_weight?: number | null
  raw_data?: { detail_response?: { data?: { editCommonCollectBoxDetail?: import('./miaoshou').SourceDetail } }; units?: Record<string,string> } | null
}
export interface Task {
  id: string; candidate_id: string; batch_id: string; input_version: number; status: string; stage: string
  attempts: number; error_code: string | null; error_message: string | null; created_at: string
  evaluation?: Evaluation | null; partial_vision?: Vision | null; reused?: boolean
}
export interface Review {
  id: string; candidate_id: string; evaluation_id: string; input_version: number; reviewer_id: string
  action: string; note: string; created_at: string; candidate_name: string; reviewer_name: string
}
export interface Page<T> { items: T[]; total: number; page: number; page_size: number }
export interface ImportResult { row?: number; source_id?: string; id?: string; status: string; error?: string }
export interface Providers {
  vision: { provider: string; model: string; configured: boolean }; text: { provider: string; model: string; configured: boolean }
  sources: Array<{ name: string; available: boolean; reason: string; keyword_search: boolean }>
}
export interface SourceProduct { id: string; title: string; thumbnail: string; sources: Array<{ sourceItemUrl?: string }> }

const root = '/v1/sourcing'
export const sourcing = {
  providers: () => request.get<unknown, Providers>(`${root}/providers/status`),
  candidates: (params: Record<string, unknown>) => request.get<unknown, Page<Candidate>>(`${root}/candidates`, { params }),
  candidate: (id: string) => request.get<unknown, Candidate>(`${root}/candidates/${id}`),
  create: (data: CandidateInput) => request.post<unknown, { id: string; status: string }>(`${root}/candidates`, data),
  edit: (id: string, data: CandidateInput) => request.patch<unknown, Candidate>(`${root}/candidates/${id}`, data),
  import: (format: string, content: string, target_market: Market) => request.post<unknown, { results: ImportResult[]; imported: number; duplicates: number; invalid: number }>(`${root}/candidates/import`, { format, content, target_market }),
  analyze: (candidate_ids: string[]) => request.post<unknown, { batch_id: string; tasks: Task[] }>(`${root}/analyses`, { candidate_ids }),
  tasks: (params: Record<string, unknown> = {}) => request.get<unknown, Page<Task>>(`${root}/tasks`, { params }),
  task: (id: string) => request.get<unknown, Task>(`${root}/tasks/${id}`),
  retry: (id: string) => request.post<unknown, Task>(`${root}/tasks/${id}/retry`),
  review: (candidate: Candidate, action: string, note = '') => request.post(`${root}/candidates/${candidate.id}/review`, { evaluation_id: candidate.evaluation?.id, input_version: candidate.version, action, note }),
  history: (params: Record<string, unknown> = {}) => request.get<unknown, Page<Review>>(`${root}/reviews`, { params }),
  sourceProducts: (page: number) => request.get<unknown, Page<SourceProduct>>(`${root}/sources/miaoshou/products`, { params: { page, page_size: 20 } }),
  sourceImport: (product_ids: string[], target_market: Market, currency: string) => request.post<unknown, { results: ImportResult[] }>(`${root}/sources/miaoshou/import`, { product_ids, target_market, currency }),
}
export const taskLabels: Record<string, string> = { queued: '排队 / 等待重试', running: '分析中', succeeded: '已完成', failed: '失败' }
export const reviewLabels: Record<string, string> = { pending: '待选择', approved: '已选择', rejected: '已排除' }
