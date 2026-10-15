<template>
  <div>
    <el-alert title="公共采集箱 ID 与 TK 采集箱 ID 不同。SPU 货源价、ERP SKU 价格分开保留；未来 TikTok 售价尚未设置。" type="info" :closable="false" />
    <template v-if="data">
      <el-descriptions :column="3" border class="section">
        <el-descriptions-item label="公共采集箱 ID">{{ commonId || data.commonCollectBoxDetailId || '未知' }}</el-descriptions-item>
        <el-descriptions-item label="SPU 货源价（原值）">{{ data.price ?? '未知' }} {{ currency || '币种待确认' }}</el-descriptions-item>
        <el-descriptions-item label="未来 TikTok 售价">未设置</el-descriptions-item>
        <el-descriptions-item label="总库存（原值）">{{ data.stock ?? '未知' }}</el-descriptions-item>
        <el-descriptions-item label="重量（kg，原值）">{{ data.weight ?? '未知' }}</el-descriptions-item>
        <el-descriptions-item label="SKU 数">{{ skus.length }}</el-descriptions-item>
        <el-descriptions-item label="图片数">{{ (data.imgUrls || []).length }}</el-descriptions-item>
        <el-descriptions-item label="货源链接"><template v-if="sources.length"><el-link v-for="x in sources" :key="x.url || x.id" :href="x.url" target="_blank" type="primary" class="source">{{ x.id || x.url }}</el-link></template><template v-else>未知</template></el-descriptions-item>
        <el-descriptions-item label="标题" :span="3">{{ data.title || '待补充' }}</el-descriptions-item>
      </el-descriptions>
      <div class="images"><el-image v-for="src in data.imgUrls || []" :key="src" :src="src" fit="contain" referrerpolicy="no-referrer" :preview-src-list="data.imgUrls" class="image" /></div>
      <p>SKU price 是公共采集箱的价格字段（文档标为售价）；oriPrice 是原始售价。未经确认不会写为 SKU 采购价或 TikTok 售价。</p>
      <el-table :data="skus"><el-table-column prop="key" label="原始规格键" min-width="170" /><el-table-column prop="price" label="price（ERP SKU售价）" min-width="170" /><el-table-column prop="oriPrice" label="oriPrice（原始售价）" min-width="170" /><el-table-column prop="stock" label="stock（库存）" /><el-table-column prop="weight" label="weight（kg）" /><el-table-column label="包装尺寸（cm）" min-width="180"><template #default="{ row }">{{ row.packageLength ?? '?' }} × {{ row.packageWidth ?? '?' }} × {{ row.packageHeight ?? '?' }}</template></el-table-column></el-table>
      <el-collapse class="section"><el-collapse-item title="原始 sourceSupplierInfo / sourceMataInfo（未验证供应商资质）"><pre>sourceSupplierInfo: {{ JSON.stringify(data.sourceSupplierInfo ?? null, null, 2) }}
sourceMataInfo: {{ JSON.stringify(data.sourceMataInfo ?? null, null, 2) }}</pre></el-collapse-item><el-collapse-item title="全部原始商品字段及 sourceList"><pre>{{ JSON.stringify(data, null, 2) }}</pre></el-collapse-item></el-collapse>
    </template>
    <el-empty v-else description="未保存妙手原始详情，请先同步；缺失价格、重量、库存不会填模拟值" />
  </div>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import type { SourceDetail } from '@/api/miaoshou'
const props = defineProps<{ data: SourceDetail | null; commonId?: string | null; currency?: string }>()
const sources = computed(() => (props.data?.sourceList || []).map(x => x as { sourceItemId?: string | number; sourceItemUrl?: string }).map(x => ({ id: x.sourceItemId != null ? String(x.sourceItemId) : '', url: x.sourceItemUrl })))
const skus = computed(() => Object.entries(props.data?.skuMap || {}).map(([key, value]) => ({ key, ...value })))
</script>
<style scoped>
.section { margin-top:16px; }.images { display:flex; gap:12px; flex-wrap:wrap; margin:16px 0; }.image { width:100px; height:100px; flex-shrink:0; }.source { margin-right:8px; }pre { white-space:pre-wrap; overflow-wrap:anywhere; font-size:12px; }p { color:#73767a; line-height:1.6; }
</style>
