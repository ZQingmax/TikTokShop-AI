<template>
  <div class="collect-center">
    <header>
      <div>
        <h2>采集上架</h2>
        <p>我的采集箱 → 商品编辑工作台 → 妙手 ERP 采集箱 → 商品上架</p>
      </div>
      <el-select v-model="market" :disabled="workbenchPanel?.dirty" style="width: 180px" @change="changeMarket"
        ><el-option v-for="m in markets" :key="m" :value="m" :label="marketNames[m]"
      /></el-select>
    </header>
    <el-tabs v-model="tab" class="main-tabs" :before-leave="beforeTabLeave" @tab-change="changeTab">
      <el-tab-pane label="我的采集箱" name="mybox">
        <el-alert
          type="info"
          :closable="false"
          show-icon
          title="选择商品进入编辑工作台，完善文案、图片、SKU 与店铺资料；检查通过后确认同步到妙手店铺采集箱。"
        />
        <el-card class="section" shadow="never">
          <div class="toolbar">
            <el-input
              v-model="box.keyword"
              placeholder="名称 / 货源 ID"
              clearable
              style="width: 220px"
              @keyup.enter="searchBox"
              @clear="searchBox"
            /><el-select
              v-model="box.status"
              clearable
              placeholder="全部同步状态"
              style="width: 170px"
              @change="searchBox"
              ><el-option
                v-for="(label, key) in syncLabels"
                :key="key"
                :value="key"
                :label="`${label}（${box.counts[key] || 0}）`" /></el-select
            ><el-button @click="loadBox">刷新</el-button>
            <span class="spacer" />
            <el-button type="primary" :disabled="!boxSelection.length" :loading="busy" @click="enterWorkbench(boxSelection)"
              >进入商品编辑工作台（{{ boxSelection.length }}）</el-button
            ><el-button :disabled="!boxSelection.length" :loading="busy" @click="removeItems(boxSelection)"
              >移出采集箱</el-button
            >
          </div>
          <el-table
            class="section"
            :data="box.items"
            v-loading="box.loading"
            row-key="id"
            @selection-change="(rows: CollectBoxItem[]) => (boxSelection = rows)"
          >
            <el-table-column type="selection" width="45" :selectable="(r: CollectBoxItem) => r.sync_status !== 'syncing'" />
            <el-table-column label="商品" min-width="320"
              ><template #default="{ row }"
                ><div class="product">
                  <el-image
                    v-if="row.main_image"
                    :src="row.main_image"
                    class="thumb"
                    fit="contain"
                    referrerpolicy="no-referrer"
                  />
                  <div>
                    <strong>{{ row.name || '待补充名称' }}</strong>
                    <p class="muted">
                      {{ row.purchase_price ?? '未知' }} {{ row.currency }} · {{ row.supplier || '供应商待核实' }}
                    </p>
                    <el-link :href="row.product_url" target="_blank" rel="noopener noreferrer">查看货源</el-link>
                  </div>
                </div></template
              ></el-table-column
            >
            <el-table-column label="品类 / 备注" min-width="180"
              ><template #default="{ row }"
                ><p>{{ row.category || '品类未知' }}</p>
                <p class="muted">{{ row.note || '—' }}</p></template
              ></el-table-column
            >
            <el-table-column label="妙手同步" min-width="220"
              ><template #default="{ row }"
                ><el-tag :type="syncTagType[row.sync_status as BoxSyncStatus]">{{
                  syncLabels[row.sync_status as BoxSyncStatus]
                }}</el-tag>
                <p v-if="row.miaoshou_box" class="muted">
                  {{ boxLabels[row.miaoshou_box as MiaoshouBox] }}{{ row.miaoshou_detail_id ? ` · ID ${row.miaoshou_detail_id}` : '' }}
                </p>
                <p v-if="row.sync_error" class="error">{{ row.sync_error }}</p></template
              ></el-table-column
            >
            <el-table-column label="加入时间" width="170"
              ><template #default="{ row }">{{ formatTime(row.created_at) }}</template></el-table-column
            >
            <el-table-column label="操作" width="200" fixed="right"
              ><template #default="{ row }"
                ><el-button link type="primary" @click="enterWorkbench([row])"
                  >编辑商品</el-button
                ><el-button link @click="editNote(row)">备注</el-button
                ><el-button v-if="row.sync_task_id" link @click="showJob(row.sync_task_id)">任务</el-button
                ><el-button link type="danger" :disabled="row.sync_status === 'syncing'" @click="removeItems([row])"
                  >移出</el-button
                ></template
              ></el-table-column
            >
            <template #empty
              ><el-empty description="采集箱为空：在「选品中心 → 候选商品库」中点击「加入我的采集箱」" :image-size="80"
            /></template>
          </el-table>
          <el-pagination
            class="section"
            v-model:current-page="box.page"
            :total="box.total"
            :page-size="20"
            layout="total, prev, pager, next"
            @current-change="loadBox"
          />
        </el-card>
      </el-tab-pane>
      <el-tab-pane label="商品编辑工作台" name="workbench" lazy>
        <ProductWorkbench ref="workbenchPanel" :market="market" :draft-id="String(route.query.draft || '') || undefined" :active="tab === 'workbench'" />
      </el-tab-pane>
      <el-tab-pane label="妙手 ERP 采集箱" name="miaoshou">
        <el-card shadow="never">
          <div class="toolbar">
            <el-radio-group v-model="ms.box" @change="searchMiaoshou"
              ><el-radio-button value="common">公用采集箱</el-radio-button
              ><el-radio-button value="tiktok">TikTok 采集箱</el-radio-button></el-radio-group
            ><el-input
              v-model="ms.sourceId"
              placeholder="货源 ID"
              clearable
              style="width: 200px"
              @keyup.enter="searchMiaoshou"
              @clear="searchMiaoshou"
            /><el-select v-if="ms.box === 'common'" v-model="ms.commonTab" style="width: 140px" @change="searchMiaoshou"
              ><el-option v-for="(label, key) in commonStatus" :key="key" :value="key" :label="label" /></el-select
            ><el-select
              v-else
              v-model="ms.tiktokStatus"
              clearable
              placeholder="全部发布状态"
              style="width: 150px"
              @change="searchMiaoshou"
              ><el-option v-for="(label, key) in tiktokStatus" :key="key" :value="key" :label="label" /></el-select
            ><el-button :loading="ms.loading" @click="loadMiaoshou">刷新</el-button>
            <span class="muted">实时读取妙手 ERP 数据，只读。</span>
          </div>
          <el-alert v-if="ms.error" class="section" type="warning" :closable="false" :title="ms.error" />
          <el-table v-if="ms.box === 'common'" class="section" :data="ms.common" v-loading="ms.loading">
            <el-table-column label="商品" min-width="320"
              ><template #default="{ row }"
                ><div class="product">
                  <el-image v-if="row.thumbnail" :src="row.thumbnail" class="thumb" fit="contain" referrerpolicy="no-referrer" />
                  <div>
                    <strong>{{ row.title || '无标题' }}</strong>
                    <p class="muted">公共采集箱 ID {{ row.commonCollectBoxDetailId }}</p>
                    <el-link
                      v-for="s in row.sources"
                      :key="s.sourceItemId"
                      :href="s.sourceItemUrl"
                      target="_blank"
                      rel="noopener noreferrer"
                      >货源 {{ s.sourceItemId }}</el-link
                    >
                  </div>
                </div></template
              ></el-table-column
            >
            <el-table-column label="货源价 / SKU 价" width="180"
              ><template #default="{ row }"
                >{{ row.price ?? '未知' }}
                <p class="muted">{{ row.minSkuPrice ?? '?' }} – {{ row.maxSkuPrice ?? '?' }}</p></template
              ></el-table-column
            >
            <el-table-column label="库存 / 重量" width="130"
              ><template #default="{ row }">{{ row.stock ?? '未知' }} / {{ row.weight ?? '未知' }} kg</template></el-table-column
            >
            <el-table-column label="状态" min-width="160"
              ><template #default="{ row }"
                ><el-tag>{{ row.status || '未知' }}</el-tag>
                <p v-if="row.reason" class="error">{{ row.reason }}</p></template
              ></el-table-column
            >
            <el-table-column label="操作" width="90"
              ><template #default="{ row }"
                ><el-button link type="primary" @click="showCommonDetail(row.id)">详情</el-button></template
              ></el-table-column
            >
          </el-table>
          <el-table v-else class="section" :data="ms.tiktok" v-loading="ms.loading">
            <el-table-column label="商品" min-width="320"
              ><template #default="{ row }"
                ><div class="product">
                  <el-image v-if="row.thumbnail" :src="row.thumbnail" class="thumb" fit="contain" referrerpolicy="no-referrer" />
                  <div>
                    <strong>{{ row.title || '无标题' }}</strong>
                    <p class="muted">TK 采集箱 ID {{ row.id }} · 公共采集箱 ID {{ row.common_detail_id ?? '—' }}</p>
                    <p v-if="row.item_num" class="muted">货号 {{ row.item_num }}</p>
                  </div>
                </div></template
              ></el-table-column
            >
            <el-table-column label="价格 / 库存" width="160"
              ><template #default="{ row }">{{ row.price ?? '未知' }} / {{ row.stock ?? '未知' }}</template></el-table-column
            >
            <el-table-column label="分组 / 店铺" min-width="180"
              ><template #default="{ row }"
                >{{ row.group || '未分组' }}
                <p class="muted">{{ row.shop_ids.length ? `店铺 ${row.shop_ids.join('、')}` : '未关联店铺' }}</p></template
              ></el-table-column
            >
            <el-table-column prop="created_at" label="创建时间" width="170" />
            <el-table-column label="操作" width="90"
              ><template #default="{ row }"
                ><el-button link type="primary" @click="showTiktokDetail(row)">详情</el-button></template
              ></el-table-column
            >
          </el-table>
          <el-pagination
            v-if="ms.box === 'common'"
            class="section"
            v-model:current-page="ms.page"
            :total="ms.total"
            :page-size="20"
            layout="total, prev, pager, next"
            @current-change="loadMiaoshou"
          />
          <div v-else class="toolbar section">
            <el-button :disabled="ms.page === 1" @click="changeTiktokPage(-1)">上一页</el-button
            ><span class="muted">第 {{ ms.page }} 页</span
            ><el-button :disabled="!ms.hasMore" @click="changeTiktokPage(1)">下一页</el-button>
          </div>
        </el-card>
      </el-tab-pane>
      <el-tab-pane label="商品上架" name="listing">
        <ListingPanel :market="market" :market-label="marketNames[market]" :active="tab === 'listing'" />
      </el-tab-pane>
      <el-tab-pane label="任务记录" name="tasks">
        <el-card shadow="never">
          <div class="toolbar">
            <el-button @click="loadJobs">刷新任务</el-button
            ><span class="muted">采集任务只提交一次；结果不确定时仅查询平台状态，不重复采集或认领。</span>
          </div>
          <el-table class="section" :data="jobs.items">
            <el-table-column label="任务" min-width="260"
              ><template #default="{ row }"
                >{{ jobKind(row) }}
                <p class="muted">{{ row.id }}</p></template
              ></el-table-column
            >
            <el-table-column label="地区" width="80" prop="target_market" />
            <el-table-column label="状态 / 进度" width="200"
              ><template #default="{ row }"
                >{{ sourceStatus[row.status] || row.status }} · {{ row.completed }}/{{ row.total }}</template
              ></el-table-column
            >
            <el-table-column prop="error_message" label="异常" min-width="220" />
            <el-table-column label="创建时间" width="170"
              ><template #default="{ row }">{{ formatTime(row.created_at) }}</template></el-table-column
            >
            <el-table-column label="操作" width="110"
              ><template #default="{ row }"
                ><el-button link @click="showJob(row.id)">详情 / 查询</el-button></template
              ></el-table-column
            >
          </el-table>
          <el-pagination
            class="section"
            v-model:current-page="jobs.page"
            :total="jobs.total"
            :page-size="10"
            layout="total, prev, pager, next"
            @current-change="loadJobs"
          />
        </el-card>
      </el-tab-pane>
    </el-tabs>
    <el-dialog v-model="jobDialog" title="妙手同步任务" width="900px"
      ><template v-if="job"
        ><p>{{ jobKind(job) }} · {{ sourceStatus[job.status] || job.status }} · {{ job.error_message }}</p>
        <el-table :data="job.items"
          ><el-table-column prop="source_item_id" label="货源 ID" /><el-table-column
            prop="common_detail_id"
            label="公共采集箱 ID" /><el-table-column
            prop="platform_detail_id"
            label="TK 采集箱 ID" /><el-table-column label="状态"
            ><template #default="{ row }">{{ row.state }}</template></el-table-column
          ><el-table-column prop="error" label="异常"
        /></el-table>
        <p class="muted">只有妙手详情（及 TikTok 采集箱列表）确认后才标记完成；结果不确定时查询平台状态。</p>
        <el-button :loading="busy" @click="showJob(job.id)">刷新</el-button
        ><el-button
          v-if="['failed', 'uncertain'].includes(job.status)"
          :loading="busy"
          @click="reconcile"
          >查询平台状态</el-button
        ></template
      ></el-dialog
    >
    <el-dialog v-model="tkDetail.visible" title="TikTok 采集箱详情" width="1080px" top="5vh"
      ><div v-if="tkDetail.row && tkDetail.row.shop_ids.length > 1" class="toolbar"
        ><span class="muted">店铺</span
        ><el-select v-model="tkDetail.shopId" style="width: 200px" @change="loadTiktokDetail"
          ><el-option v-for="s in tkDetail.row.shop_ids" :key="s" :label="`店铺 ${s}`" :value="String(s)" /></el-select
      ></div>
      <div v-loading="tkDetail.loading" class="section">
        <TiktokBoxDetails :data="tkDetail.data" :detail-id="tkDetail.row?.id" :shop-id="tkDetail.shopId" /></div
    ></el-dialog>
    <el-dialog v-model="detailDialog" title="公共采集箱详情" width="1080px" top="5vh"
      ><MiaoshouSourceDetails :data="commonDetail ?? null" :common-id="commonDetailId"
    /></el-dialog>
  </div>
</template>
<script setup lang="ts">
import { onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { markets, type Market } from '@/api/sourcing'
import ProductWorkbench from '@/components/ProductWorkbench.vue'
import MiaoshouSourceDetails from '@/components/MiaoshouSourceDetails.vue'
import TiktokBoxDetails from '@/components/TiktokBoxDetails.vue'
import ListingPanel from '@/components/ListingPanel.vue'
import { workbench } from '@/api/workbench'
import {
  miaoshou,
  miaoshouBoxes,
  sourceStatus,
  tiktokStatus,
  commonStatus,
  type CommonProduct,
  type SourceDetail,
  type SourceJob,
  type TiktokBoxProduct,
  type TiktokBoxDetail,
} from '@/api/miaoshou'
import {
  collectBox,
  boxLabels,
  syncLabels,
  type BoxSyncStatus,
  type CollectBoxItem,
  type MiaoshouBox,
} from '@/api/collectBox'

const route = useRoute(),
  router = useRouter()
const workbenchPanel = ref<InstanceType<typeof ProductWorkbench>>()
const marketNames: Record<Market, string> = {
  MY: '马来西亚 MY',
  TH: '泰国 TH',
  VN: '越南 VN',
  SG: '新加坡 SG',
  PH: '菲律宾 PH',
  ID: '印度尼西亚 ID',
}
const syncTagType: Record<BoxSyncStatus, 'info' | 'warning' | 'success' | 'danger'> = {
  not_synced: 'info',
  syncing: 'warning',
  synced: 'success',
  failed: 'danger',
}
const market = ref<Market>('MY'),
  tab = ref(String(route.query.tab || 'mybox')),
  busy = ref(false)
const box = reactive({
  items: [] as CollectBoxItem[],
  total: 0,
  page: 1,
  keyword: '',
  status: '',
  loading: false,
  counts: {} as Partial<Record<BoxSyncStatus, number>>,
})
const boxSelection = ref<CollectBoxItem[]>([])
const ms = reactive({
  box: 'common' as MiaoshouBox,
  sourceId: '',
  commonTab: 'all',
  tiktokStatus: '',
  page: 1,
  total: 0,
  hasMore: false,
  loading: false,
  error: '',
  common: [] as CommonProduct[],
  tiktok: [] as TiktokBoxProduct[],
})
const jobs = reactive({ items: [] as SourceJob[], total: 0, page: 1 })
const job = ref<SourceJob>(),
  jobDialog = ref(false),
  commonDetail = ref<SourceDetail>(),
  commonDetailId = ref(''),
  detailDialog = ref(false)

const formatTime = (v?: string | null) => (v ? new Date(v).toLocaleString() : '—')
const jobKind = (j: SourceJob) =>
  j.kind === 'collect'
    ? j.items[0]?.claim_platform === 'tiktok'
      ? '采集 → 认领到 TikTok 采集箱'
      : '采集到公用采集箱'
    : '同步公共采集箱详情'

// 用户取消确认框时返回 false，不抛出未处理的拒绝
const confirmed = (p: Promise<unknown>) => p.then(() => true, () => false)
async function action(fn: () => Promise<void>) {
  if (busy.value) return
  busy.value = true
  try {
    await fn()
  } catch {
    // 请求层已提示接口错误
  } finally {
    busy.value = false
  }
}
async function loadBox() {
  box.loading = true
  try {
    const r = await collectBox.items({
      target_market: market.value,
      page: box.page,
      keyword: box.keyword || undefined,
      sync_status: box.status || undefined,
    })
    box.items = r.items
    box.total = r.total
    box.counts = r.counts
  } finally {
    box.loading = false
  }
}
async function searchBox() {
  box.page = 1
  await loadBox()
}
async function enterWorkbench(rows: CollectBoxItem[]) {
  if (!rows.length) return
  if (rows.length > 50) {
    ElMessage.warning('一次最多创建 50 件商品草稿')
    return
  }
  await action(async () => {
    const r = await workbench.create(rows.map((x) => x.id))
    await router.replace({ query: { ...route.query, tab: 'workbench', draft: r.items[0].id } })
    tab.value = 'workbench'
    ElMessage.success('商品草稿已准备，可开始编辑')
  })
}
async function beforeTabLeave() {
  return tab.value === 'workbench' ? await workbenchPanel.value?.confirmLeave() ?? true : true
}
async function removeItems(rows: CollectBoxItem[]) {
  const ok = await confirmed(ElMessageBox.confirm(
    `将 ${rows.length} 件商品移出我的采集箱？只影响本系统，已同步到妙手的商品不会被删除。`,
    '移出采集箱',
    { type: 'warning' },
  ))
  if (!ok) return
  await action(async () => {
    const r = await collectBox.remove(rows.map((x) => x.id))
    ElMessage.success(`已移出 ${r.removed} 件`)
    await loadBox()
  })
}
async function editNote(row: CollectBoxItem) {
  let value = ''
  try {
    ;({ value } = await ElMessageBox.prompt('备注', '编辑备注', {
      inputValue: row.note,
      inputType: 'textarea',
      inputValidator: (v) => (v || '').length <= 2000 || '最多 2000 字',
    }))
  } catch {
    return
  }
  await action(async () => {
    await collectBox.note(row.id, value || '')
    await loadBox()
  })
}
async function loadMiaoshou() {
  ms.loading = true
  ms.error = ''
  try {
    if (ms.box === 'common') {
      const r = await miaoshou.products(ms.page, ms.sourceId, ms.commonTab)
      ms.common = r.items
      ms.total = r.total
    } else {
      const r = await miaoshouBoxes.tiktok(ms.page, ms.sourceId, ms.tiktokStatus)
      ms.tiktok = r.items
      ms.hasMore = r.has_more
    }
  } catch (e) {
    const x = e as { response?: { data?: { detail?: string } } }
    ms.error = x.response?.data?.detail || '妙手采集箱读取失败'
  } finally {
    ms.loading = false
  }
}
async function searchMiaoshou() {
  ms.page = 1
  await loadMiaoshou()
}
async function changeTiktokPage(delta: number) {
  ms.page += delta
  await loadMiaoshou()
}
async function showCommonDetail(id: string) {
  try {
    const r = await miaoshou.detail(id)
    commonDetailId.value = id
    commonDetail.value = r.data.editCommonCollectBoxDetail
    detailDialog.value = true
  } catch (e) {
    const x = e as { response?: { data?: { detail?: string } } }
    ElMessage.error(x.response?.data?.detail || '公共采集箱详情读取失败')
  }
}
const tkDetail = reactive({
  visible: false,
  loading: false,
  row: null as TiktokBoxProduct | null,
  shopId: '',
  data: null as TiktokBoxDetail | null,
})
async function showTiktokDetail(row: TiktokBoxProduct) {
  // Shop-mode detail needs a shop; unlinked products only have the public box detail.
  if (!row.shop_ids.length) {
    if (row.common_detail_id == null) return ElMessage.warning('该商品未关联店铺，也没有公共采集箱 ID，无法读取详情')
    ElMessage.info('该商品未关联店铺，显示公共采集箱详情')
    return showCommonDetail(String(row.common_detail_id))
  }
  Object.assign(tkDetail, { visible: true, row, shopId: String(row.shop_ids[0]), data: null })
  await loadTiktokDetail()
}
async function loadTiktokDetail() {
  if (!tkDetail.row) return
  tkDetail.loading = true
  tkDetail.data = null
  try {
    tkDetail.data = (await miaoshouBoxes.detail(tkDetail.row.id, tkDetail.shopId)).data
  } catch (e) {
    const x = e as { response?: { data?: { detail?: string } } }
    ElMessage.error(x.response?.data?.detail || 'TikTok 采集箱详情读取失败')
  } finally {
    tkDetail.loading = false
  }
}
async function loadJobs() {
  const r = await miaoshou.jobs(jobs.page)
  jobs.items = r.items
  jobs.total = r.total
}
async function showJob(id: string) {
  job.value = await miaoshou.job(id)
  jobDialog.value = true
}
async function reconcile() {
  await action(async () => {
    if (job.value) job.value = await miaoshou.reconcile(job.value.id)
  })
}
async function changeMarket() {
  box.page = 1
  boxSelection.value = []
  await loadBox()
}
async function changeTab() {
  await router.replace({ query: { ...route.query, tab: tab.value } })
  if (tab.value === 'mybox') await loadBox()
  if (tab.value === 'miaoshou') await loadMiaoshou()
  if (tab.value === 'tasks') await loadJobs()
}
watch(
  () => route.query.tab,
  (v) => {
    tab.value = String(v || 'mybox')
  },
)
let timer: ReturnType<typeof setInterval> | undefined
onMounted(async () => {
  await changeTab()
  if (tab.value !== 'mybox') await loadBox()
  // 有同步中的商品或任务时定时刷新
  timer = setInterval(() => {
    if (busy.value) return
    if (tab.value === 'mybox' && box.items.some((x) => x.sync_status === 'syncing')) void loadBox().catch(() => {})
    if (tab.value === 'tasks') void loadJobs().catch(() => {})
  }, 8000)
})
onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>
<style scoped>
.collect-center {
  padding: 24px;
}
header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
h2 {
  margin: 0;
}
header p,
.muted {
  color: #73767a;
  font-size: 13px;
}
.error {
  color: #f56c6c;
  font-size: 13px;
}
.section {
  margin-top: 16px;
}
.main-tabs :deep(.el-tabs__item) {
  font-size: 15px;
}
.toolbar {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  align-items: center;
}
.spacer {
  flex: 1;
}
.product {
  display: flex;
  gap: 12px;
  align-items: center;
}
.product .el-link {
  margin-right: 8px;
}
.thumb {
  width: 72px;
  height: 72px;
  flex-shrink: 0;
}
p {
  margin: 4px 0;
  line-height: 1.5;
  overflow-wrap: anywhere;
}
.images {
  display: flex;
  gap: 12px;
  overflow: auto;
}
.images .el-image {
  width: 120px;
  height: 120px;
  flex-shrink: 0;
}
</style>
