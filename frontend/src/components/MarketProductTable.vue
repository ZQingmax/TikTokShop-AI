<template>
  <div>
    <div class="filters">
      <el-input v-model="keyword" clearable placeholder="搜索商品名称" style="width: 240px" />
      <el-select v-model="category" clearable placeholder="全部已抓取品类" style="width: 240px"><el-option v-for="c in categories" :key="c" :label="c" :value="c" /></el-select>
      <span>已选 {{ selected.length }} / 20 条；排名仅属于各自榜单</span>
    </div>
    <el-table ref="table" :data="paged" row-key="row_number" max-height="540" @selection-change="change">
      <el-table-column type="selection" :reserve-selection="true" :selectable="selectable" width="45" />
      <el-table-column type="expand"><template #default="{ row }">
        <div class="details">
          <p>来源类型：{{ row.source_kind === 'ranking' ? '榜单页' : '商品或导入来源' }} · 抓取时间：{{ row.fetched_at ? new Date(row.fetched_at).toLocaleString() : '未知' }}</p>
          <el-table v-if="row.rankings?.length" :data="row.rankings"><el-table-column prop="category" label="来源品类" /><el-table-column label="原始排名"><template #default="scope">{{ scope.row.rank ?? '未知' }}</template></el-table-column><el-table-column label="统计日期 / 周期"><template #default="scope">{{ scope.row.observed_on || '未知' }} / {{ scope.row.period || '未知' }}</template></el-table-column><el-table-column label="原始指标"><template #default="scope">销量：{{ scope.row.raw?.sales_period || '未知' }} · GMV：{{ scope.row.raw?.gmv_period || '未知' }}</template></el-table-column></el-table>
          <pre v-if="row.raw">{{ JSON.stringify(row.raw, null, 2) }}</pre>
        </div>
      </template></el-table-column>
      <el-table-column label="商品" min-width="290"><template #default="{ row }"><div class="product"><el-image v-if="row.image_url" :src="row.image_url" fit="contain" referrerpolicy="no-referrer" class="image" /><div><strong>{{ row.name }}</strong><p><el-link :href="row.source_url" target="_blank" rel="noopener noreferrer">{{ row.source_kind === 'ranking' ? '查看来源榜单' : '查看来源' }}</el-link></p></div></div></template></el-table-column>
      <el-table-column prop="target_market" label="国家" width="70" />
      <el-table-column label="品类 / 店铺" min-width="180"><template #default="{ row }"><div v-for="c in rowCategories(row)" :key="c">{{ c }}</div><p class="muted">{{ row.shop || '店铺未知' }}</p></template></el-table-column>
      <el-table-column label="价格" width="130"><template #default="{ row }">{{ row.raw?.price || (row.price ?? '未知') }} {{ row.currency || '' }}</template></el-table-column>
      <el-table-column label="周期销量 / 销售额" width="165"><template #default="{ row }">{{ row.raw?.sales_period || (row.sales ?? '未知') }}<p>{{ row.raw?.gmv_period || (row.revenue ?? '未知') }}</p></template></el-table-column>
      <el-table-column label="累计销量 / 销售额" width="165"><template #default="{ row }">{{ row.raw?.total_sales || (row.total_sales ?? '未知') }}<p>{{ row.raw?.total_gmv || (row.total_revenue ?? '未知') }}</p></template></el-table-column>
      <el-table-column label="原始排名" width="110"><template #default="{ row }">{{ row.rankings?.length > 1 ? '多榜单，见详情' : (row.rank ?? '未知') }}</template></el-table-column>
      <el-table-column label="统计日期 / 周期" min-width="160"><template #default="{ row }">{{ row.observed_on || '未知' }}<p>{{ row.period || '未知' }}</p></template></el-table-column>
    </el-table>
    <el-pagination v-model:current-page="page" :page-size="20" :total="filtered.length" layout="total, prev, pager, next" />
  </div>
</template>
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { rowCategories, type MarketRow } from '@/api/marketEvidence'
const props = defineProps<{ rows: MarketRow[] }>()
const emit = defineEmits<{ selection: [rows: MarketRow[]] }>()
const table = ref<{ clearSelection: () => void; toggleRowSelection: (row: MarketRow, selected: boolean) => void }>(), selected = ref<MarketRow[]>([])
const keyword = ref(''), category = ref(''), page = ref(1)
// 合并后的商品按其所有来源品类参与筛选，不只看第一个榜单
const categories = computed(() => [...new Set(props.rows.flatMap(rowCategories))])
const filtered = computed(() => props.rows.filter(r => r.name.toLowerCase().includes(keyword.value.toLowerCase()) && (!category.value || rowCategories(r).includes(category.value))))
const paged = computed(() => filtered.value.slice((page.value - 1) * 20, page.value * 20))
function selectable(row: MarketRow) { return selected.value.length < 20 || selected.value.some(r => r.row_number === row.row_number) }
function change(rows: MarketRow[]) {
  selected.value = rows.slice(0, 20)
  for (const row of rows.slice(20)) table.value?.toggleRowSelection(row, false)
  emit('selection', selected.value)
}
watch([keyword, category], () => { page.value = 1 })
watch(() => props.rows, () => { page.value = 1; selected.value = []; table.value?.clearSelection(); emit('selection', []) })
</script>
<style scoped>
.filters { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; margin: 12px 0; }
.product { display: flex; gap: 10px; align-items: center; }.image { width: 56px; height: 56px; flex-shrink: 0; }
.muted { color: var(--el-text-color-secondary); }.details { padding: 12px 35px; }pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 260px; overflow: auto; }
.el-pagination { margin-top: 12px; }
</style>
