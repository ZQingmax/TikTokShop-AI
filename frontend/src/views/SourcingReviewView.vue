<template>
  <div class="page">
    <div class="heading"><h2>人工选品审核</h2><el-button @click="$router.push('/sourcing')">返回智能选品</el-button></div>
    <el-alert title="审核绑定 AI 评估 ID、商品输入版本及登录用户。通过仅保存选品决策；不发布、不认领、不采购。" type="info" :closable="false" />
    <el-card class="section">
      <el-tabs v-model="tab" @tab-change="changeTab"><el-tab-pane label="待审核" name="pending" /><el-tab-pane label="已通过" name="approved" /><el-tab-pane label="已拒绝" name="rejected" /><el-tab-pane label="已收藏" name="favorite" /><el-tab-pane label="审核历史" name="history" /></el-tabs>
      <div class="toolbar" v-if="tab !== 'history'"><el-select v-model="market" clearable placeholder="目标站点"><el-option v-for="m in markets" :key="m" :label="m" :value="m" /></el-select><el-input v-model="keyword" placeholder="候选池搜索" clearable style="width:280px" @keyup.enter="search" /><el-button @click="search">搜索 / 刷新</el-button></div>
      <el-table v-if="tab !== 'history'" :data="items" v-loading="loading" class="section">
        <el-table-column label="商品" min-width="280"><template #default="{ row }"><div class="product"><el-image v-if="row.main_image" :src="row.main_image" fit="cover" class="thumb" referrerpolicy="no-referrer" /><div><strong>{{ row.name || '待补充资料' }}</strong><p>{{ row.target_market }} · {{ row.purchase_price ?? '未知' }} {{ row.currency }}</p><el-tag>{{ reviewLabels[row.review_status] }}</el-tag><el-tag v-if="row.favorite" type="warning">已收藏</el-tag></div></div></template></el-table-column>
        <el-table-column label="AI 评估" min-width="270"><template #default="{ row }"><template v-if="row.evaluation"><el-tag :type="row.evaluation.stale ? 'warning' : 'success'">{{ row.evaluation.stale ? '过期，需重新分析' : '视觉评分 ' + row.evaluation.visual_score }}</el-tag><p>{{ row.evaluation.text_analysis?.recommendation_reasons.join('；') || row.evaluation.vision.score_basis.join('；') }}</p><span class="muted">文本：{{ row.evaluation.text_status === 'succeeded' ? '已完成' : '未配置' }} · 风险 {{ row.evaluation.vision.potential_risks.length }} 项</span></template><span v-else class="muted">尚无成功评估，请先分析</span></template></el-table-column>
        <el-table-column label="版本 / 来源" width="180"><template #default="{ row }">v{{ row.version }}<p>{{ row.data_source }}</p></template></el-table-column>
        <el-table-column label="操作" width="140"><template #default="{ row }"><el-button type="primary" link @click="open(row)">查看 / 审核</el-button></template></el-table-column>
      </el-table>
      <el-table v-else :data="history" v-loading="loading"><el-table-column prop="candidate_name" label="商品" min-width="240" /><el-table-column label="操作" width="100"><template #default="{ row }">{{ actionLabels[row.action] }}</template></el-table-column><el-table-column prop="reviewer_name" label="操作用户" /><el-table-column prop="input_version" label="输入版本" width="90" /><el-table-column prop="evaluation_id" label="AI 评估 ID" min-width="280" /><el-table-column prop="note" label="备注" min-width="180" /><el-table-column label="时间" min-width="180"><template #default="{ row }">{{ new Date(row.created_at).toLocaleString() }}</template></el-table-column></el-table>
      <el-pagination class="section" v-model:current-page="page" :page-size="20" :total="total" layout="total, prev, pager, next" @current-change="load" />
    </el-card>
    <el-dialog v-model="dialog" :title="current?.name || '选品审核'" width="900px"><template v-if="current"><p>{{ current.target_market }} · {{ current.purchase_price ?? '未知' }} {{ current.currency }} · 供应商 {{ current.supplier || '未知' }}</p><SourcingEvaluation :evaluation="current.evaluation" /><el-input v-model="note" type="textarea" placeholder="填写审核理由或备注" :maxlength="2000" :rows="3" /><p class="muted">当前版本 v{{ current.version }}；评估 ID {{ current.evaluation?.id || '无' }}</p></template><template #footer><el-button @click="dialog = false">关闭</el-button><el-button :disabled="!canReview" :loading="saving" @click="decide(current?.favorite ? 'unfavorite' : 'favorite')">{{ current?.favorite ? '取消收藏' : '收藏' }}</el-button><el-button type="danger" :disabled="!canReview" :loading="saving" @click="decide('reject')">拒绝</el-button><el-button type="success" :disabled="!canReview" :loading="saving" @click="decide('approve')">通过：保存选品决策</el-button></template></el-dialog>
  </div>
</template>
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import SourcingEvaluation from '@/components/SourcingEvaluation.vue'
import { sourcing, markets, reviewLabels, type Candidate, type Market, type Review } from '@/api/sourcing'
const tab = ref('pending'), market = ref<Market | ''>(''), keyword = ref(''), page = ref(1), total = ref(0), loading = ref(false)
const items = ref<Candidate[]>([]), history = ref<Review[]>([]), current = ref<Candidate>(), dialog = ref(false), note = ref(''), saving = ref(false)
const actionLabels: Record<string, string> = { approve: '通过', reject: '拒绝', favorite: '收藏', unfavorite: '取消收藏' }
const canReview = computed(() => current.value?.evaluation && !current.value.evaluation.stale)
async function load() { loading.value = true; try { if (tab.value === 'history') { const r = await sourcing.history({ page: page.value }); history.value = r.items; total.value = r.total } else { const params: Record<string, unknown> = { page: page.value, keyword: keyword.value, sort: 'visual_score' }; if (market.value) params.target_market = market.value; if (tab.value === 'favorite') params.favorite = true; else params.review_status = tab.value; const r = await sourcing.candidates(params); items.value = r.items; total.value = r.total } } catch {} finally { loading.value = false } }
async function changeTab() { page.value = 1; await load() }
async function search() { page.value = 1; await load() }
async function open(row: Candidate) { try { current.value = await sourcing.candidate(row.id); note.value = ''; dialog.value = true } catch {} }
async function decide(action: string) { if (!current.value || !canReview.value) return; saving.value = true; try { await sourcing.review(current.value, action, note.value); ElMessage.success('审核决策已保存'); current.value = await sourcing.candidate(current.value.id); if (['approve', 'reject'].includes(action)) dialog.value = false; await load() } catch {} finally { saving.value = false } }
onMounted(load)
</script>
<style scoped>
.page { padding:24px; }.heading { display:flex; align-items:center; justify-content:space-between; }.section { margin-top:20px; }.toolbar { display:flex; flex-wrap:wrap; gap:12px; }.product { display:flex; gap:12px; align-items:center; }.thumb { width:64px; height:64px; flex-shrink:0; }.muted { color:#73767a; font-size:13px; }p { overflow-wrap:anywhere; line-height:1.5; }
</style>
