import type { Draft, FillSuggestions, SourceSku } from '@/api/workbench'

// A suggested value for one empty field. Only `fillable` hints are applied by Tab.
export interface Hint { value: any; text: string; source: string; fillable: boolean }
export interface Pricing { rate: number | null; markup: number | null }

export const packageFields = ['weight', 'packageLength', 'packageWidth', 'packageHeight'] as const
const norm = (s: string) => String(s).trim().toLowerCase()
const sameNames = (a: string[], b: string[]) => a.length === b.length && [...a].map(norm).sort().join('\u0001') === [...b].map(norm).sort().join('\u0001')

function money(value: number, currency: string) {
  return ['VND', 'IDR'].includes(currency) ? Math.round(value) : Math.round(value * 100) / 100
}

// Source SKU for a draft row: by spec value names (through the AI spec mapping when adopted),
// or the only source SKU for a single default row.
function matchSku(draft: Draft, key: string, skus: SourceSku[], aliases: Record<string, string>) {
  const names = new Map<string, string>()
  for (const prop of draft.content.skuPropertyList || []) for (const v of prop.attrValueList || []) names.set(String(v.attrValueId), v.attrValue)
  const ids = key.split(';').filter(Boolean)
  if (!ids.length) return skus.length === 1 ? skus[0] : undefined
  const variants = [ids.map(id => aliases[id] ?? names.get(id) ?? id), ids.map(id => names.get(id) ?? id)]
  return skus.find(s => s.names.length && variants.some(v => sameNames(v, s.names)))
}

export function buildHints(draft: Draft, s: FillSuggestions | undefined, ctx: { productRules: any[]; warehouseId?: string; pricing: Pricing }) {
  const hints: Record<string, Hint> = {}
  if (!s) return hints
  const ai = s.ai
  const sameCategory = !!ai && !!ai.cid && ai.cid === draft.content.cid
  const add = (key: string, value: any, text: string, source: string, fillable = true) => { if (!hints[key]) hints[key] = { value, text, source, fillable } }
  for (const field of packageFields) {
    const found = s.source.fields[field]
    if (found) add(field, found.value, String(found.value), found.source)
  }
  if (ai?.weight) add('weight', ai.weight.value, String(ai.weight.value), `AI 估算：${ai.weight.reason}`)
  if (ai?.package) {
    const reason = `AI 估算：${ai.package.reason}`
    add('packageLength', ai.package.length, String(ai.package.length), reason)
    add('packageWidth', ai.package.width, String(ai.package.width), reason)
    add('packageHeight', ai.package.height, String(ai.package.height), reason)
  }
  if (ai?.category && !draft.content.cid) add('cid', ai.category.cid, ai.category.path, `AI 建议：${ai.category.reason}`)
  if (sameCategory) {
    for (const attr of ai!.attributes) {
      const rule = ctx.productRules.find(r => String(r.attrId) === attr.attr_id)
      const labels = [...attr.value_ids.map(id => rule?.values?.find((v: any) => String(v.id) === id)?.name || id), ...attr.custom_values]
      add(`attr:${attr.attr_id}`, [...attr.value_ids, ...attr.custom_values], labels.join('、'), `AI 建议：${attr.reason}`)
    }
  }
  const aliases: Record<string, string> = {}
  if (sameCategory) for (const spec of ai!.sale_specs) for (const v of spec.values) aliases[v.value_id] = v.source_value
  const productWeight = draft.content.weight ?? hints.weight?.value
  for (const key of Object.keys(draft.content.skuMap || {})) {
    const sku = matchSku(draft, key, s.source.skus, aliases)
    const aiWeight = ai?.sku_weights.find(w => w.sku_key === key)
    if (sku?.item_num) add(`sku:${key}:itemNum`, sku.item_num, sku.item_num, '货源 SKU 编号')
    if (sku?.stock != null && ctx.warehouseId) add(`sku:${key}:stock`, sku.stock, String(sku.stock), '货源（供应商）库存，请按实际可售数量调整')
    if (sku?.weight) add(`sku:${key}:weight`, sku.weight, String(sku.weight), '货源 SKU 重量')
    else if (aiWeight) add(`sku:${key}:weight`, aiWeight.weight, String(aiWeight.weight), `AI 估算：${aiWeight.reason}`)
    else if (productWeight) add(`sku:${key}:weight`, productWeight, String(productWeight), '同商品重量')
    const sourceCost = sku?.purchase_price ?? (s.source.skus.length === 1 ? s.source.skus[0].purchase_price : null)
    if (sourceCost != null) add(`sku:${key}:originPrice`, sourceCost, String(sourceCost), '货源采购价')
    // An operator-entered 货源价格 wins over the collected purchase price.
    const cost = draft.content.skuMap[key]?.originPrice ?? sourceCost
    if (cost != null) {
      const { rate, markup } = ctx.pricing
      if (rate && markup) {
        const price = money(cost * rate * markup, draft.currency)
        add(`sku:${key}:price`, price, String(price), `货源价 ${cost} ${s.source.currency} × 汇率 ${rate} × 倍率 ${markup}`)
      } else add(`sku:${key}:price`, null, `货源 ${cost} ${s.source.currency}`, '设置上方定价规则后可按 Tab 填入', false)
    }
  }
  return hints
}
