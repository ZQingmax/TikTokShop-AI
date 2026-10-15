<template>
  <div class="products-container">
    <div class="page-header">
      <div>
        <h2>商品管理</h2>
        <p class="muted">
          商品来自妙手 TikTok 采集箱，成本价来自关联的 1688 货源。{{ syncedAt ? `上次同步 ${formatTime(syncedAt)}` : '尚未同步' }}
        </p>
      </div>
      <el-button type="primary" :loading="syncing" @click="sync()">从妙手同步</el-button>
    </div>

    <el-card shadow="never" class="filter-card">
      <el-tabs v-model="filters.status" @tab-change="search">
        <el-tab-pane :label="`全部（${total}）`" name="" />
        <el-tab-pane v-for="(s, key) in productStatus" :key="key" :label="`${s.label}（${counts[key] || 0}）`" :name="key" />
      </el-tabs>
      <div class="toolbar">
        <el-input
          v-model="filters.keyword"
          placeholder="名称 / TK 采集箱 ID / 货源 ID / 货号"
          clearable
          style="width: 280px"
          @keyup.enter="search"
          @clear="search"
        />
        <el-select v-model="filters.market" placeholder="全部站点" clearable style="width: 160px" @change="search"
          ><el-option v-for="m in markets" :key="m" :value="m" :label="m"
        /></el-select>
        <el-button @click="search">搜索</el-button>
      </div>
    </el-card>

    <el-card shadow="never" class="table-card">
      <el-alert v-if="error" :title="error" type="error" :closable="false" class="alert" />
      <el-table v-loading="loading" :data="rows" row-key="id">
        <template #empty>
          <el-empty :description="syncedAt ? '没有符合条件的商品' : '还没有商品，点击「从妙手同步」导入妙手 TikTok 采集箱商品'" :image-size="80" />
        </template>
        <el-table-column label="商品" min-width="340"
          ><template #default="{ row }"
            ><div class="product">
              <el-image v-if="row.thumbnail" :src="row.thumbnail" class="thumb" fit="contain" referrerpolicy="no-referrer" />
              <div>
                <strong>{{ row.name }}</strong>
                <p class="muted">TK 采集箱 ID {{ row.miaoshou_detail_id || '—' }}{{ row.item_num ? ` · 货号 ${row.item_num}` : '' }}</p>
              </div>
            </div></template
          ></el-table-column
        >
        <el-table-column label="站点 / 店铺" width="170"
          ><template #default="{ row }"
            >{{ row.market || '未知站点' }}
            <p class="muted">{{ row.shop_ids.length ? `店铺 ${row.shop_ids.join('、')}` : '未认领店铺' }}</p></template
          ></el-table-column
        >
        <el-table-column label="TikTok 售价" width="170" align="right"
          ><template #default="{ row }"
            ><template v-if="row.sale_price !== null"
              >{{ priceRange(row) }}<p class="muted">{{ row.sku_count }} 个 SKU</p></template
            ><span v-else class="muted">{{ row.shop_ids.length ? '未设置' : '认领店铺后设置' }}</span></template
          ></el-table-column
        >
        <el-table-column label="成本价（货源）" width="170" align="right"
          ><template #default="{ row }"
            ><template v-if="row.cost_price !== null"
              >{{ money(row.cost_price, row.cost_currency) }}
              <p class="muted">{{ row.cost_source === 'sourcing' ? '货源采购价' : '妙手货源价' }}</p></template
            ><span v-else class="muted">未关联货源</span>
            <p v-if="row.source_product_id" class="muted">
              <el-link v-if="row.source_url" :href="row.source_url" target="_blank" type="primary">1688 {{ row.source_product_id }}</el-link
              ><template v-else>1688 {{ row.source_product_id }}</template>
            </p></template
          ></el-table-column
        >
        <el-table-column label="库存" width="110" align="right"
          ><template #default="{ row }">{{ row.stock ?? '—' }}</template></el-table-column
        >
        <el-table-column label="妙手状态" width="120"
          ><template #default="{ row }"
            ><el-tag :type="productStatus[row.miaoshou_status]?.type || 'info'" size="small">{{
              productStatus[row.miaoshou_status]?.label || '本地商品'
            }}</el-tag></template
          ></el-table-column
        >
        <el-table-column label="同步时间" width="160"
          ><template #default="{ row }">{{ formatTime(row.synced_at) }}</template></el-table-column
        >
        <el-table-column label="操作" width="140" fixed="right"
          ><template #default="{ row }"
            ><el-button link type="primary" :disabled="!row.miaoshou_detail_id || row.miaoshou_status === 'removed'" @click="showDetail(row)"
              >详情</el-button
            ><el-button
              v-if="row.miaoshou_status === 'notPublished' && row.shop_ids.length"
              link
              type="success"
              @click="router.push({ path: '/collect', query: { tab: 'listing' } })"
              >去上架</el-button
            ></template
          ></el-table-column
        >
      </el-table>
      <div class="pagination-wrapper">
        <el-pagination
          v-model:current-page="pagination.page"
          v-model:page-size="pagination.pageSize"
          :page-sizes="[10, 20, 50]"
          :total="pagination.total"
          layout="total, sizes, prev, pager, next"
          background
          @size-change="fetchProducts"
          @current-change="fetchProducts"
        />
      </div>
    </el-card>

    <el-dialog v-model="detail.visible" title="TikTok 采集箱详情" width="1080px" top="5vh"
      ><div v-if="detail.row && detail.row.shop_ids.length > 1" class="toolbar"
        ><span class="muted">店铺</span
        ><el-select v-model="detail.shopId" style="width: 200px" @change="loadDetail"
          ><el-option v-for="s in detail.row.shop_ids" :key="s" :label="`店铺 ${s}`" :value="s" /></el-select
      ></div>
      <div v-loading="detail.loading" class="section">
        <TiktokBoxDetails :data="detail.data" :detail-id="detail.row?.miaoshou_detail_id || ''" :shop-id="detail.shopId" /></div
    ></el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { markets } from '@/api/sourcing'
import { products, productStatus, type SyncedProduct } from '@/api/products'
import { miaoshouBoxes, type TiktokBoxDetail } from '@/api/miaoshou'
import TiktokBoxDetails from '@/components/TiktokBoxDetails.vue'

const router = useRouter()
const STALE_MS = 30 * 60 * 1000
const filters = reactive({ keyword: '', status: '', market: '' })
const pagination = reactive({ page: 1, pageSize: 20, total: 0 })
const rows = ref<SyncedProduct[]>([]), loading = ref(false), syncing = ref(false), error = ref('')
const counts = ref<Record<string, number>>({}), total = ref(0), syncedAt = ref<string | null>(null)
const detail = reactive({ visible: false, loading: false, row: null as SyncedProduct | null, shopId: '', data: null as TiktokBoxDetail | null })

function errorText(e: unknown, fallback: string) {
  const value = (e as { response?: { data?: { detail?: unknown } } }).response?.data?.detail
  return typeof value === 'string' ? value : fallback
}
function money(value: string | null, currency: string | null) {
  return value === null ? '—' : `${Number(value).toFixed(2)} ${currency || ''}`.trim()
}
function priceRange(row: SyncedProduct) {
  if (row.sale_price_max === null || row.sale_price_max === row.sale_price) return money(row.sale_price, row.sale_currency)
  return `${Number(row.sale_price).toFixed(2)}–${money(row.sale_price_max, row.sale_currency)}`
}
function formatTime(value: string | null | undefined) {
  if (!value) return '—'
  const d = new Date(value)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

async function fetchSummary() {
  const r = await products.summary()
  counts.value = r.counts
  total.value = Object.values(r.counts).reduce((a, b) => a + b, 0)
  syncedAt.value = r.synced_at
}
async function fetchProducts() {
  loading.value = true
  try {
    const r = await products.list({
      page: pagination.page,
      page_size: pagination.pageSize,
      keyword: filters.keyword || undefined,
      miaoshou_status: filters.status || undefined,
      market: filters.market || undefined,
    })
    rows.value = r.items
    pagination.total = r.total
  } catch (e) {
    error.value = errorText(e, '商品列表加载失败')
  } finally {
    loading.value = false
  }
}
async function search() {
  pagination.page = 1
  await fetchProducts()
}
async function sync(quiet = false) {
  syncing.value = true
  error.value = ''
  try {
    const r = await products.sync()
    if (!quiet) ElMessage.success(`已同步 ${r.total} 个商品（新增 ${r.created}，更新 ${r.updated}，移出妙手 ${r.removed}）`)
    if (r.detail_failed) ElMessage.warning(`${r.detail_failed} 个商品的店铺详情读取失败，售价与库存保留上次同步的值`)
    await Promise.all([fetchSummary(), fetchProducts()])
  } catch (e) {
    error.value = errorText(e, '从妙手同步失败')
  } finally {
    syncing.value = false
  }
}
async function showDetail(row: SyncedProduct) {
  if (!row.miaoshou_detail_id) return
  if (!row.shop_ids.length) {
    // Shop-mode detail needs a shop; unclaimed products only have the public collect-box record.
    return ElMessage.warning('该商品未认领店铺，暂无店铺模式详情；可在「采集上架 → 商品编辑工作台」认领到店铺')
  }
  Object.assign(detail, { visible: true, row, shopId: row.shop_ids[0], data: null })
  await loadDetail()
}
async function loadDetail() {
  if (!detail.row?.miaoshou_detail_id) return
  detail.loading = true
  try {
    detail.data = (await miaoshouBoxes.detail(detail.row.miaoshou_detail_id, detail.shopId)).data
  } catch (e) {
    ElMessage.error(errorText(e, 'TikTok 采集箱详情读取失败'))
  } finally {
    detail.loading = false
  }
}

onMounted(async () => {
  try {
    await fetchSummary()
  } catch (e) {
    error.value = errorText(e, '商品统计加载失败')
  }
  await fetchProducts()
  // Keep the list close to 妙手 without a manual click: re-sync when it was never synced or is stale.
  if (!syncedAt.value || Date.now() - new Date(syncedAt.value).getTime() > STALE_MS) await sync(true)
})
</script>

<style scoped>
.products-container { padding: 0; }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; }
.page-header h2 { margin: 0 0 4px; font-size: 20px; color: var(--el-text-color-primary); }
.filter-card { margin-bottom: 16px; }
.toolbar { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }
.section { margin-top: 16px; }
.alert { margin-bottom: 12px; }
.muted { color: #73767a; font-size: 13px; margin: 0; }
.product { display: flex; gap: 12px; align-items: center; }
.thumb { width: 56px; height: 56px; flex-shrink: 0; }
p { margin: 4px 0 0; line-height: 1.5; overflow-wrap: anywhere; }
.pagination-wrapper { display: flex; justify-content: flex-end; margin-top: 16px; }
</style>
