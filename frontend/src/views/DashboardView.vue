<template>
  <div class="dashboard-container" v-loading="loading">
    <div class="dashboard-header">
      <div>
        <h2>工作台</h2>
        <p class="dashboard-subtitle">
          欢迎回来，{{ userStore.userInfo?.nickname || '管理员' }}！数据来自妙手（订单每 10 分钟自动同步）。{{ syncLabel(stats?.sync?.orders) }}
        </p>
      </div>
      <el-button :loading="syncing" @click="sync">立即同步</el-button>
    </div>

    <el-row :gutter="20" class="stats-row">
      <el-col v-for="item in statCards" :key="item.title" :xs="12" :sm="6">
        <el-card shadow="hover" class="stat-card" :body-style="{ padding: '20px' }">
          <div class="stat-card-content">
            <div class="stat-info">
              <div class="stat-title">{{ item.title }}</div>
              <div class="stat-value">{{ item.value }}</div>
              <div v-if="item.trend !== null && item.trend !== undefined" class="stat-trend" :class="item.trend >= 0 ? 'up' : 'down'">
                {{ item.trend >= 0 ? '+' : '' }}{{ item.trend }}% <span class="stat-trend-label">较昨日</span>
              </div>
              <div v-else class="stat-note">{{ item.note }}</div>
            </div>
            <div class="stat-icon" :style="{ backgroundColor: item.bgColor }">
              <el-icon :size="28" :style="{ color: item.iconColor }"><component :is="item.icon" /></el-icon>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-alert
      v-if="stats && stats.unconverted_income_records"
      class="stats-row"
      type="warning"
      :closable="false"
      show-icon
      :title="`有 ${stats.unconverted_income_records} 笔订单收入的币种没有配置人民币汇率，未计入销售额。`"
    />

    <el-row :gutter="20" class="chart-row">
      <el-col :xs="24" :lg="16">
        <el-card shadow="hover">
          <template #header><span>近 7 天销售额（CNY）与订单数</span></template>
          <div class="chart-wrap">
            <div ref="salesChartRef" class="chart-container"></div>
            <el-empty v-if="!hasSales" class="chart-empty" description="近 7 天暂无订单" :image-size="60" />
          </div>
        </el-card>
      </el-col>
      <el-col :xs="24" :lg="8">
        <el-card shadow="hover">
          <template #header><span>订单状态分布</span></template>
          <div class="chart-wrap">
            <div ref="orderChartRef" class="chart-container"></div>
            <el-empty v-if="!hasStatus" class="chart-empty" description="暂无订单" :image-size="60" />
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="hover" class="recent-orders">
      <template #header>
        <div class="card-header">
          <span>最近订单</span>
          <el-button type="primary" link @click="router.push('/orders')">查看全部</el-button>
        </div>
      </template>
      <el-table :data="recentOrders" style="width: 100%">
        <template #empty><el-empty description="还没有订单。商品在 TikTok 店铺售出后，订单会从妙手自动同步到这里。" :image-size="60" /></template>
        <el-table-column prop="tiktok_order_id" label="订单编号" min-width="180" />
        <el-table-column label="店铺 / 站点" min-width="160"
          ><template #default="{ row }">{{ row.shop_name || '—' }} {{ row.site ? `· ${row.site}` : '' }}</template></el-table-column
        >
        <el-table-column label="金额" width="140"><template #default="{ row }">{{ money(row.total_amount, row.currency) }}</template></el-table-column>
        <el-table-column label="状态" width="110"
          ><template #default="{ row }"><el-tag size="small">{{ row.status_text || row.status }}</el-tag></template></el-table-column
        >
        <el-table-column label="下单时间" width="170"><template #default="{ row }">{{ formatTime(row.created_at) }}</template></el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, markRaw, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ShoppingCart, Money, Clock, Goods } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'
import { useUserStore } from '@/stores/user'
import { useThemeStore } from '@/stores/theme'
import {
  getDashboardStats,
  getDashboardRecentOrders,
  getDashboardSalesTrend,
  getDashboardOrderDistribution,
} from '@/api/index'
import { orders, formatTime, money, syncLabel, errorText, type SyncStates } from '@/api/operations'

interface Stats {
  today_orders: number; today_sales: string; pending_orders: number; overdue_orders: number
  total_products: number; published_products: number; unpublished_products: number
  unconverted_income_records: number; order_trend: number | null; sales_trend: number | null; sync: SyncStates
}

const router = useRouter()
const userStore = useUserStore()
const themeStore = useThemeStore()
const salesChartRef = ref<HTMLElement>()
const orderChartRef = ref<HTMLElement>()
let salesChart: echarts.ECharts | null = null
let orderChart: echarts.ECharts | null = null
const loading = ref(false), syncing = ref(false)
const stats = ref<Stats | null>(null)
const recentOrders = ref<any[]>([])
const trend = ref<{ sales: number[]; orders: number[] }>({ sales: [], orders: [] })
const statusData = ref<{ name: string; value: number }[]>([])
const hasSales = computed(() => trend.value.orders.some((n) => n > 0))
const hasStatus = computed(() => statusData.value.length > 0)

const statCards = computed(() => {
  const s = stats.value
  return [
    { title: '今日订单', value: s ? String(s.today_orders) : '—', trend: s?.order_trend, note: '昨日无订单，暂无对比',
      icon: markRaw(ShoppingCart), iconColor: '#1677ff', bgColor: '#ECF5FF' },
    { title: '今日销售额（CNY）', value: s ? `¥${Number(s.today_sales).toFixed(2)}` : '—', trend: s?.sales_trend, note: '昨日无销售额，暂无对比',
      icon: markRaw(Money), iconColor: '#67C23A', bgColor: '#F0F9EB' },
    { title: '待发货包裹', value: s ? String(s.pending_orders) : '—', trend: null,
      note: s?.overdue_orders ? `其中 ${s.overdue_orders} 个已超过最迟发货时间` : '没有超时包裹',
      icon: markRaw(Clock), iconColor: '#E6A23C', bgColor: '#FDF6EC' },
    { title: '商品（妙手）', value: s ? String(s.total_products) : '—', trend: null,
      note: s ? `已发布 ${s.published_products} · 未发布 ${s.unpublished_products}` : '',
      icon: markRaw(Goods), iconColor: '#F56C6C', bgColor: '#FEF0F0' },
  ]
})

function initSalesChart(dates: string[], sales: number[], counts: number[]) {
  if (!salesChartRef.value) return
  if (!salesChart) salesChart = echarts.init(salesChartRef.value)
  salesChart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['销售额', '订单数'], top: 0 },
    grid: { left: '3%', right: '4%', bottom: '3%', top: 36, containLabel: true },
    xAxis: { type: 'category', boundaryGap: false, data: dates },
    yAxis: [{ type: 'value', name: 'CNY' }, { type: 'value', name: '订单', minInterval: 1 }],
    series: [
      { name: '销售额', type: 'line', smooth: true, areaStyle: { opacity: 0.2 }, data: sales, itemStyle: { color: '#1677ff' } },
      { name: '订单数', type: 'bar', yAxisIndex: 1, data: counts, barMaxWidth: 18, itemStyle: { color: '#E6A23C' } },
    ],
  }, true)
}

function initOrderChart(data: { name: string; value: number }[]) {
  if (!orderChartRef.value) return
  if (!orderChart) orderChart = echarts.init(orderChartRef.value)
  orderChart.setOption({
    tooltip: { trigger: 'item' },
    legend: { bottom: '0', left: 'center' },
    series: [{
      name: '订单状态', type: 'pie', radius: ['40%', '70%'], avoidLabelOverlap: false,
      itemStyle: { borderRadius: 10, borderColor: '#fff', borderWidth: 2 },
      label: { show: false, position: 'center' },
      emphasis: { label: { show: true, fontSize: 16, fontWeight: 'bold' } },
      labelLine: { show: false },
      data,
    }],
  }, true)
}

function handleResize() {
  salesChart?.resize()
  orderChart?.resize()
}

function applyChartTheme() {
  const styles = getComputedStyle(document.documentElement)
  const color = (name: string) => styles.getPropertyValue(name).trim()
  const text = color('--el-text-color-regular')
  const border = color('--el-border-color-light')
  const tooltip = { backgroundColor: color('--el-bg-color-overlay'), borderColor: border, textStyle: { color: text } }
  const axis = { axisLabel: { color: text }, nameTextStyle: { color: text }, splitLine: { lineStyle: { color: border } } }
  salesChart?.setOption({
    textStyle: { color: text }, tooltip, legend: { textStyle: { color: text } },
    xAxis: axis, yAxis: [axis, axis],
    series: [{ itemStyle: { color: color('--app-brand') } }, {}],
  })
  orderChart?.setOption({
    textStyle: { color: text }, tooltip, legend: { textStyle: { color: text } },
    series: [{ itemStyle: { borderColor: color('--el-bg-color') } }],
  })
}

watch(() => themeStore.current, applyChartTheme, { flush: 'post' })

async function loadDashboardData() {
  loading.value = true
  try {
    const [statsRes, ordersRes, trendRes, distRes] = await Promise.allSettled([
      getDashboardStats(), getDashboardRecentOrders(), getDashboardSalesTrend(), getDashboardOrderDistribution(),
    ])
    if (statsRes.status === 'fulfilled') stats.value = statsRes.value as unknown as Stats
    if (ordersRes.status === 'fulfilled' && Array.isArray(ordersRes.value)) recentOrders.value = ordersRes.value
    if (trendRes.status === 'fulfilled' && trendRes.value) {
      const t = trendRes.value as unknown as { dates: string[]; sales: number[]; orders: number[] }
      trend.value = { sales: t.sales || [], orders: t.orders || [] }
      initSalesChart(t.dates || [], trend.value.sales, trend.value.orders)
    }
    if (distRes.status === 'fulfilled') {
      statusData.value = (distRes.value as unknown as { data: { name: string; value: number }[] })?.data || []
      initOrderChart(statusData.value)
    }
    applyChartTheme()
    if ([statsRes, ordersRes, trendRes, distRes].some((r) => r.status === 'rejected')) ElMessage.error('部分仪表盘数据加载失败')
  } finally {
    loading.value = false
  }
}

async function sync() {
  syncing.value = true
  try {
    const r = await orders.sync()
    if (r.orders.status === 'failed' || r.purchase_orders.status === 'failed') ElMessage.warning(r.orders.error || r.purchase_orders.error || '同步失败')
    else ElMessage.success('已从妙手同步订单与采购单')
    await loadDashboardData()
  } catch (e) {
    ElMessage.error(errorText(e, '同步失败'))
  } finally {
    syncing.value = false
  }
}

onMounted(() => {
  loadDashboardData()
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  salesChart?.dispose()
  orderChart?.dispose()
})
</script>

<style scoped>
.dashboard-container { padding: 20px; }
.dashboard-header { margin-bottom: 24px; display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; }
.dashboard-header h2 { margin: 0 0 4px; font-size: 22px; color: var(--el-text-color-primary); }
.dashboard-subtitle { margin: 0; font-size: 14px; color: var(--el-text-color-secondary); }
.stats-row { margin-bottom: 20px; }
.stat-card-content { display: flex; justify-content: space-between; align-items: center; }
.stat-title { font-size: 14px; color: var(--el-text-color-secondary); margin-bottom: 8px; }
.stat-value { font-size: 24px; font-weight: 700; color: var(--el-text-color-primary); margin-bottom: 8px; }
.stat-trend { font-size: 12px; display: flex; align-items: center; gap: 2px; }
.stat-trend.up { color: #67C23A; }
.stat-trend.down { color: #F56C6C; }
.stat-trend-label { color: var(--el-text-color-secondary); margin-left: 4px; }
.stat-note { font-size: 12px; color: var(--el-text-color-secondary); }
.stat-icon { width: 56px; height: 56px; border-radius: 12px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.chart-row { margin-bottom: 20px; }
.chart-wrap { position: relative; }
.chart-container { height: 320px; width: 100%; }
.chart-empty { position: absolute; inset: 0; background: var(--el-bg-color, #fff); }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.recent-orders { margin-bottom: 20px; }
</style>
