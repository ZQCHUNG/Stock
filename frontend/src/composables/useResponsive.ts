import { ref, onMounted, onUnmounted, computed } from 'vue'

const width = ref(typeof window !== 'undefined' ? window.innerWidth : 1200)

let _listenerCount = 0
function _onResize() { width.value = window.innerWidth }

export function useResponsive() {
  onMounted(() => {
    if (_listenerCount === 0) window.addEventListener('resize', _onResize)
    _listenerCount++
    _onResize()
  })
  onUnmounted(() => {
    _listenerCount--
    if (_listenerCount === 0) window.removeEventListener('resize', _onResize)
  })

  const isMobile = computed(() => width.value < 768)
  const isTablet = computed(() => width.value >= 768 && width.value < 1200)
  const cols = (mobile: number, tablet: number, desktop: number) =>
    computed(() => isMobile.value ? mobile : isTablet.value ? tablet : desktop)

  return { isMobile, isTablet, width, cols }
}
