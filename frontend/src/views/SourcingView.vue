<template>
  <div class="selection-center">
    <header>
      <div>
        <h2>选品中心</h2>
        <p>市场依据 → 1688 货源 → 候选库 → 人工选择 → 妙手采集箱</p>
      </div>
      <el-select v-model="market" style="width: 180px" @change="changeMarket"
        ><el-option v-for="m in markets" :key="m" :value="m" :label="marketNames[m]"
      /></el-select>
    </header>
    <el-tabs v-model="tab" class="main-tabs" @tab-change="changeTab">
      <el-tab-pane label="市场调研" name="market">
        <el-alert
          title="依据来自 FastMoss 抓取或导入资料；本店数据不代表全市场。未提供市场证据时仅生成潜力建议，不生成热度、增长或利润结论。"
          type="info"
          :closable="false"
          show-icon
        />
        <el-card class="section" shadow="never"
          ><template #header
            ><div class="card-head">
              <span class="card-title">FastMoss 市场商品</span
              ><span class="muted">按国家与品类抓取新品榜，完成后在下方「选择市场依据」中勾选商品</span>
            </div></template
          >
          <FastmossPanel :market="market" @report="openFastmossReport" @category="autoCategory" />
        </el-card>
        <el-card class="section" shadow="never"
          ><template #header
            ><div class="card-head">
              <span class="card-title">导入榜单</span
              ><span class="muted"
                >支持 FastMoss 原始 CSV、模板 UTF-8 CSV / XLSX，最多 500 条、2 MB；缺失指标保留未知。默认地区：{{
                  marketNames[market]
                }}</span
              >
            </div></template
          >
          <div class="toolbar">
            <el-button @click="downloadTemplate">下载 CSV 模板</el-button
            ><el-input
              v-model="upload.name"
              placeholder="榜单名称"
              style="width: 200px"
            /><el-select v-model="upload.scope" style="width: 130px" @change="clearPreview"
              ><el-option value="market" label="市场榜单" /><el-option
                value="shop"
                label="本店数据" /></el-select
            ><input type="file" accept=".csv,.xlsx" @change="readReport" /><el-button
              :disabled="!upload.content"
              :loading="busy"
              @click="previewReport"
              >预览导入</el-button
            >
          </div>
          <el-input
            v-model="upload.source_url"
            class="section-sm"
            placeholder="导入 FastMoss 原始 CSV 时，补充实际来源榜单链接（文件已含链接时可不填）"
            @input="clearPreview"
          />
        </el-card>
        <el-card class="section" shadow="never"
          ><template #header
            ><div class="card-head">
              <span class="card-title">选择市场依据</span>
              <div class="toolbar">
                <el-select
                  v-model="reportId"
                  clearable
                  placeholder="选择已导入 / 抓取的榜单（可不选）"
                  style="width: 360px"
                  @change="selectReport"
                  ><el-option
                    v-for="r in reports"
                    :key="r.id"
                    :value="r.id"
                    :label="`${r.name} · ${r.scope === 'shop' ? '本店数据' : '市场榜单'}`" /></el-select
                ><el-button :disabled="reportPage === 1" @click="changeReportPage(-1)">上一页</el-button
                ><span class="muted">{{ reportPage }} / {{ Math.max(1, Math.ceil(reportTotal / 20)) }}</span
                ><el-button :disabled="reportPage * 20 >= reportTotal" @click="changeReportPage(1)"
                  >下一页</el-button
                >
              </div>
            </div></template
          >
          <template v-if="selectedReport"
            ><div class="toolbar">
              <el-select
                v-model="periodFilter"
                clearable
                placeholder="全部统计口径（不按排名排序）"
                style="width: 300px"
                ><el-option v-for="p in periods" :key="p" :value="p" :label="p"
              /></el-select>
              <span class="muted"
                >选择 1–20 条作为本次依据。排名仅在当前榜单、相同统计日期与周期内排序。</span
              >
            </div>
            <MarketProductTable :key="reportId" :rows="reportRows" @selection="selectRows" />
          </template>
          <el-empty
            v-else
            description="尚未选择榜单：抓取 FastMoss 或导入榜单后在此选择依据商品"
            :image-size="80"
          />
        </el-card>
        <div class="next-bar">
          <span>{{
            selectedReport ? `已选 ${reportSelection.length} / 20 条依据` : '未选择市场依据'
          }}</span
          ><el-button type="primary" @click="goTab('ai')">下一步：设置采购条件</el-button>
        </div>
      </el-tab-pane>
      <el-tab-pane label="AI 选品" name="ai">
        <el-card shadow="never"
          ><template #header
            ><div class="card-head">
              <span class="card-title">市场依据</span
              ><el-button link type="primary" @click="goTab('market')">修改依据</el-button>
            </div></template
          >
          <el-descriptions v-if="selectedReport" :column="3" border>
            <el-descriptions-item label="榜单">{{ selectedReport.name }}</el-descriptions-item>
            <el-descriptions-item label="类型">{{
              selectedReport.scope === 'shop' ? '本店数据' : '市场榜单'
            }}</el-descriptions-item>
            <el-descriptions-item label="已选商品"
              ><el-tag :type="reportSelection.length ? 'success' : 'warning'"
                >{{ reportSelection.length }} / 20 条</el-tag
              ></el-descriptions-item
            >
          </el-descriptions>
          <el-alert
            v-else
            type="warning"
            :closable="false"
            show-icon
            title="未选择市场依据：将仅生成地区潜力建议并寻找货源，不生成热度、增长或利润结论。"
          />
        </el-card>
        <el-card class="section" shadow="never"
          ><template #header><span class="card-title">设置采购条件并启动 AI 选品</span></template>
          <el-form label-position="top" class="goal-form">
            <el-row :gutter="20">
              <el-col :xs="24" :md="12"
                ><el-form-item label="采购品类" required
                  ><div class="inline">
                    <el-input
                      v-model="goal.category"
                      placeholder="如家居收纳"
                      maxlength="100"
                      @input="categoryTouched = true"
                    /><el-button
                      v-if="categoryTouched && reportSelection.length"
                      link
                      type="primary"
                      @click="resetCategory"
                      >按已选商品重新带入</el-button
                    >
                  </div></el-form-item
                ></el-col
              >
              <el-col :xs="24" :md="8"
                ><el-form-item label="采购价区间（CNY）"
                  ><div class="inline">
                    <el-input-number
                      v-model="goal.price_min"
                      :min="0"
                      :precision="2"
                      placeholder="最低"
                      :controls="false"
                    /><span>至</span
                    ><el-input-number
                      v-model="goal.price_max"
                      :min="0"
                      :precision="2"
                      placeholder="最高"
                      :controls="false"
                    />
                  </div></el-form-item
                ></el-col
              >
              <el-col :xs="24" :md="4"
                ><el-form-item label="候选上限（件）"
                  ><el-input-number v-model="goal.max_candidates" :min="1" :max="30" /></el-form-item
              ></el-col>
              <el-col :xs="24" :md="12"
                ><el-form-item label="指定关键词"
                  ><el-input v-model="keywords" placeholder="可选，用逗号分隔" /></el-form-item
              ></el-col>
              <el-col :xs="24" :md="12"
                ><el-form-item label="排除词"
                  ><el-input v-model="excludeWords" placeholder="可选，用逗号分隔" /></el-form-item
              ></el-col>
              <el-col :span="24"
                ><el-form-item label="选品偏好"
                  ><el-input
                    v-model="goal.preferences"
                    type="textarea"
                    :rows="3"
                    placeholder="选品偏好或需核实的采购条件"
                    maxlength="500"
                    show-word-limit /></el-form-item
              ></el-col>
            </el-row>
          </el-form>
          <div class="toolbar">
            <el-button type="primary" size="large" :loading="busy" @click="startDiscovery">{{
              reportId ? '依据榜单寻找货源' : '生成地区潜力建议并找货源'
            }}</el-button
            ><span class="muted">结果自动进入候选商品库；此操作不采集到妙手。</span>
          </div>
        </el-card>
      </el-tab-pane>
      <el-tab-pane label="候选商品库" name="candidates">
        <div class="toolbar">
          <el-input
            v-model="keyword"
            placeholder="名称 / 来源商品 ID"
            clearable
            style="width: 240px"
            @keyup.enter="searchCandidates"
          /><el-select
            v-model="decisionFilter"
            clearable
            placeholder="全部选品状态"
            style="width: 160px"
            ><el-option value="pending" label="待选择" /><el-option
              value="approved"
              label="已选择" /><el-option value="rejected" label="已排除" /></el-select
          ><el-select v-model="sort" style="width: 160px"
            ><el-option value="newest" label="最新加入" /><el-option
              value="price_asc"
              label="采购价升序（CNY）" /></el-select
          ><el-button @click="searchCandidates">筛选</el-button
          ><el-button @click="openEditor()">手动添加</el-button
          ><el-button @click="$router.push('/sourcing/1688')">搜索 1688</el-button>
        </div>
        <div class="toolbar section">
          <el-button type="primary" :disabled="!selection.length" :loading="busy" @click="addToBox(selection)"
            >加入我的采集箱（{{ selection.length }}）</el-button
          ><el-button :disabled="!selection.length" :loading="busy" @click="analyze"
            >文字证据分析</el-button
          ><el-button @click="loadCandidates">刷新结果</el-button
          ><el-tag
            v-if="sourceFilter"
            closable
            @close="clearSourceFilter"
            >来源：{{ sourceFilter }}</el-tag
          >
        </div>
        <el-table
          class="section"
          :data="candidates"
          v-loading="loading"
          row-key="id"
          @selection-change="(rows: EvidenceCandidate[]) => (selection = rows)"
        >
          <el-table-column type="selection" width="45" />
          <el-table-column label="商品 / 采购条件" min-width="290"
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
                  <p>
                    {{ row.purchase_price ?? '未知' }} {{ row.currency }} · 起批量
                    {{ row.min_order_quantity ?? '未知' }}
                  </p>
                  <p>{{ row.supplier || '供应商待核实' }}</p>
                  <el-link :href="row.product_url" target="_blank" rel="noopener noreferrer"
                    >查看货源</el-link
                  >
                </div>
              </div></template
            ></el-table-column
          >
          <el-table-column label="市场依据 / 推荐理由" min-width="300"
            ><template #default="{ row }"
              ><el-tag>{{
                row.market_evidence?.length
                  ? `${row.market_evidence.length} 条来源记录`
                  : '缺少市场证据'
              }}</el-tag
              ><el-tag v-if="row.evaluation?.stale" type="warning">分析已过期</el-tag>
              <p>{{ reasons(row) }}</p>
              <span class="muted">{{
                row.completeness === 'ready' ? '基础资料已提供，规格仍需核实' : '资料待补充'
              }}</span></template
            ></el-table-column
          >
          <el-table-column label="选择 / 采集" width="210"
            ><template #default="{ row }"
              ><el-tag>{{ reviewLabels[row.review_status] }}</el-tag
              ><el-tag v-if="row.in_collect_box" type="success" class="tag-gap">已在我的采集箱</el-tag>
              <p>{{ collectionLabel(row) }}</p>
              <el-button
                v-if="row.collection_task_id"
                link
                @click="showCollection(row.collection_task_id)"
                >采集详情</el-button
              ></template
            ></el-table-column
          >
          <el-table-column label="操作" width="190"
            ><template #default="{ row }"
              ><el-button link type="primary" @click="showDetail(row)">依据与差异</el-button
              ><el-button link @click="openEditor(row)">补充</el-button
              ><el-button v-if="row.in_collect_box" link @click="$router.push('/collect')">查看采集箱</el-button
              ><el-button
                v-else
                link
                type="primary"
                :disabled="row.review_status === 'rejected'"
                @click="addToBox([row])"
                >加入我的采集箱</el-button
              ><el-button
                link
                :type="row.review_status === 'rejected' ? 'primary' : 'danger'"
                @click="decide(row)"
                >{{ row.review_status === 'rejected' ? '恢复' : '排除' }}</el-button
              ></template
            ></el-table-column
          > </el-table
        ><el-pagination
          class="section"
          v-model:current-page="page"
          :total="total"
          :page-size="20"
          layout="total, prev, pager, next"
          @current-change="loadCandidates"
        />
      </el-tab-pane>
      <el-tab-pane label="任务记录" name="tasks">
        <el-button @click="loadTasks">刷新任务</el-button>
        <h3>AI 选品任务</h3>
        <el-table :data="discoveryJobs"
          ><el-table-column prop="id" label="任务" min-width="250" /><el-table-column
            prop="status_label"
            label="状态"
            width="140"
          /><el-table-column
            prop="progress_message"
            label="进度 / 结果"
            min-width="350"
          /><el-table-column label="操作"
            ><template #default="{ row }"
              ><el-button link @click="showDiscovery(row.id)">结果</el-button></template
            ></el-table-column
          ></el-table
        ><el-pagination
          v-model:current-page="discoveryPage"
          :total="discoveryTotal"
          :page-size="20"
          layout="prev, pager, next"
          @current-change="loadTasks"
        />
        <h3>文字分析任务</h3>
        <el-table :data="analysisJobs"
          ><el-table-column prop="candidate_id" label="候选商品" /><el-table-column label="状态"
            ><template #default="{ row }">{{ taskLabels[row.status] }}</template></el-table-column
          ><el-table-column prop="error_message" label="异常" /><el-table-column label="操作"
            ><template #default="{ row }"
              ><el-button v-if="row.status === 'failed'" link @click="retryAnalysis(row.id)"
                >重试文字分析</el-button
              ></template
            ></el-table-column
          ></el-table
        ><el-pagination
          v-model:current-page="analysisPage"
          :total="analysisTotal"
          :page-size="20"
          layout="prev, pager, next"
          @current-change="loadTasks"
        />
        <h3>妙手采集任务</h3>
        <el-table :data="collectionJobs"
          ><el-table-column prop="id" label="任务" /><el-table-column label="状态"
            ><template #default="{ row }"
              >{{ sourceStatus[row.status] }} · {{ row.completed }}/{{ row.total }}</template
            ></el-table-column
          ><el-table-column prop="error_message" label="异常" /><el-table-column label="操作"
            ><template #default="{ row }"
              ><el-button link @click="showCollection(row.id)">详情 / 查询</el-button></template
            ></el-table-column
          ></el-table
        ><el-pagination
          v-model:current-page="collectionPage"
          :total="collectionTotal"
          :page-size="10"
          layout="prev, pager, next"
          @current-change="loadTasks"
        />
        <el-collapse class="section"
          ><el-collapse-item title="历史选品决策" name="history"
            ><el-table :data="history"
              ><el-table-column prop="candidate_name" label="商品" /><el-table-column
                prop="action"
                label="决定" /><el-table-column
                prop="input_version"
                label="资料版本" /><el-table-column prop="note" label="备注" /><el-table-column
                prop="created_at"
                label="时间" /></el-table
            ><el-pagination
              v-model:current-page="historyPage"
              :total="historyTotal"
              :page-size="20"
              layout="prev, pager, next"
              @current-change="loadTasks" /></el-collapse-item
        ></el-collapse>
      </el-tab-pane>
    </el-tabs>
    <el-dialog v-model="previewDialog" title="确认导入榜单" width="1000px"
      ><p>
        {{ upload.name }} · {{ marketNames[market] }} ·
        {{ upload.scope === 'shop' ? '本店数据' : '市场榜单' }} · {{ previewRows.length }} 条
      </p>
      <el-table :data="previewRows" max-height="420"
        ><el-table-column prop="name" label="商品" /><el-table-column
          prop="source_platform"
          label="来源" /><el-table-column prop="target_market" label="地区" /><el-table-column
          prop="observed_on"
          label="统计日期" /><el-table-column label="排名 / 销量"
          ><template #default="{ row }"
            >{{ row.rank ?? '未知' }} / {{ row.sales ?? '未知' }}</template
          ></el-table-column
        ><el-table-column prop="source_url" label="原始链接" /></el-table
      ><template #footer
        ><el-button type="primary" :loading="busy" @click="confirmImport"
          >确认保存</el-button
        ></template
      ></el-dialog
    >
    <el-dialog v-model="detailDialog" title="选品依据与货源核对" width="950px"
      ><template v-if="detail"
        ><h3>{{ detail.name }}</h3>
        <p>
          {{ detail.target_market }} · {{ detail.purchase_price ?? '未知' }} {{ detail.currency }}
        </p>
        <div class="images">
          <el-image
            v-if="detail.main_image"
            :src="detail.main_image"
            referrerpolicy="no-referrer"
            fit="contain"
          /><el-image
            v-for="e in detail.market_evidence?.filter((x) => x.image_url)"
            :key="e.evidence_id"
            :src="e.image_url"
            fit="contain"
            referrerpolicy="no-referrer"
          />
        </div>
        <p class="muted">图片仅供人工对照；系统未分析图片。</p>
        <el-alert
          v-if="detail.evaluation?.stale"
          title="资料或依据已更新，以下分析已过期，请重新分析。"
          type="warning"
          :closable="false"
        />
        <el-table :data="detail.market_evidence"
          ><el-table-column prop="name" label="依据商品" /><el-table-column label="来源 / 口径"
            ><template #default="{ row }"
              ><el-link :href="row.source_url" target="_blank" rel="noopener noreferrer">{{
                row.source_platform
              }}</el-link>
              <p>
                {{ row.scope === 'shop' ? '本店数据' : '市场榜单' }} · {{ row.observed_on }} ·
                {{ row.period || '周期未知' }}
              </p></template
            ></el-table-column
          ><el-table-column label="原始指标"
            ><template #default="{ row }"
              >排名 {{ row.rank ?? '未知' }} · 销量 {{ row.sales ?? '未知' }}
              <p>
                销售额 {{ row.revenue ?? '未知' }} {{ row.currency || '币种未知' }} · 价格
                {{ row.price ?? '未知' }}
              </p></template
            ></el-table-column
          ></el-table
        >
        <template v-if="detail.evaluation?.evidence?.kind === 'market_evidence_v2'"
          ><div v-for="entry in analysisSections" :key="entry.key">
            <h4>{{ entry.label }}</h4>
            <p v-for="(line, i) in analysisLines(entry.key)" :key="i">{{ line }}</p>
          </div>
          <h4>市场依据解释</h4>
          <p v-for="claim in detailAnalysis.market_basis || []" :key="claim.evidence_id">
            {{ evidenceName(claim.evidence_id) }}：{{ claim.reason }}
          </p></template
        >
        <p v-else>尚无当前文字证据分析。历史评估可查询，但不参与选品。</p>
        <el-collapse
          ><el-collapse-item title="历史评估记录（不参与推荐）">
            <pre>{{ JSON.stringify(evaluationHistory, null, 2) }}</pre>
            <el-pagination
              v-model:current-page="evaluationPage"
              :total="evaluationTotal"
              :page-size="20"
              layout="prev, pager, next"
              @current-change="loadEvaluationHistory" /></el-collapse-item></el-collapse
        ><el-input
          v-model="note"
          type="textarea"
          placeholder="人工备注"
          maxlength="2000"
        /><el-button class="section" @click="saveNote">保存备注</el-button></template
      ></el-dialog
    >
    <el-dialog
      v-model="editDialog"
      :title="editingId ? '补充商品资料' : '手动添加候选'"
      width="720px"
      ><el-form label-width="100px"
        ><el-form-item label="1688 链接"><el-input v-model="form.product_url" /></el-form-item
        ><el-form-item label="名称"><el-input v-model="form.name" /></el-form-item
        ><el-form-item label="采购价"><el-input v-model="form.purchase_price" /></el-form-item
        ><el-form-item label="主图链接"><el-input v-model="form.main_image" /></el-form-item
        ><el-form-item label="品类"><el-input v-model="form.category" /></el-form-item
        ><el-form-item label="供应商"><el-input v-model="form.supplier" /></el-form-item
        ><el-form-item label="材质/尺寸/规格"
          ><el-input v-model="form.description" type="textarea" /></el-form-item></el-form
      ><template #footer
        ><el-button type="primary" :loading="busy" @click="saveCandidate">保存</el-button></template
      ></el-dialog
    >
    <el-dialog v-model="jobDialog" title="妙手采集结果" width="900px"
      ><template v-if="job"
        ><p>{{ sourceStatus[job.status] }} · {{ job.error_message }}</p>
        <el-table :data="job.items"
          ><el-table-column prop="source_item_id" label="货源 ID" /><el-table-column
            prop="common_detail_id"
            label="妙手采集箱 ID" /><el-table-column prop="state" label="状态" /><el-table-column
            prop="error"
            label="异常"
        /></el-table>
        <p class="muted">只有平台详情确认并同步成功才标记完成；结果不确定时查询平台状态。</p>
        <el-button :loading="busy" @click="showCollection(job.id)">刷新</el-button
        ><el-button
          v-if="['failed', 'uncertain', 'waiting'].includes(job.status)"
          :loading="busy"
          @click="reconcile"
          >查询平台状态</el-button
        ></template
      ></el-dialog
    >
    <el-dialog v-model="discoveryDialog" title="AI 选品结果" width="950px"
      ><p>{{ discoveryDetail?.progress_message }}</p>
      <el-table :data="discoveryDetail?.results"
        ><el-table-column label="货源"
          ><template #default="{ row }"
            ><el-link :href="row.canonical_url" target="_blank" rel="noopener noreferrer">{{
              row.snippet_title || row.canonical_url
            }}</el-link></template
          ></el-table-column
        ><el-table-column prop="status" label="状态" /><el-table-column
          prop="status_reason"
          label="说明"
        /><el-table-column label="候选库"
          ><template #default="{ row }">{{
            row.candidate_id ? '已关联' : '未入库'
          }}</template></el-table-column
        ></el-table
      ></el-dialog
    >
  </div>
</template>
<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import FastmossPanel from '@/components/FastmossPanel.vue'
import MarketProductTable from '@/components/MarketProductTable.vue'
import {
  sourcing,
  markets,
  reviewLabels,
  taskLabels,
  type CandidateInput,
  type Market,
  type Task,
  type Review,
  type Evaluation,
} from '@/api/sourcing'
import { miaoshou, sourceStatus, type SourceJob } from '@/api/miaoshou'
import { collectBox } from '@/api/collectBox'
import {
  evidenceApi,
  selectedCategoryNames,
  type MarketRow,
  type Report,
  type EvidenceCandidate,
  type ReportUpload,
  type Analysis,
  type DiscoveryJob,
} from '@/api/marketEvidence'
const route = useRoute(),
  router = useRouter()
const marketNames: Record<Market, string> = {
  MY: '马来西亚 MY',
  TH: '泰国 TH',
  VN: '越南 VN',
  SG: '新加坡 SG',
  PH: '菲律宾 PH',
  ID: '印度尼西亚 ID',
}
const market = ref<Market>('MY'),
  tab = ref(String(route.query.tab || 'market')),
  busy = ref(false),
  loading = ref(false)
const reports = ref<Report[]>([]),
  reportId = ref(''),
  reportSelection = ref<MarketRow[]>([]),
  reportPage = ref(1),
  reportTotal = ref(0),
  periodFilter = ref('')
const upload = reactive<ReportUpload>({
  name: '',
  format: 'csv',
  content: '',
  target_market: 'MY',
  scope: 'market',
})
const previewRows = ref<MarketRow[]>([]),
  previewDialog = ref(false),
  previewPayload = ref<ReportUpload>()
const selectedReport = computed(() => reports.value.find((r) => r.id === reportId.value))
const periodKey = (r: MarketRow) => `${r.observed_on || '未知日期'} / ${r.period || '未知周期'}`
const periods = computed(() => [...new Set(selectedReport.value?.rows.map(periodKey) || [])])
const reportRows = computed(() => {
  const rows = selectedReport.value?.rows || []
  return periodFilter.value
    ? rows
        .filter((r) => periodKey(r) === periodFilter.value)
        .slice()
    : rows
})
const goal = reactive({
    category: '家居日用品',
    price_min: undefined as number | undefined,
    price_max: undefined as number | undefined,
    max_candidates: 20,
    preferences: '',
  }),
  keywords = ref(''),
  excludeWords = ref('')
const candidates = ref<EvidenceCandidate[]>([]),
  selection = ref<EvidenceCandidate[]>([]),
  page = ref(1),
  total = ref(0),
  keyword = ref(''),
  decisionFilter = ref(''),
  sort = ref('newest'),
  sourceFilter = ref(String(route.query.source || ''))
const evaluationHistory = ref<Evaluation[]>([]),
  evaluationPage = ref(1),
  evaluationTotal = ref(0)
const detail = ref<EvidenceCandidate>(),
  detailDialog = ref(false),
  note = ref('')
const analysisSections = [
  { key: 'matching_facts', label: '文字资料确认的匹配项' },
  { key: 'differences', label: '差异与待核实项' },
  { key: 'recommendation_reasons', label: '推荐理由' },
  { key: 'information_gaps', label: '信息缺口' },
  { key: 'limitations', label: '分析局限' },
]
const detailAnalysis = computed(() => (detail.value?.evaluation?.text_analysis || {}) as Analysis)
const analysisLines = (key: string) => (detailAnalysis.value as Record<string, string[]>)[key] || []
const evidenceName = (id: string) =>
  detail.value?.market_evidence.find((e) => e.evidence_id === id)?.name || id
const discoveryJobs = ref<DiscoveryJob[]>([]),
  analysisJobs = ref<Task[]>([]),
  collectionJobs = ref<SourceJob[]>([]),
  history = ref<Review[]>([])
const discoveryPage = ref(1),
  discoveryTotal = ref(0),
  analysisPage = ref(1),
  analysisTotal = ref(0),
  collectionPage = ref(1),
  collectionTotal = ref(0),
  historyPage = ref(1),
  historyTotal = ref(0)
const job = ref<SourceJob>(),
  jobDialog = ref(false),
  discoveryDetail = ref<DiscoveryJob>(),
  discoveryDialog = ref(false)
const editDialog = ref(false),
  editingId = ref('')
const blank = (): CandidateInput => ({
  source_platform: '1688',
  source_product_id: null,
  product_url: '',
  name: null,
  main_image: null,
  images: [],
  description: '',
  purchase_price: null,
  currency: 'CNY',
  skus: [],
  category: null,
  supplier: null,
  target_market: market.value,
  source_note: '',
})
const form = reactive<CandidateInput>(blank())
async function action(fn: () => Promise<void>) {
  if (busy.value) return
  busy.value = true
  try {
    await fn()
  } catch (e) {
    const x = e as { response?: { data?: { detail?: unknown } } }
    if (!x.response) ElMessage.error('操作未完成，请检查连接或文件格式')
  } finally {
    busy.value = false
  }
}
function clearPreview() {
  previewRows.value = []
  previewPayload.value = undefined
}
// Excel 在中文系统导出的 CSV 常为 GBK：严格 UTF-8 解码失败时按 GB18030 解码并提示，不静默产生乱码
async function decodeCsv(file: File) {
  const bytes = new Uint8Array(await file.arrayBuffer())
  try {
    return new TextDecoder('utf-8', { fatal: true }).decode(bytes)
  } catch {
    ElMessage.info('文件不是 UTF-8 编码，已按 GBK/GB18030 读取，请在预览中核对中文是否正确')
    return new TextDecoder('gb18030').decode(bytes)
  }
}
async function readReport(event: Event) {
  clearPreview()
  upload.content = ''
  const f = (event.target as HTMLInputElement).files?.[0]
  if (!f) return
  if (f.size > 2_000_000) {
    ElMessage.error('文件不能超过 2 MB')
    return
  }
  upload.name ||= f.name
  upload.format = f.name.toLowerCase().endsWith('.xlsx') ? 'xlsx' : 'csv'
  if (upload.format === 'csv') upload.content = await decodeCsv(f)
  else {
    const bytes = new Uint8Array(await f.arrayBuffer())
    let binary = ''
    for (const b of bytes) binary += String.fromCharCode(b)
    upload.content = btoa(binary)
  }
}
async function previewReport() {
  await action(async () => {
    const payload = { ...upload, target_market: market.value }
    const result = await evidenceApi.preview(payload)
    previewPayload.value = payload
    previewRows.value = result.rows
    previewDialog.value = true
  })
}
async function confirmImport() {
  await action(async () => {
    if (!previewPayload.value) return
    const r = await evidenceApi.import(previewPayload.value)
    previewDialog.value = false
    reportPage.value = 1
    await loadReports()
    if (!reports.value.some((x) => x.id === r.id)) reports.value.unshift(r)
    reportId.value = r.id
    selectReport()
    ElMessage.success('榜单已保存')
  })
}
function downloadTemplate() {
  const header =
    'name,source_platform,source_url,observed_on,target_market,category,image_url,rank,sales,revenue,price,currency,period\r\n'
  const url = URL.createObjectURL(new Blob(['\ufeff' + header], { type: 'text/csv;charset=utf-8' }))
  const a = document.createElement('a')
  a.href = url
  a.download = 'market-evidence-template.csv'
  a.click()
  URL.revokeObjectURL(url)
}
async function openFastmossReport(id: string) {
  const requestedMarket = market.value
  const report = await evidenceApi.report(id)
  if (requestedMarket !== market.value || report.target_market !== market.value) return
  if (!reports.value.some(r => r.id === id)) reports.value.unshift(report)
  reportId.value = id
  selectReport()
}
async function changeReportPage(delta: number) { reportPage.value += delta; reportId.value = ""; selectReport(); await loadReports() }
async function clearSourceFilter() { sourceFilter.value = ""; await searchCandidates() }
async function loadReports() {
  const requestedMarket = market.value
  const r = await evidenceApi.reports(requestedMarket, reportPage.value)
  if (market.value !== requestedMarket) return
  const pinned = selectedReport.value
  reports.value = r.items
  if (pinned && !reports.value.some(row => row.id === pinned.id)) reports.value.unshift(pinned)
  reportTotal.value = r.total
}
function selectReport() {
  reportSelection.value = []
  periodFilter.value = ''
}
// 采购品类：默认带入已选商品的实际品类（无选择时用抓取品类）；用户手动修改后不再覆盖
const categoryTouched = ref(false)
let panelCategory = ''
function autoCategory(name: string) {
  panelCategory = name.slice(0, 100)
  if (!categoryTouched.value && !reportSelection.value.length && panelCategory) goal.category = panelCategory
}
function selectRows(rows: MarketRow[]) {
  reportSelection.value = rows
  if (categoryTouched.value) return
  const names = selectedCategoryNames(rows)
  if (names) goal.category = names
  else if (!rows.length && panelCategory) goal.category = panelCategory
}
function resetCategory() {
  categoryTouched.value = false
  selectRows(reportSelection.value)
}
async function changeMarket() {
  reportId.value = ''
  reportPage.value = 1
  selectReport()
  clearPreview()
  page.value = 1
  selection.value = []
  await Promise.all([loadReports(), loadCandidates()])
}
async function goTab(name: string) {
  tab.value = name
  await changeTab()
}
async function changeTab() {
  await router.replace({ query: { ...route.query, tab: tab.value } })
  if (tab.value === 'candidates') await loadCandidates()
  if (tab.value === 'tasks') await loadTasks()
}
watch(
  () => route.query.tab,
  (v) => {
    tab.value = String(v || 'market')
  },
)
const split = (s: string) =>
  s
    .split(/[,，\n]/)
    .map((x) => x.trim())
    .filter(Boolean)
async function startDiscovery() {
  if (!goal.category.trim()) {
    ElMessage.warning('请填写品类')
    return
  }
  if (reportId.value && (!reportSelection.value.length || reportSelection.value.length > 20)) {
    ElMessage.warning('请选择 1–20 条榜单记录')
    return
  }
  await action(async () => {
    await evidenceApi.createTask({
      ...goal,
      request_key: crypto.randomUUID(),
      target_market: market.value,
      report_id: reportId.value || null,
      report_rows: reportSelection.value.map((r) => r.row_number),
      keywords: split(keywords.value),
      exclude_words: split(excludeWords.value),
      auto_collect: false,
    })
    tab.value = 'tasks'
    await changeTab()
    ElMessage.success('AI 选品任务已创建')
  })
}
async function loadCandidates() {
  loading.value = true
  try {
    const r = await evidenceApi.candidates({
      target_market: market.value,
      page: page.value,
      keyword: keyword.value,
      sort: sort.value,
      currency: 'CNY',
      review_status: decisionFilter.value || undefined,
      data_source: sourceFilter.value || undefined,
    })
    candidates.value = r.items
    total.value = r.total
    selection.value = []
  } finally {
    loading.value = false
  }
}
async function searchCandidates() {
  page.value = 1
  await loadCandidates()
}
function reasons(row: EvidenceCandidate) {
  return row.evaluation?.evidence?.kind === 'market_evidence_v2'
    ? row.evaluation.text_analysis?.recommendation_reasons?.join('；') || '暂无推荐理由'
    : '待文字证据分析；旧评分不参与推荐'
}
function collectionLabel(row: EvidenceCandidate) {
  const item = row.collection?.items.find((x) => x.source_item_id === row.source_product_id)
  if (item?.state === 'saved') return '已确认采集成功'
  if (row.collection)
    return item?.error || sourceStatus[row.collection.status] || row.collection.status
  return row.miaoshou_detail_id && row.sync_status === 'synced' ? '已有妙手采集记录' : '未采集'
}
async function addToBox(rows: EvidenceCandidate[]) {
  const ids = rows.filter((r) => !r.in_collect_box && r.review_status !== 'rejected').map((r) => r.id)
  if (!ids.length) {
    ElMessage.info('所选商品已在我的采集箱或已排除')
    return
  }
  await action(async () => {
    const r = await collectBox.add(ids)
    ElMessage.success(`已加入我的采集箱 ${r.added} 件${r.skipped ? `，${r.skipped} 件已存在` : ''}，可在「采集上架」中同步到妙手`)
    await loadCandidates()
  })
}
async function analyze() {
  await action(async () => {
    await sourcing.analyze(selection.value.map((r) => r.id))
    ElMessage.success('文字分析已提交')
    tab.value = 'tasks'
    await changeTab()
  })
}
async function showDetail(row: EvidenceCandidate) {
  detail.value = await evidenceApi.candidate(row.id)
  note.value = detail.value.operator_note || ''
  evaluationPage.value = 1
  await loadEvaluationHistory()
  detailDialog.value = true
}
async function loadEvaluationHistory() {
  if (!detail.value) return
  const r = await evidenceApi.evaluations(detail.value.id, evaluationPage.value)
  evaluationHistory.value = r.items
  evaluationTotal.value = r.total
}
async function decide(row: EvidenceCandidate) {
  await evidenceApi.operations(row.id, {
    review_status: row.review_status === 'rejected' ? 'pending' : 'rejected',
    input_version: row.version,
  })
  await loadCandidates()
}
async function saveNote() {
  if (detail.value) {
    await evidenceApi.operations(detail.value.id, { operator_note: note.value })
    ElMessage.success('备注已保存')
  }
}
function openEditor(row?: EvidenceCandidate) {
  editingId.value = row?.id || ''
  const data = blank()
  if (row)
    for (const k of Object.keys(data))
      (data as unknown as Record<string, unknown>)[k] = (row as unknown as Record<string, unknown>)[
        k
      ]
  Object.assign(form, data)
  editDialog.value = true
}
async function saveCandidate() {
  await action(async () => {
    const data = { ...form }
    for (const k of ['name', 'main_image', 'purchase_price', 'category', 'supplier'] as const)
      if (data[k] === '') (data as unknown as Record<string, unknown>)[k] = null
    if (editingId.value) await sourcing.edit(editingId.value, data)
    else await sourcing.create(data)
    editDialog.value = false
    await loadCandidates()
  })
}
async function loadTasks() {
  const [d, a, c, h] = await Promise.all([
    evidenceApi.tasks(discoveryPage.value),
    sourcing.tasks({ page: analysisPage.value, page_size: 20 }),
    miaoshou.jobs(collectionPage.value),
    sourcing.history({ page: historyPage.value }),
  ])
  discoveryJobs.value = d.items
  discoveryTotal.value = d.total
  analysisJobs.value = a.items
  analysisTotal.value = a.total
  collectionJobs.value = c.items
  collectionTotal.value = c.total
  history.value = h.items
  historyTotal.value = h.total
}
async function retryAnalysis(id: string) {
  await action(async () => {
    await sourcing.retry(id)
    await loadTasks()
  })
}
async function showCollection(id: string) {
  job.value = await miaoshou.job(id)
  jobDialog.value = true
}
async function reconcile() {
  await action(async () => {
    if (job.value) job.value = await miaoshou.reconcile(job.value.id)
  })
}
async function showDiscovery(id: string) {
  discoveryDetail.value = await evidenceApi.task(id)
  discoveryDialog.value = true
}
let timer: ReturnType<typeof setInterval> | undefined
onMounted(async () => {
  await Promise.all([loadReports(), loadCandidates(), loadTasks()])
  timer = setInterval(() => {
    if (tab.value === 'tasks' && !busy.value) void loadTasks().catch(() => {})
  }, 8000)
})
onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>
<style scoped>
.selection-center {
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
.section {
  margin-top: 16px;
}
.section-sm {
  margin-top: 12px;
}
.main-tabs :deep(.el-tabs__item) {
  font-size: 15px;
}
.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.card-title {
  font-weight: 600;
  font-size: 15px;
}
.next-bar {
  position: sticky;
  bottom: 0;
  z-index: 5;
  margin-top: 16px;
  padding: 12px 16px;
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 16px;
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-light);
  border-radius: 4px;
  box-shadow: 0 -2px 8px rgba(0, 0, 0, 0.04);
}
.inline {
  display: flex;
  gap: 8px;
  align-items: center;
  width: 100%;
}
.goal-form :deep(.el-input-number) {
  width: 100%;
}
.toolbar {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  align-items: center;
}
.tag-gap {
  margin-left: 6px;
}
.product {
  display: flex;
  gap: 12px;
  align-items: center;
}
.thumb {
  width: 80px;
  height: 80px;
  flex-shrink: 0;
}
p {
  line-height: 1.5;
  overflow-wrap: anywhere;
}
.images {
  display: flex;
  gap: 12px;
  overflow: auto;
}
.images .el-image {
  width: 150px;
  height: 150px;
  flex-shrink: 0;
}
pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  max-height: 400px;
  overflow: auto;
}
</style>
