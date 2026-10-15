<template>
  <div>
    <el-alert title="TikTok 采集箱店铺模式详情，只读查看；不保存、不发布。售价为妙手 TK 采集箱中的值，originPrice 为货源价格。" type="info" :closable="false" />
    <template v-if="data">
      <el-descriptions :column="3" border class="section">
        <el-descriptions-item label="TK 采集箱 ID">{{ detailId }}</el-descriptions-item>
        <el-descriptions-item label="店铺">{{ shopId }}</el-descriptions-item>
        <el-descriptions-item label="类目 CID">{{ data.cid || '未设置' }}</el-descriptions-item>
        <el-descriptions-item label="重量（kg）">{{ data.weight ?? '未知' }}</el-descriptions-item>
        <el-descriptions-item label="包装尺寸（cm）">{{ data.packageLength ?? '?' }} × {{ data.packageWidth ?? '?' }} × {{ data.packageHeight ?? '?' }}</el-descriptions-item>
        <el-descriptions-item label="品牌 ID">{{ data.brandId || '无' }}</el-descriptions-item>
        <el-descriptions-item label="SKU 数">{{ skus.length }}</el-descriptions-item>
        <el-descriptions-item label="图片数">{{ (data.imgUrls || []).length }}</el-descriptions-item>
        <el-descriptions-item label="商品属性数">{{ (data.productAttributes || []).length }}</el-descriptions-item>
        <el-descriptions-item label="标题" :span="3">{{ data.title || '待补充' }}</el-descriptions-item>
      </el-descriptions>
      <div class="images"><el-image v-for="src in data.imgUrls || []" :key="src" :src="src" fit="contain" referrerpolicy="no-referrer" :preview-src-list="data.imgUrls" preview-teleported class="image" /></div>
      <h4>SKU</h4>
      <el-table :data="skus"><el-table-column label="规格" min-width="200"><template #default="{ row }"><div class="spec"><el-image v-if="row.img" :src="row.img" fit="contain" referrerpolicy="no-referrer" class="spec-img" />{{ row.label }}</div></template></el-table-column><el-table-column prop="itemNum" label="SKU 货号" min-width="140" /><el-table-column prop="price" label="price（售价）" /><el-table-column prop="originPrice" label="originPrice（货源价）" min-width="130" /><el-table-column prop="stock" label="库存" /><el-table-column prop="weight" label="重量（kg）" /></el-table>
      <template v-if="(data.productAttributes || []).length">
        <h4>商品属性</h4>
        <el-descriptions :column="2" border><el-descriptions-item v-for="a in data.productAttributes" :key="a.attributeId" :label="a.attributeName || a.attributeId">{{ (a.attributeValues || []).map(v => v.valueName || v.valueId).join('、') || '—' }}</el-descriptions-item></el-descriptions>
      </template>
      <el-collapse class="section"><el-collapse-item title="详细描述（纯文本）"><pre>{{ notesText || '无' }}</pre></el-collapse-item><el-collapse-item title="全部原始字段"><pre>{{ JSON.stringify(data, null, 2) }}</pre></el-collapse-item></el-collapse>
    </template>
    <el-empty v-else description="未读取到 TikTok 采集箱详情" />
  </div>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import type { TiktokBoxDetail } from '@/api/miaoshou'
const props = defineProps<{ data: TiktokBoxDetail | null; detailId?: string; shopId?: string | number }>()
const values = computed(() => {
  const map = new Map<string, { name: string; img?: string }>()
  for (const prop of props.data?.skuPropertyList || []) for (const v of prop.attrValueList || []) map.set(String(v.attrValueId), { name: v.attrValue || String(v.attrValueId), img: v.imgUrl })
  return map
})
const skus = computed(() => Object.entries(props.data?.skuMap || {}).filter(([, v]) => String(v.isDelete ?? '0') !== '1').map(([key, value]) => {
  const parts = key.split(';').filter(Boolean)
  return { key, label: parts.map(x => values.value.get(x)?.name || x).join(' / ') || '默认规格', img: parts.map(x => values.value.get(x)?.img).find(Boolean), ...value }
}))
// notes may be HTML; render as text only, never as markup.
const notesText = computed(() => props.data?.notes ? new DOMParser().parseFromString(props.data.notes, 'text/html').body.textContent?.trim() : '')
</script>
<style scoped>
.section { margin-top:16px; }.images { display:flex; gap:12px; flex-wrap:wrap; margin:16px 0; }.image { width:100px; height:100px; flex-shrink:0; }
.spec { display:flex; gap:8px; align-items:center; }.spec-img { width:36px; height:36px; flex-shrink:0; }
pre { white-space:pre-wrap; overflow-wrap:anywhere; font-size:12px; }h4 { margin:16px 0 8px; }
</style>
