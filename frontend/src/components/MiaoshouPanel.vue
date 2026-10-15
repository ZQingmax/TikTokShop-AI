<template>
  <el-card class="panel">
    <template #header><div class="toolbar"><strong>妙手 ERP · 真实货源</strong><el-tag :type="connection.connected ? 'success' : connection.configured ? 'warning' : 'info'">{{ connection.connected ? '真实鉴权成功' : connection.configured ? '凭证已配置 / 未验证连接' : '未配置凭证' }}</el-tag><el-select v-model="market" style="width:110px" aria-label="妙手目标站点"><el-option v-for="m in markets" :key="m" :label="m" :value="m" /></el-select><el-button :loading="checking" @click="check">验证连接</el-button><el-button :disabled="!connection.configured" type="primary" @click="collectDialog = true">链接采集</el-button><el-button :disabled="!connection.configured" @click="openBox">公共采集箱同步</el-button></div></template>
    <p class="muted">{{ connection.connected ? `已验证 TK ${connection.site || market} 站点；本页返回店铺 ${connection.shop_count ?? 0} 个。` : connection.reason || '仅检查配置不代表鉴权成功。' }} 只开放店铺读取、链接采集、公共采集箱列表和详情。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-collapse><el-collapse-item title="采集 / 同步任务进度（刷新后恢复）"><el-table :data="jobs"><el-table-column label="任务" min-width="280"><template #default="{ row }"><el-button link type="primary" @click="showJob(row)">{{ row.id }}</el-button><p>{{ row.kind === 'collect' ? '链接采集' : '公共采集箱同步' }} · {{ row.target_market }}</p></template></el-table-column><el-table-column label="状态 / 进度" min-width="190"><template #default="{ row }">{{ sourceStatus[row.status] }}<el-progress :percentage="row.total ? Math.round(row.completed / row.total * 100) : 0" /><span>{{ row.completed }} / {{ row.total }} · {{ row.stage }}</span></template></el-table-column><el-table-column prop="error_message" label="错误原因" min-width="240" /><el-table-column label="操作" width="160"><template #default="{ row }"><el-button v-if="['failed','uncertain'].includes(row.status)" link type="primary" @click="reconcile(row)">查询平台状态</el-button></template></el-table-column></el-table><el-pagination v-model:current-page="jobPage" :page-size="10" :total="jobTotal" layout="total, prev, pager, next" @current-change="loadJobs" /><el-button class="section" @click="loadJobs">刷新采集任务</el-button></el-collapse-item></el-collapse>
    <el-dialog v-model="collectDialog" title="通过妙手 API 采集真实货源链接" width="760px">
      <el-alert title="先检查已有货源；缺失链接只提交一次。超时或结果不确定时仅查询平台状态，不自动重复采集。此操作不认领、不发布、不采购。" type="info" :closable="false" />
      <div class="toolbar section"><el-select v-model="market" aria-label="采集目标站点"><el-option v-for="m in markets" :key="m" :label="m" :value="m" /></el-select><el-select v-model="currency" aria-label="确认货源币种"><el-option v-for="c in currencies" :key="c" :label="c" :value="c" /></el-select><span>请确认接口未提供的币种</span></div>
      <el-input v-model="links" type="textarea" :rows="6" placeholder="每行一个 1688 商品链接，最多 50 条" class="section" />
      <el-checkbox v-model="analyzeAfter">同步成功且资料完整后进入现有 AI 评估</el-checkbox>
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
      <template #footer><el-button @click="collectDialog = false">关闭</el-button><el-button type="primary" :loading="submitting" @click="collect">提交采集任务</el-button></template>
    </el-dialog>
    <el-dialog v-model="boxDialog" title="公共采集箱同步与 AI 入口" width="1060px">
      <el-alert title="读取公共采集箱；同步保留原始价格和单位。核心信息改变将使旧评估过期。公共采集箱 ID 不作为 TK 采集箱 ID。" type="info" :closable="false" />
      <div class="toolbar section"><el-input v-model="sourceId" placeholder="授权采集箱按源商品 ID 查询" style="width:260px" /><el-select v-model="tab" style="width:150px"><el-option v-for="(label,value) in boxTabs" :key="value" :label="label" :value="value" /></el-select><el-button @click="searchBox">查询授权采集箱</el-button><el-select v-model="market" style="width:100px" aria-label="同步目标站点"><el-option v-for="m in markets" :key="m" :label="m" :value="m" /></el-select><el-select v-model="currency" style="width:100px" aria-label="同步币种"><el-option v-for="c in currencies" :key="c" :label="c" :value="c" /></el-select></div>
      <div class="toolbar section"><el-checkbox v-model="analyzeAfter">同步后进入 AI 评估</el-checkbox><el-button type="primary" :disabled="!selected.length" :loading="submitting" @click="sync">同步选中商品</el-button></div>
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
      <el-table :data="products" v-loading="loading" @selection-change="onSelection"><el-table-column type="selection" width="45" /><el-table-column prop="id" label="公共采集箱详情 ID" min-width="155" /><el-table-column prop="title" label="商品" min-width="230" /><el-table-column label="源商品 ID" min-width="140"><template #default="{ row }">{{ sourceIds(row) }}</template></el-table-column><el-table-column label="SPU价 / 库存 / 重量" min-width="180"><template #default="{ row }">{{ row.price ?? '价格未知' }}（币种需确认）<p>库存 {{ row.stock ?? '未知' }} · {{ row.weight ?? '未知' }} kg</p></template></el-table-column><el-table-column label="平台状态" min-width="140"><template #default="{ row }">{{ row.status || '未知' }}<p>{{ row.reason }}</p></template></el-table-column><el-table-column label="详情" width="80"><template #default="{ row }"><el-button link type="primary" @click="showDetail(row.id)">查看</el-button></template></el-table-column></el-table>
      <el-pagination v-model:current-page="boxPage" :page-size="20" :total="boxTotal" layout="total, prev, pager, next" @current-change="loadBox" />
    </el-dialog>
    <el-dialog v-model="detailDialog" title="妙手原始货源详情" width="1080px"><MiaoshouSourceDetails :data="detail" :common-id="detailId" /></el-dialog>
    <el-dialog v-model="jobDialog" title="采集同步任务进度" width="900px"><template v-if="currentJob"><p>{{ currentJob.id }} · {{ sourceStatus[currentJob.status] }} · {{ currentJob.stage }}</p><el-progress :percentage="currentJob.total ? Math.round(currentJob.completed / currentJob.total * 100) : 0" /><el-alert v-if="currentJob.error_message" :title="currentJob.error_message" type="error" :closable="false" /><el-table :data="currentJob.items"><el-table-column prop="source_item_id" label="源商品 ID" /><el-table-column prop="common_detail_id" label="公共采集箱详情 ID" /><el-table-column label="状态" width="170"><template #default="{ row }">{{ row.state === 'saved' ? '已保存 PostgreSQL' : row.state }}<p v-if="row.reused_platform">复用已有平台记录</p></template></el-table-column><el-table-column prop="error" label="错误" /><el-table-column label="AI / 详情" width="150"><template #default="{ row }"><el-button v-if="row.common_detail_id" link @click="showDetail(row.common_detail_id)">详情</el-button><el-button v-if="row.candidate_id" link type="primary" :disabled="row.completeness !== 'ready'" @click="analyze(row.candidate_id)">AI 分析</el-button></template></el-table-column></el-table><p>已创建的 AI 任务：{{ currentJob.items.map(x => x.analysis_task_id).filter(Boolean).join('，') || '未提交，可从候选池或上方按钮进入' }}</p></template><template #footer><el-button @click="loadJobs">刷新任务详情</el-button><el-button v-if="currentJob && ['failed','uncertain'].includes(currentJob.status)" @click="reconcile(currentJob)">只查询平台状态</el-button><el-button @click="jobDialog = false">关闭</el-button></template></el-dialog>
  </el-card>
</template>
<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { sourcing, markets, type Market } from '@/api/sourcing'
import { miaoshou, sourceStatus, type CommonProduct, type MiaoshouConnection, type SourceDetail, type SourceJob } from '@/api/miaoshou'
import MiaoshouSourceDetails from './MiaoshouSourceDetails.vue'
const emit = defineEmits<{ changed: [] }>()
const currencies = ['CNY','USD','THB','VND','MYR','SGD','PHP','IDR']
const boxTabs: Record<string,string> = { all: '全部', noClaimed: '未认领', claimed: '已认领', collectFail: '采集失败', collectSuccess: '采集成功' }
const connection = ref<MiaoshouConnection>({ configured: false, connected: null })
const market = ref<Market>('MY'), currency = ref('CNY'), checking = ref(false), error = ref(''), submitting = ref(false)
const collectDialog = ref(false), boxDialog = ref(false), detailDialog = ref(false), jobDialog = ref(false)
const links = ref(''), analyzeAfter = ref(false), sourceId = ref(''), tab = ref('all'), selected = ref<string[]>([])
const products = ref<CommonProduct[]>([]), boxPage = ref(1), boxTotal = ref(0), loading = ref(false)
const jobs = ref<SourceJob[]>([]), jobPage = ref(1), jobTotal = ref(0), currentJob = ref<SourceJob>()
const detail = ref<SourceDetail | null>(null), detailId = ref('')
const requestKeys = new Map<string,string>()
let timer: ReturnType<typeof setInterval> | undefined
let polling = false, disposed = false
function sourceIds(row: CommonProduct) { return row.sources.map(x => x.sourceItemId || '未知').join(' / ') }
function onSelection(rows: CommonProduct[]) { selected.value = rows.map(x => x.id) }
function errorText(e: unknown) { const data = (e as { response?: { data?: { detail?: unknown } } }).response?.data?.detail; return typeof data === 'string' ? data : '请求失败，请查看任务或服务端状态' }
function keyFor(data: unknown) { const signature = JSON.stringify(data); if (!requestKeys.has(signature)) requestKeys.set(signature, crypto.randomUUID()); return requestKeys.get(signature)! }
async function check() { checking.value = true; error.value = ''; try { connection.value = await miaoshou.check(market.value); if (!connection.value.connected) error.value = connection.value.reason || '鉴权失败' } catch (e) { error.value = errorText(e) } finally { checking.value = false } }
async function loadJobs() { try { const old = jobs.value.map(x => `${x.id}:${x.status}:${x.completed}`).join('|'); const r = await miaoshou.jobs(jobPage.value); jobs.value = r.items; jobTotal.value = r.total; if (currentJob.value) currentJob.value = await miaoshou.job(currentJob.value.id); const next = jobs.value.map(x => `${x.id}:${x.status}:${x.completed}`).join('|'); if (old !== next && jobs.value.some(x => x.completed > 0)) emit('changed') } catch (e) { error.value = errorText(e) } }
async function collect() { const input = links.value.split('\n').map(x => x.trim()).filter(Boolean); if (!input.length || input.length > 50) { ElMessage.error('请输入 1–50 个货源链接'); return } const data = { links: input, target_market: market.value, currency: currency.value, analyze_after_sync: analyzeAfter.value }; submitting.value = true; error.value = ''; try { currentJob.value = await miaoshou.collect({ request_key: keyFor(data), ...data }); requestKeys.delete(JSON.stringify(data)); collectDialog.value = false; jobDialog.value = true; await loadJobs() } catch (e) { error.value = errorText(e) } finally { submitting.value = false } }
async function openBox() { boxDialog.value = true; error.value = ''; await loadBox() }
async function loadBox() { loading.value = true; try { const r = await miaoshou.products(boxPage.value, sourceId.value, tab.value); products.value = r.items; boxTotal.value = r.total; selected.value = [] } catch (e) { error.value = errorText(e) } finally { loading.value = false } }
async function searchBox() { boxPage.value = 1; error.value = ''; await loadBox() }
async function sync() { const data = { common_detail_ids: selected.value, target_market: market.value, currency: currency.value, analyze_after_sync: analyzeAfter.value }; submitting.value = true; error.value = ''; try { currentJob.value = await miaoshou.sync({ request_key: keyFor(data), ...data }); requestKeys.delete(JSON.stringify(data)); boxDialog.value = false; jobDialog.value = true; await loadJobs() } catch (e) { error.value = errorText(e) } finally { submitting.value = false } }
async function showDetail(id: string) { try { detailId.value = id; detail.value = (await miaoshou.detail(id)).data.editCommonCollectBoxDetail; detailDialog.value = true } catch (e) { error.value = errorText(e) } }
async function showJob(job: SourceJob) { currentJob.value = await miaoshou.job(job.id); jobDialog.value = true }
async function reconcile(job: SourceJob) { try { currentJob.value = await miaoshou.reconcile(job.id); jobDialog.value = true; await loadJobs() } catch (e) { error.value = errorText(e) } }
async function analyze(id: string) { try { const r = await sourcing.analyze([id]); ElMessage.success(r.tasks[0]?.reused ? '复用已有 AI 任务或评估' : '已提交现有 AI 评估流程'); emit('changed') } catch (e) { error.value = errorText(e) } }
defineExpose({ openBox })
onMounted(async () => { try { connection.value = await miaoshou.status(); await loadJobs() } catch (e) { error.value = errorText(e) } if (!disposed) timer = setInterval(async () => { if (polling || document.hidden) return; polling = true; try { await loadJobs() } finally { polling = false } }, 4000) })
onUnmounted(() => { disposed = true; if (timer) clearInterval(timer) })
</script>
<style scoped>
.panel { margin-top:20px; }.toolbar { display:flex; gap:12px; flex-wrap:wrap; align-items:center; }.section { margin-top:16px; }.muted { color:#73767a; font-size:13px; }p { overflow-wrap:anywhere; line-height:1.6; }
</style>
