import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { darkTheme } from 'naive-ui'
import { setDiscreteTheme } from '../utils/discrete'

export const useThemeStore = defineStore('theme', () => {
  const isDark = ref(localStorage.getItem('theme') === 'dark')

  const naiveTheme = computed(() => isDark.value ? darkTheme : null)

  function toggle() {
    isDark.value = !isDark.value
    localStorage.setItem('theme', isDark.value ? 'dark' : 'light')
    applyBodyClass()
  }

  function applyBodyClass() {
    document.body.classList.toggle('dark', isDark.value)
    setDiscreteTheme(isDark.value)
  }

  // Apply on init
  applyBodyClass()

  return { isDark, naiveTheme, toggle }
})
