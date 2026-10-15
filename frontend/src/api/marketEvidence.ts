import request from './request'
import type { Candidate, Evaluation, Market, Page } from './sourcing'
import type { SourceJob } from './miaoshou'

export interface MarketRow {
  row_number: number
  name: string
  source_platform: string
  source_url: string
  observed_on: string | null
  target_market: Market
  category?: string
  image_url?: string
  rank?: number
  sales?: number
  revenue?: string
  price?: string
  currency?: string
  period?: string
  evidence_id?: string
  report_name?: string
  scope?: string
  fetched_at?: string
  shop?: string
  total_sales?: number | null
  total_revenue?: string | null
  source_kind?: string
  category_paths?: string[][]
  raw?: Record<string, string>
  rankings?: Array<{ category_id: string | null; category: string; rank: number | null; observed_on: string | null; period: string | null; source_url: string; raw?: Record<string, string> }>
}
/** 商品在各来源榜单中的品类（完整路径）；合并后的商品可能属于多个品类榜单 */
export function rowCategories(row: MarketRow): string[] {
  const paths = (row.category_paths || []).filter(p => p.length).map(p => p.join(' / '))
  const ranked = (row.rankings || []).map(r => r.category).filter(Boolean)
  const all = [...new Set([...paths, ...ranked])]
  return all.length ? all : [row.category || '未分类']
}

/** 已选商品的实际品类名称（取路径末级），用于带入采购品类；未分类不会被归入任何业务方向 */
export function selectedCategoryNames(rows: MarketRow[], limit = 100): string {
  const names = [...new Set(rows.flatMap(r => {
    const paths = (r.category_paths || []).filter(p => p.length)
    return paths.length ? paths.map(p => p[p.length - 1]) : [r.category || '未分类']
  }))].filter(n => n !== '未分类')
  let text = ''
  for (const name of names) {
    const next = text ? `${text}、${name}` : name
    if (next.length > limit) break
    text = next
  }
  return text
}

export interface Report {
  id: string
  name: string
  target_market: Market
  scope: string
  rows: MarketRow[]
}
export interface ReportUpload {
  name: string
  format: string
  content: string
  target_market: Market
  scope: string
  source_url?: string
}
export interface Analysis {
  market_basis?: Array<{ evidence_id: string; reason: string }>
  matching_facts?: string[]
  differences?: string[]
  recommendation_reasons?: string[]
  information_gaps?: string[]
  limitations?: string[]
}
export interface EvidenceCandidate extends Candidate {
  market_evidence: MarketRow[]
  operator_note: string
  min_order_quantity?: number
  source_price_min?: string
  source_price_max?: string
  collection_task_id?: string
  collection?: SourceJob | null
  in_collect_box?: boolean
}
export interface DiscoveryJob {
  id: string
  status: string
  status_label: string
  progress_message: string
  goal: Record<string, unknown>
  results?: Array<{
    id: string
    snippet_title?: string
    canonical_url: string
    status: string
    status_reason?: string
    candidate_id?: string
  }>
}
const root = '/v1/sourcing'
export const evidenceApi = {
  report: (id: string) => request.get<unknown, Report>(`${root}/market-reports/${id}`),
  preview: (data: ReportUpload) =>
    request.post<unknown, { rows: MarketRow[]; total: number }>(
      `${root}/market-reports/preview`,
      data,
    ),
  import: (data: ReportUpload) => request.post<unknown, Report>(`${root}/market-reports`, data),
  reports: (target_market: Market, page = 1) =>
    request.get<unknown, Page<Report>>(`${root}/market-reports`, {
      params: { target_market, page },
    }),
  candidates: (params: Record<string, unknown>) =>
    request.get<unknown, Page<EvidenceCandidate>>(`${root}/candidates`, { params }),
  candidate: (id: string) => request.get<unknown, EvidenceCandidate>(`${root}/candidates/${id}`),
  evaluations: (id: string, page: number) =>
    request.get<unknown, Page<Evaluation>>(`${root}/candidates/${id}/evaluations`, {
      params: { page },
    }),
  collect: (request_key: string, rows: Candidate[]) =>
    request.post<unknown, SourceJob>(`${root}/candidates/collect`, {
      request_key,
      candidates: rows.map((r) => ({ id: r.id, version: r.version })),
    }),
  operations: (id: string, data: Record<string, unknown>) =>
    request.patch(`${root}/candidates/${id}/operations`, data),
  createTask: (data: Record<string, unknown>) =>
    request.post<unknown, DiscoveryJob>(`${root}/discovery/tasks`, data),
  tasks: (page = 1) =>
    request.get<unknown, Page<DiscoveryJob>>(`${root}/discovery/tasks`, { params: { page } }),
  task: (id: string) => request.get<unknown, DiscoveryJob>(`${root}/discovery/tasks/${id}`),
}
