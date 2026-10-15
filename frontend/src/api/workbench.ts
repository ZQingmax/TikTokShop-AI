import request from './request'
import type { Market } from './sourcing'

export interface EditorialContent {
  title: string; notes: string; bullet_points: string[]; imgUrls: string[]; cid: string; brandId: string
  weight: number | null; packageLength: number | null; packageWidth: number | null; packageHeight: number | null
  isCodOpen: '0' | '1'; deliveryOptionSetType: 'default'; skuMap: Record<string, any>
  skuPropertyList: any[]; productAttributes: any[]; productCertifications: any[]
  manufacturerIds: string[]; responsiblePersonIds: string[]; sizeChartType: '' | 'image'; sizeChart: string
  confirmed_facts: string; recognized_text: any[]
  descImgUrls: string[]; sourceAttributes: { name: string; value: string }[]
}
export interface Draft {
  id: string; collect_item_id: string | null; shop_id: number | null; market: Market; currency: string; language: string
  source_snapshot: Record<string, any>; content: EditorialContent; version: number; checked_version: number | null
  synced_version: number | null; state: string; validation: { valid: boolean; errors: { field: string; message: string }[] } | null
  common_detail_id: string | null; platform_detail_id: string | null; updated_at: string
}
export interface WorkbenchTask {
  id: string; draft_id: string; kind: string; input_version: number; status: string; stage: string
  result: Record<string, any>; steps: Record<string, any>; error_code: string | null; error_message: string | null
  adopted_version: number | null; created_at: string
  operation: { image_urls?: string[]; prompt?: string; source_lang?: string } | null
}
export interface WorkbenchConfig {
  configured: boolean; miaoshou_configured: boolean; text_model: string; image_model: string
  ocr_model: string; copy_model: string; fill_model: string
  translation_model: string; resolution: string; language: string
}
export interface WorkbenchOptions { categories: Record<string, any>; metadata: Record<string, any>; warehouses: Record<string, any> }
export interface SourceSku { names: string[]; item_num: string; stock: number | null; weight: number | null; purchase_price: number | null }
export interface FillSuggestions {
  source: {
    fields: Record<string, { value: number; source: string }>
    specs: { name: string; values: { name: string; image: string }[] }[]
    skus: SourceSku[]; currency: string; attributes: { name: string; value: string }[]; desc_images: string[]
  }
  ai: null | {
    task_id: string; input_version: number; cid: string
    category: { cid: string; path: string; reason: string } | null
    weight: { value: number; reason: string } | null
    package: { length: number; width: number; height: number; reason: string } | null
    sku_weights: { sku_key: string; weight: number; reason: string }[]
    attributes: { attr_id: string; name: string; value_ids: string[]; custom_values: string[]; reason: string }[]
    sale_specs: { source_property: string; attr_id: string; name: string; values: { source_value: string; value_id: string }[] }[]
  }
}
const root = '/v1/product-workbench'
export const workbench = {
  config: () => request.get<unknown, WorkbenchConfig>(`${root}/config`),
  create: (ids: string[], shop_id?: number) => request.post<unknown, { items: Draft[] }>(`${root}/drafts`, { ids, shop_id: shop_id || null }),
  list: (params: { market: string; state?: string; keyword?: string; page: number }) => request.get<unknown, { items: Draft[]; total: number }>(`${root}/drafts`, { params }),
  detail: (id: string) => request.get<unknown, Draft>(`${root}/drafts/${id}`),
  save: (draft: Draft) => request.patch<unknown, Draft>(`${root}/drafts/${draft.id}`, { version: draft.version, shop_id: draft.shop_id, language: draft.language, content: draft.content }),
  check: (draft: Draft) => request.post<unknown, Draft>(`${root}/drafts/${draft.id}/check`, { version: draft.version }),
  shops: (market: string, page = 1) => request.get<unknown, { items: any[]; has_more: boolean }>(`${root}/shops`, { params: { market, page } }),
  options: (id: string, cid = '') => request.get<unknown, WorkbenchOptions>(`${root}/drafts/${id}/options`, { params: { cid: cid || undefined } }),
  ai: (draft: Draft, kind: string, image_urls: string[], prompt: string, source_lang = 'auto') => request.post<unknown, WorkbenchTask>(`${root}/drafts/${draft.id}/ai-tasks`, { request_key: crypto.randomUUID(), version: draft.version, kind, image_urls, prompt, source_lang }),
  tasks: (id: string) => request.get<unknown, { items: WorkbenchTask[] }>(`${root}/drafts/${id}/tasks`),
  suggestions: (id: string) => request.get<unknown, FillSuggestions>(`${root}/drafts/${id}/suggestions`),
  adopt: (draft: Draft, task: WorkbenchTask, confirm_stale: boolean, image_action = 'append', replace_url?: string) => request.post<unknown, Draft>(`${root}/tasks/${task.id}/adopt`, { version: draft.version, confirm_stale, image_action, replace_url: replace_url || null }),
  retry: (task: WorkbenchTask, resubmit_model: boolean, resubmit_transfer: boolean, resubmit_save = false) => request.post<unknown, WorkbenchTask>(`${root}/tasks/${task.id}/retry`, { resubmit_model, resubmit_transfer, resubmit_save }),
  removeTask: (task: WorkbenchTask) => request.delete<unknown, { id: string; deleted: boolean }>(`${root}/tasks/${task.id}`),
  sync: (draft: Draft, overwrite_remote = false) => request.post<unknown, WorkbenchTask>(`${root}/drafts/${draft.id}/sync`, { request_key: crypto.randomUUID(), version: draft.version, overwrite_remote }),
  removeDraft: (draft: Draft) => request.delete<unknown, { id: string; deleted: boolean }>(`${root}/drafts/${draft.id}`),
}
export const draftStates: Record<string, string> = { editing: '编辑中', ready: '检查通过', synced: '已同步', modified: '有未同步修改' }
export const taskStates: Record<string, string> = { queued: '排队', running: '执行中', waiting: '等待平台确认', succeeded: '完成', failed: '失败', uncertain: '结果不确定' }
export const taskTagTypes: Record<string, 'primary' | 'success' | 'info' | 'warning' | 'danger'> = { queued: 'info', running: 'primary', waiting: 'primary', succeeded: 'success', failed: 'danger', uncertain: 'warning' }
export const taskKinds: Record<string, string> = { ocr: '文字识别', copy: '生成文案', generate: '文字生成新图', edit: '编辑图片', fill: 'AI 填充建议', translate: '图片翻译', sync: '同步妙手采集箱' }
