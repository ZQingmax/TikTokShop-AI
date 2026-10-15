import { defineStore } from 'pinia'
import { ref } from 'vue'

export const themes = [
  { value: 'blue', label: '蓝白', color: '#1677ff' },
  { value: 'green', label: '绿白', color: '#16865b' },
  { value: 'purple', label: '紫白', color: '#8054d9' },
  { value: 'yellow', label: '黄白', color: '#a66b00' },
  { value: 'dark', label: '护眼深色', color: '#8faee0' },
] as const

type Theme = (typeof themes)[number]['value']
const STORAGE_KEY = 'app-theme'

function isTheme(value: unknown): value is Theme {
  return themes.some((theme) => theme.value === value)
}

export const useThemeStore = defineStore('theme', () => {
  let saved: string | null = null
  try { saved = localStorage.getItem(STORAGE_KEY) } catch { /* 使用默认主题 */ }
  const current = ref<Theme>(isTheme(saved) ? saved : 'blue')

  function apply() {
    document.documentElement.dataset.theme = current.value
    document.documentElement.classList.toggle('dark', current.value === 'dark')
  }

  function setTheme(value: unknown) {
    if (!isTheme(value)) return
    current.value = value
    apply()
    try { localStorage.setItem(STORAGE_KEY, value) } catch { /* 本次会话仍可切换 */ }
  }

  apply()
  return { current, setTheme }
})
