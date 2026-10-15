<template>
  <el-container class="layout-container">
    <el-aside :width="isCollapse ? '64px' : '220px'" class="layout-aside">
      <div class="logo-container">
        <img class="logo-mark" src="/logo.png" alt="" />
        <span v-show="!isCollapse" class="logo-text">TikTok运营</span>
      </div>

      <el-menu :default-active="activeMenu" :collapse="isCollapse" :collapse-transition="false" router class="aside-menu aside-main">
        <template v-for="(group, gi) in menuGroups" :key="gi">
          <li v-if="gi > 0" class="menu-divider" role="separator" />
          <el-menu-item v-for="item in group" :key="item.path" :index="item.path">
            <el-icon><component :is="item.icon" /></el-icon>
            <template #title>{{ item.title }}</template>
          </el-menu-item>
        </template>
      </el-menu>

      <el-menu :default-active="activeMenu" :collapse="isCollapse" :collapse-transition="false" router class="aside-menu aside-bottom">
        <el-menu-item index="/settings">
          <el-icon><Setting /></el-icon>
          <template #title>系统设置</template>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container class="main-container">
      <el-header class="layout-header">
        <div class="header-left">
          <el-icon class="collapse-btn" @click="isCollapse = !isCollapse">
            <Expand v-if="isCollapse" />
            <Fold v-else />
          </el-icon>
          <el-breadcrumb separator="/">
            <el-breadcrumb-item :to="{ path: '/dashboard' }">首页</el-breadcrumb-item>
            <el-breadcrumb-item v-if="currentRoute.meta?.title">
              {{ currentRoute.meta.title as string }}
            </el-breadcrumb-item>
          </el-breadcrumb>
        </div>

        <div class="header-right">
          <el-dropdown trigger="click" @command="handleCommand">
            <span class="user-info">
              <el-avatar :size="32" class="user-avatar">
                {{ (userStore.userInfo?.nickname || '管')[0] }}
              </el-avatar>
              <span class="user-name">{{ userStore.userInfo?.nickname || '管理员' }}</span>
              <el-icon class="el-icon--right"><ArrowDown /></el-icon>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="settings">
                  <el-icon><Setting /></el-icon>系统设置
                </el-dropdown-item>
                <el-dropdown-item command="logout">
                  <el-icon><SwitchButton /></el-icon>退出登录
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <el-dropdown trigger="click" @command="themeStore.setTheme">
            <el-button text class="theme-trigger" aria-label="切换当前主题" :title="`切换主题（当前：${currentTheme.label}）`">
              <el-icon :size="18"><Sunny /></el-icon>
              <span>主题</span>
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item v-for="theme in themes" :key="theme.value" :command="theme.value"
                  :class="{ 'theme-selected': themeStore.current === theme.value }">
                  <span class="theme-swatch" :style="{ background: theme.color }" />
                  {{ theme.label }}
                  <el-icon v-if="themeStore.current === theme.value" class="el-icon--right"><Check /></el-icon>
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>

      <el-main class="layout-main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { ref, computed, markRaw } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import {
  DataBoard, Goods, List, Van, Service, Wallet, ShoppingBag,
  Expand, Fold, ArrowDown, SwitchButton, Box, TrendCharts, Setting, Check, Sunny,
} from '@element-plus/icons-vue'
import { useUserStore } from '@/stores/user'
import { themes, useThemeStore } from '@/stores/theme'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const themeStore = useThemeStore()
const currentTheme = computed(() => themes.find((theme) => theme.value === themeStore.current)!)
const isCollapse = ref(false)

// 运营看板 | 商品与上架 | 货源 | 订单履约 | 客服财务；系统设置固定在侧栏底部。
const menuGroups = [
  [{ path: '/dashboard', title: '仪表盘', icon: markRaw(DataBoard) }],
  [
    { path: '/products', title: '商品管理', icon: markRaw(Goods) },
    { path: '/sourcing', title: '选品中心', icon: markRaw(TrendCharts) },
    { path: '/collect', title: '采集上架', icon: markRaw(Box) },
  ],
  [{ path: '/sourcing/1688', title: '1688 货源中心', icon: markRaw(ShoppingBag) }],
  [
    { path: '/orders', title: '订单管理', icon: markRaw(List) },
    { path: '/fulfillment', title: '履约管理', icon: markRaw(Van) },
  ],
  [
    { path: '/customer-service', title: '客服管理', icon: markRaw(Service) },
    { path: '/finance', title: '财务管理', icon: markRaw(Wallet) },
  ],
]

const currentRoute = computed(() => route)
const activeMenu = computed(() => route.path)

async function handleCommand(command: string) {
  if (command === 'settings') {
    router.push('/settings')
    return
  }
  if (command === 'logout') {
    try {
      await ElMessageBox.confirm('确定要退出登录吗？', '提示', {
        confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning',
      })
    } catch {
      return
    }
    await userStore.logout()
  }
}
</script>

<style scoped>
.layout-container { height: 100vh; overflow: hidden; }
.layout-aside {
  display: flex; flex-direction: column; background: var(--app-aside-bg);
  border-right: 1px solid var(--app-aside-border); transition: width 0.3s ease; overflow: hidden;
}
.logo-container {
  height: 60px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; gap: 10px;
  padding: 0 16px; background: var(--app-aside-logo-bg); overflow: hidden; white-space: nowrap;
}
.logo-mark {
  object-fit: contain; padding: 2px;
  width: 30px; height: 30px; flex-shrink: 0; border-radius: 8px; display: flex; align-items: center; justify-content: center;
  background: #fff; color: var(--app-brand); font-weight: 800; font-size: 17px;
}
.logo-text { font-size: 16px; font-weight: 700; color: #fff; letter-spacing: 0.5px; }
.aside-menu {
  --el-menu-bg-color: var(--app-aside-bg); --el-menu-text-color: var(--app-aside-text);
  --el-menu-active-color: var(--app-brand); --el-menu-hover-bg-color: var(--app-aside-hover);
  --el-menu-item-height: 46px; border-right: none; padding: 8px 0;
}
.aside-menu:not(.el-menu--collapse) { width: 220px; }
.aside-main { flex: 1; overflow-y: auto; overflow-x: hidden; }
.aside-menu :deep(.el-menu-item) { margin: 2px 10px; border-radius: 8px; }
.aside-menu.el-menu--collapse :deep(.el-menu-item) { margin: 2px 8px; }
.aside-menu :deep(.el-menu-item.is-active) { background: var(--app-aside-active-bg); font-weight: 600; }
.menu-divider { list-style: none; height: 1px; margin: 8px 16px; background: var(--app-aside-border); }
.aside-bottom { flex-shrink: 0; border-top: 1px solid var(--app-aside-border); }
.main-container { display: flex; flex-direction: column; overflow: hidden; }
.layout-header {
  display: flex; align-items: center; justify-content: space-between; height: 60px; padding: 0 20px;
  background: var(--app-header-bg); border-bottom: 1px solid var(--app-header-border); box-shadow: 0 1px 4px var(--el-color-primary-light-9);
}
.header-left { display: flex; align-items: center; gap: 16px; }
.collapse-btn { font-size: 20px; cursor: pointer; color: var(--el-text-color-regular); transition: color 0.3s; }
.collapse-btn:hover { color: var(--app-brand); }
.header-right { display: flex; align-items: center; gap: 16px; }
.theme-trigger { height: 32px; padding: 0 8px; color: var(--el-text-color-regular); }
.theme-trigger :deep(.el-icon + span) { margin-left: 6px; }
.theme-swatch { display: inline-block; width: 12px; height: 12px; border-radius: 50%; flex-shrink: 0; margin-right: 6px; }
.theme-selected { color: var(--app-brand); font-weight: 600; }
.user-info { display: flex; align-items: center; gap: 8px; cursor: pointer; color: var(--el-text-color-regular); }
.user-info:hover { color: var(--app-brand); }
.user-avatar { background-color: var(--app-brand); color: #fff; font-size: 14px; }
.user-name { font-size: 14px; }
.layout-main { background: var(--app-main-bg); padding: 0; overflow-y: auto; }
</style>
