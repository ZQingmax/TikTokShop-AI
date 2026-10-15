<template>
  <div class="page">
    <div class="heading">
      <div>
        <h2>1688 货源中心</h2>
        <p class="muted">通过本机 1688 CLI（你本人的 1688 登录会话）只读搜索真实货源；不自动采购、付款、联系卖家或上架。</p>
      </div>
      <div><el-button @click="$router.push('/sourcing')">选品中心</el-button><el-button @click="$router.push('/sourcing/review')">候选商品库</el-button></div>
    </div>

    <!-- CLI 状态 -->
    <el-card shadow="never" class="status-card" v-loading="statusLoading">
      <div class="status-row">
        <el-tag :type="stateType(status?.state)" size="large" effect="dark">{{ status?.label || '检测中…' }}</el-tag>
        <span v-if="status?.version" class="muted">CLI {{ status.version }}</span>
        <span v-if="status" class="muted">浏览器：{{ status.browser_ok === null ? '未知' : status.browser_ok ? '正常' : '异常' }}</span>
        <span v-if="status?.last_verified_at" class="muted">登录最近验证：{{ fmtTime(status.last_verified_at) }}</span>
        <span v-if="status?.last_query" class="muted">最近查询：{{ status.last_query.label }}（{{ fmtTime(status.last_query.at) }}）</span>
        <el-button size="small" :loading="statusLoading" @click="loadStatus(true)">重新检测</el-button>
      </div>
      <el-alert v-if="status && status.state !== 'logged_in'" class="section" :type="status.state === 'cli_not_installed' || status.state === 'browser_error' ? 'error' : 'warning'" :closable="false" show-icon>
        <template #title>{{ status.label }}</template>
        <div>{{ status.hint }}</div>
        <div v-if="status.state === 'not_logged_in' || status.state === 'login_expired'" class="cmd">
          请在运行后端的同一台电脑、同一用户的终端中执行：<code>1688 login</code>，用 1688 App 扫码。系统不会代你登录，也不会读取 Cookie。
        </div>
        <div v-if="status.daemon?.paused_until" class="muted">CLI 守护进程暂停至 {{ fmtTime(status.daemon.paused_until) }}；处理后可执行 <code>1688 daemon reload</code></div>
      </el-alert>
    </el-card>

    <el-tabs v-model="tab" class="section" @tab-change="onTab">
      <!-- 货源搜索 -->
      <el-tab-pane label="货源搜索" name="search">
        <el-card shadow="never">
          <div class="toolbar">
            <el-input v-model="form.keyword" class="kw" maxlength="50" clearable placeholder="输入中文关键词，如：露营灯" @keyup.enter="doSearch()">
              <template #prepend>关键词</template>
            </el-input>
            <el-button type="primary" :icon="Search" :loading="searching && mode === 'keyword'" :disabled="searching" @click="doSearch()">搜索</el-button>
            <el-upload :auto-upload="false" :show-file-list="false" accept=".jpg,.jpeg,.png,.webp" :on-change="onImage" :disabled="searching">
              <el-button :icon="Picture" :loading="searching && mode === 'image'" :disabled="searching">以图搜图</el-button>
            </el-upload>
          </div>
          <div class="toolbar filters">
            <span class="muted">采购价 ¥</span>
            <el-input-number v-model="form.price_min" :min="0" :max="1000000" :precision="2" :controls="false" placeholder="最低" class="num" />
            <span>–</span>
            <el-input-number v-model="form.price_max" :min="0" :max="1000000" :precision="2" :controls="false" placeholder="最高" class="num" />
            <el-select v-model="form.sort" class="sel">
              <el-option label="综合排序" value="relevance" /><el-option label="销量优先" value="best-selling" />
              <el-option label="价格从低到高" value="price-asc" /><el-option label="价格从高到低" value="price-desc" />
            </el-select>
            <el-select v-model="form.max" class="sel-sm"><el-option v-for="n in [10, 20]" :key="n" :label="`${n} 条`" :value="n" /></el-select>
            <el-checkbox v-model="form.factory_only">只看工厂</el-checkbox>
            <el-checkbox v-model="form.exclude_ads">过滤广告</el-checkbox>
            <span class="muted">加入候选库站点</span>
            <el-select v-model="market" class="sel-sm"><el-option v-for="m in markets" :key="m" :label="m" :value="m" /></el-select>
          </div>
        </el-card>

        <div class="section" v-loading="searching" element-loading-text="正在通过 1688 CLI 查询，首次可能需要 10–60 秒…">
          <el-alert v-if="searchError" type="error" :closable="false" show-icon :title="errTitle(searchError)">
            <div v-if="searchError.hint">{{ searchError.hint }}</div>
            <el-button size="small" class="retry" @click="retry">重试</el-button>
          </el-alert>
          <template v-else-if="result">
            <div class="result-head">
              <span>{{ mode === 'image' ? '以图搜图' : `“${result.keyword}”` }}：{{ result.items.length }} 条<span v-if="result.total_before_filter" class="muted">（筛选前 {{ result.total_before_filter }}）</span></span>
              <span class="muted">{{ result.cached ? '近期缓存结果' : '实时查询' }} · {{ fmtTime(result.fetched_at) }}</span>
            </div>
            <el-alert type="info" :closable="false" :title="result.notice" class="section-sm" />
            <el-empty v-if="!result.items.length" description="1688 没有返回符合条件的商品，可调整关键词或筛选条件" />
            <div v-else class="grid">
              <el-card v-for="item in result.items" :key="item.offer_id" shadow="hover" class="offer" :body-style="{ padding: '0' }">
                <div class="thumb" @click="openDetail(item.offer_id)">
                  <img v-if="item.main_image" :src="item.main_image" referrerpolicy="no-referrer" loading="lazy" alt="" />
                  <div v-else class="noimg">无图片</div>
                  <el-tag v-if="item.is_ad" class="ad" size="small" type="info">广告</el-tag>
                </div>
                <div class="offer-body">
                  <div class="title" :title="item.title || ''" @click="openDetail(item.offer_id)">{{ item.title || '（无标题）' }}</div>
                  <div class="price">{{ fmtPrice(item.price) }}</div>
                  <div class="meta">起批量：{{ item.min_order_quantity ?? '查看详情获取' }}</div>
                  <div class="meta">1688 成交：{{ item.sales.text ?? '数据源未提供' }}</div>
                  <div class="meta ellipsis" :title="item.supplier.name || ''">
                    {{ item.supplier.name || '供应商未提供' }}
                    <el-tag v-if="item.verified.factory" size="small" type="success">工厂</el-tag>
                    <el-tag v-if="item.verified.super_factory" size="small" type="warning">超级工厂</el-tag>
                  </div>
                  <div class="meta muted">{{ [item.location.province, item.location.city].filter(Boolean).join(' ') || '地区未提供' }}<span v-if="item.supplier.years"> · {{ item.supplier.years }} 年</span></div>
                  <div class="actions">
                    <el-button size="small" @click="openDetail(item.offer_id)">查看详情</el-button>
                    <el-button size="small" type="primary" :loading="saving === item.offer_id" @click="save(item.offer_id)">加入候选库</el-button>
                  </div>
                  <el-link class="supplier-link" type="primary" :underline="false" @click="openSupplier(item.offer_id)">供应商画像 ›</el-link>
                </div>
              </el-card>
            </div>
          </template>
          <el-empty v-else-if="!searching" description="输入关键词或上传商品图片开始搜索；默认每次最多 20 条，短时间内重复搜索使用缓存" />
        </div>
      </el-tab-pane>

      <!-- 供应商搜索 -->
      <el-tab-pane label="供应商搜索" name="suppliers">
        <el-card shadow="never">
          <div class="toolbar">
            <el-input v-model="supplierForm.keyword" class="kw" maxlength="50" clearable placeholder="如：露营灯" @keyup.enter="searchSuppliers()">
              <template #prepend>关键词</template>
            </el-input>
            <el-input v-model="supplierForm.province" class="sel" maxlength="20" clearable placeholder="省份（可选）" />
            <el-checkbox v-model="supplierForm.factory_only">只看工厂</el-checkbox>
            <el-button type="primary" :loading="supplierLoading" @click="searchSuppliers()">搜索供应商</el-button>
          </div>
          <p class="muted">“平台指标”由 1688 提供，原样展示；“CLI 参考分”是 1688-cli 的本地规则打分，不是平台数据。</p>
        </el-card>
        <div class="section" v-loading="supplierLoading">
          <el-alert v-if="supplierError" type="error" :closable="false" show-icon :title="errTitle(supplierError)">
            <div v-if="supplierError.hint">{{ supplierError.hint }}</div>
            <el-button size="small" class="retry" @click="searchSuppliers()">重试</el-button>
          </el-alert>
          <el-empty v-else-if="suppliers && !suppliers.length" description="没有符合条件的供应商" />
          <el-table v-else-if="suppliers" :data="suppliers" border>
            <el-table-column label="公司" min-width="200">
              <template #default="{ row }">
                <div class="strong">{{ row.company_name || '名称未提供' }}</div>
                <div class="muted">{{ [row.location.province, row.location.city].filter(Boolean).join(' ') || '地区未提供' }}</div>
                <div><el-tag v-if="row.factory.is_factory" size="small" type="success">工厂</el-tag> <el-tag v-if="row.factory.super_factory" size="small" type="warning">超级工厂</el-tag></div>
              </template>
            </el-table-column>
            <el-table-column label="经营年限" width="90"><template #default="{ row }">{{ row.service_years ?? '—' }}</template></el-table-column>
            <el-table-column label="平台指标" min-width="180">
              <template #default="{ row }">
                <div>综合服务分：{{ row.platform_metrics.composite_score ?? '—' }}</div>
                <div>旺旺响应率：{{ pct(row.platform_metrics.response_rate) }}</div>
                <div>回头率：{{ pct(row.platform_metrics.repeat_rate) }}</div>
              </template>
            </el-table-column>
            <el-table-column label="CLI 参考分（非平台）" width="130"><template #default="{ row }">{{ row.cli_score?.score ?? '—' }}</template></el-table-column>
            <el-table-column label="相关商品" min-width="220">
              <template #default="{ row }">
                <div class="previews">
                  <a v-for="o in row.offers_preview.slice(0, 4)" :key="o.offer_id || o.title" :title="o.title" @click.prevent="o.offer_id && openDetail(o.offer_id)">
                    <img v-if="o.image" :src="o.image" referrerpolicy="no-referrer" loading="lazy" alt="" /><span v-else class="noimg-sm">无图</span>
                  </a>
                  <span v-if="!row.offers_preview.length" class="muted">数据源未提供</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="150">
              <template #default="{ row }">
                <el-button v-if="row.member_id" size="small" link type="primary" @click="openSupplier(row.member_id)">查看画像</el-button>
                <el-link v-if="row.shop_url" :href="row.shop_url" target="_blank" type="primary">1688 店铺</el-link>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-else description="按关键词搜索 1688 企业（公司搜索）" />
        </div>
      </el-tab-pane>

      <el-tab-pane label="我的候选商品" name="candidates">
        <el-empty description="候选商品已统一到选品中心"><el-button type="primary" @click="$router.push('/sourcing?tab=candidates&source=1688_cli')">打开候选商品库</el-button></el-empty>
      </el-tab-pane>
    </el-tabs>

    <!-- 商品详情 -->
    <el-drawer v-model="detailOpen" size="720px" :title="detail?.title || '商品详情'" destroy-on-close>
      <div v-loading="detailLoading" class="drawer-body">
        <el-alert v-if="detailError" type="error" :closable="false" show-icon :title="errTitle(detailError)">
          <div v-if="detailError.hint">{{ detailError.hint }}</div>
          <el-button size="small" class="retry" @click="openDetail(detailId!, true)">重试</el-button>
        </el-alert>
        <template v-if="detail">
          <el-carousel v-if="detail.images.length" height="320px" indicator-position="outside" :autoplay="false">
            <el-carousel-item v-for="src in detail.images" :key="src"><img class="slide" :src="src" referrerpolicy="no-referrer" alt="" /></el-carousel-item>
          </el-carousel>
          <el-empty v-else description="数据源未提供图片" />
          <el-descriptions :column="2" border class="section">
            <el-descriptions-item label="采购价（CNY）">{{ fmtPrice(detail.price) }}</el-descriptions-item>
            <el-descriptions-item label="起批量">{{ detail.min_order_quantity ?? '未提供' }} {{ detail.unit || '' }}</el-descriptions-item>
            <el-descriptions-item label="混批">{{ detail.mix_order_quantity ?? '未提供' }}</el-descriptions-item>
            <el-descriptions-item label="1688 成交">{{ detail.sold_count ?? '未提供' }}</el-descriptions-item>
            <el-descriptions-item label="发货地">{{ detail.shipping.send_area || [detail.shipping.province, detail.shipping.city].filter(Boolean).join(' ') || '未提供' }}</el-descriptions-item>
            <el-descriptions-item label="单件重量">{{ detail.shipping.unit_weight ?? '未提供' }}</el-descriptions-item>
            <el-descriptions-item label="供应商" :span="2">
              {{ detail.supplier.name || '未提供' }}
              <el-button size="small" link type="primary" @click="openSupplier(detail.supplier.member_id || detail.offer_id)">供应商画像</el-button>
            </el-descriptions-item>
            <el-descriptions-item label="来源" :span="2"><el-link :href="detail.product_url" target="_blank" type="primary">{{ detail.product_url }}</el-link></el-descriptions-item>
          </el-descriptions>

          <h4>阶梯采购价</h4>
          <el-table v-if="detail.price_tiers.length" :data="detail.price_tiers" size="small" border>
            <el-table-column label="起订数量" prop="min_qty" /><el-table-column label="单价（CNY）"><template #default="{ row }">{{ row.price ?? '—' }}</template></el-table-column>
          </el-table>
          <p v-else class="muted">数据源未提供阶梯价</p>

          <h4>SKU 规格（{{ detail.skus.length }}）</h4>
          <el-table v-if="detail.skus.length" :data="detail.skus" size="small" border max-height="300">
            <el-table-column label="规格" prop="specs" min-width="200" show-overflow-tooltip />
            <el-table-column label="价格" width="90"><template #default="{ row }">{{ row.price ?? '—' }}</template></el-table-column>
            <el-table-column label="库存" width="90"><template #default="{ row }">{{ row.stock ?? '—' }}</template></el-table-column>
            <el-table-column label="已售" width="80"><template #default="{ row }">{{ row.sale_count ?? '—' }}</template></el-table-column>
          </el-table>
          <p v-else class="muted">数据源未提供 SKU</p>

          <h4>商品属性</h4>
          <el-descriptions v-if="detail.attributes.length" :column="2" border size="small">
            <el-descriptions-item v-for="(a, i) in detail.attributes" :key="i" :label="a.name || '—'">{{ a.value || '—' }}</el-descriptions-item>
          </el-descriptions>
          <p v-else class="muted">数据源未提供属性</p>

          <h4>包装信息</h4>
          <el-table v-if="detail.package_info.length" :data="detail.package_info" size="small" border>
            <el-table-column label="规格" prop="spec" min-width="140" />
            <el-table-column label="长×宽×高"><template #default="{ row }">{{ [row.length, row.width, row.height].map(v => v ?? '—').join(' × ') }}</template></el-table-column>
            <el-table-column label="重量" width="90"><template #default="{ row }">{{ row.weight ?? '—' }}</template></el-table-column>
          </el-table>
          <p v-else class="muted">数据源未提供包装信息</p>
          <p class="muted section">采集时间：{{ fmtTime(detail.fetched_at) }}{{ detail.cached ? '（近期缓存）' : '' }}</p>
        </template>
      </div>
      <template #footer>
        <el-select v-model="market" class="sel-sm"><el-option v-for="m in markets" :key="m" :label="m" :value="m" /></el-select>
        <el-button type="primary" :disabled="!detailId" :loading="saving === detailId" @click="detailId && save(detailId)">加入候选库</el-button>
      </template>
    </el-drawer>

    <!-- 供应商画像 -->
    <el-drawer v-model="supplierOpen" size="560px" :title="supplier?.company_name || '供应商画像'" destroy-on-close>
      <div v-loading="supplierDetailLoading" class="drawer-body">
        <el-alert v-if="supplierDetailError" type="error" :closable="false" show-icon :title="errTitle(supplierDetailError)">
          <div v-if="supplierDetailError.hint">{{ supplierDetailError.hint }}</div>
          <el-button size="small" class="retry" @click="openSupplier(supplierTarget!)">重试</el-button>
        </el-alert>
        <template v-if="supplier">
          <el-descriptions :column="1" border>
            <el-descriptions-item label="公司名称">{{ supplier.company_name || '未提供' }}</el-descriptions-item>
            <el-descriptions-item label="身份">{{ supplier.identity || '未提供' }}</el-descriptions-item>
            <el-descriptions-item label="所在地">{{ (supplier.factory.location as string) || (supplier.factory.address as string) || '未提供' }}</el-descriptions-item>
            <el-descriptions-item label="经营年限">{{ supplier.factory.tp_years ?? '未提供' }}</el-descriptions-item>
            <el-descriptions-item label="工厂标识">
              <el-tag v-if="supplier.factory.is_factory" size="small" type="success">工厂</el-tag>
              <el-tag v-if="supplier.factory.super_factory" size="small" type="warning">超级工厂</el-tag>
              <span v-if="!supplier.factory.is_factory && !supplier.factory.super_factory" class="muted">平台未标注</span>
            </el-descriptions-item>
            <el-descriptions-item label="成立时间">{{ supplier.factory.established_at || '未提供' }}</el-descriptions-item>
            <el-descriptions-item label="员工规模">{{ supplier.factory.employee_scale || '未提供' }}</el-descriptions-item>
            <el-descriptions-item label="在售商品数">{{ supplier.offers_available_count ?? '未提供' }}</el-descriptions-item>
            <el-descriptions-item label="1688 店铺"><el-link v-if="supplier.shop_url" :href="supplier.shop_url" target="_blank" type="primary">打开店铺</el-link><span v-else class="muted">未提供</span></el-descriptions-item>
          </el-descriptions>
          <h4>平台提供的指标</h4>
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item label="回头率">{{ pct(supplier.platform_metrics.retention_rate) }}</el-descriptions-item>
            <el-descriptions-item label="企业标签">{{ supplier.platform_metrics.company_label || '未提供' }}</el-descriptions-item>
            <el-descriptions-item v-for="s in supplier.platform_metrics.service_scores" :key="s.key || s.label || ''" :label="s.label || s.key || '服务分'">{{ s.score ?? '—' }}</el-descriptions-item>
          </el-descriptions>
          <p v-if="!supplier.platform_metrics.service_scores.length && supplier.platform_metrics.retention_rate == null" class="muted">平台未提供复购、响应等指标；本系统不展示推算或伪造的评价。</p>
          <div v-if="supplier.platform_metrics.shop_tags.length || supplier.factory.tags.length" class="section">
            <el-tag v-for="t in [...supplier.platform_metrics.shop_tags, ...supplier.factory.tags]" :key="t" size="small" class="tag">{{ t }}</el-tag>
          </div>
          <el-alert v-for="w in supplier.warnings" :key="w" type="warning" :closable="false" :title="w" class="section-sm" />
          <p class="muted section">采集时间：{{ fmtTime(supplier.fetched_at) }}</p>
        </template>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, type UploadFile } from 'element-plus'
import { Picture, Search, Star, StarFilled } from '@element-plus/icons-vue'
import { alibaba1688, cliError, operationsLabels, type CliCandidateFields, type CliError, type CliStatus, type OfferDetail,
  type Price, type SearchResult, type SupplierDetail, type SupplierItem } from '@/api/alibaba1688'
import { markets, type Candidate, type Market } from '@/api/sourcing'

type Row = Candidate & CliCandidateFields

const tab = ref('search')
const market = ref<Market>('MY')
const status = ref<CliStatus | null>(null)
const statusLoading = ref(false)

const form = reactive({ keyword: '', price_min: undefined as number | undefined, price_max: undefined as number | undefined,
  sort: 'relevance', max: 20, factory_only: false, exclude_ads: false })
const mode = ref<'keyword' | 'image'>('keyword')
const lastImage = ref<File | null>(null)
const searching = ref(false)
const result = ref<SearchResult | null>(null)
const searchError = ref<CliError | null>(null)
const saving = ref<string | null>(null)

const detailOpen = ref(false)
const detailId = ref<string | null>(null)
const detail = ref<OfferDetail | null>(null)
const detailLoading = ref(false)
const detailError = ref<CliError | null>(null)

const supplierOpen = ref(false)
const supplierTarget = ref<string | null>(null)
const supplier = ref<SupplierDetail | null>(null)
const supplierDetailLoading = ref(false)
const supplierDetailError = ref<CliError | null>(null)

const supplierForm = reactive({ keyword: '', province: '', factory_only: false })
const suppliers = ref<SupplierItem[] | null>(null)
const supplierLoading = ref(false)
const supplierError = ref<CliError | null>(null)

const candFilter = reactive({ sourcing_status: '' as string, favorite: undefined as boolean | undefined, keyword: '' })
const cands = reactive({ items: [] as Row[], total: 0, page: 1 })
const candLoading = ref(false)
const notes = reactive<Record<string, string>>({})

function toError(e: unknown): CliError {
  return cliError(e) || { state: 'request_failed', code: 'REQUEST_FAILED', label: '请求失败', message: (e as Error)?.message || '网络错误', hint: null, retryable: true }
}
function errTitle(e: CliError) { return e.message.startsWith(e.label) ? e.message : `${e.label}：${e.message}` }
function stateType(state?: string) {
  if (state === 'logged_in') return 'success'
  if (!state) return 'info'
  return ['cli_not_installed', 'browser_error'].includes(state) ? 'danger' : 'warning'
}
function fmtTime(v?: string | null) { return v ? new Date(v).toLocaleString('zh-CN', { hour12: false }) : '—' }
function num(v: string | number) { return Number(v).toString() }
function pct(v: unknown) {
  if (v === null || v === undefined || v === '') return '平台未提供'
  const n = Number(v)
  return Number.isFinite(n) ? `${(n <= 1 ? n * 100 : n).toFixed(1)}%` : String(v)
}
function fmtPrice(p: Price) {
  if (p.min == null && p.max == null) return p.text || '价格未提供'
  if (p.min != null && p.max != null && p.min !== p.max) return `¥${p.min}–${p.max}`
  return `¥${p.min ?? p.max}`
}

async function loadStatus(refresh = false) {
  statusLoading.value = true
  try { status.value = await alibaba1688.status(refresh) } catch { /* 全局提示已显示 */ } finally { statusLoading.value = false }
}

async function doSearch(file?: File) {
  if (!file && !form.keyword.trim()) { ElMessage.warning('请输入关键词'); return }
  if (form.price_min != null && form.price_max != null && form.price_min > form.price_max) { ElMessage.warning('最低价不能高于最高价'); return }
  mode.value = file ? 'image' : 'keyword'
  searching.value = true
  searchError.value = null
  try {
    result.value = file
      ? await alibaba1688.imageSearch(file, form.max)
      : await alibaba1688.search({ keyword: form.keyword.trim(), max: form.max, sort: form.sort, price_min: form.price_min ?? null,
          price_max: form.price_max ?? null, factory_only: form.factory_only, exclude_ads: form.exclude_ads })
  } catch (e) {
    result.value = null
    searchError.value = toError(e)
  } finally {
    searching.value = false
    loadStatus()
  }
}
function retry() { doSearch(mode.value === 'image' && lastImage.value ? lastImage.value : undefined) }

function onImage(upload: UploadFile) {
  const file = upload.raw
  if (!file) return
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) { ElMessage.error('仅支持 JPG、PNG、WebP 图片'); return }
  const limit = status.value?.limits.image_max_bytes || 5 * 1024 * 1024
  if (file.size > limit) { ElMessage.error(`图片不能超过 ${Math.floor(limit / 1024 / 1024)} MB`); return }
  lastImage.value = file
  doSearch(file)
}

async function openDetail(offerId: string, refresh = false) {
  detailOpen.value = true
  detailId.value = offerId
  detail.value = null
  detailError.value = null
  detailLoading.value = true
  try { detail.value = await alibaba1688.product(offerId, refresh) } catch (e) { detailError.value = toError(e) } finally { detailLoading.value = false }
}

async function openSupplier(target: string) {
  supplierOpen.value = true
  supplierTarget.value = target
  supplier.value = null
  supplierDetailError.value = null
  supplierDetailLoading.value = true
  try { supplier.value = await alibaba1688.supplier(target) } catch (e) { supplierDetailError.value = toError(e) } finally { supplierDetailLoading.value = false }
}

async function save(offerId: string) {
  saving.value = offerId
  try {
    const r = await alibaba1688.save(offerId, market.value, true)
    if (r.status === 'duplicate') ElMessage.info('该商品已在候选库中，已刷新 1688 平台数据（不覆盖你的备注和状态）')
    else ElMessage.success(r.detail_fetched ? '已加入候选库（含详情）' : '已加入候选库（详情获取失败，仅保存搜索列表数据）')
    if (r.detail_error) ElMessage.warning(r.detail_error)
    if (tab.value === 'candidates') loadCandidates(cands.page)
  } catch { /* 全局提示已显示 */ } finally { saving.value = null }
}

async function searchSuppliers() {
  if (!supplierForm.keyword.trim()) { ElMessage.warning('请输入关键词'); return }
  supplierLoading.value = true
  supplierError.value = null
  try {
    suppliers.value = (await alibaba1688.supplierSearch({ keyword: supplierForm.keyword.trim(), max: 20, factory_only: supplierForm.factory_only,
      province: supplierForm.province.trim() || null })).items
  } catch (e) { suppliers.value = null; supplierError.value = toError(e) } finally { supplierLoading.value = false }
}

async function loadCandidates(page = 1) {
  candLoading.value = true
  try {
    const params: Record<string, unknown> = { page, page_size: 20 }
    if (candFilter.sourcing_status) params.sourcing_status = candFilter.sourcing_status
    if (candFilter.favorite !== undefined && candFilter.favorite !== null && (candFilter.favorite as unknown) !== '') params.favorite = candFilter.favorite
    if (candFilter.keyword.trim()) params.keyword = candFilter.keyword.trim()
    const data = await alibaba1688.candidates(params)
    cands.items = data.items
    cands.total = data.total
    cands.page = data.page
    for (const row of data.items) notes[row.id] = row.operator_note || ''
  } catch { /* 全局提示已显示 */ } finally { candLoading.value = false }
}

async function updateOps(row: Row, data: { favorite?: boolean; operator_note?: string; sourcing_status?: string }) {
  try {
    const updated = await alibaba1688.operations(row.id, data)
    Object.assign(row, { favorite: updated.favorite, operator_note: updated.operator_note, sourcing_status: updated.sourcing_status })
    ElMessage.success('已保存')
  } catch { notes[row.id] = row.operator_note || '' }
}

function onTab(name: string | number) { if (name === 'candidates') loadCandidates(cands.page) }

onMounted(() => loadStatus())
</script>

<style scoped>
.page { padding: 4px; }
.heading { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; flex-wrap: wrap; }
.heading h2 { margin: 0 0 6px; }
.muted { color: var(--el-text-color-secondary); font-size: 13px; }
.section { margin-top: 16px; }
.section-sm { margin: 8px 0; }
.status-card { margin-top: 12px; }
.status-row { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.cmd { margin-top: 6px; }
code { background: var(--app-soft-bg); padding: 1px 6px; border-radius: 3px; }
.toolbar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.filters { margin-top: 12px; }
.kw { width: 360px; max-width: 100%; }
.num { width: 110px; }
.sel { width: 150px; }
.sel-sm { width: 90px; }
.retry { margin-top: 8px; }
.result-head { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 8px; margin-bottom: 4px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 14px; margin-top: 12px; }
.offer .thumb { position: relative; height: 200px; background: var(--app-soft-bg); cursor: pointer; overflow: hidden; }
.offer .thumb img { width: 100%; height: 100%; object-fit: cover; }
.offer .ad { position: absolute; top: 8px; left: 8px; }
.noimg { display: flex; align-items: center; justify-content: center; height: 100%; color: var(--el-text-color-placeholder); }
.offer-body { padding: 10px 12px 12px; }
.title { font-size: 14px; line-height: 20px; height: 40px; overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; cursor: pointer; }
.title:hover { color: var(--app-brand); }
.price { color: #f56c6c; font-size: 18px; font-weight: 600; margin: 6px 0 4px; }
.meta { font-size: 12px; color: var(--el-text-color-regular); line-height: 20px; }
.ellipsis { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.actions { display: flex; gap: 6px; margin-top: 8px; }
.supplier-link { margin-top: 6px; font-size: 12px; }
.strong { font-weight: 600; }
.previews { display: flex; gap: 6px; }
.previews img, .noimg-sm { width: 48px; height: 48px; object-fit: cover; border-radius: 4px; cursor: pointer; background: var(--app-soft-bg); display: inline-flex; align-items: center; justify-content: center; font-size: 12px; color: var(--el-text-color-placeholder); }
.cand { display: flex; gap: 10px; align-items: flex-start; }
.cand img { width: 64px; height: 64px; object-fit: cover; border-radius: 4px; flex: none; }
.drawer-body { min-height: 200px; }
.slide { width: 100%; height: 100%; object-fit: contain; background: var(--app-soft-bg); }
.tag { margin: 0 6px 6px 0; }
h4 { margin: 18px 0 8px; }
</style>
