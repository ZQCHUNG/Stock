<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { NButton, NSpace, NPopover, NInput, NList, NListItem, NText, NEmpty } from 'naive-ui'
import { configsApi, type SavedConfig } from '../api/configs'
import { message } from '../utils/discrete'
import { buildShareUrl } from '../utils/urlConfig'
import { useRoute } from 'vue-router'

const props = defineProps<{
  configType: 'backtest' | 'screener'
  getCurrentConfig: () => Record<string, any>
}>()

const emit = defineEmits<{
  load: [config: Record<string, any>]
}>()

const configs = ref<SavedConfig[]>([])
const saveName = ref('')
const showSave = ref(false)
const showLoad = ref(false)
const searchQuery = ref('')
const sortBy = ref<'name' | 'date'>('date')
const editingName = ref('')
const editNewName = ref('')

const filteredConfigs = computed(() => {
  let list = [...configs.value]
  const q = searchQuery.value.trim().toLowerCase()
  if (q) {
    list = list.filter(c => c.name.toLowerCase().includes(q))
  }
  if (sortBy.value === 'name') {
    list.sort((a, b) => a.name.localeCompare(b.name, 'zh-TW'))
  }
  // 'date' is default order from backend (newest first)
  return list
})

async function loadList() {
  try {
    configs.value = await configsApi.list(props.configType)
  } catch { /* handled by interceptor */ }
}

async function save() {
  const name = saveName.value.trim()
  if (!name) return
  try {
    await configsApi.save(props.configType, name, props.getCurrentConfig())
    message.success(`已保存「${name}」`)
    saveName.value = ''
    showSave.value = false
    await loadList()
  } catch { /* handled by interceptor */ }
}

async function remove(name: string) {
  try {
    await configsApi.remove(props.configType, name)
    message.success(`已刪除「${name}」`)
    await loadList()
  } catch { /* handled by interceptor */ }
}

function load(config: Record<string, any>) {
  emit('load', config)
  showLoad.value = false
  message.success('已載入配置')
}

function startRename(name: string) {
  editingName.value = name
  editNewName.value = name
}

async function confirmRename(oldName: string) {
  const newName = editNewName.value.trim()
  if (!newName || newName === oldName) {
    editingName.value = ''
    return
  }
  try {
    await configsApi.rename(props.configType, oldName, newName)
    message.success(`已重命名為「${newName}」`)
    editingName.value = ''
    await loadList()
  } catch { /* handled by interceptor */ }
}

function cancelRename() {
  editingName.value = ''
}

function share() {
  const route = useRoute()
  const url = buildShareUrl(route.path, props.configType, props.getCurrentConfig())
  navigator.clipboard.writeText(url).then(() => {
    message.success('分享連結已複製到剪貼簿')
  }).catch(() => {
    message.info(url)
  })
}

function toggleSort() {
  sortBy.value = sortBy.value === 'date' ? 'name' : 'date'
}

onMounted(loadList)
</script>

<template>
  <NSpace :size="4">
    <NButton size="tiny" quaternary @click="share">分享</NButton>
    <NPopover v-model:show="showSave" trigger="click" placement="bottom">
      <template #trigger>
        <NButton size="tiny" quaternary>保存配置</NButton>
      </template>
      <div style="width: 220px; padding: 4px">
        <NInput v-model:value="saveName" size="small" placeholder="配置名稱" @keyup.enter="save" />
        <NButton size="small" type="primary" style="margin-top: 8px; width: 100%" @click="save" :disabled="!saveName.trim()">
          保存
        </NButton>
      </div>
    </NPopover>

    <NPopover v-model:show="showLoad" trigger="click" placement="bottom" @update:show="(v: boolean) => { if (v) loadList() }">
      <template #trigger>
        <NButton size="tiny" quaternary>載入配置</NButton>
      </template>
      <div style="width: 280px; max-height: 360px; overflow-y: auto; padding: 4px">
        <NEmpty v-if="!configs.length" description="尚無保存的配置" style="padding: 16px 0" />
        <template v-else>
          <NSpace :size="4" style="margin-bottom: 6px" align="center">
            <NInput
              v-model:value="searchQuery"
              size="tiny"
              placeholder="搜尋配置..."
              clearable
              style="flex: 1"
            />
            <NButton size="tiny" quaternary @click="toggleSort" style="font-size: 11px; white-space: nowrap">
              {{ sortBy === 'date' ? '按時間' : '按名稱' }}
            </NButton>
          </NSpace>
          <NEmpty v-if="!filteredConfigs.length" description="無匹配結果" style="padding: 12px 0" />
          <NList v-else hoverable clickable :show-divider="false">
            <NListItem v-for="c in filteredConfigs" :key="c.name" @click="editingName !== c.name && load(c.config)">
              <div style="display: flex; justify-content: space-between; align-items: center">
                <div style="flex: 1; min-width: 0">
                  <template v-if="editingName === c.name">
                    <NInput
                      v-model:value="editNewName"
                      size="tiny"
                      autofocus
                      style="width: 100%"
                      @keyup.enter="confirmRename(c.name)"
                      @keyup.escape="cancelRename"
                      @blur="confirmRename(c.name)"
                      @click.stop
                    />
                  </template>
                  <template v-else>
                    <NText strong style="font-size: 13px">{{ c.name }}</NText>
                    <br />
                    <NText depth="3" style="font-size: 11px">{{ c.updatedAt?.slice(0, 16).replace('T', ' ') }}</NText>
                  </template>
                </div>
                <NSpace :size="0" style="flex-shrink: 0; margin-left: 8px">
                  <NButton size="tiny" quaternary @click.stop="startRename(c.name)">改名</NButton>
                  <NButton size="tiny" quaternary type="error" @click.stop="remove(c.name)">刪除</NButton>
                </NSpace>
              </div>
            </NListItem>
          </NList>
        </template>
      </div>
    </NPopover>
  </NSpace>
</template>
