<template>
  <div class="orders-container">
    <div class="page-header">
      <div>
        <h2>订单管理</h2>
        <p class="muted">TikTok 订单来自妙手包裹（每 10 分钟自动同步）。{{ syncLabel(syncStates?.orders) }}</p>
      </div>
      <el-button type="primary" :loading="syncing" @click="sync">从妙手同步</el-button>
    </div>

    <el-card shadow="never" class="section">
      <el-tabs v-model="filters.status" @tab-change="search">
        <el-tab-pane :label="`全部（${total}）`" name="" />
        <el-tab-pane v-for="(s, key) in packageStatus" :key="key" :label="`${s.label}（${counts[key] || 0}）`" :name="key" />
      </el-tabs>
      <div class="toolbar">
        <el-input v-model="filters.search" placeholder="订单号 / 包裹号 / 运单号 / 商品名" clearable style="width: 280px" @keyup.enter="search" @clear="search" />
        <el-select v-model="filters.site" placeholder="全部站点" clearable style="width: 140px" @change="search"
          ><el-option v-for="m in markets" :key="m" :value="m" :label="m"
        /></el-select>
        <el-button @click="search">搜索</el-button>
      </div>
    </el-card>

    <el-card shadow="never" class="section">
      <el-alert v-if="error" :title="error" type="error" :closable="false" class="alert" />
      <el-table v-loading="loading" :data="rows" row-key="id" @row-click="openDetail">
        <template #empty
          ><el-empty
            :description="syncStates?.orders?.status === 'succeeded' ? '妙手中暂无 TikTok 订单。商品发布并售出后，订单会自动出现在这里。' : '尚未从妙手同步订单'"
            :image-size="70"
        /></template>
        <el-table-column label="订单" min-width="300"
          ><template #default="{ row }"
            ><div class="product">
              <el-image v-if="row.first_item?.image_url" :src="row.first_item.image_url" class="thumb" fit="contain" referrerpolicy="no-referrer" />
              <div>
                <strong>{{ row.tiktok_order_id || '—' }}</strong>
                <p class="muted">{{ row.first_item?.name || '—' }}{{ row.item_count && row.item_count > 1 ? ` 等 ${row.item_count} 件` : '' }}</p>
              </div>
            </div></template
          ></el-table-column
        >
        <el-table-column label="店铺 / 站点" min-width="150"
          ><template #default="{ row }">{{ row.shop_name || row.shop_id || '—' }}<p class="muted">{{ row.site || '—' }}</p></template></el-table-column
        >
        <el-table-column label="订单金额" width="140" align="right"
          ><template #default="{ row }">{{ money(row.total_amount, row.currency) }}<p class="muted">佣金 {{ money(row.commission_fee) }}</p></template></el-table-column
        >
        <el-table-column label="状态" width="120"
          ><template #default="{ row }"
            ><el-tag :type="packageStatus[row.app_package_status]?.type || 'info'" size="small">{{
              row.status_text || packageStatus[row.app_package_status]?.label || row.status
            }}</el-tag></template
          ></el-table-column
        >
        <el-table-column label="最迟发货 / 运单" min-width="170"
          ><template #default="{ row }"
            ><span :class="{ overdue: isOverdue(row) }">{{ formatTime(row.ship_by_at) }}</span>
            <p class="muted">{{ row.tracking_number || '未出运单' }}</p></template
          ></el-table-column
        >
        <el-table-column label="下单时间" width="160"><template #default="{ row }">{{ formatTime(row.ordered_at || row.created_at) }}</template></el-table-column>
      </el-table>
      <div class="pagination-wrapper">
        <el-pagination
          v-model:current-page="pagination.page"
          v-model:page-size="pagination.pageSize"
          :page-sizes="[20, 50, 100]"
          :total="pagination.total"
          layout="total, sizes, prev, pager, next"
          background
          @size-change="fetchOrders"
          @current-change="fetchOrders"
        />
      </div>
    </el-card>

    <el-drawer v-model="detailVisible" title="订单详情" size="640px">
      <template v-if="detail">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="订单号">{{ detail.tiktok_order_id || '—' }}</el-descriptions-item>
          <el-descriptions-item label="妙手包裹 ID">{{ detail.miaoshou_package_id || '—' }}</el-descriptions-item>
          <el-descriptions-item label="状态">{{ detail.status_text || packageStatus[detail.app_package_status || '']?.label || detail.status }}</el-descriptions-item>
          <el-descriptions-item label="平台状态">{{ detail.platform_status || '—' }}</el-descriptions-item>
          <el-descriptions-item label="店铺">{{ detail.shop_name || detail.shop_id || '—' }} · {{ detail.site || '—' }}</el-descriptions-item>
          <el-descriptions-item label="履约方式">{{ fulfillmentTypes[detail.fulfillment_type || ''] || detail.fulfillment_type || '—' }}</el-descriptions-item>
          <el-descriptions-item label="订单金额">{{ money(detail.total_amount, detail.currency) }}</el-descriptions-item>
          <el-descriptions-item label="商品金额">{{ money(detail.product_amount, detail.currency) }}</el-descriptions-item>
          <el-descriptions-item label="平台佣金">{{ money(detail.commission_fee, detail.currency) }}</el-descriptions-item>
          <el-descriptions-item label="预估回款">{{ money(detail.escrow_amount, detail.currency) }}</el-descriptions-item>
          <el-descriptions-item label="下单时间">{{ formatTime(detail.ordered_at) }}</el-descriptions-item>
          <el-descriptions-item label="最迟发货">{{ formatTime(detail.ship_by_at) }}</el-descriptions-item>
          <el-descriptions-item label="发货时间">{{ formatTime(detail.shipped_at) }}</el-descriptions-item>
          <el-descriptions-item label="运单号">{{ detail.tracking_number || '—' }}</el-descriptions-item>
          <el-descriptions-item label="收件地区" :span="2">{{ region(detail.shipping_address) }}</el-descriptions-item>
          <el-descriptions-item v-if="detail.remark" label="买家留言" :span="2">{{ detail.remark }}</el-descriptions-item>
        </el-descriptions>
        <h4>商品</h4>
        <el-table :data="detail.items" size="small">
          <el-table-column label="商品" min-width="240"
            ><template #default="{ row }"
              ><div class="product">
                <el-image v-if="row.image_url" :src="row.image_url" class="thumb-sm" fit="contain" referrerpolicy="no-referrer" />
                <div>{{ row.product_name }}<p class="muted">{{ row.sku_code || '' }}{{ row.product_id ? '' : ' · 未关联本地商品' }}</p></div>
              </div></template
            ></el-table-column
          >
          <el-table-column prop="quantity" label="数量" width="70" />
          <el-table-column label="单价" width="100"><template #default="{ row }">{{ money(row.unit_price) }}</template></el-table-column>
          <el-table-column label="小计" width="100"><template #default="{ row }">{{ money(row.subtotal) }}</template></el-table-column>
        </el-table>
        <h4>财务（由订单派生）</h4>
        <el-table :data="detail.finance" size="small">
          <template #empty><span class="muted">无（已取消 / 已退款订单不计收入）</span></template>
          <el-table-column label="类型" width="90"><template #default="{ row }">{{ financeTypes[row.type] || row.type }}</template></el-table-column>
          <el-table-column label="金额" width="140"><template #default="{ row }">{{ money(row.amount, row.currency) }}</template></el-table-column>
          <el-table-column label="人民币" width="120"><template #default="{ row }">{{ row.cny_amount === null ? '无汇率' : `¥${Number(row.cny_amount).toFixed(2)}` }}</template></el-table-column>
          <el-table-column prop="description" label="说明" />
        </el-table>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { markets } from '@/api/sourcing'
import { orders, packageStatus, formatTime, money, errorText, syncLabel, type OrderDetail, type OrderRow, type SyncStates } from '@/api/operations'

const fulfillmentTypes: Record<string, string> = { platformFulfillment: '平台仓', sellerFulfillment: '卖家自发货', platformLogisticsFulfillment: '平台物流' }
const financeTypes: Record<string, string> = { income: '收入', fee: '佣金', cost: '货源成本', refund: '退款' }
const filters = reactive({ status: '', search: '', site: '' })
const pagination = reactive({ page: 1, pageSize: 20, total: 0 })
const rows = ref<OrderRow[]>([]), loading = ref(false), syncing = ref(false), error = ref('')
const counts = ref<Record<string, number>>({}), total = ref(0), syncStates = ref<SyncStates | null>(null)
const detailVisible = ref(false), detail = ref<OrderDetail | null>(null)

function isOverdue(row: OrderRow) {
  return row.app_package_status === 'wait_seller_send' && !!row.ship_by_at && new Date(row.ship_by_at).getTime() < Date.now()
}
function region(address: Record<string, string>) {
  return [address?.countryName || address?.country, address?.state, address?.city].filter(Boolean).join(' / ') || '—'
}
async function fetchSummary() {
  const [summary, state] = await Promise.all([orders.summary(), orders.syncState()])
  counts.value = summary.counts
  total.value = Object.values(summary.counts).reduce((a, b) => a + b, 0)
  syncStates.value = state
}
async function fetchOrders() {
  loading.value = true
  error.value = ''
  try {
    const r = await orders.list({
      page: pagination.page, page_size: pagination.pageSize, app_package_status: filters.status || undefined,
      site: filters.site || undefined, search: filters.search || undefined,
    })
    rows.value = r.items
    pagination.total = r.total
  } catch (e) {
    error.value = errorText(e, '订单列表加载失败')
  } finally {
    loading.value = false
  }
}
async function search() {
  pagination.page = 1
  await fetchOrders()
}
async function sync() {
  syncing.value = true
  try {
    const r = await orders.sync()
    syncStates.value = r
    if (r.orders.status === 'failed') ElMessage.warning(r.orders.error || '订单同步失败')
    else ElMessage.success(`已同步 ${r.orders.counts.total ?? 0} 个包裹`)
    await Promise.all([fetchSummary(), fetchOrders()])
  } catch (e) {
    ElMessage.error(errorText(e, '订单同步失败'))
  } finally {
    syncing.value = false
  }
}
async function openDetail(row: OrderRow) {
  try {
    detail.value = await orders.get(row.id)
    detailVisible.value = true
  } catch (e) {
    ElMessage.error(errorText(e, '订单详情加载失败'))
  }
}
onMounted(async () => {
  try {
    await fetchSummary()
  } catch (e) {
    error.value = errorText(e, '订单统计加载失败')
  }
  await fetchOrders()
})
</script>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; }
.page-header h2 { margin: 0 0 4px; font-size: 20px; color: var(--el-text-color-primary); }
.section { margin-bottom: 16px; }
.toolbar { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }
.alert { margin-bottom: 12px; }
.muted { color: #73767a; font-size: 13px; margin: 0; }
.product { display: flex; gap: 12px; align-items: center; }
.thumb { width: 52px; height: 52px; flex-shrink: 0; }
.thumb-sm { width: 36px; height: 36px; flex-shrink: 0; }
p { margin: 4px 0 0; line-height: 1.5; overflow-wrap: anywhere; }
.overdue { color: #f56c6c; font-weight: 600; }
h4 { margin: 20px 0 8px; }
.pagination-wrapper { display: flex; justify-content: flex-end; margin-top: 16px; }
</style>
