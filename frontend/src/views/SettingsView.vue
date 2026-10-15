<template>
  <div class="settings-container">
    <div class="page-header">
      <h2 class="page-title">系统设置</h2>
    </div>

    <el-card shadow="never">
      <el-tabs v-model="tab" @tab-change="onTab">
        <!-- 修改密码 -->
        <el-tab-pane label="修改密码" name="password">
          <el-form ref="passwordFormRef" :model="passwordForm" :rules="passwordRules" label-width="110px" class="password-form" @submit.prevent>
            <el-form-item label="当前密码" prop="current">
              <el-input v-model="passwordForm.current" type="password" show-password autocomplete="current-password" />
            </el-form-item>
            <el-form-item label="新密码" prop="next">
              <el-input v-model="passwordForm.next" type="password" show-password autocomplete="new-password" placeholder="至少 8 位" />
            </el-form-item>
            <el-form-item label="确认新密码" prop="confirm">
              <el-input v-model="passwordForm.confirm" type="password" show-password autocomplete="new-password" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="passwordSaving" @click="changePassword">修改密码</el-button>
            </el-form-item>
          </el-form>
          <p class="hint">修改成功后，所有设备上的登录（包括“记住我”）都会失效，需要用新密码重新登录。</p>
        </el-tab-pane>

        <!-- 角色 -->
        <el-tab-pane label="系统角色" name="roles">
          <div v-loading="rolesLoading">
            <p class="hint">权限说明与后端接口的实际校验一致。当前账号角色：<el-tag size="small">{{ roleLabel(currentRole) }}</el-tag></p>
            <el-row :gutter="16">
              <el-col v-for="role in roles" :key="role.name" :xs="24" :sm="12" :lg="6" class="role-col">
                <el-card shadow="hover" :class="['role-card', { current: role.name === currentRole }]">
                  <template #header>
                    <div class="role-head">
                      <span class="role-name">{{ role.display_name }}</span>
                      <span class="muted">{{ role.name }} · {{ role.user_count }} 人</span>
                    </div>
                  </template>
                  <p class="role-summary">{{ role.summary }}</p>
                  <div v-if="role.permissions.length" class="role-list">
                    <div class="list-title">可以</div>
                    <ul><li v-for="item in role.permissions" :key="item">{{ item }}</li></ul>
                  </div>
                  <div v-if="role.restrictions.length" class="role-list">
                    <div class="list-title">限制</div>
                    <ul><li v-for="item in role.restrictions" :key="item">{{ item }}</li></ul>
                  </div>
                </el-card>
              </el-col>
            </el-row>

            <template v-if="canManage">
              <h3 class="section-title">用户角色</h3>
              <el-table :data="users" stripe v-loading="usersLoading">
                <el-table-column prop="username" label="用户名" min-width="180" />
                <el-table-column prop="nickname" label="昵称" min-width="120" />
                <el-table-column label="状态" width="90">
                  <template #default="{ row }">
                    <el-tag :type="row.is_active ? 'success' : 'info'" size="small">{{ row.is_active ? '启用' : '停用' }}</el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="角色" width="200">
                  <template #default="{ row }">
                    <el-select
                      :model-value="row.role"
                      size="small"
                      :disabled="row.is_self || roleSaving === row.id"
                      @change="(value: string) => changeRole(row, value)"
                    >
                      <el-option v-for="role in roles" :key="role.name" :label="role.display_name" :value="role.name" />
                    </el-select>
                  </template>
                </el-table-column>
                <el-table-column label="说明" min-width="160">
                  <template #default="{ row }"><span class="muted">{{ row.is_self ? '不能修改自己的角色' : '' }}</span></template>
                </el-table-column>
              </el-table>
            </template>
            <p v-else class="hint">只有管理员可以查看用户列表和修改角色。</p>
          </div>
        </el-tab-pane>

        <!-- 模型设置 -->
        <el-tab-pane label="模型设置" name="models">
          <div v-loading="modelsLoading">
            <el-alert type="info" :closable="false" show-icon class="block">
              <template #title>
                为各 AI 场景选择阿里百炼模型。未选择时使用服务器配置的默认模型；新选择只影响之后提交的任务。
                候选模型名称和价格核对自百炼官方文档（2026-10-15，华北2 北京地域刊例价），实际以百炼账单为准。
                {{ modelsEditable ? '' : '只有管理员可以修改。' }}
              </template>
            </el-alert>
            <el-card v-for="scenario in scenarios" :key="scenario.key" shadow="never" class="scenario-card">
              <template #header>
                <div class="scenario-head">
                  <div>
                    <span class="scenario-name">{{ scenario.label }}</span>
                    <span class="muted scenario-used">{{ scenario.used_in }}</span>
                  </div>
                  <div class="scenario-current">
                    当前使用：<el-tag size="small" type="success">{{ scenario.effective_model }}</el-tag>
                    <el-tag v-if="!scenario.selected_model" size="small" type="info">默认</el-tag>
                    <span v-else class="muted">由 {{ scenario.updated_by || '未知' }} 于 {{ formatTime(scenario.updated_at) }} 设置</span>
                  </div>
                </div>
              </template>
              <el-radio-group v-model="modelDraft[scenario.key]" class="candidate-list" :disabled="!modelsEditable">
                <el-radio v-for="candidate in scenario.candidates" :key="candidate.id" :value="candidate.id" class="candidate" border>
                  <div class="candidate-body">
                    <div class="candidate-title">
                      <span class="candidate-id">{{ candidate.id }}</span>
                      <el-tag size="small" effect="plain">{{ candidate.tier }}</el-tag>
                      <el-tag v-if="candidate.id === scenario.default_model" size="small" type="info" effect="plain">默认</el-tag>
                    </div>
                    <div class="candidate-note">{{ candidate.note }}</div>
                    <div class="candidate-price">{{ candidate.price }}</div>
                  </div>
                </el-radio>
              </el-radio-group>
              <p v-if="!scenario.candidates.some((c) => c.id === scenario.default_model)" class="hint">
                服务器默认模型 {{ scenario.default_model }} 不在候选列表中，恢复默认后仍使用它。
              </p>
              <div v-if="modelsEditable" class="scenario-actions">
                <el-button
                  type="primary"
                  size="small"
                  :disabled="modelDraft[scenario.key] === scenario.effective_model"
                  :loading="modelSaving === scenario.key"
                  @click="saveModel(scenario, modelDraft[scenario.key])"
                >保存</el-button>
                <el-button size="small" :disabled="!scenario.selected_model" :loading="modelSaving === scenario.key" @click="saveModel(scenario, null)">
                  恢复默认（{{ scenario.default_model }}）
                </el-button>
              </div>
            </el-card>
            <p class="hint">
              非默认的图片生成模型尚未在本系统实测调用；若百炼拒绝该模型，任务会失败并显示原因，可切回默认。
              选品中的 DeepSeek 文本分析使用独立的 DeepSeek 配置，不在此处切换，但其用量会记录在「模型用量」中。
            </p>
          </div>
        </el-tab-pane>

        <!-- 用量 -->
        <el-tab-pane label="模型用量" name="usage">
          <div class="usage-toolbar">
            <el-date-picker
              v-model="usageRange"
              type="daterange"
              value-format="YYYY-MM-DD"
              range-separator="至"
              start-placeholder="开始日期"
              end-placeholder="结束日期"
              :clearable="false"
              @change="loadUsage"
            />
            <el-radio-group v-model="usageGroup">
              <el-radio-button value="scenario">按场景</el-radio-button>
              <el-radio-button value="model">按模型</el-radio-button>
              <el-radio-button value="date">按日期</el-radio-button>
            </el-radio-group>
            <el-button :loading="usageLoading" @click="loadUsage">刷新</el-button>
          </div>
          <p class="hint">
            数字全部来自百炼 / DeepSeek 响应中的 usage 字段，不做估算。文本模型按输入 / 输出 tokens 计量，图片模型按张数计量。
            “—”表示该组调用没有返回这一项；“未返回用量”为响应中没有 usage 的调用次数（这些调用不计入合计）。
            日期按北京时间统计。
          </p>
          <div v-loading="usageLoading">
            <el-row :gutter="16" class="usage-cards">
              <el-col v-for="card in usageCards" :key="card.title" :xs="12" :sm="6">
                <el-card shadow="hover">
                  <div class="summary-title">{{ card.title }}</div>
                  <div class="summary-value">{{ card.value }}</div>
                  <div class="summary-note">{{ card.note }}</div>
                </el-card>
              </el-col>
            </el-row>

            <el-table :data="usageRows" stripe class="block">
              <template #empty><el-empty description="该时间范围内没有模型调用记录" :image-size="60" /></template>
              <el-table-column v-if="usageGroup === 'scenario'" label="场景" min-width="200">
                <template #default="{ row }">{{ row.label }}</template>
              </el-table-column>
              <el-table-column v-if="usageGroup === 'model'" label="模型" min-width="200">
                <template #default="{ row }">{{ row.model }} <span class="muted">· {{ providerLabel(row.provider) }}</span></template>
              </el-table-column>
              <el-table-column v-if="usageGroup === 'date'" prop="day" label="日期" min-width="120" />
              <el-table-column prop="calls" label="调用次数" width="100" align="right" />
              <el-table-column label="输入 tokens" width="130" align="right">
                <template #default="{ row }">{{ num(row.input_tokens) }}</template>
              </el-table-column>
              <el-table-column label="输出 tokens" width="130" align="right">
                <template #default="{ row }">{{ num(row.output_tokens) }}</template>
              </el-table-column>
              <el-table-column label="合计 tokens" width="130" align="right">
                <template #default="{ row }">{{ num(row.total_tokens) }}</template>
              </el-table-column>
              <el-table-column label="输入图片" width="100" align="right">
                <template #default="{ row }">{{ num(row.input_images) }}</template>
              </el-table-column>
              <el-table-column label="生成图片" width="100" align="right">
                <template #default="{ row }">{{ num(row.output_images) }}</template>
              </el-table-column>
              <el-table-column label="未返回用量" width="110" align="right">
                <template #default="{ row }">
                  <el-tag v-if="row.missing_usage" type="warning" size="small">{{ row.missing_usage }} 次</el-tag>
                  <span v-else class="muted">0</span>
                </template>
              </el-table-column>
            </el-table>

            <h3 class="section-title">最近调用（最多 50 条）</h3>
            <el-table :data="usage?.recent || []" stripe size="small">
              <template #empty><el-empty description="暂无调用记录" :image-size="60" /></template>
              <el-table-column label="时间" width="170">
                <template #default="{ row }">{{ formatTime(row.called_at) }}</template>
              </el-table-column>
              <el-table-column prop="label" label="场景" min-width="170" />
              <el-table-column label="模型" min-width="150">
                <template #default="{ row }">{{ row.model }}</template>
              </el-table-column>
              <el-table-column label="结果" width="90">
                <template #default="{ row }">
                  <el-tag :type="row.status === 'succeeded' ? 'success' : 'warning'" size="small">
                    {{ row.status === 'succeeded' ? '已采用' : '输出被拒' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="用量" min-width="220">
                <template #default="{ row }">
                  <el-tag v-if="!row.has_usage" type="info" size="small">未返回用量</el-tag>
                  <span v-else>{{ usageText(row) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="用户" width="120">
                <template #default="{ row }">{{ row.user || '—' }}</template>
              </el-table-column>
            </el-table>
          </div>
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { system, type ModelScenario, type RoleInfo, type SystemUser, type UsageGroup, type UsageRecord, type UsageSummary } from '@/api/system'
import { useUserStore } from '@/stores/user'

const TABS = ['password', 'roles', 'models', 'usage']
const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const tab = ref(TABS.includes(route.query.tab as string) ? (route.query.tab as string) : 'password')
const loaded = new Set<string>()

function formatTime(value: string | null) {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—'
}
const num = (value: number | null | undefined) => (value === null || value === undefined ? '—' : value.toLocaleString('zh-CN'))
const providerLabel = (value?: string) => ({ bailian: '阿里百炼', deepseek: 'DeepSeek' } as Record<string, string>)[value || ''] || value || ''

function onTab(name: string | number) {
  router.replace({ query: { ...route.query, tab: String(name) } })
  void load(String(name))
}

async function load(name: string) {
  if (loaded.has(name)) return
  loaded.add(name)
  if (name === 'roles') await loadRoles()
  else if (name === 'models') await loadModels()
  else if (name === 'usage') await loadUsage()
}

// ---------- 修改密码 ----------
const passwordFormRef = ref<FormInstance>()
const passwordForm = reactive({ current: '', next: '', confirm: '' })
const passwordSaving = ref(false)
const passwordRules: FormRules = {
  current: [{ required: true, message: '请输入当前密码', trigger: 'blur' }],
  next: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 8, max: 72, message: '新密码长度为 8–72 位', trigger: 'blur' },
    {
      validator: (_rule, value, callback) =>
        value && value === passwordForm.current ? callback(new Error('新密码不能与当前密码相同')) : callback(),
      trigger: 'blur',
    },
  ],
  confirm: [
    { required: true, message: '请再次输入新密码', trigger: 'blur' },
    {
      validator: (_rule, value, callback) => (value !== passwordForm.next ? callback(new Error('两次输入的新密码不一致')) : callback()),
      trigger: 'blur',
    },
  ],
}

async function changePassword() {
  if (!(await passwordFormRef.value?.validate().catch(() => false))) return
  passwordSaving.value = true
  try {
    await system.changePassword(passwordForm.current, passwordForm.next)
    ElMessage.success('密码已修改，请用新密码重新登录')
    await userStore.logout()
  } catch {
    // 错误提示（如“当前密码不正确”）由请求拦截器显示
  } finally {
    passwordSaving.value = false
  }
}

// ---------- 角色 ----------
const roles = ref<RoleInfo[]>([])
const currentRole = ref('')
const canManage = ref(false)
const users = ref<SystemUser[]>([])
const rolesLoading = ref(false)
const usersLoading = ref(false)
const roleSaving = ref('')
const roleLabel = (name: string) => roles.value.find((r) => r.name === name)?.display_name || name

async function loadRoles() {
  rolesLoading.value = true
  try {
    const data = await system.roles()
    roles.value = data.roles
    currentRole.value = data.current_role
    canManage.value = data.can_manage
    if (data.can_manage) await loadUsers()
  } finally {
    rolesLoading.value = false
  }
}

async function loadUsers() {
  usersLoading.value = true
  try {
    users.value = await system.users()
  } finally {
    usersLoading.value = false
  }
}

async function changeRole(user: SystemUser, role: string) {
  if (role === user.role) return
  try {
    await ElMessageBox.confirm(
      `将 ${user.nickname || user.username} 的角色从「${roleLabel(user.role)}」改为「${roleLabel(role)}」？对方下一次操作即按新角色校验权限。`,
      '修改角色',
      { type: 'warning', confirmButtonText: '确定修改', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  roleSaving.value = user.id
  try {
    const updated = await system.setRole(user.id, role)
    Object.assign(user, updated, { is_self: user.is_self })
    ElMessage.success('角色已修改')
    const data = await system.roles()
    roles.value = data.roles
  } catch {
    // 拦截器已提示
  } finally {
    roleSaving.value = ''
  }
}

// ---------- 模型设置 ----------
const scenarios = ref<ModelScenario[]>([])
const modelsEditable = ref(false)
const modelsLoading = ref(false)
const modelSaving = ref('')
const modelDraft = reactive<Record<string, string>>({})

async function loadModels() {
  modelsLoading.value = true
  try {
    const data = await system.models()
    scenarios.value = data.scenarios
    modelsEditable.value = data.can_edit
    for (const s of data.scenarios) modelDraft[s.key] = s.effective_model
  } finally {
    modelsLoading.value = false
  }
}

async function saveModel(scenario: ModelScenario, model: string | null) {
  modelSaving.value = scenario.key
  try {
    const updated = await system.setModel(scenario.key, model)
    Object.assign(scenario, updated)
    modelDraft[scenario.key] = updated.effective_model
    ElMessage.success(`「${scenario.label}」之后的任务将使用 ${updated.effective_model}`)
  } catch {
    modelDraft[scenario.key] = scenario.effective_model
  } finally {
    modelSaving.value = ''
  }
}

// ---------- 用量 ----------
function dayString(date: Date) {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}
const today = new Date()
const usageRange = ref<[string, string]>([dayString(new Date(today.getTime() - 29 * 86400000)), dayString(today)])
const usageGroup = ref<'scenario' | 'model' | 'date'>('scenario')
const usage = ref<UsageSummary>()
const usageLoading = ref(false)

async function loadUsage() {
  usageLoading.value = true
  try {
    usage.value = await system.usage(usageRange.value[0], usageRange.value[1])
  } finally {
    usageLoading.value = false
  }
}

const usageRows = computed<UsageGroup[]>(() => {
  if (!usage.value) return []
  return { scenario: usage.value.by_scenario, model: usage.value.by_model, date: usage.value.by_date }[usageGroup.value]
})

const usageCards = computed(() => {
  const t = usage.value?.totals
  return [
    { title: '调用次数', value: t ? num(t.calls) : '—', note: t?.missing_usage ? `其中 ${t.missing_usage} 次未返回用量` : '全部返回了用量' },
    { title: '输入 tokens', value: num(t?.input_tokens), note: '文本 / 视觉模型' },
    { title: '输出 tokens', value: num(t?.output_tokens), note: '文本 / 视觉模型' },
    { title: '生成图片', value: t?.output_images == null ? '—' : `${num(t.output_images)} 张`, note: '图片生成 / 编辑 / 翻译' },
  ]
})

function usageText(row: UsageRecord) {
  const parts: string[] = []
  if (row.input_tokens !== null || row.output_tokens !== null) parts.push(`输入 ${num(row.input_tokens)} / 输出 ${num(row.output_tokens)} tokens`)
  if (row.input_images) parts.push(`输入 ${row.input_images} 张图`)
  if (row.output_images !== null) parts.push(`生成 ${row.output_images} 张图`)
  return parts.join('；') || '响应中有 usage，但没有 tokens 或张数字段'
}

onMounted(() => void load(tab.value))
</script>

<style scoped>
.settings-container { padding: 20px; }
.page-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
.page-title { margin: 0; font-size: 22px; color: var(--el-text-color-primary); }
.hint { margin: 12px 0; font-size: 13px; line-height: 1.7; color: var(--el-text-color-secondary); }
.muted { color: var(--el-text-color-secondary); font-size: 13px; }
.block { margin-bottom: 16px; }
.section-title { margin: 24px 0 12px; font-size: 16px; color: var(--el-text-color-primary); }
.password-form { max-width: 460px; margin-top: 8px; }
.role-col { margin-bottom: 16px; }
.role-card { height: 100%; }
.role-card.current { border-color: var(--el-color-primary); }
.role-head { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }
.role-name { font-weight: 600; color: var(--el-text-color-primary); }
.role-summary { margin: 0 0 8px; color: var(--el-text-color-regular); font-size: 13px; }
.role-list { font-size: 13px; color: var(--el-text-color-regular); }
.role-list ul { margin: 4px 0 8px; padding-left: 18px; line-height: 1.7; }
.list-title { font-weight: 600; color: var(--el-text-color-secondary); }
.scenario-card { margin-bottom: 16px; }
.scenario-head { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; }
.scenario-name { font-weight: 600; font-size: 15px; color: var(--el-text-color-primary); margin-right: 8px; }
.scenario-current { display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--el-text-color-regular); flex-wrap: wrap; }
.candidate-list { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; width: 100%; }
.candidate { height: auto; margin: 0 !important; padding: 10px 12px; align-items: flex-start; white-space: normal; }
.candidate :deep(.el-radio__input) { margin-top: 3px; }
.candidate-body { display: flex; flex-direction: column; gap: 4px; }
.candidate-title { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.candidate-id { font-weight: 600; font-family: ui-monospace, Consolas, monospace; color: var(--el-text-color-primary); }
.candidate-note { font-size: 12px; line-height: 1.6; color: var(--el-text-color-regular); }
.candidate-price { font-size: 12px; color: var(--el-color-warning); }
.scenario-actions { margin-top: 12px; }
.usage-toolbar { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; }
.usage-cards { margin-bottom: 16px; }
.usage-cards .el-col { margin-bottom: 12px; }
.summary-title { font-size: 14px; color: var(--el-text-color-secondary); margin-bottom: 8px; }
.summary-value { font-size: 24px; font-weight: 700; color: var(--el-text-color-primary); margin-bottom: 8px; }
.summary-note { font-size: 12px; color: var(--el-text-color-secondary); }
</style>
