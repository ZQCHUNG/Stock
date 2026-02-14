import { ref } from 'vue'
import { createDiscreteApi, darkTheme, type ConfigProviderProps } from 'naive-ui'

const themeRef = ref<ConfigProviderProps>({})

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const { message, notification } = createDiscreteApi(['message', 'notification'], {
  configProviderProps: themeRef as any,
})

function setDiscreteTheme(isDark: boolean) {
  themeRef.value = isDark ? { theme: darkTheme } : {}
}

export { message, notification, setDiscreteTheme }
