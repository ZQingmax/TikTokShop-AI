<template>
  <div class="login-container">
    <div class="login-card">
      <div class="login-header">
        <img class="login-logo" src="/logo.png" alt="" />
        <h2 class="login-title">TikTok跨境电商运营系统</h2>
        <p class="login-subtitle">请使用您的账号登录</p>
      </div>

      <el-form
        ref="loginFormRef"
        :model="loginForm"
        :rules="loginRules"
        class="login-form"
        size="large"
        @keyup.enter="handleLogin"
      >
        <el-form-item prop="username">
          <el-input
            v-model="loginForm.username"
            placeholder="请输入用户名"
            :prefix-icon="User"
            clearable
          />
        </el-form-item>

        <el-form-item prop="password">
          <el-input
            v-model="loginForm.password"
            type="password"
            placeholder="请输入密码"
            :prefix-icon="Lock"
            show-password
            clearable
          />
        </el-form-item>

        <el-form-item class="remember-row">
          <el-checkbox v-model="remember">记住我（7 天内免登录）</el-checkbox>
          <span class="remember-hint">不会在浏览器保存密码</span>
        </el-form-item>

        <el-form-item>
          <el-button
            type="primary"
            class="login-button"
            :loading="loading"
            @click="handleLogin"
          >
            {{ loading ? '登录中...' : '登 录' }}
          </el-button>
        </el-form-item>
      </el-form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { User, Lock } from '@element-plus/icons-vue'
import { useUserStore } from '@/stores/user'
import { session } from '@/api/session'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

const loginFormRef = ref<FormInstance>()
const loading = ref(false)

const rememberedUsername = session.rememberedUsername()
const loginForm = reactive({
  username: rememberedUsername,
  password: '',
})
// 上次勾选过“记住我”则默认保持勾选
const remember = ref(!!rememberedUsername)

// 与后端 LoginRequest 一致（2–200 字符）；用户名常为邮箱，首尾空白不计入长度
const loginRules: FormRules = {
  username: [
    { required: true, whitespace: true, message: '请输入用户名', trigger: 'blur' },
    {
      validator: (_rule, value: string, callback) => {
        const length = (value || '').trim().length
        if (length < 2 || length > 200) callback(new Error('用户名长度为2-200个字符'))
        else callback()
      },
      trigger: 'blur',
    },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, max: 30, message: '密码长度为6-30个字符', trigger: 'blur' },
  ],
}

async function handleLogin() {
  if (!loginFormRef.value) return
  await loginFormRef.value.validate(async (valid) => {
    if (!valid) return
    loading.value = true
    try {
      await userStore.login(loginForm.username.trim(), loginForm.password, remember.value)
      ElMessage.success('登录成功')
      const redirect = (route.query.redirect as string) || '/dashboard'
      // 只允许站内跳转，避免 redirect 参数被用于跳往外部站点
      await router.push(redirect.startsWith('/') && !redirect.startsWith('//') ? redirect : '/dashboard')
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status
      if (status === 401) ElMessage.error('用户名或密码错误')
      else if (status === 403) ElMessage.error('账号已停用，请联系管理员')
      else if (!status) ElMessage.error('无法连接服务器，请检查网络或后端服务')
      // 其他状态码（422/5xx）已由全局拦截器提示
    } finally {
      loading.value = false
    }
  })
}
</script>

<style scoped>
.login-container {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 100vh;
  background: var(--app-login-bg);
}

.login-card {
  width: 420px;
  padding: 40px;
  background: var(--el-bg-color);
  border-radius: 12px;
  border-top: 4px solid var(--app-brand);
  box-shadow: 0 20px 50px var(--el-color-primary-light-9);
}

.login-logo {
  width: 64px;
  height: 64px;
  margin-bottom: 12px;
}

.login-header {
  text-align: center;
  margin-bottom: 36px;
}

.login-title {
  font-size: 24px;
  font-weight: 700;
  color: var(--el-text-color-primary);
  margin: 0 0 8px;
}

.login-subtitle {
  font-size: 14px;
  color: var(--el-text-color-secondary);
  margin: 0;
}

.login-form {
  width: 100%;
}

.remember-row :deep(.el-form-item__content) {
  justify-content: space-between;
}

.remember-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.login-button {
  width: 100%;
  height: 44px;
  font-size: 16px;
  letter-spacing: 4px;
}
</style>
