<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useMerchantStore } from '@/stores/merchant'
import type { MerchantConfig } from '@/types/electron'
import {
  Plus, Search, Edit3, Trash2, ExternalLink,
  Globe, Settings, User, Key, ChevronDown,
  LogIn, ShieldCheck, ShieldAlert, ShieldOff, Loader2,
  FileText, X
} from 'lucide-vue-next'

const merchantStore = useMerchantStore()
const searchQuery = ref('')
const showForm = ref(false)
const editingMerchant = ref<MerchantConfig | null>(null)
const showAdvanced = ref(false)
const loginLoading = ref<string>('')  // 正在登录的商家 ID

// 登录日志相关
interface LogEntry {
  timestamp: number
  level: 'info' | 'warn' | 'error' | 'debug'
  message: string
}
const loginLogs = ref<Map<string, LogEntry[]>>(new Map())
const loginProgress = ref<Map<string, { progress: number; message: string }>>(new Map())
const showLogDrawer = ref(false)
const logDrawerMerchantId = ref('')
const logDrawerMerchantName = ref('')

let unsubProgress: (() => void) | null = null
let unsubLog: (() => void) | null = null

const formData = ref({
  name: '',
  url: '',
  login_url: '',
  username: '',
  password: '',
  username_selector: '',
  password_selector: '',
  submit_selector: '',
  status: 'active' as MerchantConfig['status']
})

onMounted(async () => {
  await merchantStore.fetchMerchants()

  // 监听登录进度事件
  unsubProgress = (window as any).electronAPI?.onPythonEvent?.((event: string, data: any) => {
    if (event === 'task:progress' && data.merchantId) {
      loginProgress.value.set(data.merchantId, {
        progress: data.progress || 0,
        message: data.message || ''
      })
      // 如果是运行中状态也记录一条日志
      if (data.message && data.status !== 'logged_in') {
        const logs = loginLogs.value.get(data.merchantId) || []
        logs.push({
          timestamp: Date.now(),
          level: data.status === 'error' ? 'error' : 'info',
          message: data.message
        })
        loginLogs.value.set(data.merchantId, logs)
      }
    }
  })

  // 监听登录日志事件
  unsubLog = (window as any).electronAPI?.onPythonEvent?.((event: string, data: any) => {
    if (event === 'task:log' && data.merchantId) {
      const logs = loginLogs.value.get(data.merchantId) || []
      logs.push({
        timestamp: data.log?.timestamp ? data.log.timestamp * 1000 : Date.now(),
        level: data.log?.level || 'info',
        message: data.log?.message || ''
      })
      loginLogs.value.set(data.merchantId, logs)
    }
  })
})

onUnmounted(() => {
  unsubProgress?.()
  unsubLog?.()
})

const filteredMerchants = ref<MerchantConfig[]>(merchantStore.merchants)

function openCreateForm() {
  editingMerchant.value = null
  formData.value = {
    name: '', url: '', login_url: '', username: '', password: '',
    username_selector: '', password_selector: '', submit_selector: '',
    status: 'active'
  }
  showForm.value = true
}

function openEditForm(merchant: MerchantConfig) {
  editingMerchant.value = merchant
  formData.value = {
    name: merchant.name,
    url: merchant.url,
    login_url: merchant.login_url || '',
    username: merchant.username || '',
    password: merchant.password || '',
    username_selector: merchant.username_selector || '',
    password_selector: merchant.password_selector || '',
    submit_selector: merchant.submit_selector || '',
    status: merchant.status
  }
  showForm.value = true
}

async function handleSave() {
  if (editingMerchant.value) {
    await merchantStore.updateMerchant(editingMerchant.value.id, formData.value)
  } else {
    await merchantStore.addMerchant(formData.value as any)
  }
  showForm.value = false
  filteredMerchants.value = [...merchantStore.merchants]
}

async function handleDelete(id: string) {
  await merchantStore.deleteMerchant(id)
  filteredMerchants.value = [...merchantStore.merchants]
}

async function handleLogin(merchant: MerchantConfig) {
  loginLoading.value = merchant.id
  // 初始化日志
  loginLogs.value.set(merchant.id, [{
    timestamp: Date.now(),
    level: 'info',
    message: `🔍 开始登录: ${merchant.name}`
  }])
  loginProgress.value.set(merchant.id, { progress: 0, message: '开始登录...' })

  // 打开日志抽屉
  logDrawerMerchantId.value = merchant.id
  logDrawerMerchantName.value = merchant.name
  showLogDrawer.value = true

  try {
    const result = await window.electronAPI.merchantTestLogin(merchant.id)
    // 记录结果
    const logs = loginLogs.value.get(merchant.id) || []
    if (result?.success) {
      logs.push({ timestamp: Date.now(), level: 'info', message: result.message || '登录成功' })
    } else {
      logs.push({ timestamp: Date.now(), level: 'error', message: result?.message || '登录失败' })
    }
    loginLogs.value.set(merchant.id, logs)

    // 刷新商家列表以获取最新的 last_login_at
    await merchantStore.fetchMerchants()
    filteredMerchants.value = [...merchantStore.merchants]
  } catch (e: any) {
    const logs = loginLogs.value.get(merchant.id) || []
    logs.push({ timestamp: Date.now(), level: 'error', message: `登录异常: ${e.message || e}` })
    loginLogs.value.set(merchant.id, logs)
  } finally {
    loginLoading.value = ''
  }
}

function openLoginLogs(merchantId: string, merchantName: string) {
  logDrawerMerchantId.value = merchantId
  logDrawerMerchantName.value = merchantName
  showLogDrawer.value = true
}

function clearLoginLogs(merchantId: string) {
  loginLogs.value.set(merchantId, [])
}

function getStatusBadge(status: string) {
  const map: Record<string, { label: string; class: string }> = {
    active: { label: '正常', class: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' },
    inactive: { label: '停用', class: 'bg-gray-500/10 text-gray-400 border-gray-500/20' },
    error: { label: '异常', class: 'bg-rose-500/10 text-rose-400 border-rose-500/20' }
  }
  return map[status] || map.inactive
}

function getCredentialStatus(merchant: MerchantConfig) {
  if (!merchant.last_login_at || merchant.last_login_at === 0) {
    return { icon: ShieldOff, label: '未登录', class: 'text-dark-500', bgClass: 'bg-dark-700/30' }
  }
  const now = Date.now() / 1000
  const expiresAt = merchant.credential_expires_at || 0
  if (expiresAt > 0 && expiresAt < now) {
    return { icon: ShieldAlert, label: '凭证过期', class: 'text-amber-400', bgClass: 'bg-amber-500/10' }
  }
  if (expiresAt > 0) {
    const remaining = expiresAt - now
    if (remaining < 600) { // 10 分钟内过期
      return { icon: ShieldAlert, label: '即将过期', class: 'text-amber-400', bgClass: 'bg-amber-500/10' }
    }
    return { icon: ShieldCheck, label: '凭证有效', class: 'text-emerald-400', bgClass: 'bg-emerald-500/10' }
  }
  // 有登录记录但无过期时间（session cookie 等情况，凭证有效性未知）
  return { icon: ShieldAlert, label: '待验证', class: 'text-amber-400', bgClass: 'bg-amber-500/10' }
}

function formatTime(timestamp: number) {
  if (!timestamp || timestamp === 0) return '-'
  return new Date(timestamp * 1000).toLocaleString('zh-CN')
}
</script>

<template>
  <div class="space-y-6">
    <!-- 页面标题 -->
    <div class="flex items-center justify-between">
      <div>
        <h1 class="text-xl font-semibold text-dark-100">商家配置管理</h1>
        <p class="text-sm text-dark-400 mt-1">配置商家端登录信息，管理登录凭证</p>
      </div>
      <button 
        @click="openCreateForm"
        class="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-primary hover:bg-primary/90 text-white font-medium transition-all shadow-lg shadow-primary/25 hover:shadow-primary/40 active:scale-[0.98]"
      >
        <Plus class="w-4 h-4" />
        添加商家
      </button>
    </div>

    <!-- 搜索栏 -->
    <div class="glass-card p-4">
      <div class="relative max-w-md">
        <Search class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-dark-500" />
        <input 
          v-model="searchQuery"
          type="text" 
          placeholder="搜索商家名称或URL..."
          class="w-full pl-10 pr-4 py-2.5 bg-dark-800/50 border border-dark-700/50 rounded-lg text-sm text-dark-100 placeholder:text-dark-500 focus:outline-none focus:border-primary/50 focus:bg-dark-800 transition-colors"
        />
      </div>
    </div>

    <!-- 商家列表 -->
    <div v-if="filteredMerchants.length > 0" class="grid gap-4">
      <TransitionGroup name="list">
        <div 
          v-for="merchant in filteredMerchants.filter(m => 
            !searchQuery || m.name.includes(searchQuery) || m.url.includes(searchQuery)
          )" 
          :key="merchant.id"
          class="glass-card-hover p-5 group"
        >
          <div class="flex items-start justify-between">
            <!-- 左侧信息 -->
            <div class="flex items-start gap-4 flex-1 min-w-0">
              <!-- 图标 -->
              <div class="w-12 h-12 rounded-xl bg-gradient-to-br from-primary/20 to-cyan-500/10 flex items-center justify-center flex-shrink-0 border border-primary/10">
                <Globe class="w-6 h-6 text-primary" />
              </div>
              
              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-3 mb-1">
                  <h3 class="text-base font-semibold text-dark-100 truncate">{{ merchant.name }}</h3>
                  <span class="px-2 py-0.5 rounded-full text-xs border" :class="getStatusBadge(merchant.status)">
                    {{ getStatusBadge(merchant.status).label }}
                  </span>
                </div>
                
                <p class="text-sm text-dark-400 truncate mb-3">{{ merchant.login_url || merchant.url }}</p>
                
                <!-- 标签组 -->
                <div class="flex flex-wrap gap-2">
                  <span 
                    v-if="merchant.username"
                    class="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-dark-800/60 text-xs text-dark-400"
                  >
                    <User class="w-3 h-3" />
                    {{ merchant.username }}
                  </span>
                  <!-- 凭证状态 -->
                  <span 
                    class="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-xs"
                    :class="[getCredentialStatus(merchant).bgClass, getCredentialStatus(merchant).class]"
                  >
                    <component :is="getCredentialStatus(merchant).icon" class="w-3 h-3" />
                    {{ getCredentialStatus(merchant).label }}
                  </span>
                  <span 
                    v-if="merchant.last_login_at && merchant.last_login_at > 0"
                    class="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-dark-800/60 text-xs text-dark-500"
                  >
                    登录于 {{ formatTime(merchant.last_login_at) }}
                  </span>
                  <!-- 登录中状态 -->
                  <span 
                    v-if="loginLoading === merchant.id && loginProgress.get(merchant.id)"
                    class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs bg-primary/10 text-primary animate-pulse"
                  >
                    <Loader2 class="w-3 h-3 animate-spin" />
                    {{ loginProgress.get(merchant.id)?.message || '登录中...' }}
                  </span>
                </div>
              </div>
            </div>

            <!-- 右侧操作按钮 -->
            <div class="flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity ml-4">
              <!-- 登录按钮 -->
              <button 
                @click="handleLogin(merchant)"
                :disabled="loginLoading === merchant.id"
                class="p-2 rounded-lg hover:bg-primary/10 text-dark-400 hover:text-primary transition-colors disabled:opacity-50"
                title="登录获取凭证"
              >
                <Loader2 v-if="loginLoading === merchant.id" class="w-4 h-4 animate-spin" />
                <LogIn v-else class="w-4 h-4" />
              </button>
              <!-- 查看日志按钮 -->
              <button 
                v-if="loginLogs.get(merchant.id)?.length"
                @click="openLoginLogs(merchant.id, merchant.name)"
                class="p-2 rounded-lg hover:bg-dark-700/50 text-dark-400 hover:text-dark-200 transition-colors"
                title="查看登录日志"
              >
                <FileText class="w-4 h-4" />
              </button>
              <button 
                @click="openEditForm(merchant)"
                class="p-2 rounded-lg hover:bg-dark-700/50 text-dark-400 hover:text-primary transition-colors"
                title="编辑"
              >
                <Edit3 class="w-4 h-4" />
              </button>
              <button 
                @click="$router.push(`/tasks?merchantId=${merchant.id}`)"
                class="p-2 rounded-lg hover:bg-dark-700/50 text-dark-400 hover:text-emerald-400 transition-colors"
                title="查看任务"
              >
                <ExternalLink class="w-4 h-4" />
              </button>
              <button 
                @click="handleDelete(merchant.id)"
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
        <Settings class="w-8 h-8 text-dark-600" />
      </div>
      <p class="text-dark-400 mb-1">暂无商家配置</p>
      <p class="text-sm text-dark-600 mb-4">点击上方按钮添加第一个商家端配置</p>
      <button 
        @click="openCreateForm"
        class="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-primary/10 text-primary hover:bg-primary/20 text-sm transition-colors"
      >
        <Plus class="w-4 h-4" /> 添加商家
      </button>
    </div>

    <!-- 配置表单弹窗 -->
    <Teleport to="body">
      <Transition name="modal">
        <div v-if="showForm" class="fixed inset-0 z-50 flex items-center justify-center p-4" @click.self="showForm = false">
          <!-- 背景遮罩 -->
          <div class="absolute inset-0 bg-black/60 backdrop-blur-sm"></div>
          
          <!-- 表单面板 -->
          <div class="relative w-full max-w-2xl glass-card p-6 max-h-[85vh] overflow-y-auto">
            <h2 class="text-lg font-semibold text-dark-100 mb-6">
              {{ editingMerchant ? '编辑商家配置' : '添加新商家' }}
            </h2>

            <form @submit.prevent="handleSave" class="space-y-5">
              <!-- 基本信息 -->
              <div class="grid grid-cols-2 gap-4">
                <div>
                  <label class="block text-sm font-medium text-dark-300 mb-1.5">商家名称 *</label>
                  <input 
                    v-model="formData.name" required type="text" placeholder="如：美团商家后台"
                    class="input-field"
                  />
                </div>
                <div>
                  <label class="block text-sm font-medium text-dark-300 mb-1.5">状态</label>
                  <select v-model="formData.status" class="input-field cursor-pointer">
                    <option value="active">启用</option>
                    <option value="inactive">停用</option>
                  </select>
                </div>
              </div>

              <div>
                <label class="block text-sm font-medium text-dark-300 mb-1.5">访问地址 *</label>
                <input 
                  v-model="formData.url" required type="url" placeholder="https://example.com/dashboard"
                  class="input-field"
                />
              </div>

              <div>
                <label class="block text-sm font-medium text-dark-300 mb-1.5">登录页面地址</label>
                <input 
                  v-model="formData.login_url" type="url" placeholder="https://example.com/login（留空则使用访问地址）"
                  class="input-field"
                />
              </div>

              <!-- 登录凭证（自动填写） -->
              <div class="pt-4 border-t border-dark-700/50">
                <div class="flex items-center gap-2 mb-3">
                  <User class="w-4 h-4 text-primary" />
                  <span class="text-sm font-medium text-dark-300">登录凭证（登录时自动填写）</span>
                </div>

                <div class="grid grid-cols-2 gap-4">
                  <div>
                    <label class="block text-xs font-medium text-dark-400 mb-1.5">账号 / 用户名</label>
                    <input
                      v-model="formData.username" type="text" placeholder="登录用的用户名"
                      class="input-field"
                    />
                  </div>
                  <div>
                    <label class="block text-xs font-medium text-dark-400 mb-1.5">密码</label>
                    <input
                      v-model="formData.password" type="password" placeholder="登录密码"
                      class="input-field"
                    />
                  </div>
                </div>
                <p class="mt-2 text-xs text-dark-500 flex items-center gap-1">
                  <Key class="w-3 h-3" />
                  验证码需要手动处理，账号密码会自动填入表单。保存后在列表点击登录按钮获取凭证。
                </p>

                <!-- 高级设置（可折叠） -->
                <div class="mt-3 border border-dark-700/50 rounded-lg overflow-hidden">
                  <button
                    type="button"
                    @click="showAdvanced = !showAdvanced"
                    class="w-full flex items-center justify-between px-3.5 py-2.5 bg-dark-800/40 hover:bg-dark-800/60 transition-colors text-left"
                  >
                    <span class="flex items-center gap-1.5 text-xs font-medium text-dark-400">
                      <Settings class="w-3.5 h-3.5" />
                      高级设置
                    </span>
                    <ChevronDown class="w-4 h-4 text-dark-500 transition-transform duration-200" :class="{ 'rotate-180': showAdvanced }" />
                  </button>

                  <Transition name="expand">
                    <div v-if="showAdvanced" class="px-3.5 py-3 space-y-2.5 border-t border-dark-700/30">
                      <p class="text-[11px] text-dark-500 mb-1">元素选择器（#id / .class，留空使用默认值）</p>

                      <div>
                        <label class="block text-[11px] text-dark-500 mb-0.5">用户名输入框</label>
                        <input
                          v-model="formData.username_selector" type="text"
                          placeholder="#username"
                          class="selector-input"
                        />
                      </div>
                      <div>
                        <label class="block text-[11px] text-dark-500 mb-0.5">密码输入框</label>
                        <input
                          v-model="formData.password_selector" type="text"
                          placeholder="#password"
                          class="selector-input"
                        />
                      </div>
                      <div>
                        <label class="block text-[11px] text-dark-500 mb-0.5">登录按钮</label>
                        <input
                          v-model="formData.submit_selector" type="text"
                          placeholder=".btn-login, #submitBtn"
                          class="selector-input"
                        />
                      </div>
                    </div>
                  </Transition>
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
                  class="px-5 py-2 rounded-lg bg-primary hover:bg-primary/90 text-white text-sm font-medium transition-all shadow-lg shadow-primary/25 active:scale-[0.98]"
                >
                  {{ editingMerchant ? '保存修改' : '创建配置' }}
                </button>
              </div>
            </form>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- 登录日志抽屉 -->
    <Teleport to="body">
      <Transition name="drawer">
        <div v-if="showLogDrawer && logDrawerMerchantId" class="fixed inset-0 z-50 flex" @click.self="showLogDrawer = false">
          <div class="absolute inset-0 bg-black/40 backdrop-blur-sm" @click="showLogDrawer = false"></div>
          
          <div class="ml-auto w-[420px] h-full glass-card border-l border-dark-700/50 flex flex-col relative z-10">
            <div class="flex items-center justify-between p-4 border-b border-dark-700/50">
              <div>
                <h3 class="text-base font-semibold text-dark-100">登录日志</h3>
                <p class="text-xs text-dark-500 mt-0.5">{{ logDrawerMerchantName }}</p>
              </div>
              <button 
                @click="showLogDrawer = false"
                class="p-1.5 rounded-lg hover:bg-dark-800/50 text-dark-400 transition-colors"
              >
                <X class="w-4 h-4" />
              </button>
            </div>

            <!-- 进度条 -->
            <div v-if="loginLoading === logDrawerMerchantId && loginProgress.get(logDrawerMerchantId)" class="px-4 pt-3">
              <div class="flex items-center gap-2 mb-1.5">
                <Loader2 class="w-3.5 h-3.5 animate-spin text-primary" />
                <span class="text-xs text-primary font-medium">{{ loginProgress.get(logDrawerMerchantId)?.message }}</span>
              </div>
              <div class="w-full h-1.5 bg-dark-800/50 rounded-full overflow-hidden">
                <div 
                  class="h-full bg-primary rounded-full transition-all duration-500"
                  :style="{ width: `${loginProgress.get(logDrawerMerchantId)?.progress || 0}%` }"
                ></div>
              </div>
            </div>

            <div class="flex-1 overflow-y-auto p-4 space-y-1.5 font-mono text-xs">
              <template v-if="loginLogs.get(logDrawerMerchantId)?.length">
                <div 
                  v-for="(log, idx) in (loginLogs.get(logDrawerMerchantId) || [])" 
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
                    class="uppercase w-6 flex-shrink-0 font-semibold text-center"
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
                @click="clearLoginLogs(logDrawerMerchantId)"
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

.selector-input {
  @apply w-full px-2.5 py-1.5 bg-dark-800/40 border border-dark-700/50 rounded-md text-xs text-dark-200 placeholder:text-dark-600 focus:outline-none focus:border-primary/40 transition-colors font-mono;
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

.expand-enter-active,
.expand-leave-active {
  transition: all 0.2s ease;
  overflow: hidden;
}
.expand-enter-from,
.expand-leave-to {
  opacity: 0;
  max-height: 0;
  padding-top: 0;
  padding-bottom: 0;
}
.expand-enter-to,
.expand-leave-from {
  opacity: 1;
  max-height: 300px;
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
</style>
