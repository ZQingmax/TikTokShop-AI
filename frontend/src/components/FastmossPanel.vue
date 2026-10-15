<template>
  <section class="fastmoss">
    <div class="controls">
      <el-tag>主营方向：家居日用品</el-tag>
      <el-button :loading="busy" @click="check">检查连接</el-button>
      <el-button :loading="busy" :disabled="active" @click="refresh">连接并刷新分类</el-button>
      <span class="hint">{{ connection || '首次使用请连接已登录 FastMoss 的浏览器，再刷新真实分类。' }}</span>
    </div>
    <div class="controls">
      <el-select v-model="primary" clearable placeholder="一级品类（筛选下方选项）" style="width: 240px">
        <el-option v-for="c in roots" :key="c.id" :value="c.id" :label="c.name" />
      </el-select>
      <el-select v-model="ids" multiple filterable collapse-tags collapse-tags-tooltip placeholder="选择一级或子品类，可多选" style="min-width: 320px; flex: 1" @change="saveSelection">
        <el-option v-for="c in choices" :key="c.id" :value="c.id" :label="optionLabel(c)" />
      </el-select>
      <el-button :disabled="!categories.length" @click="household">家居日用品快捷范围</el-button>
      <div class="page-count"><el-input-number v-model="pages" :min="1" :max="10" @change="persist" /><span>页 / 品类</span></div>
      <el-button type="primary" :loading="submitting" :disabled="busy || active || !ids.length || ids.length > 20 || invalid.length > 0" @click="start">开始抓取</el-button>
    </div>
    <p v-if="categories.length && !hasChildren" class="hint">该榜单来源页面只提供一级品类筛选（无子品类）；如需更细的范围，请在抓取结果中按商品名称筛选。</p>
    <el-alert v-if="invalid.length" type="warning" :closable="false" :title="`已保存分类已失效：${invalid.join('、')}。请重新选择。`" />
    <el-alert v-if="ids.length > 20" type="warning" :closable="false" title="每次最多选择 20 个品类，请缩小本次范围。" />
    <p class="hint">当前国家：{{ market }} · 来源：FastMoss 新品榜。先按国家和品类筛选，再抓取；最多保存 500 条。快捷范围仅匹配真实分类，不含家具。</p>
    <div v-if="job" class="job">
      <div class="controls">
        <el-tag :type="job.status === 'failed' ? 'danger' : job.status === 'partial' ? 'warning' : 'info'">{{ labels[job.status] }}</el-tag>
        <span>{{ job.progress }}</span>
        <el-button v-if="job.report_id" @click="emit('report', job.report_id)">查看本次商品</el-button>
        <el-button v-if="job.report_id" @click="download(job.id)">下载原始 CSV</el-button>
        <el-button v-if="job.status === 'failed' || job.status === 'partial'" :disabled="submitting || busy" @click="retry">重新抓取</el-button>
        <el-button v-if="pollError" @click="resume">重新连接任务</el-button>
      </div>
      <p v-if="job.status === 'queued'" class="hint">等待本机 Worker；若持续排队，请运行 start-fastmoss-local.ps1。</p>
      <el-alert v-if="job.error || pollError" :title="job.error || pollError" type="warning" :closable="false" />
      <div v-for="r in job.category_results" :key="r.category.id" class="hint">{{ r.category.path.join(' / ') }}：{{ r.status === 'succeeded' ? `${r.rows} 条` : r.error }}</div>
    </div>
    <el-collapse @change="loadHistory">
      <el-collapse-item title="FastMoss 抓取任务记录" name="history">
        <el-table :data="history">
          <el-table-column label="时间" width="175"><template #default="{ row }">{{ new Date(row.created_at).toLocaleString() }}</template></el-table-column>
          <el-table-column label="分类" min-width="200"><template #default="{ row }">{{ row.categories.map((c: FastmossCategory) => c.path.join(' / ')).join('、') }}</template></el-table-column>
          <el-table-column label="状态" width="100"><template #default="{ row }">{{ labels[row.status as FastmossTask['status']] }}</template></el-table-column>
          <el-table-column prop="row_count" label="商品数" width="80" />
          <el-table-column label="操作" width="200"><template #default="{ row }"><el-button link @click="inspect(row)">详情</el-button><el-button v-if="row.report_id" link @click="emit('report', row.report_id)">商品</el-button><el-button v-if="row.report_id" link @click="download(row.id)">CSV</el-button></template></el-table-column>
        </el-table>
        <el-pagination v-model:current-page="historyPage" :page-size="20" :total="historyTotal" layout="prev, pager, next" @current-change="loadHistory" />
      </el-collapse-item>
    </el-collapse>
  </section>
</template>

<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { fastmoss, type FastmossCategory, type FastmossTask } from '@/api/fastmoss'
import type { Market } from '@/api/sourcing'
const props = defineProps<{ market: Market }>()
const emit = defineEmits<{ report: [id: string]; category: [name: string] }>()
const categories = ref<FastmossCategory[]>([]), ids = ref<string[]>([]), primary = ref(''), pages = ref(3)
const busy = ref(false), submitting = ref(false), connection = ref(''), job = ref<FastmossTask>(), pollError = ref('')
const history = ref<FastmossTask[]>([]), historyPage = ref(1), historyTotal = ref(0)
const labels = { queued: '等待中', running: '抓取中', succeeded: '已完成', partial: '部分完成', failed: '失败' }
let timer: ReturnType<typeof setTimeout> | undefined, generation = 0, disposed = false
let pendingRequest: { signature: string; key: string } | undefined
const active = computed(() => !!job.value && ['queued', 'running'].includes(job.value.status))
const roots = computed(() => categories.value.filter(c => !c.parent_id))
const choices = computed(() => categories.value.filter(c => !primary.value || c.path[0] === categories.value.find(r => r.id === primary.value)?.name || ids.value.includes(c.id)))
const invalid = computed(() => ids.value.filter(id => !categories.value.some(c => c.id === id)))
const hasChildren = computed(() => categories.value.some(c => c.parent_id))
const optionLabel = (c: FastmossCategory) => c.path.join(' / ') + (c.name_en ? `（${c.name_en}）` : '')
function key() {
  let user = 'local'
  try { user = JSON.parse(localStorage.getItem('userInfo') || '{}').id || user } catch { /* no profile */ }
  return `fastmoss:${user}:${props.market}`
}
function persist() { localStorage.setItem(key(), JSON.stringify({ ids: ids.value, pages: pages.value })) }
function saveSelection() {
  persist()
  const names = categories.value.filter(c => ids.value.includes(c.id)).map(c => c.name)
  // 找货源接口的品类上限为 100 字：按完整名称截断，不截半个名称
  let text = ''
  for (const name of names) { const next = text ? `${text}、${name}` : name; if (next.length > 100) break; text = next }
  if (text) emit('category', text)
}
function household() {
  const matches = categories.value.filter(c => c.household)
  // Pick the observed leaves, so a broad household parent cannot include furniture children.
  ids.value = matches.filter(c => !categories.value.some(child => child.parent_id === c.id)).map(c => c.id)
  if (!ids.value.length) ElMessage.warning('当前真实分类未匹配到家居日用品，请手动选择')
  saveSelection()
}
async function check() {
  busy.value = true
  try { connection.value = (await fastmoss.status()).message } finally { busy.value = false }
}
async function refresh() {
  const market = props.market
  busy.value = true
  try {
    const result = await fastmoss.refresh(market)
    if (market !== props.market) return
    categories.value = result.items
    connection.value = `已读取 ${result.items.length} 个真实分类`
    if (!ids.value.length) household()
  } finally { busy.value = false }
}
async function start() {
  if (submitting.value || active.value || !ids.value.length || invalid.value.length) return
  const market = props.market
  submitting.value = true
  const signature = JSON.stringify([market, [...ids.value].sort(), pages.value])
  if (pendingRequest?.signature !== signature) pendingRequest = { signature, key: crypto.randomUUID() }
  try {
    const created = await fastmoss.create({ request_key: pendingRequest.key, target_market: market, category_ids: ids.value, pages: pages.value })
    pendingRequest = undefined
    if (market !== props.market) return
    job.value = created
    resume()
  } finally { submitting.value = false }
}
function retry() {
  if (!job.value) return
  ids.value = job.value.categories.map(c => c.id)
  pages.value = job.value.pages
  saveSelection()
  if (invalid.value.length) { ElMessage.warning('请刷新分类并重新选择失效项'); return }
  void start()
}
function resume() { pollError.value = ''; clearTimeout(timer); void poll(generation) }
async function poll(version: number) {
  if (!job.value || disposed || version !== generation) return
  const id = job.value.id
  try {
    const result = await fastmoss.task(id)
    if (disposed || version !== generation || job.value?.id !== id) return
    job.value = result
    if (['queued', 'running'].includes(result.status)) timer = setTimeout(() => void poll(version), 2000)
    else if (result.report_id) emit('report', result.report_id)
  } catch { if (version === generation) pollError.value = '任务连接中断，后台任务继续运行，可点击重新连接。' }
}
async function loadHistory() {
  const market = props.market
  const result = await fastmoss.tasks(market, historyPage.value)
  if (market !== props.market) return
  history.value = result.items; historyTotal.value = result.total
}
function inspect(task: FastmossTask) {
  clearTimeout(timer); generation++; job.value = task; pollError.value = ''
  if (active.value) resume()
}
async function download(id: string) {
  const blob = await fastmoss.csv(id)
  const url = URL.createObjectURL(blob), a = document.createElement('a')
  a.href = url; a.download = `fastmoss-${id}.csv`; a.click(); URL.revokeObjectURL(url)
}
watch(() => props.market, async () => {
  const version = ++generation
  clearTimeout(timer); job.value = undefined; categories.value = []; primary.value = ''; pollError.value = ''; historyPage.value = 1
  try {
    const saved = JSON.parse(localStorage.getItem(key()) || '{}')
    ids.value = Array.isArray(saved.ids) ? saved.ids.filter((x: unknown) => typeof x === 'string') : []
    pages.value = Math.min(10, Math.max(1, Number(saved.pages) || 3))
  } catch { ids.value = []; pages.value = 3 }
  try {
    const [catalog, tasks] = await Promise.all([fastmoss.categories(props.market), fastmoss.tasks(props.market)])
    if (version !== generation || disposed) return
    categories.value = catalog.items; history.value = tasks.items; historyTotal.value = tasks.total
    if (categories.value.length && !ids.value.length) household()
    else if (!invalid.value.length) saveSelection()
    job.value = tasks.items.find(t => ['queued', 'running'].includes(t.status)) || tasks.items[0]
    if (active.value) resume()
    else if (job.value?.report_id) emit('report', job.value.report_id)
  } catch { connection.value = 'FastMoss 服务暂不可用，请检查数据库迁移与后端服务' }
}, { immediate: true })
onUnmounted(() => { disposed = true; generation++; clearTimeout(timer) })
</script>

<style scoped>
.controls { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-bottom: 12px; }
.page-count { display: flex; gap: 8px; align-items: center; white-space: nowrap; }
.hint { color: #788492; font-size: 12px; margin: 8px 0; }
.job { background: var(--app-main-bg); border: 1px solid var(--app-card-border); border-radius: 6px; padding: 12px; margin: 12px 0; }
</style>
