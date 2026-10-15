<template>
  <div class="page">
    <div class="heading">
      <div><h2>自动发现</h2><p>选品目标 → AI 规划关键词 → 搜索真实 1688 货源 → 去重 → 确认后妙手采集 → AI 评估排名 → 候选池人工审核</p></div>
      <div><el-button @click="$router.push('/sourcing')">返回 AI 智能选品</el-button><el-button @click="$router.push('/sourcing/review')">选品审核</el-button></div>
    </div>
    <el-alert type="info" :closable="false" :title="status?.data_policy || '搜索结果只用于提取真实 1688 商品链接，商品资料以妙手采集为准。'" />
    <el-alert v-if="status && !searchAvailable" class="section" type="warning" :closable="false"
              :title="'搜索数据源不可用：' + (status.sources.find(s => s.available === false)?.reason || '') + '。任务会明确失败，不会生成示例商品。'" />

    <el-row :gutter="20" class="section">
      <el-col :xs="24" :lg="9">
        <el-card>
          <template #header><strong>选品目标</strong></template>
          <el-form label-width="96px">
            <el-form-item label="目标站点"><el-select v-model="form.target_market"><el-option v-for="m in markets" :key="m" :label="marketNames[m] + ' ' + m" :value="m" /></el-select></el-form-item>
            <el-form-item label="商品品类"><el-select v-model="form.category" filterable allow-create default-first-option placeholder="选择或输入"><el-option v-for="c in categories" :key="c" :label="c" :value="c" /></el-select></el-form-item>
            <el-form-item label="采购价 CNY"><div class="price"><el-input-number v-model="priceMin" :min="0" :precision="2" :controls="false" placeholder="下限" /><span>–</span><el-input-number v-model="priceMax" :min="0" :precision="2" :controls="false" placeholder="上限" /></div></el-form-item>
            <el-form-item label="关键词"><el-select v-model="form.keywords" multiple filterable allow-create default-first-option :multiple-limit="10" placeholder="可选；不填由 DeepSeek 规划" /></el-form-item>
            <el-form-item label="排除词"><el-select v-model="form.exclude_words" multiple filterable allow-create default-first-option :multiple-limit="20" placeholder="如：二手、仿牌" /></el-form-item>
            <el-form-item label="选品偏好"><el-input v-model="form.preferences" type="textarea" :rows="2" maxlength="500" placeholder="如：轻小件、适合短视频演示、免安装" /></el-form-item>
            <el-form-item label="最多发现"><el-input-number v-model="form.max_candidates" :min="1" :max="status?.limits.max_results || 30" /><span class="muted"> 件（上限 {{ status?.limits.max_results ?? 30 }}）</span></el-form-item>
            <el-form-item label="自动采集"><el-switch v-model="autoCollect" :disabled="!status?.limits.auto_collect_enabled" /><span class="muted"> {{ status?.limits.auto_collect_enabled ? '开启后跳过确认，按搜索排序采集前 ' + status.limits.max_collect + ' 件' : '验收通过前未开放；先预览再确认采集' }}</span></el-form-item>
            <el-button type="primary" :loading="creating" :disabled="!form.category" @click="start">开始自动选品</el-button>
          </el-form>
          <el-divider />
          <p class="muted">搜索：{{ status?.sources.map(s => s.name + (s.available ? '（可用）' : '（不可用）')).join('；') }}</p>
          <p class="muted">关键词规划：DeepSeek {{ status?.planner.configured ? status.planner.model : '未配置' }} · 视觉：百炼 {{ status?.vision.configured ? status.vision.model : '未配置' }} · 采集：妙手 {{ status?.collector.configured ? '已配置' : '未配置' }}</p>
          <p class="muted">单任务预算：搜索 {{ status?.limits.max_search_calls }} 次 · 模型 {{ status?.limits.max_model_calls }} 次 · 采集 {{ status?.limits.max_collect }} 件</p>
        </el-card>
      </el-col>

      <el-col :xs="24" :lg="15">
        <el-card v-loading="loadingTask">
          <template #header><div class="heading"><strong>当前任务</strong><span v-if="task" class="muted">{{ task.id }}</span></div></template>
          <el-empty v-if="!task" description="还没有任务。设置目标后点击“开始自动选品”，或从下方历史中选择。" />
          <template v-else>
            <el-steps :active="activeStep" :process-status="task.status === 'failed' ? 'error' : 'process'" finish-status="success" align-center>
              <el-step v-for="s in steps" :key="s.key" :title="s.title" />
            </el-steps>
            <div class="state">
              <el-tag :type="statusType(task.status)" size="large">{{ task.status_label }}</el-tag>
              <el-tag v-if="task.running" type="primary" effect="plain">Worker 执行中</el-tag>
              <span>{{ task.progress_message }}</span>
            </div>
            <p class="muted">目标：{{ marketNames[task.goal.target_market] }} · {{ task.goal.category }} · 采购价 {{ task.goal.price_min ?? '不限' }}–{{ task.goal.price_max ?? '不限' }} CNY
              · 用量：搜索 {{ task.usage.search_calls }}/{{ task.budget.search_calls }}，模型 {{ task.usage.model_calls }}/{{ task.budget.model_calls }}，采集 {{ task.usage.collect }}/{{ task.budget.collect }}</p>
            <el-alert v-for="(e, i) in task.stage_errors" :key="i" class="err" :type="e.code === 'worker_interrupted' ? 'info' : 'warning'" :closable="false" :title="`[${e.stage}] ${e.code}：${e.message}`" />
            <div class="actions">
              <el-button v-if="['queued', 'awaiting_confirmation'].includes(task.status) && !task.running" @click="cancelTask">取消任务</el-button>
              <el-button v-if="task.status === 'awaiting_confirmation'" type="primary" :disabled="!picked.length" :loading="confirming" @click="confirm">确认批量采集（{{ picked.length }}/{{ task.budget.collect }}）</el-button>
              <el-button @click="refresh">刷新</el-button>
            </div>

            <el-tabs v-model="tab" class="section">
              <el-tab-pane label="搜索计划" name="plan">
                <el-table :data="task.plan?.keywords || []" empty-text="尚未生成">
                  <el-table-column prop="keyword" label="关键词" width="160" />
                  <el-table-column label="来源" width="100"><template #default="{ row }"><el-tag size="small">{{ row.origin === 'user' ? '用户' : 'DeepSeek' }}</el-tag></template></el-table-column>
                  <el-table-column prop="angle" label="角度" width="110" />
                  <el-table-column prop="rationale" label="规划理由" />
                </el-table>
                <p v-if="task.plan?.rejected?.length" class="muted">已拒绝：{{ task.plan.rejected.map(r => `${r.keyword}（${r.rejected_reason}）`).join('；') }}</p>
                <p v-if="task.plan?.evidence" class="muted">模型 {{ task.plan.evidence.model }} · 请求 ID {{ task.plan.evidence.request_id }} · {{ task.plan.evidence.prompt_version }}</p>
                <h4>搜索记录（结果来源）</h4>
                <el-table :data="task.search_log" empty-text="尚未搜索">
                  <el-table-column label="查询" min-width="220"><template #default="{ row }"><code>{{ row.query }}</code><p class="muted">{{ row.provider }} · 第 {{ row.page + 1 }} 页 · {{ fmt(row.at) }}</p></template></el-table-column>
                  <el-table-column label="结果" width="230"><template #default="{ row }">
                    <template v-if="row.state === 'done'">{{ row.result_count }} 条 · 1688 商品 {{ row.offer_hits }} · 新增 {{ row.new_unique }}<p class="muted">{{ rejectedText(row.rejected) }}</p></template>
                    <el-tag v-else-if="row.state === 'skipped_budget'" type="info">预算不足未执行</el-tag>
                    <span v-else class="error">{{ row.error_code }}：{{ row.error }}</span>
                  </template></el-table-column>
                </el-table>
              </el-tab-pane>

              <el-tab-pane :label="`发现结果（${task.results?.length || 0}）`" name="results">
                <p v-if="task.status === 'awaiting_confirmation'" class="muted">勾选最多 {{ task.budget.collect }} 件进行妙手采集；已在候选池的商品会直接复用，不重复采集。标题来自搜索摘要，仅作预览。</p>
                <el-table :data="task.results || []" row-key="id" @selection-change="onPick" empty-text="暂无真实发现结果">
                  <el-table-column v-if="task.status === 'awaiting_confirmation'" type="selection" width="45" :selectable="(r: DiscoveryResult) => r.status === 'discovered'" />
                  <el-table-column label="排名" width="70"><template #default="{ row }">{{ row.rank_position ?? '—' }}</template></el-table-column>
                  <el-table-column label="商品" min-width="280"><template #default="{ row }">
                    <div class="product">
                      <el-image v-if="row.candidate?.main_image" :src="row.candidate.main_image" fit="cover" class="thumb" referrerpolicy="no-referrer" />
                      <div>
                        <strong>{{ row.candidate?.name || row.snippet_title || '（摘要已过期，待采集详情）' }}</strong>
                        <p><el-link :href="row.canonical_url" target="_blank" rel="noopener noreferrer">1688 · {{ row.source_item_id }}</el-link>
                          <span class="muted"> · 关键词“{{ row.search_keyword }}” 第 {{ row.search_position }} 位</span></p>
                      </div>
                    </div>
                  </template></el-table-column>
                  <el-table-column label="采购价" width="110"><template #default="{ row }">{{ row.candidate ? (row.candidate.purchase_price ?? '未知') + ' ' + row.candidate.currency : '采集后获取' }}</template></el-table-column>
                  <el-table-column label="AI 评分" width="120"><template #default="{ row }">
                    <template v-if="row.assessment"><strong>{{ row.rank_score }}</strong><p><el-tag size="small" :type="recType(row.assessment.ranking.recommendation)">{{ recLabel(row.assessment.ranking.recommendation) }}</el-tag></p></template><span v-else class="muted">—</span>
                  </template></el-table-column>
                  <el-table-column label="状态" min-width="170"><template #default="{ row }"><el-tag size="small" :type="resultType(row.status)">{{ resultLabels[row.status] || row.status }}</el-tag><p class="muted">{{ row.status_reason }}</p></template></el-table-column>
                  <el-table-column label="操作" width="140"><template #default="{ row }">
                    <el-button link type="primary" @click="openDrawer(row)">详情</el-button>
                    <el-button v-if="row.candidate_id" link @click="$router.push('/sourcing/review')">去审核</el-button>
                  </template></el-table-column>
                </el-table>
                <p v-if="task.collect_task" class="muted">妙手采集任务 {{ task.collect_task.id }}：{{ task.collect_task.status }} · {{ task.collect_task.completed }}/{{ task.collect_task.total }}（超时只查询平台状态，不重复提交）</p>
              </el-tab-pane>
            </el-tabs>
          </template>
        </el-card>
      </el-col>
    </el-row>

    <el-card class="section">
      <template #header><div class="heading"><strong>历史发现任务（刷新后从 PostgreSQL 恢复）</strong><el-button @click="loadHistory">刷新</el-button></div></template>
      <el-table :data="history" highlight-current-row @row-click="(row: DiscoveryTask) => select(row.id)">
        <el-table-column label="创建时间" width="170"><template #default="{ row }">{{ fmt(row.created_at) }}</template></el-table-column>
        <el-table-column label="目标" min-width="220"><template #default="{ row }">{{ marketNames[row.goal.target_market] }} · {{ row.goal.category }} · {{ row.goal.price_min ?? '—' }}–{{ row.goal.price_max ?? '—' }} CNY</template></el-table-column>
        <el-table-column label="状态" width="130"><template #default="{ row }"><el-tag :type="statusType(row.status)">{{ row.status_label }}</el-tag></template></el-table-column>
        <el-table-column label="结果" min-width="200"><template #default="{ row }">{{ countsText(row.result_counts) }}</template></el-table-column>
      </el-table>
      <el-pagination class="section" v-model:current-page="historyPage" :page-size="10" :total="historyTotal" layout="total, prev, pager, next" @current-change="loadHistory" />
    </el-card>

    <el-drawer v-model="drawer" size="560px" :title="current?.candidate?.name || current?.snippet_title || '发现结果详情'">
      <template v-if="current">
        <p><el-link :href="current.canonical_url" target="_blank" rel="noopener noreferrer">真实来源：{{ current.canonical_url }}</el-link></p>
        <p class="muted">发现方式：{{ current.provider }} · 查询 <code>{{ current.search_query }}</code> · 第 {{ current.search_position }} 位 · {{ fmt(current.discovered_at) }}</p>
        <template v-if="current.candidate">
          <div class="gallery"><el-image v-for="src in [current.candidate.main_image, ...(current.candidate.images || [])].filter(Boolean).slice(0, 8)" :key="String(src)" :src="String(src)" :preview-src-list="[String(src)]" fit="cover" class="thumb" referrerpolicy="no-referrer" /></div>
          <p><b>采购价：</b>{{ current.candidate.purchase_price ?? '未知' }} {{ current.candidate.currency }}（妙手 SPU 货源价，需人工核实）</p>
          <p><b>品类：</b>{{ current.candidate.category || '未知' }} · <b>候选版本：</b>v{{ current.candidate.version }} · <b>审核：</b>{{ current.candidate.review_status }}</p>
          <p class="muted">妙手公共采集箱 ID {{ current.candidate.miaoshou_detail_id || '—' }} · 数据来源 {{ current.candidate.data_source }}</p>
        </template>
        <el-alert v-else type="info" :closable="false" title="尚未采集：标题来自搜索摘要，价格、图片需妙手采集后获取。" />
        <template v-if="current.assessment">
          <el-divider>AI 评分（{{ current.rank_score }}）</el-divider>
          <p class="muted">{{ current.assessment.ranking.formula }}</p>
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item v-for="(v, k) in current.assessment.ranking.components" :key="k" :label="dimensionLabels[k] || k">{{ v }}（权重 {{ current.assessment.ranking.weights[k] }}）</el-descriptions-item>
          </el-descriptions>
          <h4>推荐理由与解释</h4>
          <p><b>卖点：</b>{{ current.assessment.output.selling_points.join('；') }}</p>
          <p v-for="k in dims" :key="k"><b>{{ dimNames[k] }}（{{ current.assessment.output[k].score }}，{{ levelLabels[current.assessment.output[k].level] }}）：</b>{{ current.assessment.output[k].explanation }}<br><span class="muted">依据：{{ current.assessment.output[k].evidence.join('；') }}</span></p>
          <p><b>总结：</b>{{ current.assessment.output.summary }}</p>
          <h4>风险</h4>
          <p v-for="(f, i) in current.assessment.output.compliance_flags" :key="i"><el-tag type="warning" size="small">合规</el-tag> {{ f }}</p>
          <p v-if="!current.assessment.output.compliance_flags.length" class="muted">模型未列出合规风险，不代表无风险，需人工核实。</p>
          <h4>未接入的数据</h4>
          <el-tag v-for="(v, k) in current.assessment.not_connected" :key="k" type="info" class="tag">{{ notConnectedLabels[k] || k }}：{{ v.status }}</el-tag>
          <p class="muted">局限：{{ current.assessment.output.limitations.join('；') }}</p>
          <p class="muted">证据：{{ current.assessment.evidence.provider }} / {{ current.assessment.evidence.model }} · 请求 {{ current.assessment.evidence.request_id }} · 评估 {{ current.assessment.evidence.evaluation_id }} · 输入版本 v{{ current.assessment.evidence.input_version }} · 视觉 {{ current.assessment.evidence.vision_model }}</p>
        </template>
        <div class="actions">
          <el-button v-if="current.candidate_id" type="primary" @click="$router.push('/sourcing/review')">进入选品审核</el-button>
          <el-button v-if="current.candidate_id" @click="$router.push('/sourcing')">在候选池查看</el-button>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { markets, type Market } from '@/api/sourcing'
import { discovery, resultLabels, dimensionLabels, notConnectedLabels, stageOrder, type DiscoveryResult, type DiscoveryStatus, type DiscoveryTask } from '@/api/discovery'

const marketNames: Record<string, string> = { TH: '泰国', VN: '越南', MY: '马来西亚', SG: '新加坡', PH: '菲律宾', ID: '印尼' }
const categories = ['家居用品', '厨房用品', '收纳整理', '清洁用品', '个护美妆工具', '手机配件', '宠物用品', '户外运动', '文具办公', '服饰配件']
const steps = [{ key: 'planning', title: '规划' }, { key: 'searching', title: '搜索' }, { key: 'filtering', title: '去重筛选' },
  { key: 'awaiting_confirmation', title: '确认' }, { key: 'collecting', title: '采集' }, { key: 'analyzing', title: '分析排名' }, { key: 'completed', title: '完成' }]
const dims = ['short_video_potential', 'market_fit', 'homogeneity_risk', 'ip_compliance_risk'] as const
const dimNames: Record<string, string> = { short_video_potential: '短视频展示潜力', market_fit: '目标市场适配', homogeneity_risk: '同质化风险', ip_compliance_risk: '侵权及类目合规风险' }
const levelLabels: Record<string, string> = { low: '低', medium: '中', high: '高' }

const route = useRoute(), router = useRouter()
const status = ref<DiscoveryStatus>(), task = ref<DiscoveryTask>(), history = ref<DiscoveryTask[]>([])
const historyPage = ref(1), historyTotal = ref(0), creating = ref(false), confirming = ref(false), loadingTask = ref(false)
const picked = ref<string[]>([]), tab = ref('plan'), drawer = ref(false), current = ref<DiscoveryResult>()
const priceMin = ref<number | undefined>(5), priceMax = ref<number | undefined>(30), autoCollect = ref(false)
const form = reactive({ target_market: 'TH' as Market, category: '家居用品', keywords: [] as string[], exclude_words: [] as string[], preferences: '', max_candidates: 30 })

const searchAvailable = computed(() => status.value?.sources.some(s => s.available))
const activeStep = computed(() => {
  if (!task.value) return 0
  const s = task.value.status
  if (s === 'completed' || s === 'partial_failed') return steps.length
  const idx = stageOrder.indexOf(s === 'queued' ? 'planning' : s)
  return idx >= 0 ? idx : stageOrder.indexOf(task.value.resume_stage)
})
const isActive = (s?: string) => !!s && !['completed', 'partial_failed', 'failed', 'cancelled'].includes(s)
const fmt = (v?: string | null) => (v ? new Date(v).toLocaleString() : '—')
const statusType = (s: string) => (s === 'completed' ? 'success' : s === 'failed' ? 'danger' : s === 'partial_failed' ? 'warning' : s === 'cancelled' ? 'info' : 'primary')
const resultType = (s: string) => (s === 'ranked' ? 'success' : ['collect_failed', 'analysis_failed'].includes(s) ? 'danger' : ['price_filtered', 'incomplete', 'skipped_budget', 'not_selected'].includes(s) ? 'info' : 'primary')
const recLabel = (r: string) => ({ recommended: '推荐', consider: '可考虑', not_recommended_compliance: '合规风险高' } as Record<string, string>)[r] || r
const recType = (r: string) => (r === 'recommended' ? 'success' : r === 'consider' ? 'primary' : 'danger')
const rejectedText = (r?: Record<string, number>) => (r && Object.keys(r).length ? '过滤：' + Object.entries(r).map(([k, v]) => `${({ not_1688_offer_url: '非商品页', missing_title: '无标题', excluded_word: '含排除词', over_limit: '超过上限' } as Record<string, string>)[k] || k} ${v}`).join('，') : '')
const countsText = (c?: Record<string, number>) => (c && Object.keys(c).length ? Object.entries(c).map(([k, v]) => `${resultLabels[k] || k} ${v}`).join('；') : '无结果')
const uuid = () => (crypto.randomUUID ? crypto.randomUUID() : 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => { const r = (Math.random() * 16) | 0; return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16) }))

async function loadHistory() { try { const r = await discovery.tasks(historyPage.value); history.value = r.items; historyTotal.value = r.total } catch {} }
async function select(id: string) {
  loadingTask.value = true
  try {
    task.value = await discovery.task(id); picked.value = []
    if (route.query.task !== id) router.replace({ query: { ...route.query, task: id } })
    if (task.value.results?.length && task.value.status !== 'planning') tab.value = 'results'
  } catch {} finally { loadingTask.value = false }
}
async function refresh() { if (task.value) { try { task.value = await discovery.task(task.value.id) } catch {} } }
async function start() {
  creating.value = true
  try {
    const t = await discovery.create({ request_key: uuid(), target_market: form.target_market, category: form.category,
      price_min: priceMin.value != null ? priceMin.value.toFixed(2) : null, price_max: priceMax.value != null ? priceMax.value.toFixed(2) : null,
      currency: 'CNY', keywords: form.keywords, exclude_words: form.exclude_words, preferences: form.preferences,
      max_candidates: form.max_candidates, auto_collect: autoCollect.value })
    ElMessage.success(t.reused ? '相同目标已有进行中的任务，已打开该任务' : '任务已创建，Worker 将开始执行')
    tab.value = 'plan'; await select(t.id); await loadHistory()
  } catch {} finally { creating.value = false }
}
function onPick(rows: DiscoveryResult[]) {
  const max = task.value?.budget.collect ?? 5
  if (rows.length > max) ElMessage.warning(`最多选择 ${max} 件，超出部分不会提交`)
  picked.value = rows.slice(0, max).map(r => r.source_item_id)
}
async function confirm() {
  if (!task.value) return
  try { await ElMessageBox.confirm(`将通过妙手 fetch_item 采集 ${picked.value.length} 件真实 1688 商品（已在公共采集箱的只同步不重复提交）。确认？`, '确认批量采集', { type: 'warning' }) } catch { return }
  confirming.value = true
  try { task.value = { ...task.value, ...(await discovery.confirm(task.value.id, picked.value)) }; picked.value = []; await refresh() } catch {} finally { confirming.value = false }
}
async function cancelTask() { if (!task.value) return; try { await discovery.cancel(task.value.id); await refresh(); await loadHistory() } catch {} }
function openDrawer(row: DiscoveryResult) { current.value = row; drawer.value = true }

let timer: ReturnType<typeof setInterval> | undefined, polling = false
onMounted(async () => {
  try { status.value = await discovery.status() } catch {}
  await loadHistory()
  const id = (route.query.task as string) || history.value.find(t => isActive(t.status))?.id || history.value[0]?.id
  if (id) await select(id)
  timer = setInterval(async () => {
    if (polling || document.hidden || !task.value || !isActive(task.value.status) || task.value.status === 'awaiting_confirmation') return
    polling = true
    try { const before = task.value.status; await refresh(); if (before !== task.value?.status) await loadHistory() } finally { polling = false }
  }, 4000)
})
onUnmounted(() => { if (timer) clearInterval(timer) })
</script>

<style scoped>
.page { padding: 24px; } .heading { display:flex; justify-content:space-between; align-items:center; gap:16px; flex-wrap:wrap; } h2 { margin:0; }
.section { margin-top:20px; } .muted { color:#73767a; font-size:13px; } .error { color:#f56c6c; } .price { display:flex; gap:8px; align-items:center; }
.state { display:flex; gap:12px; align-items:center; margin:16px 0 8px; flex-wrap:wrap; } .actions { display:flex; gap:12px; margin-top:12px; flex-wrap:wrap; }
.err { margin-top:8px; } .product { display:flex; gap:12px; align-items:center; } .thumb { width:64px; height:64px; flex-shrink:0; border-radius:4px; }
.gallery { display:flex; gap:8px; flex-wrap:wrap; margin:12px 0; } .tag { margin:0 8px 8px 0; } p { overflow-wrap:anywhere; line-height:1.5; margin:4px 0; }
code { background:var(--app-soft-bg); padding:0 4px; border-radius:3px; }
</style>
