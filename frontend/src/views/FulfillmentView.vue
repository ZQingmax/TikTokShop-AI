<template>
  <div class="fulfillment-container">
    <div class="page-header">
      <div>
        <h2>履约管理</h2>
        <p class="muted">
          发货包裹来自妙手订单包裹，采购单来自妙手采购（1688），每 10 分钟自动同步。{{ syncLabel(syncStates?.purchase_orders) }}
        </p>
      </div>
      <el-button type="primary" :loading="syncing" @click="sync">从妙手同步</el-button>
    </div>

    <el-row :gutter="16" class="section">
      <el-col :span="6"><el-card shadow="never"><div class="stat-title">待发货包裹</div><div class="stat-value">{{ summary.to_ship }}</div></el-card></el-col>
      <el-col :span="6"
        ><el-card shadow="never"
          ><div class="stat-title">超过最迟发货时间</div><div class="stat-value" :class="{ danger: summary.overdue }">{{ summary.overdue }}</div></el-card
        ></el-col
      >
      <el-col :span="6"><el-card shadow="never"><div class="stat-title">运输中（已发货）</div><div class="stat-value">{{ summary.shipped }}</div></el-card></el-col>
      <el-col :span="6"><el-card shadow="never"><div class="stat-title">采购单</div><div class="stat-value">{{ poCount }}</div></el-card></el-col>
    </el-row>

    <el-card shadow="never">
      <el-alert v-if="error" :title="error" type="error" :closable="false" class="alert" />
      <el-tabs v-model="activeTab" @tab-change="load">
        <el-tab-pane label="待发货" name="to_ship" />
        <el-tab-pane label="已发货" name="shipped" />
        <el-tab-pane label="采购单（1688）" name="purchase" />
        <el-tab-pane label="采购到货物流" name="inbound" />
      </el-tabs>

      <el-table v-if="activeTab === 'to_ship' || activeTab === 'shipped'" v-loading="loading" :data="outbound">
        <template #empty
          ><el-empty
            :description="activeTab === 'to_ship' ? '没有待发货的包裹' : '没有运输中的包裹'"
            :image-size="60"
        /></template>
        <el-table-column label="订单 / 包裹" min-width="200"
          ><template #default="{ row }">{{ row.tiktok_order_id || '—' }}<p class="muted">包裹 {{ row.miaoshou_package_id }}</p></template></el-table-column
        >
        <el-table-column label="商品" min-width="280"
          ><template #default="{ row }"
            ><div v-for="(item, i) in row.items" :key="i" class="product">
              <el-image v-if="item.image_url" :src="item.image_url" class="thumb" fit="contain" referrerpolicy="no-referrer" />
              <span>{{ item.name }}<span class="muted"> {{ item.sku || '' }} × {{ item.quantity }}</span></span>
            </div></template
          ></el-table-column
        >
        <el-table-column label="店铺 / 站点" min-width="150"><template #default="{ row }">{{ row.shop_name || '—' }}<p class="muted">{{ row.site || '—' }}</p></template></el-table-column>
        <el-table-column v-if="activeTab === 'to_ship'" label="最迟发货" width="170"
          ><template #default="{ row }"><span :class="{ danger: isOverdue(row.ship_by_at) }">{{ formatTime(row.ship_by_at) }}</span></template></el-table-column
        >
        <el-table-column v-else label="发货时间" width="170"><template #default="{ row }">{{ formatTime(row.shipped_at) }}</template></el-table-column>
        <el-table-column label="物流 / 运单" min-width="200"
          ><template #default="{ row }">{{ row.carrier || '未选择物流' }}<p class="muted">{{ row.tracking_number || '未出运单' }}</p></template></el-table-column
        >
      </el-table>

      <el-table v-else-if="activeTab === 'purchase'" v-loading="loading" :data="purchaseOrders">
        <template #empty><el-empty description="妙手中暂无采购单" :image-size="60" /></template>
        <el-table-column label="采购单" min-width="200"
          ><template #default="{ row }">{{ row.po_sn || '—' }}<p class="muted">{{ row.alibaba_order_id ? `1688 ${row.alibaba_order_id}` : '未下 1688 单' }}</p></template></el-table-column
        >
        <el-table-column prop="supplier_name" label="供应商" min-width="160" />
        <el-table-column label="商品" min-width="260"
          ><template #default="{ row }"
            ><div v-for="(item, i) in row.items" :key="i">
              {{ item.name || '—' }}<span class="muted"> {{ item.spec || '' }} × {{ item.quantity ?? '?' }}（到货 {{ item.received ?? 0 }}）</span>
            </div></template
          ></el-table-column
        >
        <el-table-column label="金额" width="120" align="right"><template #default="{ row }">{{ money(row.total_amount, row.currency) }}</template></el-table-column>
        <el-table-column prop="status" label="状态" width="120" />
        <el-table-column label="运单" min-width="150"><template #default="{ row }">{{ row.tracking_number || '—' }}</template></el-table-column>
        <el-table-column label="创建时间" width="160"><template #default="{ row }">{{ formatTime(row.ordered_at || row.created_at) }}</template></el-table-column>
      </el-table>

      <el-table v-else v-loading="loading" :data="shipments">
        <template #empty><el-empty description="暂无采购到货物流" :image-size="60" /></template>
        <el-table-column prop="po_sn" label="采购单" min-width="160" />
        <el-table-column prop="carrier" label="物流公司" width="140" />
        <el-table-column prop="tracking_number" label="运单号" min-width="180" />
        <el-table-column label="状态" width="110"><template #default="{ row }">{{ shipmentStatus[row.status] || row.status }}</template></el-table-column>
        <el-table-column label="发货方 → 收货仓" min-width="240"><template #default="{ row }">{{ row.origin || '—' }} → {{ row.destination || '—' }}</template></el-table-column>
      </el-table>

      <div class="pagination-wrap">
        <el-pagination v-model:current-page="page" :total="totalRows" :page-size="20" layout="total, prev, pager, next" @current-change="loadRows" />
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  fulfillment, orders, formatTime, money, errorText, syncLabel,
  type OutboundRow, type PurchaseOrderRow, type ShipmentRow, type SyncStates,
} from '@/api/operations'

const shipmentStatus: Record<string, string> = { pending: '待发货', in_transit: '运输中', delivered: '已送达', returned: '已退回', exception: '异常' }
const activeTab = ref<'to_ship' | 'shipped' | 'purchase' | 'inbound'>('to_ship')
const summary = reactive({ to_ship: 0, overdue: 0, shipped: 0, purchase_orders: {} as Record<string, number> })
const poCount = computed(() => Object.values(summary.purchase_orders).reduce((a, b) => a + b, 0))
const outbound = ref<OutboundRow[]>([]), purchaseOrders = ref<PurchaseOrderRow[]>([]), shipments = ref<ShipmentRow[]>([])
const page = ref(1), totalRows = ref(0), loading = ref(false), syncing = ref(false), error = ref('')
const syncStates = ref<SyncStates | null>(null)

function isOverdue(value: string | null) {
  return !!value && new Date(value).getTime() < Date.now()
}
async function loadSummary() {
  const [s, state] = await Promise.all([fulfillment.summary(), orders.syncState()])
  Object.assign(summary, s)
  syncStates.value = state
}
async function loadRows() {
  loading.value = true
  error.value = ''
  try {
    if (activeTab.value === 'to_ship' || activeTab.value === 'shipped') {
      const r = await fulfillment.outbound(activeTab.value, page.value)
      outbound.value = r.items
      totalRows.value = r.total
    } else if (activeTab.value === 'purchase') {
      const r = await fulfillment.purchaseOrders(page.value)
      purchaseOrders.value = r.items
      totalRows.value = r.total
    } else {
      const r = await fulfillment.shipments(page.value)
      shipments.value = r.items
      totalRows.value = r.total
    }
  } catch (e) {
    error.value = errorText(e, '履约数据加载失败')
  } finally {
    loading.value = false
  }
}
async function load() {
  page.value = 1
  await loadRows()
}
async function sync() {
  syncing.value = true
  try {
    const r = await orders.sync()
    syncStates.value = r
    const failed = [r.orders, r.purchase_orders].find((x) => x.status === 'failed')
    if (failed) ElMessage.warning(failed.error || '同步失败')
    else ElMessage.success('已从妙手同步包裹与采购单')
    await Promise.all([loadSummary(), loadRows()])
  } catch (e) {
    ElMessage.error(errorText(e, '同步失败'))
  } finally {
    syncing.value = false
  }
}
onMounted(async () => {
  try {
    await loadSummary()
  } catch (e) {
    error.value = errorText(e, '履约统计加载失败')
  }
  await loadRows()
})
</script>

<style scoped>
.fulfillment-container { padding: 0; }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; }
.page-header h2 { margin: 0 0 4px; font-size: 20px; color: var(--el-text-color-primary); }
.section { margin-bottom: 16px; }
.alert { margin-bottom: 12px; }
.muted { color: #73767a; font-size: 13px; margin: 0; }
.stat-title { font-size: 13px; color: var(--el-text-color-secondary); }
.stat-value { font-size: 24px; font-weight: 700; color: var(--el-text-color-primary); margin-top: 6px; }
.danger { color: #f56c6c; font-weight: 600; }
.product { display: flex; gap: 8px; align-items: center; margin: 2px 0; }
.thumb { width: 36px; height: 36px; flex-shrink: 0; }
p { margin: 4px 0 0; line-height: 1.5; overflow-wrap: anywhere; }
.pagination-wrap { display: flex; justify-content: flex-end; margin-top: 16px; }
</style>
