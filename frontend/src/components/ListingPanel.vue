<template>
  <div>
    <el-alert type="info" :closable="false" show-icon>
      <template #title>
        按妙手规则把 TikTok 采集箱商品发布到已认领的店铺。每个商品先用店铺模式详情预检（标题 25–255 字符、描述、图片、重量尺寸、末级类目、必填属性与认证、SKU
        售价与店铺仓库库存），只有预检通过的商品才会提交；已发布的商品不会重复发布。发布请求只提交一次，结果不确定时只查询，不自动重发。
      </template>
    </el-alert>

    <el-card class="section" shadow="never">
      <div class="toolbar">
        <el-select v-model="filters.status" style="width: 140px" @change="search"
          ><el-option v-for="(label, key) in statusOptions" :key="key" :value="key" :label="label"
        /></el-select>
        <el-input v-model="filters.sourceId" placeholder="货源 ID" clearable style="width: 200px" @keyup.enter="search" @clear="search" />
        <el-button @click="loadProducts">刷新</el-button>
        <el-divider direction="vertical" />
        <span class="muted">已选 {{ selected.length }} 个</span>
        <el-button :disabled="!selected.length" :loading="submitting === 'check'" @click="start('check', selected)">批量预检</el-button>
        <el-button type="primary" :disabled="!selected.length" :loading="submitting === 'publish'" @click="start('publish', selected)"
          >批量上架</el-button
        >
      </div>
      <el-alert v-if="error" class="section" :title="error" type="error" :closable="false" />
      <el-table
        class="section"
        :data="products"
        v-loading="loading"
        row-key="id"
        @selection-change="(rows: TiktokBoxProduct[]) => (selected = rows)"
      >
        <el-table-column type="selection" width="45" :selectable="(row: TiktokBoxProduct) => row.shop_ids.length > 0" />
        <el-table-column label="商品" min-width="340"
          ><template #default="{ row }"
            ><div class="product">
              <el-image v-if="row.thumbnail" :src="row.thumbnail" class="thumb" fit="contain" referrerpolicy="no-referrer" />
              <div>
                <strong>{{ row.title || '无标题' }}</strong>
                <p class="muted">TK 采集箱 ID {{ row.id }}{{ row.item_num ? ` · 货号 ${row.item_num}` : '' }}</p>
              </div>
            </div></template
          ></el-table-column
        >
        <el-table-column label="价格 / 库存" width="150"
          ><template #default="{ row }">{{ row.price ?? '未知' }} / {{ row.stock ?? '未知' }}</template></el-table-column
        >
        <el-table-column label="发布店铺" width="190"
          ><template #default="{ row }"
            ><el-tag v-if="!row.shop_ids.length" type="warning">未认领店铺</el-tag
            ><span v-else-if="row.shop_ids.length === 1">店铺 {{ row.shop_ids[0] }}</span
            ><el-select v-else v-model="shopChoice[row.id]" size="small" style="width: 160px"
              ><el-option v-for="s in row.shop_ids" :key="s" :value="String(s)" :label="`店铺 ${s}`" /></el-select></template
        ></el-table-column>
        <el-table-column label="最近预检 / 发布" min-width="260"
          ><template #default="{ row }"
            ><template v-if="latest(row)"
              ><el-tag :type="itemState[latest(row)!.state]?.type || 'info'">{{ itemState[latest(row)!.state]?.label || latest(row)!.state }}</el-tag>
              <ul v-if="latest(row)!.errors?.length || latest(row)!.error" class="issues">
                <li v-for="(e, i) in latest(row)!.errors || []" :key="i">{{ e.message }}</li>
                <li v-if="latest(row)!.error">{{ latest(row)!.error }}</li>
              </ul>
              <ul v-if="latest(row)!.warnings?.length" class="issues warn">
                <li v-for="(e, i) in latest(row)!.warnings" :key="i">{{ e.message }}</li>
              </ul></template
            ><span v-else-if="!row.shop_ids.length" class="muted">请先在商品编辑工作台认领到店铺</span
            ><span v-else class="muted">未检查</span></template
          ></el-table-column
        >
        <el-table-column label="操作" width="150" fixed="right"
          ><template #default="{ row }"
            ><el-button link type="primary" :disabled="!row.shop_ids.length" @click="start('check', [row])">预检</el-button
            ><el-button link type="primary" :disabled="!row.shop_ids.length" @click="start('publish', [row])">上架</el-button></template
          ></el-table-column
        >
      </el-table>
      <div class="toolbar section">
        <el-button :disabled="filters.page === 1" @click="changePage(-1)">上一页</el-button
        ><span class="muted">第 {{ filters.page }} 页</span
        ><el-button :disabled="!hasMore" @click="changePage(1)">下一页</el-button>
      </div>
    </el-card>

    <el-card class="section" shadow="never">
      <template #header
        ><div class="toolbar"><strong>上架任务</strong><el-button size="small" @click="loadTasks">刷新</el-button></div></template
      >
      <el-table :data="tasks" row-key="id">
        <el-table-column type="expand"
          ><template #default="{ row }"
            ><el-table :data="row.items" size="small">
              <el-table-column label="商品" min-width="260"
                ><template #default="{ row: item }">{{ item.title || '—' }}<p class="muted">TK 采集箱 ID {{ item.detail_id }}</p></template></el-table-column
              >
              <el-table-column prop="shop_id" label="店铺" width="120" />
              <el-table-column label="结果" width="150"
                ><template #default="{ row: item }"
                  ><el-tag :type="itemState[item.state]?.type || 'info'">{{ itemState[item.state]?.label || item.state }}</el-tag></template
                ></el-table-column
              >
              <el-table-column label="原因 / 提示" min-width="320"
                ><template #default="{ row: item }"
                  ><ul class="issues">
                    <li v-for="(e, i) in item.errors || []" :key="i">{{ e.message }}</li>
                    <li v-if="item.error">{{ item.error }}</li>
                  </ul>
                  <ul v-if="item.warnings?.length" class="issues warn">
                    <li v-for="(e, i) in item.warnings" :key="i">{{ e.message }}</li>
                  </ul>
                  <el-collapse v-if="item.record"
                    ><el-collapse-item title="妙手发布记录（原始）"><pre>{{ JSON.stringify(item.record, null, 2) }}</pre></el-collapse-item></el-collapse
                  ></template
                ></el-table-column
              >
            </el-table></template
          ></el-table-column
        >
        <el-table-column label="类型" width="90"><template #default="{ row }">{{ row.kind === 'publish' ? '上架' : '预检' }}</template></el-table-column>
        <el-table-column label="状态" width="130"
          ><template #default="{ row }">{{ listingStatus[row.status] || row.status }}</template></el-table-column
        >
        <el-table-column label="商品结果" min-width="260"
          ><template #default="{ row }"
            ><span v-for="(n, state) in row.counts" :key="state" class="count"
              >{{ itemState[state]?.label || state }} {{ n }}</span
            ></template
          ></el-table-column
        >
        <el-table-column label="说明" min-width="220"><template #default="{ row }">{{ row.error_message || '' }}</template></el-table-column>
        <el-table-column label="创建时间" width="170"><template #default="{ row }">{{ formatTime(row.created_at) }}</template></el-table-column>
        <el-table-column label="操作" width="110"
          ><template #default="{ row }"
            ><el-button v-if="row.status === 'uncertain'" link type="primary" @click="reconcile(row)">查询结果</el-button></template
          ></el-table-column
        >
      </el-table>
      <el-pagination
        class="section"
        v-model:current-page="taskPage"
        :total="taskTotal"
        :page-size="10"
        layout="total, prev, pager, next"
        @current-change="loadTasks"
      />
    </el-card>

    <el-card class="section" shadow="never">
      <el-collapse @change="(open: string[]) => open.includes('records') && loadRecords()"
        ><el-collapse-item title="妙手发布记录（只读，原始字段）" name="records">
          <el-alert v-if="recordError" :title="recordError" type="error" :closable="false" />
          <el-empty v-else-if="!records.length" description="暂无发布记录" :image-size="60" />
          <pre v-for="(r, i) in records" :key="i" class="record">{{ JSON.stringify(r) }}</pre>
        </el-collapse-item></el-collapse
      >
    </el-card>
  </div>
</template>
<script setup lang="ts">
import { onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { Market } from '@/api/sourcing'
import { miaoshouBoxes, type TiktokBoxProduct } from '@/api/miaoshou'
import { listing, listingStatus, itemState, type ListingItem, type ListingTask } from '@/api/listing'

const props = defineProps<{ market: Market; marketLabel: string; active: boolean }>()
const statusOptions: Record<string, string> = { notPublished: '未发布', timingPublish: '定时发布', published: '已发布', '': '全部状态' }
const filters = reactive({ status: 'notPublished', sourceId: '', page: 1 })
const products = ref<TiktokBoxProduct[]>([]), hasMore = ref(false), loading = ref(false), error = ref('')
const selected = ref<TiktokBoxProduct[]>([]), shopChoice = reactive<Record<string, string>>({})
const tasks = ref<ListingTask[]>([]), taskPage = ref(1), taskTotal = ref(0)
const records = ref<Array<Record<string, unknown>>>([]), recordError = ref('')
const submitting = ref<'' | 'check' | 'publish'>('')
const ACTIVE = ['queued', 'running', 'waiting']

function errorText(e: unknown, fallback: string) {
  const detail = (e as { response?: { data?: { detail?: unknown } } }).response?.data?.detail
  return typeof detail === 'string' ? detail : fallback
}
function formatTime(value: string) {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : ''
}
function shopOf(row: TiktokBoxProduct) {
  return shopChoice[row.id] || String(row.shop_ids[0])
}
// Latest result for this product in its chosen shop, from the newest task that included it.
function latest(row: TiktokBoxProduct): ListingItem | undefined {
  const shop = shopOf(row)
  for (const task of tasks.value) {
    const item = task.items.find((x) => x.detail_id === row.id && x.shop_id === shop)
    if (item) return item
  }
  return undefined
}

async function loadProducts() {
  loading.value = true
  error.value = ''
  try {
    const r = await miaoshouBoxes.tiktok(filters.page, filters.sourceId, filters.status)
    products.value = r.items
    hasMore.value = r.has_more
    for (const row of r.items) if (row.shop_ids.length && !shopChoice[row.id]) shopChoice[row.id] = String(row.shop_ids[0])
  } catch (e) {
    error.value = errorText(e, '妙手 TikTok 采集箱读取失败')
  } finally {
    loading.value = false
  }
}
async function search() {
  filters.page = 1
  await loadProducts()
}
async function changePage(delta: number) {
  filters.page += delta
  await loadProducts()
}
async function loadTasks() {
  try {
    const r = await listing.tasks(taskPage.value)
    tasks.value = r.items
    taskTotal.value = r.total
  } catch (e) {
    error.value = errorText(e, '上架任务读取失败')
  }
}
async function loadRecords() {
  recordError.value = ''
  try {
    records.value = (await listing.records(1)).items
  } catch (e) {
    recordError.value = errorText(e, '妙手发布记录读取失败')
  }
}

async function start(kind: 'check' | 'publish', rows: TiktokBoxProduct[]) {
  const items = rows.filter((x) => x.shop_ids.length).map((x) => ({ detail_id: x.id, shop_id: shopOf(x) }))
  if (!items.length) return
  if (kind === 'publish') {
    const shops = [...new Set(items.map((x) => x.shop_id))].join('、')
    try {
      await ElMessageBox.confirm(
        `将 ${items.length} 个商品发布到 ${props.marketLabel} 店铺 ${shops}。系统会先逐个预检，只提交预检通过的商品；提交后商品进入 TikTok 店铺审核，无法在此撤回。`,
        '确认上架',
        { confirmButtonText: '确认上架', cancelButtonText: '取消', type: 'warning' },
      )
    } catch {
      return
    }
  }
  submitting.value = kind
  try {
    const task = await listing.create({ request_key: crypto.randomUUID(), kind, market: props.market, items })
    ElMessage.success(task.reused ? '已有相同任务，显示该任务进度' : kind === 'publish' ? '上架任务已提交，正在预检并发布' : '预检任务已提交')
    taskPage.value = 1
    await loadTasks()
  } catch (e) {
    ElMessage.error(errorText(e, kind === 'publish' ? '上架任务提交失败' : '预检任务提交失败'))
  } finally {
    submitting.value = ''
  }
}
async function reconcile(task: ListingTask) {
  try {
    await listing.reconcile(task.id)
    await loadTasks()
  } catch (e) {
    ElMessage.error(errorText(e, '查询失败'))
  }
}

let timer: ReturnType<typeof setInterval> | undefined
let polling = false
async function poll() {
  if (polling || document.hidden || !props.active || !tasks.value.some((x) => ACTIVE.includes(x.status))) return
  polling = true
  try {
    const before = tasks.value.filter((x) => ACTIVE.includes(x.status)).map((x) => x.id)
    await loadTasks()
    // Publishing changes the products' 妙手 status: refresh the list once a publish task finishes.
    if (tasks.value.some((x) => x.kind === 'publish' && before.includes(x.id) && !ACTIVE.includes(x.status))) await loadProducts()
  } finally {
    polling = false
  }
}
async function refresh() {
  await Promise.all([loadProducts(), loadTasks()])
}
defineExpose({ refresh })
watch(
  () => props.active,
  (active) => active && refresh(),
)
onMounted(async () => {
  if (props.active) await refresh()
  timer = setInterval(poll, 4000)
})
onUnmounted(() => timer && clearInterval(timer))
</script>
<style scoped>
.section { margin-top: 16px; }
.toolbar { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }
.muted { color: #73767a; font-size: 13px; }
.product { display: flex; gap: 12px; align-items: center; }
.thumb { width: 64px; height: 64px; flex-shrink: 0; }
p { margin: 4px 0; line-height: 1.5; overflow-wrap: anywhere; }
.issues { margin: 6px 0 0; padding-left: 18px; color: #c45656; font-size: 12px; line-height: 1.6; }
.issues.warn { color: #b88230; }
.count { margin-right: 12px; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; font-size: 12px; margin: 0; }
.record { padding: 6px 0; border-bottom: 1px solid var(--el-border-color-light); }
</style>
