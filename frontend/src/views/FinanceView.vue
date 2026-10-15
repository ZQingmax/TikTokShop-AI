<template>
  <div class="finance-container">
    <div class="page-header">
      <h2 class="page-title">财务管理</h2>
      <el-button v-if="canEditRates" :icon="Money" @click="openRates">汇率设置</el-button>
    </div>
    <p class="page-subtitle">
      财务记录由妙手同步的订单派生：收入 = 订单金额，手续费 = 平台佣金，成本 = 关联货源成本价 × 数量。已取消 / 已退款订单不计收入。
    </p>
    <el-alert
      v-if="unconvertedText"
      class="summary-row"
      type="warning"
      :closable="false"
      show-icon
      :title="`以下币种没有配置人民币汇率，未计入人民币合计：${unconvertedText}`"
    >
      <el-button v-if="canEditRates" link type="primary" @click="openRates">去设置汇率</el-button>
    </el-alert>

    <!-- 财务概览卡片 -->
    <el-row :gutter="20" class="summary-row" v-loading="summaryLoading">
      <el-col :xs="12" :sm="6" v-for="card in summaryCards" :key="card.title">
        <el-card shadow="hover" class="summary-card" :body-style="{ padding: '20px' }">
          <div class="summary-card-content">
            <div class="summary-info">
              <div class="summary-title">{{ card.title }}</div>
              <div class="summary-value">{{ card.value }}</div>
              <div class="summary-note">{{ card.note }}</div>
            </div>
            <div class="summary-icon" :style="{ backgroundColor: card.bgColor }">
              <el-icon :size="28" :style="{ color: card.iconColor }">
                <component :is="card.icon" />
              </el-icon>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 交易记录 -->
    <el-card shadow="hover">
      <template #header>
        <span>交易记录</span>
      </template>

      <!-- 筛选栏 -->
      <div class="filter-bar">
        <el-select v-model="txFilter.type" placeholder="全部类型" clearable style="width: 120px" @change="searchTransactions">
          <el-option v-for="(label, key) in txTypeMap" :key="key" :label="label" :value="key" />
        </el-select>
      </div>

      <!-- 交易表格 -->
      <el-table :data="transactions" stripe v-loading="txLoading" style="width: 100%">
        <template #empty><el-empty description="暂无财务记录。订单从妙手同步后会自动生成。" :image-size="60" /></template>
        <el-table-column prop="type" label="类型" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="txTagType(row.type)" size="small">{{ txTypeMap[row.type] || row.type }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="amount" label="金额" width="120" align="right">
          <template #default="{ row }">
            <span :class="amountClass(row.type)">{{ formatAmount(row.amount, row.type, row.currency) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="currency" label="货币" width="70" align="center" />
        <el-table-column prop="exchange_rate" label="汇率" width="90" align="right">
          <template #default="{ row }">{{ row.exchange_rate ?? '-' }}</template>
        </el-table-column>
        <el-table-column prop="cny_amount" label="人民币金额" width="120" align="right">
          <template #default="{ row }">
            <span v-if="row.cny_amount === null" class="muted">无汇率</span>
            <span v-else :class="amountClass(row.type)">{{ formatCNY(row.cny_amount) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="描述" min-width="180" show-overflow-tooltip />
        <el-table-column prop="site" label="站点" width="80" align="center" />
        <el-table-column prop="created_at" label="创建时间" width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
      </el-table>

      <div class="pagination-wrap">
        <el-pagination
          v-model:current-page="txPage"
          v-model:page-size="txPageSize"
          :total="txTotal"
          :page-sizes="[10, 20, 50]"
          layout="total, sizes, prev, pager, next, jumper"
          @size-change="fetchTransactions"
          @current-change="fetchTransactions"
        />
      </div>
    </el-card>

    <!-- 汇率设置：只显示已录入的值，不预填任何数字 -->
    <el-dialog v-model="ratesVisible" title="人民币汇率设置" width="860px">
      <p class="rates-hint">
        汇率含义：1 人民币（CNY）= 汇率 × 外币，即填写 1 元人民币可兑换的外币数量。请填写实际使用的汇率，最多 6 位小数。
        保存后会为该币种还没有人民币金额的财务记录补算。
      </p>
      <el-table :data="rates" v-loading="ratesLoading" style="width: 100%">
        <el-table-column prop="currency" label="币种" width="70" />
        <el-table-column label="当前汇率" width="130" align="right">
          <template #default="{ row }">
            <span v-if="row.rate">{{ trimRate(row.rate) }}</span>
            <span v-else class="muted">未设置</span>
          </template>
        </el-table-column>
        <el-table-column label="最后更新" min-width="150">
          <template #default="{ row }">
            <template v-if="row.updated_at">
              <div>{{ formatTime(row.updated_at) }}</div>
              <div class="muted">{{ row.updated_by_name || '无记录（非本页录入）' }}</div>
            </template>
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>
        <el-table-column label="未换算记录" width="96" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.unconverted_records" type="warning" size="small">{{ row.unconverted_records }} 笔</el-tag>
            <span v-else class="muted">0</span>
          </template>
        </el-table-column>
        <el-table-column label="新汇率" min-width="230">
          <template #default="{ row }">
            <div class="rate-edit">
              <el-input v-model="rateDrafts[row.currency]" :placeholder="`1 CNY = ? ${row.currency}`" size="small" clearable />
              <el-checkbox v-model="recomputeAll[row.currency]" size="small" :disabled="!row.rate">重算全部</el-checkbox>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="" width="80" align="center">
          <template #default="{ row }">
            <el-button type="primary" size="small" :loading="savingCurrency === row.currency" @click="saveRate(row)">保存</el-button>
          </template>
        </el-table-column>
      </el-table>
      <p class="rates-hint">
        勾选“重算全部”会用新汇率重新计算该币种的所有财务记录（包括已按旧汇率换算的历史记录）；不勾选只补算尚未换算的记录。
      </p>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, markRaw } from 'vue'
import { ElMessage } from 'element-plus'
import { TrendCharts, Coin, Wallet, DataLine, Money } from '@element-plus/icons-vue'
import { getFinanceSummary, getTransactions, getExchangeRates, saveExchangeRate, type ExchangeRateItem } from '@/api'
import { useUserStore } from '@/stores/user'

// ========== 类型映射 ==========
const txTypeMap: Record<string, string> = {
  income: '收入',
  cost: '成本',
  refund: '退款',
  fee: '平台佣金',
}

function txTagType(type: string): string {
  const map: Record<string, string> = { income: 'success', cost: 'danger', refund: 'warning', fee: 'info', withdrawal: 'primary' }
  return map[type] || 'info'
}

// ========== 工具函数 ==========
function formatAmount(val: number | undefined, type: string, currency: string): string {
  if (val === undefined || val === null) return '-'
  const prefix = type === 'refund' || type === 'cost' || type === 'fee' ? '-' : ''
  return `${prefix}${Number(val).toFixed(2)} ${currency || ''}`.trim()
}

function formatCNY(val: number | undefined): string {
  if (val === undefined || val === null) return '-'
  return `¥${Number(val).toFixed(2)}`
}

function amountClass(type: string): string {
  if (type === 'income') return 'amount-income'
  if (type === 'cost') return 'amount-cost'
  if (type === 'refund') return 'amount-refund'
  return ''
}

function formatTime(val: string | undefined): string {
  if (!val) return '-'
  const d = new Date(val)
  if (isNaN(d.getTime())) return val
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

// ========== 财务概览 ==========
const summaryLoading = ref(false)
const summaryData = ref<any>({})

const summaryCards = ref([
  { title: '总收入（CNY）', value: '¥0.00', note: '订单金额合计', icon: markRaw(TrendCharts), iconColor: '#67C23A', bgColor: '#F0F9EB' },
  { title: '货源成本（CNY）', value: '¥0.00', note: '关联商品成本价 × 数量', icon: markRaw(Coin), iconColor: '#F56C6C', bgColor: '#FEF0F0' },
  { title: '净利润（CNY）', value: '¥0.00', note: '收入 − 成本 − 佣金 − 退款', icon: markRaw(Wallet), iconColor: '#1677ff', bgColor: '#ECF5FF' },
  { title: '利润率', value: '—', note: '净利润 ÷ 收入', icon: markRaw(DataLine), iconColor: '#E6A23C', bgColor: '#FDF6EC' },
])
const unconvertedText = computed(() =>
  Object.entries(summaryData.value.unconverted || {}).map(([currency, n]) => `${currency}（${n} 笔）`).join('、'),
)

async function fetchSummary() {
  summaryLoading.value = true
  try {
    const res = await getFinanceSummary()
    const data = res.data || res
    summaryData.value = data

    summaryCards.value[0].value = `¥${Number(data.total_revenue || 0).toFixed(2)}`
    summaryCards.value[1].value = `¥${Number(data.total_cost || 0).toFixed(2)}`
    summaryCards.value[2].value = `¥${Number(data.net_profit || 0).toFixed(2)}`
    // profit_rate is a fraction; only meaningful when there is revenue.
    summaryCards.value[3].value = Number(data.total_revenue) > 0 ? `${(Number(data.profit_rate) * 100).toFixed(1)}%` : '—'
  } catch (e: any) {
    ElMessage.error(e?.message || '获取财务概览失败')
  } finally {
    summaryLoading.value = false
  }
}

// ========== 交易记录 ==========
const txLoading = ref(false)
const transactions = ref<any[]>([])
const txPage = ref(1)
const txPageSize = ref(10)
const txTotal = ref(0)
const txFilter = reactive({ type: '' })

function searchTransactions() {
  txPage.value = 1
  fetchTransactions()
}

async function fetchTransactions() {
  txLoading.value = true
  try {
    const params: Record<string, unknown> = { page: txPage.value, page_size: txPageSize.value }
    if (txFilter.type) params.type = txFilter.type
    const res = await getTransactions(params)
    const data = res.data || res
    transactions.value = data.items || data.results || data.list || data.data || []
    txTotal.value = data.total || data.count || 0
  } catch (e: any) {
    ElMessage.error(e?.message || '获取交易记录失败')
  } finally {
    txLoading.value = false
  }
}

// ========== 汇率设置 ==========
const userStore = useUserStore()
const canEditRates = computed(() => ['admin', 'operator'].includes(userStore.userInfo?.role || ''))
const ratesVisible = ref(false)
const ratesLoading = ref(false)
const rates = ref<ExchangeRateItem[]>([])
const rateDrafts = reactive<Record<string, string>>({})
const recomputeAll = reactive<Record<string, boolean>>({})
const savingCurrency = ref('')

function trimRate(rate: string): string {
  return rate.includes('.') ? rate.replace(/0+$/, '').replace(/\.$/, '') : rate
}

async function fetchRates() {
  ratesLoading.value = true
  try {
    rates.value = (await getExchangeRates()).items
  } catch {
    // 错误提示由请求拦截器显示
  } finally {
    ratesLoading.value = false
  }
}

function openRates() {
  ratesVisible.value = true
  fetchRates()
}

async function saveRate(row: ExchangeRateItem) {
  const value = (rateDrafts[row.currency] || '').trim()
  // 与后端一致：大于 0，最多 4 位整数、6 位小数（财务记录的汇率列为 NUMERIC(10, 6)）
  if (!/^\d{1,4}(\.\d{1,6})?$/.test(value) || Number(value) <= 0) {
    ElMessage.warning('请输入大于 0 的汇率，最多 4 位整数、6 位小数')
    return
  }
  savingCurrency.value = row.currency
  try {
    const saved = await saveExchangeRate(row.currency, value, !!recomputeAll[row.currency])
    ElMessage.success(`已保存 ${row.currency} 汇率，重新换算 ${saved.recomputed_records ?? 0} 笔记录`)
    rateDrafts[row.currency] = ''
    recomputeAll[row.currency] = false
    await Promise.all([fetchRates(), fetchSummary(), fetchTransactions()])
  } catch {
    // 错误提示由请求拦截器显示
  } finally {
    savingCurrency.value = ''
  }
}

// ========== 初始化 ==========
onMounted(() => {
  fetchSummary()
  fetchTransactions()
})
</script>

<style scoped>
.finance-container { padding: 20px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.page-title { margin: 0; font-size: 22px; color: var(--el-text-color-primary); }
.rates-hint { margin: 0 0 12px; font-size: 13px; color: var(--el-text-color-regular); line-height: 1.6; }
.rate-edit { display: flex; gap: 8px; align-items: center; }
.summary-row { margin-bottom: 20px; }
.summary-card-content { display: flex; justify-content: space-between; align-items: center; }
.summary-info { flex: 1; }
.summary-title { font-size: 14px; color: var(--el-text-color-secondary); margin-bottom: 8px; }
.summary-value { font-size: 24px; font-weight: 700; color: var(--el-text-color-primary); margin-bottom: 8px; }
.summary-note { font-size: 12px; color: var(--el-text-color-secondary); }
.page-subtitle { margin: -8px 0 16px; font-size: 13px; color: var(--el-text-color-secondary); }
.muted { color: var(--el-text-color-secondary); }
.summary-icon { width: 56px; height: 56px; border-radius: 12px; display: flex; align-items: center; justify-content: center; }
.filter-bar { display: flex; gap: 12px; align-items: center; margin-bottom: 16px; }
.pagination-wrap { display: flex; justify-content: flex-end; margin-top: 16px; }
.amount-income { color: #67C23A; font-weight: 600; }
.amount-cost { color: #F56C6C; font-weight: 600; }
.amount-refund { color: #E6A23C; font-weight: 600; }
</style>
