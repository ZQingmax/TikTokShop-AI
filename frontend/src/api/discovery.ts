import request from './request'
import type { Market, Page } from './sourcing'

export interface DiscoveryGoal {
  target_market: Market; category: string; price_min: string | null; price_max: string | null; currency: 'CNY'
  keywords: string[]; exclude_words: string[]; preferences: string; max_candidates: number
}
export interface PlannedKeyword { keyword: string; angle: string; rationale: string; origin: 'user' | 'deepseek'; rejected_reason?: string }
export interface SearchLogEntry {
  key: string; keyword: string; query: string; page: number; provider: string; state: 'done' | 'error' | 'skipped_budget'
  at: string; result_count?: number; offer_hits?: number; new_unique?: number; duplicates_in_task?: number
  rejected?: Record<string, number>; more_available?: boolean | null; error_code?: string; error?: string
}
export interface Dimension { score: number; level: 'low' | 'medium' | 'high'; explanation: string; evidence: string[] }
export interface Assessment {
  output: {
    selling_points: string[]; short_video_potential: Dimension; market_fit: Dimension; homogeneity_risk: Dimension
    ip_compliance_risk: Dimension; compliance_flags: string[]; summary: string; limitations: string[]
  }
  ranking: { rank_score: number; components: Record<string, number>; weights: Record<string, number>; recommendation: string; formula: string }
  not_connected: Record<string, { status: string; value: null; note: string }>
  deterministic: { visual_quality: { score: number; source: string }; data_completeness: { score: number; source: string } }
  evidence: Record<string, unknown>
}
export interface DiscoveryCandidate {
  id: string; name: string | null; main_image: string | null; images: string[]; purchase_price: string | null; currency: string
  category: string | null; product_url: string; original_url: string | null; completeness: string; review_status: string
  version: number; data_source: string; miaoshou_detail_id: string | null
}
export interface DiscoveryResult {
  id: string; source_platform: string; source_item_id: string; canonical_url: string; provider: string
  search_keyword: string; search_query: string; search_position: number; discovered_at: string; status: string
  status_reason: string | null; prior_candidate_id: string | null; candidate_id: string | null; analysis_task_id: string | null
  evaluation_id: string | null; assessment: Assessment | null; rank_score: string | number | null; rank_position: number | null
  snippet_title: string | null; snippet_note: string | null; candidate?: DiscoveryCandidate
}
export interface DiscoveryTask {
  id: string; goal: DiscoveryGoal; auto_collect: boolean; status: string; status_label: string; resume_stage: string
  progress_message: string; running: boolean
  plan: { keywords: PlannedKeyword[]; rejected: PlannedKeyword[]; evidence: Record<string, unknown> | null; planner_error: { code: string; message: string } | null } | null
  search_log: SearchLogEntry[]; budget: Record<string, number>; usage: Record<string, number>
  stage_errors: Array<{ stage: string; code: string; message: string; at: string }>
  collect_task_id: string | null; created_at: string; finished_at: string | null; result_counts?: Record<string, number>
  results?: DiscoveryResult[]; collect_task?: { id: string; status: string; stage: string; completed: number; total: number } | null
  reused?: boolean
}
export interface DiscoveryStatus {
  sources: Array<{ name: string; available: boolean; reason: string; method?: string }>
  planner: { model: string; configured: boolean }; vision: { model: string; configured: boolean }
  collector: { configured: boolean; operation: string }
  limits: { max_results: number; max_keywords: number; max_search_calls: number; max_model_calls: number; max_collect: number; auto_collect_enabled: boolean }
  ranking_weights: Record<string, number>; not_connected: Record<string, { status: string; note: string }>; data_policy: string
}

const root = '/v1/sourcing/discovery'
export const discovery = {
  status: () => request.get<unknown, DiscoveryStatus>(`${root}/status`),
  create: (data: DiscoveryGoal & { request_key: string; auto_collect: boolean }) => request.post<unknown, DiscoveryTask>(`${root}/tasks`, data),
  tasks: (page: number) => request.get<unknown, Page<DiscoveryTask>>(`${root}/tasks`, { params: { page, page_size: 10 } }),
  task: (id: string) => request.get<unknown, DiscoveryTask>(`${root}/tasks/${id}`),
  confirm: (id: string, source_item_ids: string[]) => request.post<unknown, DiscoveryTask>(`${root}/tasks/${id}/confirm-collect`, { source_item_ids }),
  cancel: (id: string) => request.post<unknown, DiscoveryTask>(`${root}/tasks/${id}/cancel`),
}

export const stageOrder = ['planning', 'searching', 'filtering', 'awaiting_confirmation', 'collecting', 'analyzing', 'completed']
export const resultLabels: Record<string, string> = {
  discovered: '已发现（待确认）', filtered_out: '已过滤', not_selected: '未选择采集', selected: '已选择，待采集', collecting: '妙手采集中',
  collected: '已采集', collect_failed: '采集失败', incomplete: '资料不完整', price_filtered: '价格不符', analyzing: 'AI 分析中',
  analyzed: '已分析', analysis_failed: '分析失败', ranked: '已排名', skipped_budget: '预算不足未处理',
}
export const dimensionLabels: Record<string, string> = {
  visual_quality: '视觉展示质量', short_video_potential: '短视频展示潜力', market_fit: '目标市场适配',
  low_homogeneity: '低同质化（100−风险）', data_completeness: '资料完整度',
}
export const notConnectedLabels: Record<string, string> = {
  tiktok_sales: 'TikTok 实际销量', market_heat: '市场热度', profit_margin: '利润率', supplier_certification: '供应商认证', realtime_competition: '实时竞争数据',
}
