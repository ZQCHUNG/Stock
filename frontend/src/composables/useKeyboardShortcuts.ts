import { onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'

const PAGE_KEYS: Record<string, string> = {
  '1': 'technical',
  '2': 'watchlist',
  '3': 'backtest',
  '4': 'recommend',
  '5': 'report',
  '6': 'screener',
}

function isInputFocused(): boolean {
  const el = document.activeElement
  if (!el) return false
  const tag = el.tagName.toLowerCase()
  return tag === 'input' || tag === 'textarea' || (el as HTMLElement).isContentEditable
}

export function useKeyboardShortcuts() {
  const router = useRouter()

  function onKeydown(e: KeyboardEvent) {
    // Ctrl+K or Meta+K → focus stock search
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
      e.preventDefault()
      const input = document.querySelector('.n-auto-complete input') as HTMLInputElement | null
      input?.focus()
      return
    }

    // Esc → blur current element
    if (e.key === 'Escape') {
      ;(document.activeElement as HTMLElement)?.blur()
      return
    }

    // Number keys 1-6 → page navigation (only when not in input)
    if (!isInputFocused() && !e.ctrlKey && !e.metaKey && !e.altKey) {
      const route = PAGE_KEYS[e.key]
      if (route) {
        e.preventDefault()
        router.push({ name: route })
      }
    }
  }

  onMounted(() => window.addEventListener('keydown', onKeydown))
  onUnmounted(() => window.removeEventListener('keydown', onKeydown))
}
