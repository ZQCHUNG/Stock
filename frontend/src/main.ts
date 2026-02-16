import { createApp } from 'vue'
import { createPinia } from 'pinia'
import naive from 'naive-ui'
import router from './router'
import App from './App.vue'

// Register echarts renderer + common components globally
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { TooltipComponent, GridComponent, LegendComponent, DataZoomComponent, VisualMapComponent } from 'echarts/components'
import { LineChart, BarChart, PieChart, ScatterChart, HeatmapChart } from 'echarts/charts'
use([CanvasRenderer, TooltipComponent, GridComponent, LegendComponent, DataZoomComponent, VisualMapComponent, LineChart, BarChart, PieChart, ScatterChart, HeatmapChart])

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(naive)
app.mount('#app')
