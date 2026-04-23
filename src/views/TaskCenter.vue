<script setup lang="ts">
import { ref, onMounted, computed, onUnmounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useMerchantStore } from '@/stores/merchant'
import { useTaskConfigStore } from '@/stores/taskConfig'
import { taskConfigApi } from '@/api/taskConfig'
import type { TaskConfig } from '@/types/electron'
import {
  Plus, Play, Square, FileText, Edit3, Trash2,
  CheckCircle2, XCircle, Loader2, Terminal,
  Globe, ChevronDown, Settings, RefreshCw, Link,
  Activity, AlertTriangle, Clock, Zap
} from 'lucide-vue-next'

const route = useRoute()
const merchantStore = useMerchantStore()
const taskStore = useTaskConfigStore()

const showForm = ref(false)
const editingTask = ref<TaskConfig | null>(null)
const showCurlInput = ref(true)
const curlInput = ref('')
const parseLoading = ref(false)
const selectedTaskId = ref<string | null>(null)
const showLogDrawer = ref(false)
const executeLoading = ref<string>('')
const showMerchantDropdown = ref(false)

let unsubProgress: (() => void) | null = null
let unsubLog: (() => void) | null = null

const formData = ref({
  name: '',
  merchant_ids: [] as string[],
  curl_command: '',
  method: 'GET' as string,
  url: '',
  headers: {} as Record<string, string>,
  params: {} as Record<string, any>,
  body: '',
  inject_credential: 1,
  field_mapping: {} as Record<string, string>,
  response_extract: { enabled: false, list_path: '', fields: [] as { target: string; source: string }[] } as any,
  pagination: { enabled: false, page_field: '', size_field: '', default_size: 20, total_field: '', is_total_page: false } as any,
  status: 'idle' as TaskConfig['status']
})

// 参数编辑列表（支持动态增删）
const paramList = ref<{ key: string; value: string }[]>([])
const headerList = ref<{ key: string; value: string }[]>([])

// 动态参数映射
const mappingList = ref<{ key: string; value: string }[]>([])

// 响应提取字段列表
const extractFieldList = ref<{ target: string; source: string }[]>([])

// 点击外部关闭商家下拉框
function handleGlobalClick(e: MouseEvent) {
  const target = e.target as HTMLElement
  if (!target.closest('.merchant-dropdown')) {
    showMerchantDropdown.value = false
  }
}

onMounted(async () => {
  document.addEventListener('click', handleGlobalClick)
  await Promise.all([
    merchantStore.fetchMerchants(),
    taskStore.fetchTasks()
  ])

  // 如果从商家配置跳转过来，预选商家
  const merchantId = route.query.merchantId as string
  if (merchantId) {
    formData.value.merchant_id = merchantId
  }

  // 监听任务进度事件
  unsubProgress = taskConfigApi.onTaskProgress((data: any) => {
    const taskId = data.taskId || data.merchantId
    if (taskId) {
      taskStore.updateRunStatus(taskId, {
        status: data.status === 'logging_in' ? 'running' : data.status,
        progress: data.progress || 0,
        message: data.message || ''
      })
      if (data.status === 'error') {
        taskStore.addRunLog(taskId, 'error', data.message)
      } else if (data.status === 'success') {
        taskStore.addRunLog(taskId, 'info', data.message)
      } else if (data.message) {
        taskStore.addRunLog(taskId, 'info', data.message)
      }
    }
  })

  unsubLog = taskConfigApi.onTaskLog((data: any) => {
    const taskId = data.taskId || data.merchantId
    if (taskId) {
      taskStore.addRunLog(taskId, data.log?.level || 'info', data.log?.message || '')
    }
  })

  // 初始化所有任务的运行状态
  taskStore.tasks.forEach(t => {
    taskStore.initRunStatus(t.id, t.name, t.merchant_id, t.merchant_name || '')
  })
})

onUnmounted(() => {
  unsubProgress?.()
  unsubLog?.()
  document.removeEventListener('click', handleGlobalClick)
})

function openCreateForm() {
  editingTask.value = null
  showCurlInput.value = true
  curlInput.value = ''
  formData.value = {
    name: '',
    merchant_ids: (route.query.merchantId as string) ? [route.query.merchantId as string] : [],
    curl_command: '',
    method: 'GET',
    url: '',
    headers: {},
    params: {},
    body: '',
    inject_credential: 1,
    field_mapping: {},
    response_extract: { enabled: false, list_path: '', fields: [] },
    pagination: { enabled: false, page_field: '', size_field: '', default_size: 20, total_field: '', is_total_page: false },
    status: 'idle'
  }
  paramList.value = []
  headerList.value = []
  mappingList.value = []
  extractFieldList.value = []
  showMerchantDropdown.value = false
  showForm.value = true
}

function openEditForm(task: TaskConfig) {
  editingTask.value = task
  showCurlInput.value = false
  curlInput.value = task.curl_command || ''
  formData.value = {
    name: task.name,
    merchant_ids: task.merchant_ids || (task.merchant_id ? [task.merchant_id] : []),
    curl_command: task.curl_command || '',
    method: task.method || 'GET',
    url: task.url || '',
    headers: task.headers && typeof task.headers === 'object' ? { ...task.headers } : {},
    params: task.params && typeof task.params === 'object' ? { ...task.params } : {},
    body: task.body || '',
    inject_credential: task.inject_credential ?? 1,
    field_mapping: task.field_mapping && typeof task.field_mapping === 'object' ? { ...task.field_mapping } : {},
    response_extract: (task as any).response_extract || { enabled: false, list_path: '', fields: [] },
    pagination: (task as any).pagination || { enabled: false, page_field: '', size_field: '', default_size: 20, total_field: '', is_total_page: false },
    status: task.status
  }
  // 同步到编辑列表
  paramList.value = Object.entries(formData.value.params || {}).map(([key, value]) => ({ key, value: String(value) }))
  headerList.value = Object.entries(formData.value.headers || {}).map(([key, value]) => ({ key, value: String(value) }))
  mappingList.value = Object.entries(formData.value.field_mapping || {}).map(([key, value]) => ({ key, value: String(value) }))

  const extractConfig = formData.value.response_extract
  extractFieldList.value = Array.isArray(extractConfig?.fields)
    ? [...(extractConfig.fields as any[])]
    : []
  showMerchantDropdown.value = false
  showForm.value = true
}

async function handleParseCurl() {
  if (!curlInput.value.trim()) return
  parseLoading.value = true
  try {
    const result = await taskStore.parseCurl(curlInput.value)
    formData.value.curl_command = curlInput.value
    formData.value.method = result.method || 'GET'
    formData.value.url = result.url || ''
    formData.value.headers = result.headers || {}
    formData.value.params = result.params || {}
    formData.value.body = result.body || ''
    formData.value.inject_credential = result.inject_credential ? 1 : 0

    // 同步到编辑列表
    paramList.value = Object.entries(formData.value.params).map(([key, value]) => ({ key, value: String(value) }))
    headerList.value = Object.entries(formData.value.headers).map(([key, value]) => ({ key, value: String(value) }))

    // 自动生成任务名称
    if (!formData.value.name) {
      const selectedNames = formData.value.merchant_ids.map(id =>
        merchantStore.merchants.find(m => m.id === id)?.name || '未知商家'
      )
      formData.value.name = `${selectedNames.join('+')} - ${formData.value.method} 采集`
    }

    // 切换到编辑模式
    showCurlInput.value = false
  } finally {
    parseLoading.value = false
  }
}

function syncParamListToForm() {
  const params: Record<string, string> = {}
  paramList.value.forEach(p => {
    if (p.key) params[p.key] = p.value
  })
  formData.value.params = params
}

function syncHeaderListToForm() {
  const headers: Record<string, string> = {}
  headerList.value.forEach(h => {
    if (h.key) headers[h.key] = h.value
  })
  formData.value.headers = headers
}

function syncMappingListToForm() {
  const mapping: Record<string, string> = {}
  mappingList.value.forEach(m => {
    if (m.key) mapping[m.key] = m.value
  })
  formData.value.field_mapping = mapping
}

function addParam() {
  paramList.value.push({ key: '', value: '' })
}

function removeParam(index: number) {
  paramList.value.splice(index, 1)
  syncParamListToForm()
}

function addHeader() {
  headerList.value.push({ key: '', value: '' })
}

function removeHeader(index: number) {
  headerList.value.splice(index, 1)
  syncHeaderListToForm()
}

function addMapping() {
  mappingList.value.push({ key: '', value: '' })
}

function removeMapping(index: number) {
  mappingList.value.splice(index, 1)
  syncMappingListToForm()
}

// 响应提取字段同步
function syncExtractFieldsToForm() {
  formData.value.response_extract = {
    enabled: formData.value.response_extract?.enabled || false,
    list_path: formData.value.response_extract?.list_path || '',
    fields: [...extractFieldList.value]
  }
}

function addExtractField() {
  extractFieldList.value.push({ target: '', source: '' })
}

function removeExtractField(index: number) {
  extractFieldList.value.splice(index, 1)
  syncExtractFieldsToForm()
}

async function handleSave() {
  // 如果 CURL 输入模式有内容，自动重新解析，确保 params/body 与 curlInput 同步
  if (showCurlInput.value && curlInput.value.trim()) {
    try {
      const result = await taskStore.parseCurl(curlInput.value)
      formData.value.curl_command = curlInput.value
      formData.value.method = result.method || 'GET'
      formData.value.url = result.url || ''
      formData.value.headers = result.headers || {}
      formData.value.params = result.params || {}
      formData.value.body = result.body || ''
      formData.value.inject_credential = result.inject_credential ? 1 : 0
      paramList.value = Object.entries(formData.value.params).map(([key, value]) => ({ key, value: String(value) }))
      headerList.value = Object.entries(formData.value.headers).map(([key, value]) => ({ key, value: String(value) }))
    } catch (e) {
      console.error('[TaskCenter] 自动解析 CURL 失败:', e)
    }
  } else {
    syncParamListToForm()
    syncHeaderListToForm()
    syncMappingListToForm()
    syncExtractFieldsToForm()
  }

  if (editingTask.value) {
    await taskStore.updateTask(editingTask.value.id, formData.value)
  } else {
    await taskStore.addTask(formData.value)
  }
  showForm.value = false
  showMerchantDropdown.value = false
  // 初始化运行状态
  if (!editingTask.value) {
    const latest = taskStore.tasks[0]
    if (latest) {
      taskStore.initRunStatus(latest.id, latest.name, latest.merchant_id, latest.merchant_name || '')
    }
  }
}

async function handleDelete(id: string) {
  await taskStore.deleteTask(id)
}

async function handleExecute(task: TaskConfig) {
  executeLoading.value = task.id
  try {
    taskStore.initRunStatus(task.id, task.name, task.merchant_id, task.merchant_name || '')
    await taskStore.executeTask(task.id)
  } finally {
    executeLoading.value = ''
  }
}

function openLogs(taskId: string) {
  selectedTaskId.value = taskId
  showLogDrawer.value = true
}

function getStatusConfig(status: string) {
  const configs: Record<string, { icon: any; color: string; label: string; dotClass: string }> = {
    idle: { icon: null, color: 'text-dark-500', label: '就绪', dotClass: 'status-offline' },
    running: { icon: Loader2, color: 'text-primary', label: '运行中...', dotClass: 'status-online' },
    success: { icon: CheckCircle2, color: 'text-emerald-400', label: '成功', dotClass: 'status-online' },
    error: { icon: XCircle, color: 'text-rose-400', label: '失败', dotClass: 'status-error' },
    disabled: { icon: null, color: 'text-dark-600', label: '已禁用', dotClass: 'status-offline' }
  }
  return configs[status] || configs.idle
}

function getMethodColor(method: string) {
  const map: Record<string, string> = {
    GET: 'bg-emerald-500/10 text-emerald-400',
    POST: 'bg-blue-500/10 text-blue-400',
    PUT: 'bg-amber-500/10 text-amber-400',
    DELETE: 'bg-rose-500/10 text-rose-400',
    PATCH: 'bg-violet-500/10 text-violet-400'
  }
  return map[method?.toUpperCase()] || 'bg-dark-700/50 text-dark-400'
}

const taskList = computed(() => taskStore.tasks)

// ===== 状态统计 =====
const runningCount = computed(() => {
  // 运行中：runStatuses 中 status 为 running 的任务
  let count = 0
  taskStore.runStatuses.forEach(s => { if (s.status === 'running') count++ })
  return count
})

const failedCount = computed(() => {
  // 失败：任务配置 status=error 或 runStatuses 中 status=error
  const fromConfig = taskList.value.filter(t => t.status === 'error').length
  let fromRuntime = 0
  taskStore.runStatuses.forEach(s => { if (s.status === 'error') fromRuntime++ })
  return Math.max(fromConfig, fromRuntime)
})

const pendingCount = computed(() => {
  // 待执行：status 为 idle 或 success（非 running/error/disabled）
  return taskList.value.filter(t =>
    t.status !== 'running' && t.status !== 'error' && t.status !== 'disabled'
  ).length
})

const totalCount = computed(() => taskList.value.length)

const allExecuting = ref(false)

async function handleExecuteAll() {
  if (allExecuting.value) return
  const activeTasks = taskList.value.filter(t => t.status !== 'disabled')
  if (activeTasks.length === 0) return

  allExecuting.value = true
  try {
    for (const task of activeTasks) {
      // 跳过正在运行中的任务
      const rs = taskStore.runStatuses.get(task.id)
      if (rs && rs.status === 'running') continue

      await handleExecute(task)
      // 每个任务之间间隔一小段时间，避免并发过多
      await new Promise(r => setTimeout(r, 300))
    }
  } finally {
    allExecuting.value = false
  }
}

async function handleStopAll() {
  // 调用后端停止所有任务
  try {
    await taskConfigApi.stopAll()
  } catch (e) {
    console.error('[TaskCenter] stopAll error:', e)
  }
}
</script>

<template>
  <div class="space-y-6">
    <!-- 页面标题与操作 -->
    <div class="flex items-center justify-between">
      <div>
        <h1 class="text-xl font-semibold text-dark-100">任务调度中心</h1>
        <p class="text-sm text-dark-400 mt-1">创建采集任务，配置 CURL 命令，自动注入登录凭证</p>
      </div>
      <div class="flex items-center gap-3">
        <button
          @click="handleExecuteAll"
          :disabled="allExecuting || pendingCount === 0"
          class="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 font-medium transition-all disabled:opacity-40 disabled:cursor-not-allowed text-sm border border-emerald-500/20"
        >
          <Zap v-if="!allExecuting" class="w-4 h-4" />
          <Loader2 v-else class="w-4 h-4 animate-spin" />
          全部执行
        </button>
        <button
          @click="handleStopAll"
          :disabled="runningCount === 0"
          class="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-rose-500/10 hover:bg-rose-500/20 text-rose-400 font-medium transition-all disabled:opacity-40 disabled:cursor-not-allowed text-sm border border-rose-500/20"
        >
          <Square class="w-3.5 h-3.5 fill-current" />
          全部停止
        </button>
        <button 
          @click="openCreateForm"
          class="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-primary hover:bg-primary/90 text-white font-medium transition-all shadow-lg shadow-primary/25 active:scale-[0.98] text-sm"
        >
          <Plus class="w-4 h-4" /> 新建任务
        </button>
      </div>
    </div>

    <!-- 状态统计卡片 -->
    <div v-if="totalCount > 0" class="grid grid-cols-4 gap-4">
      <!-- 总任务数 -->
      <div class="glass-card p-4 flex items-center gap-3">
        <div class="w-10 h-10 rounded-xl bg-dark-700/60 flex items-center justify-center">
          <Terminal class="w-5 h-5 text-dark-400" />
        </div>
        <div>
          <p class="text-2xl font-bold text-dark-100">{{ totalCount }}</p>
          <p class="text-xs text-dark-500">总任务数</p>
        </div>
      </div>
      <!-- 运行中 -->
      <div class="glass-card p-4 flex items-center gap-3">
        <div class="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center">
          <Loader2 :class="['w-5 h-5 text-primary', { 'animate-spin': runningCount > 0 }]" />
        </div>
        <div>
          <p class="text-2xl font-bold text-primary">{{ runningCount }}</p>
          <p class="text-xs text-dark-500">运行中</p>
        </div>
      </div>
      <!-- 失败 -->
      <div class="glass-card p-4 flex items-center gap-3">
        <div class="w-10 h-10 rounded-xl bg-rose-500/10 flex items-center justify-center">
          <XCircle class="w-5 h-5 text-rose-400" />
        </div>
        <div>
          <p class="text-2xl font-bold text-rose-400">{{ failedCount }}</p>
          <p class="text-xs text-dark-500">失败</p>
        </div>
      </div>
      <!-- 待执行 -->
      <div class="glass-card p-4 flex items-center gap-3">
        <div class="w-10 h-10 rounded-xl bg-amber-500/10 flex items-center justify-center">
          <Clock class="w-5 h-5 text-amber-400" />
        </div>
        <div>
          <p class="text-2xl font-bold text-amber-400">{{ pendingCount }}</p>
          <p class="text-xs text-dark-500">待执行</p>
        </div>
      </div>
    </div>

    <!-- 任务列表 -->
    <div v-if="taskList.length > 0" class="space-y-3">
      <TransitionGroup name="list">
        <div 
          v-for="task in taskList" 
          :key="task.id"
          class="glass-card-hover p-5 group"
        >
          <div class="flex items-start justify-between">
            <!-- 左侧信息 -->
            <div class="flex items-start gap-4 flex-1 min-w-0">
              <!-- 方法标签 -->
              <div 
                class="w-12 h-12 rounded-xl flex items-center justify-center flex-shrink-0 text-xs font-bold"
                :class="getMethodColor(task.method)"
              >
                {{ (task.method || 'GET').toUpperCase() }}
              </div>

              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-3 mb-1">
                  <h3 class="text-base font-semibold text-dark-100 truncate">{{ task.name }}</h3>
                  <!-- 凭证注入标识 -->
                  <span 
                    v-if="task.inject_credential"
                    class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs bg-primary/10 text-primary"
                  >
                    <Link class="w-3 h-3" /> 自动凭证
                  </span>
                </div>

                <!-- 商家名 + URL -->
                <div class="flex items-center gap-2 mb-2">
                  <span class="text-xs text-dark-500">{{ task.merchant_name || '未知商家' }}</span>
                  <span class="text-dark-700">·</span>
                  <span class="text-xs text-dark-400 truncate max-w-[400px] font-mono">{{ task.url }}</span>
                </div>

                <!-- 运行状态 / 最后结果 -->
                <div class="flex items-center gap-3">
                  <div class="flex items-center gap-1.5">
                    <span class="pulse-dot" :class="getStatusConfig(task.status).dotClass"></span>
                    <span class="text-xs" :class="getStatusConfig(task.status).color">
                      {{ getStatusConfig(task.status).label }}
                    </span>
                  </div>
                  <span v-if="task.last_result" class="text-xs text-dark-500 truncate max-w-[300px]">
                    {{ task.last_result }}
                  </span>
                  <span v-if="task.last_run_at" class="text-xs text-dark-600">
                    {{ new Date(task.last_run_at * 1000).toLocaleString('zh-CN') }}
                  </span>
                </div>
              </div>
            </div>

            <!-- 右侧操作 -->
            <div class="flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity ml-4">
              <button 
                @click="handleExecute(task)"
                :disabled="executeLoading === task.id || task.status === 'running'"
                class="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-primary/10 text-primary hover:bg-primary/20 text-xs font-medium transition-colors disabled:opacity-50"
              >
                <Loader2 v-if="executeLoading === task.id" class="w-3.5 h-3.5 animate-spin" />
                <Play v-else class="w-3.5 h-3.5" /> 执行
              </button>
              <button 
                @click="openLogs(task.id)"
                class="p-2 rounded-lg hover:bg-dark-800/50 text-dark-400 hover:text-dark-200 transition-colors"
                title="日志"
              >
                <FileText class="w-4 h-4" />
              </button>
              <button 
                @click="openEditForm(task)"
                class="p-2 rounded-lg hover:bg-dark-800/50 text-dark-400 hover:text-primary transition-colors"
                title="编辑"
              >
                <Edit3 class="w-4 h-4" />
              </button>
              <button 
                @click="handleDelete(task.id)"
                class="p-2 rounded-lg hover:bg-rose-500/10 text-dark-400 hover:text-rose-400 transition-colors"
                title="删除"
              >
                <Trash2 class="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>
      </TransitionGroup>
    </div>

    <!-- 空状态 -->
    <div v-else class="glass-card p-12 text-center">
      <div class="w-16 h-16 mx-auto mb-4 rounded-2xl bg-dark-800/50 flex items-center justify-center">
        <Terminal class="w-8 h-8 text-dark-600" />
      </div>
      <p class="text-dark-400 mb-1">暂无采集任务</p>
      <p class="text-sm text-dark-600 mb-4">创建任务，配置 CURL 命令后即可执行数据采集</p>
      <button 
        @click="openCreateForm"
        class="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-primary/10 text-primary hover:bg-primary/20 text-sm transition-colors"
      >
        <Plus class="w-4 h-4" /> 新建任务
      </button>
    </div>

    <!-- 任务创建/编辑弹窗 -->
    <Teleport to="body">
      <Transition name="modal">
        <div v-if="showForm" class="fixed inset-0 z-50 flex items-center justify-center p-4" @click.self="showForm = false">
          <div class="absolute inset-0 bg-black/60 backdrop-blur-sm"></div>
          
          <div class="relative w-full max-w-3xl glass-card p-6 max-h-[85vh] overflow-y-auto">
            <h2 class="text-lg font-semibold text-dark-100 mb-6">
              {{ editingTask ? '编辑任务' : '新建采集任务' }}
            </h2>

            <form @submit.prevent="handleSave" class="space-y-5">
              <!-- 基本信息 -->
              <div class="grid grid-cols-2 gap-4">
                <div>
                  <label class="block text-sm font-medium text-dark-300 mb-1.5">任务名称 *</label>
                  <input 
                    v-model="formData.name" required type="text" placeholder="如：每日订单数据采集"
                    class="input-field"
                  />
                </div>
                <div>
                  <label class="block text-sm font-medium text-dark-300 mb-1.5">关联商家 *（可多选，执行时循环每个商家）</label>
                  <!-- 自定义多选下拉框 -->
                  <div class="relative merchant-dropdown">
                    <button
                      type="button"
                      @click="showMerchantDropdown = !showMerchantDropdown"
                      class="input-field flex items-center justify-between text-left cursor-pointer h-[42px]"
                    >
                      <span v-if="formData.merchant_ids.length === 0" class="text-dark-500">请选择商家</span>
                      <span v-else class="text-dark-100 truncate">已选 {{ formData.merchant_ids.length }} 个商家</span>
                      <ChevronDown class="w-4 h-4 text-dark-500 shrink-0 transition-transform" :class="{ 'rotate-180': showMerchantDropdown }" />
                    </button>

                    <!-- 下拉选项 -->
                    <Transition name="dropdown">
                      <div
                        v-if="showMerchantDropdown"
                        class="absolute z-20 mt-1 w-full bg-dark-900 border border-dark-700/50 rounded-lg shadow-xl shadow-black/30 max-h-[200px] overflow-y-auto"
                      >
                        <label
                          v-for="m in merchantStore.merchants"
                          :key="m.id"
                          class="flex items-center gap-2.5 px-3 py-2 hover:bg-dark-700/40 cursor-pointer transition-colors text-sm"
                          :class="{ 'bg-primary/10': formData.merchant_ids.includes(m.id) }"
                        >
                          <input
                            type="checkbox"
                            :value="m.id"
                            v-model="formData.merchant_ids"
                            class="rounded border-dark-600 bg-dark-800 text-primary focus:ring-primary/50"
                            @click.stop
                          />
                          <span class="text-dark-200">{{ m.name }}</span>
                        </label>
                        <p v-if="merchantStore.merchants.length === 0" class="text-xs text-dark-500 py-3 px-3 text-center">
                          请先添加商家配置
                        </p>
                      </div>
                    </Transition>
                  </div>
                </div>
              </div>

              <!-- CURL 输入区 -->
              <div class="border border-dark-700/50 rounded-xl overflow-hidden">
                <div class="flex items-center justify-between px-4 py-2.5 bg-dark-800/40 border-b border-dark-700/30">
                  <div class="flex items-center gap-2">
                    <Terminal class="w-4 h-4 text-primary" />
                    <span class="text-sm font-medium text-dark-300">CURL 命令</span>
                  </div>
                  <div class="flex items-center gap-2">
                    <button
                      type="button"
                      @click="showCurlInput = true"
                      class="px-2.5 py-1 rounded-md text-xs transition-colors"
                      :class="showCurlInput ? 'bg-primary/20 text-primary' : 'text-dark-500 hover:text-dark-300'"
                    >
                      输入 CURL
                    </button>
                    <button
                      type="button"
                      @click="showCurlInput = false"
                      class="px-2.5 py-1 rounded-md text-xs transition-colors"
                      :class="!showCurlInput ? 'bg-primary/20 text-primary' : 'text-dark-500 hover:text-dark-300'"
                    >
                      手动配置
                    </button>
                  </div>
                </div>

                <!-- CURL 输入模式 -->
                <div v-if="showCurlInput" class="p-4 space-y-3">
                  <textarea
                    v-model="curlInput"
                    rows="6"
                    placeholder="粘贴 curl 命令，例如：&#10;curl 'https://api.example.com/orders?page=1' \
  -H 'Accept: application/json' \
  -H 'Authorization: Bearer xxx'"
                    class="curl-textarea"
                  ></textarea>
                  <div class="flex items-center justify-between">
                    <p class="text-xs text-dark-500">
                      Cookie 会被自动移除，运行时动态注入商家登录凭证
                    </p>
                    <button
                      type="button"
                      @click="handleParseCurl"
                      :disabled="parseLoading || !curlInput.trim()"
                      class="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary hover:bg-primary/90 text-white text-xs font-medium transition-all disabled:opacity-50"
                    >
                      <Loader2 v-if="parseLoading" class="w-3 h-3 animate-spin" />
                      <RefreshCw v-else class="w-3 h-3" />
                      解析 CURL
                    </button>
                  </div>
                </div>

                <!-- 手动配置模式 -->
                <div v-else class="p-4 space-y-4">
                  <!-- HTTP 方法和 URL -->
                  <div class="grid grid-cols-[100px_1fr] gap-3">
                    <select v-model="formData.method" class="input-field cursor-pointer text-center font-bold">
                      <option value="GET">GET</option>
                      <option value="POST">POST</option>
                      <option value="PUT">PUT</option>
                      <option value="DELETE">DELETE</option>
                      <option value="PATCH">PATCH</option>
                    </select>
                    <input
                      v-model="formData.url"
                      type="url"
                      placeholder="https://api.example.com/data"
                      class="input-field font-mono"
                    />
                  </div>

                  <!-- 请求头 -->
                  <div>
                    <div class="flex items-center justify-between mb-2">
                      <label class="text-xs font-medium text-dark-400">请求头 Headers</label>
                      <button type="button" @click="addHeader" class="text-xs text-primary hover:text-primary/80">+ 添加</button>
                    </div>
                    <div class="space-y-1.5">
                      <div v-for="(h, i) in headerList" :key="i" class="flex items-center gap-2">
                        <input v-model="h.key" placeholder="Key" class="param-input" @input="syncHeaderListToForm" />
                        <input v-model="h.value" placeholder="Value" class="param-input flex-1" @input="syncHeaderListToForm" />
                        <button type="button" @click="removeHeader(i)" class="text-dark-600 hover:text-rose-400 transition-colors">
                          <Trash2 class="w-3 h-3" />
                        </button>
                      </div>
                    </div>
                  </div>

                  <!-- 查询参数 -->
                  <div>
                    <div class="flex items-center justify-between mb-2">
                      <label class="text-xs font-medium text-dark-400">查询参数 Params</label>
                      <button type="button" @click="addParam" class="text-xs text-primary hover:text-primary/80">+ 添加</button>
                    </div>
                    <div class="space-y-1.5">
                      <div v-for="(p, i) in paramList" :key="i" class="flex items-center gap-2">
                        <input v-model="p.key" placeholder="Key" class="param-input" @input="syncParamListToForm" />
                        <input v-model="p.value" placeholder="Value" class="param-input flex-1" @input="syncParamListToForm" />
                        <button type="button" @click="removeParam(i)" class="text-dark-600 hover:text-rose-400 transition-colors">
                          <Trash2 class="w-3 h-3" />
                        </button>
                      </div>
                    </div>
                  </div>

                  <!-- 请求体 -->
                  <div v-if="['POST', 'PUT', 'PATCH'].includes(formData.method)">
                    <label class="block text-xs font-medium text-dark-400 mb-1.5">请求体 Body</label>
                    <textarea
                      v-model="formData.body"
                      rows="4"
                      placeholder='{"key": "value"}'
                      class="curl-textarea font-mono text-xs"
                    ></textarea>
                  </div>

                  <!-- 动态参数映射 -->
                  <div>
                    <div class="flex items-center justify-between mb-2">
                      <div class="flex items-center gap-1.5">
                        <label class="text-xs font-medium text-dark-400">动态参数</label>
                        <span class="text-[10px] text-dark-600 leading-none">执行时自动替换请求中的同名参数</span>
                      </div>
                      <button type="button" @click="addMapping" class="text-xs text-primary hover:text-primary/80">+ 添加字段</button>
                    </div>
                    <div v-if="mappingList.length === 0" class="py-3 px-4 border border-dashed border-dark-700/50 rounded-lg text-center">
                      <p class="text-[11px] text-dark-500">
                        例如：定义 startDate → 2025-04-22，执行时自动替换 body 和 params 中的 startDate 值
                      </p>
                      <button type="button" @click="addMapping" class="mt-2 text-xs text-primary hover:text-primary/80">+ 添加第一个参数映射</button>
                    </div>
                    <div v-else class="space-y-1.5">
                      <div v-for="(m, i) in mappingList" :key="i" class="flex items-center gap-2">
                        <input v-model="m.key" placeholder="字段名 (如: startDate)" class="param-input w-40" />
                        <span class="text-dark-500 text-xs shrink-0">→</span>
                        <input v-model="m.value" placeholder="值 (如: 2025-04-22)" class="param-input flex-1 font-mono" />
                        <button type="button" @click="removeMapping(i)" class="text-dark-600 hover:text-rose-400 transition-colors">
                          <Trash2 class="w-3 h-3" />
                        </button>
                      </div>
                    </div>
                  </div>

                  <!-- 响应数据提取 -->
                  <div>
                    <div class="flex items-center justify-between mb-2">
                      <div class="flex items-center gap-1.5">
                        <label class="text-xs font-medium text-dark-400 flex items-center gap-1">
                          <input type="checkbox" v-model="formData.response_extract.enabled" class="rounded border-dark-600" />
                          响应数据提取
                        </label>
                        <span class="text-[10px] text-dark-600 leading-none">从 API 响应 JSON 中提取指定字段保存</span>
                      </div>
                    </div>

                    <div v-if="formData.response_extract?.enabled" class="space-y-3 pl-3 border-l-2 border-primary/20">
                      <!-- 列表路径 -->
                      <div>
                        <label class="block text-[11px] text-dark-500 mb-1">数据列表路径</label>
                        <input
                          v-model="formData.response_extract.list_path"
                          placeholder='如: data.records 或 data.list（空=取整个响应）'
                          class="input-field text-xs font-mono"
                        />
                        <p class="text-[10px] text-dark-600 mt-1">API 返回的数组在响应中的 JSON 路径，用点号分隔嵌套层级</p>
                      </div>

                      <!-- 提取字段 -->
                      <div>
                        <div class="flex items-center justify-between mb-1.5">
                          <label class="text-[11px] text-dark-500">提取字段映射</label>
                          <button type="button" @click="addExtractField" class="text-[11px] text-primary hover:text-primary/80">+ 添加字段</button>
                        </div>
                        <p class="text-[10px] text-dark-500 mb-1.5">
                          目标字段名 ← 源路径：从每条数据中按源路径取值，存储为目标字段名
                        </p>
                        <div v-if="extractFieldList.length === 0" class="py-2 px-3 border border-dashed border-dark-700/50 rounded text-center">
                          <p class="text-[10px] text-dark-500">未配置提取字段，将保存原始响应数据</p>
                        </div>
                        <div v-else class="space-y-1.5">
                          <div v-for="(f, i) in extractFieldList" :key="i" class="flex items-center gap-1.5">
                            <input v-model="f.target" placeholder="目标字段名" class="param-input w-28" />
                            <span class="text-dark-500 text-[11px] shrink-0">&lt;-</span>
                            <input v-model="f.source" placeholder="源路径 (如: orderNo)" class="param-input flex-1 font-mono" />
                            <button type="button" @click="removeExtractField(i)" class="text-dark-600 hover:text-rose-400 transition-colors shrink-0 p-0.5">
                              <Trash2 class="w-3 h-3" />
                            </button>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>

                  <!-- 分页循环配置 -->
                  <div>
                    <div class="flex items-center justify-between mb-2">
                      <div class="flex items-center gap-1.5">
                        <label class="text-xs font-medium text-dark-400 flex items-center gap-1">
                          <input type="checkbox" v-model="formData.pagination.enabled" class="rounded border-dark-600" />
                          自动分页循环
                        </label>
                        <span class="text-[10px] text-dark-600 leading-none">自动翻页获取所有数据</span>
                      </div>
                    </div>

                    <div v-if="formData.pagination?.enabled" class="grid grid-cols-2 gap-3 pl-3 border-l-2 border-cyan-400/20">
                      <div>
                        <label class="block text-[11px] text-dark-500 mb-1">页码参数名</label>
                        <input
                          v-model="formData.pagination.page_field"
                          placeholder="如: pageIndex / page"
                          class="input-field text-xs font-mono"
                        />
                      </div>
                      <div>
                        <label class="block text-[11px] text-dark-500 mb-1">每页数量参数名</label>
                        <input
                          v-model="formData.pagination.size_field"
                          placeholder="如: pageSize"
                          class="input-field text-xs font-mono"
                        />
                      </div>
                      <div>
                        <label class="block text-[11px] text-dark-500 mb-1">总数路径</label>
                        <input
                          v-model="formData.pagination.total_field"
                          placeholder='如: data.totalRecord 或 page.totalPage'
                          class="input-field text-xs font-mono"
                        />
                      </div>
                      <div class="col-span-2">
                        <label class="flex items-center gap-2 text-[11px] text-dark-400 cursor-pointer">
                          <input type="checkbox" v-model="formData.pagination.is_total_page" class="rounded border-dark-600" />
                          <span>该路径返回的是<strong class="text-dark-300 mx-0.5">总页数</strong>（非总记录数）</span>
                        </label>
                        <p class="text-[10px] text-dark-600 mt-1">
                          {{ formData.pagination?.is_total_page
                            ? '已选【总页数模式】：系统会根据总页数自动翻到最后一页停止'
                            : '默认【总记录数模式】：系统根据总记录数判断是否已获取全部数据' }}
                        </p>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <!-- 高级选项 -->
              <div class="grid grid-cols-2 gap-4">
                <div>
                  <label class="block text-xs font-medium text-dark-400 mb-1.5">凭证注入</label>
                  <select v-model="formData.inject_credential" class="input-field cursor-pointer text-sm">
                    <option :value="1">自动注入登录凭证</option>
                    <option :value="0">不注入凭证</option>
                  </select>
                </div>
                <div>
                  <label class="block text-xs font-medium text-dark-400 mb-1.5">任务状态</label>
                  <select v-model="formData.status" class="input-field cursor-pointer text-sm">
                    <option value="idle">启用</option>
                    <option value="disabled">禁用</option>
                  </select>
                </div>
              </div>

              <!-- 操作按钮 -->
              <div class="flex items-center justify-end gap-3 pt-4 border-t border-dark-700/50">
                <button 
                  type="button" 
                  @click="showForm = false"
                  class="px-4 py-2 rounded-lg text-dark-400 hover:text-dark-200 hover:bg-dark-800/50 transition-colors text-sm"
                >
                  取消
                </button>
                <button 
                  type="submit"
                  :disabled="!formData.name || !formData.merchant_ids.length || !formData.url"
                  class="px-5 py-2 rounded-lg bg-primary hover:bg-primary/90 text-white text-sm font-medium transition-all shadow-lg shadow-primary/25 disabled:opacity-50 disabled:cursor-not-allowed active:scale-[0.98]"
                >
                  {{ editingTask ? '保存修改' : '创建任务' }}
                </button>
              </div>
            </form>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- 日志抽屉 -->
    <Teleport to="body">
      <Transition name="drawer">
        <div v-if="showLogDrawer && selectedTaskId" class="fixed inset-0 z-50 flex" @click.self="showLogDrawer = false">
          <div class="absolute inset-0 bg-black/40 backdrop-blur-sm"></div>
          
          <div class="ml-auto w-[420px] h-full glass-card border-l border-dark-700/50 flex flex-col relative z-10">
            <div class="flex items-center justify-between p-4 border-b border-dark-700/50">
              <div>
                <h3 class="text-base font-semibold text-dark-100">执行日志</h3>
                <p class="text-xs text-dark-500 mt-0.5">
                  {{ taskStore.runStatuses.get(selectedTaskId)?.taskName || selectedTaskId }}
                </p>
              </div>
              <button 
                @click="showLogDrawer = false"
                class="p-1.5 rounded-lg hover:bg-dark-800/50 text-dark-400 transition-colors"
              >✕</button>
            </div>

            <div class="flex-1 overflow-y-auto p-4 space-y-1.5 font-mono text-xs">
              <template v-if="taskStore.runStatuses.get(selectedTaskId)?.logs.length">
                <div 
                  v-for="(log, idx) in (taskStore.runStatuses.get(selectedTaskId)?.logs || [])" 
                  :key="idx"
                  class="flex items-start gap-2 py-1 px-2 rounded"
                  :class="{
                    'bg-dark-800/30': log.level === 'info',
                    'bg-amber-500/5': log.level === 'warn',
                    'bg-rose-500/5': log.level === 'error',
                    'opacity-60': log.level === 'debug'
                  }"
                >
                  <span 
                    class="flex-shrink-0 w-12 text-right"
                    :class="{
                      'text-primary': log.level === 'info',
                      'text-amber-400': log.level === 'warn',
                      'text-rose-400': log.level === 'error',
                      'text-dark-600': log.level === 'debug'
                    }"
                  >
                    {{ new Date(log.timestamp).toLocaleTimeString() }}
                  </span>
                  <span 
                    class="uppercase w-8 flex-shrink-0 font-semibold"
                    :class="{
                      'text-primary': log.level === 'info',
                      'text-amber-400': log.level === 'warn',
                      'text-rose-400': log.level === 'error',
                      'text-dark-600': log.level === 'debug'
                    }"
                  >
                    {{ log.level.toUpperCase()[0] }}
                  </span>
                  <span class="text-dark-300 break-all">{{ log.message }}</span>
                </div>
              </template>
              <div v-else class="text-center text-dark-600 py-8">
                <FileText class="w-6 h-6 mx-auto mb-2 opacity-30" />
                暂无日志记录
              </div>
            </div>

            <div class="p-3 border-t border-dark-700/50 flex justify-end">
              <button 
                @click="selectedTaskId && taskStore.clearRunLogs(selectedTaskId)"
                class="px-3 py-1.5 rounded-lg text-xs text-dark-500 hover:text-dark-300 hover:bg-dark-800/50 transition-colors"
              >
                清空日志
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
.input-field {
  @apply w-full px-3.5 py-2.5 bg-dark-800/50 border border-dark-700/50 rounded-lg text-sm text-dark-100 placeholder:text-dark-600 focus:outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/20 transition-all;
}

.param-input {
  @apply px-2.5 py-1.5 bg-dark-800/40 border border-dark-700/50 rounded-md text-xs text-dark-200 placeholder:text-dark-600 focus:outline-none focus:border-primary/40 transition-colors font-mono;
}

.curl-textarea {
  @apply w-full px-3.5 py-3 bg-dark-800/50 border border-dark-700/50 rounded-lg text-sm text-dark-100 placeholder:text-dark-600 focus:outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/20 transition-all font-mono resize-y;
}

.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.25s ease;
}
.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}
.modal-enter-active .glass-card,
.modal-leave-active .glass-card {
  transition: transform 0.25s ease, opacity 0.25s ease;
}
.modal-enter-from .glass-card,
.modal-leave-to .glass-card {
  transform: scale(0.95);
  opacity: 0;
}

.list-enter-active,
.list-leave-active {
  transition: all 0.3s ease;
}
.list-enter-from {
  opacity: 0;
  transform: translateY(-8px);
}
.list-leave-to {
  opacity: 0;
  transform: translateX(20px);
}

.drawer-enter-active,
.drawer-leave-active {
  transition: opacity 0.25s ease;
}
.drawer-enter-active .glass-card,
.drawer-leave-active .glass-card {
  transition: transform 0.3s ease;
}
.drawer-enter-from,
.drawer-leave-to {
  opacity: 0;
}
.drawer-enter-from .glass-card,
.drawer-leave-to .glass-card {
  transform: translateX(100%);
}

.dropdown-enter-active,
.dropdown-leave-active {
  transition: opacity 0.15s ease, transform 0.15s ease;
}
.dropdown-enter-from,
.drawer-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
