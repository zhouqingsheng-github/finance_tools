<script setup lang="ts">
import { ref, onMounted, reactive, computed } from 'vue'
import { dataApi } from '@/api/data'
import { useMerchantStore } from '@/stores/merchant'
import type { CollectedRecord } from '@/api/data'
import {
  Download, Trash2,
  FileSpreadsheet, RefreshCw
} from 'lucide-vue-next'

const merchantStore = useMerchantStore()

const records = ref<CollectedRecord[]>([])
const total = ref(0)
const loading = ref(false)       // 首次加载
const loadingMore = ref(false)   // 滚动加载更多
const exporting = ref(false)
const selectedIds = ref<number[]>([])

// 是否还有更多数据（用于控制是否显示加载更多）
const hasMore = computed(() => records.value.length < total.value)

// 获取数据条数
function getDataCount(record: CollectedRecord): number {
  const raw = (record as any).raw_data
  if (!raw || typeof raw !== 'object') return 0
  return raw._count ?? (Array.isArray(raw._records) ? raw._records.length : 0)
}

// 全选状态
const isAllSelected = computed(() =>
  records.value.length > 0 && selectedIds.value.length === records.value.length
)

const filters = reactive({
  merchantId: '',
  pageSize: 20  // 每次加载条数，滚动加载可以适当加大
})

// 滚动观察器引用
let observer: IntersectionObserver | null = null
const sentinelRef = ref<HTMLElement | null>(null)

onMounted(async () => {
  await Promise.all([
    fetchRecords(),
    merchantStore.fetchMerchants()
  ])
  // 初始化 IntersectionObserver，监听底部哨兵元素进入视口
  setupScrollObserver()
})

/** 设置滚动加载的观察器 */
function setupScrollObserver() {
  if (observer) observer.disconnect()
  observer = new IntersectionObserver(
    (entries) => {
      if (entries[0].isIntersecting && hasMore.value && !loading.value && !loadingMore.value) {
        loadMore()
      }
    },
    { rootMargin: '200px' }  // 提前 200px 触发加载
  )
}

/** 观察哨兵元素 */
function observeSentinel() {
  if (observer && sentinelRef.value) {
    observer.observe(sentinelRef.value)
  }
}

/** 首次加载 / 重置加载 */
async function fetchRecords() {
  // 断开旧观察器
  if (observer) observer.disconnect()

  loading.value = true
  try {
    const result = await dataApi.list({
      merchantId: filters.merchantId || undefined,
      page: 1,
      pageSize: filters.pageSize
    })
    records.value = result.records || []
    total.value = result.total || 0
    selectedIds.value = [] // 重置清空选择

    // 重新挂载观察器
    observeSentinel()
  } finally {
    loading.value = false
  }
}

/** 滚动加载更多 */
async function loadMore() {
  if (!hasMore.value || loadingMore.value) return
  loadingMore.value = true
  try {
    const nextPage = Math.floor(records.value.length / filters.pageSize) + 1
    const result = await dataApi.list({
      merchantId: filters.merchantId || undefined,
      page: nextPage,
      pageSize: filters.pageSize
    })
    const newRecords = result.records || []
    // 追加到现有列表
    records.value.push(...newRecords)
    total.value = result.total || 0
  } finally {
    loadingMore.value = false
  }
}

function handleSearch() {
  fetchRecords()
}

/** 全选/取消全选 */
function toggleSelectAll(e: Event) {
  const checked = (e.target as HTMLInputElement).checked
  if (checked) {
    selectedIds.value = records.value.map(r => r.id as unknown as number)
  } else {
    selectedIds.value = []
  }
}

/** 切换单条选中 */
function toggleSelect(id: number) {
  const idx = selectedIds.value.indexOf(id)
  if (idx >= 0) {
    selectedIds.value.splice(idx, 1)
  } else {
    selectedIds.value.push(id)
  }
}

async function handleDelete(id: number) {
  if (!confirm('确定要删除这条记录吗？')) return
  try {
    await dataApi.delete(String(id))
    // 从当前列表移除（不重新请求）
    records.value = records.value.filter(r => String(r.id) !== String(id))
    selectedIds.value = selectedIds.value.filter(sid => sid !== id)
    total.value--
  } catch (e: any) {
    alert(`删除失败：${e.message}`)
  }
}

/** 批量删除 */
async function handleBatchDelete() {
  if (!selectedIds.value.length) return
  if (!confirm(`确定要删除选中的 ${selectedIds.value.length} 条记录吗？`)) return
  try {
    await Promise.all(selectedIds.value.map(id => dataApi.delete(String(id))))
    const removedSet = new Set(selectedIds.value.map(String))
    records.value = records.value.filter(r => !removedSet.has(String(r.id)))
    total.value -= selectedIds.value.length
    selectedIds.value = []
  } catch (e: any) {
    alert(`批量删除失败：${e.message}`)
  }
}

function formatDate(timestamp: number) {
  return new Date(timestamp * 1000).toLocaleString('zh-CN')
}

async function handleExport() {
  exporting.value = true
  try {
    const ids: number[] | undefined = selectedIds.value.length > 0
      ? [...selectedIds.value]
      : undefined

    const now = new Date()
    const suffix = ids ? `_选${ids.length}条` : ''
    const defaultName = `数据导出_${now.getFullYear()}${(now.getMonth()+1).toString().padStart(2,'0')}${now.getDate().toString().padStart(2,'0')}${suffix}.xlsx`
    const result = await window.electronAPI.showSaveDialog({
      title: '导出 Excel 文件',
      defaultPath: defaultName,
      filters: [{ name: 'Excel 工作簿', extensions: ['xlsx'] }, { name: '所有文件', extensions: ['*'] }],
    })

    if (result.canceled || !result.filePath) return

    const merchantId = filters.merchantId ? String(filters.merchantId) : undefined
    const srcPath = await dataApi.exportToExcel(merchantId, ids)
    const savedPath = await window.electronAPI.copyFile(srcPath, result.filePath)
    alert(`导出成功！共 ${ids ? ids.length : total} 条记录\n${savedPath}`)
  } catch (e: any) {
    alert(`导出失败：${e.message}`)
  } finally {
    exporting.value = false
  }
}
</script>

<template>
  <div class="space-y-6">
    <!-- 页面标题 -->
    <div class="flex items-center justify-between">
      <div>
        <h1 class="text-xl font-semibold text-dark-100">数据查看</h1>
        <p class="text-sm text-dark-400 mt-1">每次任务执行产生一条采集记录，展示字段映射后的结构化数据</p>
      </div>
      <div class="flex items-center gap-3">
        <button
          v-if="selectedIds.length > 0"
          @click="handleBatchDelete"
          class="flex items-center gap-2 px-3 py-2 rounded-lg bg-rose-500/10 text-rose-400 hover:bg-rose-500/20 transition-colors text-sm"
        >
          <Trash2 class="w-4 h-4" /> 删除选中 ({{ selectedIds.length }})
        </button>
        <button
          @click="fetchRecords"
          class="flex items-center gap-2 px-3 py-2 rounded-lg bg-dark-800/50 text-dark-300 hover:text-dark-100 hover:bg-dark-700/50 transition-colors text-sm"
        >
          <RefreshCw class="w-4 h-4" /> 刷新
        </button>
        <button
          @click="handleExport"
          :disabled="exporting || total === 0"
          class="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary hover:bg-primary/90 text-white font-medium transition-all shadow-lg shadow-primary/25 active:scale-[0.98] text-sm disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <Download v-if="!exporting" class="w-4 h-4" />
          <RefreshCw v-else class="w-4 h-4 animate-spin" />
          {{ exporting ? '导出中...' : '导出 Excel' }}
        </button>
      </div>
    </div>

    <!-- 筛选工具栏 -->
    <div class="glass-card p-4">
      <div class="flex flex-wrap items-end gap-3">
        <!-- 商家筛选 -->
        <div class="min-w-[180px]">
          <label class="block text-xs text-dark-500 mb-1.5">商家来源</label>
          <select v-model="filters.merchantId" @change="handleSearch" class="input-field cursor-pointer text-sm">
            <option value="">全部商家</option>
            <option
              v-for="m in merchantStore.merchants"
              :key="m.id" :value="m.id"
            >{{ m.name }}</option>
          </select>
        </div>

        <!-- 统计信息 -->
        <div class="flex gap-3 ml-auto items-center self-end">
          <span v-if="total > 0" class="text-xs text-dark-500">
            共 {{ total }} 条 · 已加载 {{ records.length }} 条
          </span>
          <span v-if="!hasMore && records.length > 0" class="inline-flex items-center px-2 py-0.5 rounded-md text-xs bg-emerald-500/10 text-emerald-400">
            已全部加载
          </span>
        </div>
      </div>
    </div>

    <!-- 数据表格容器（可滚动） -->
    <div class="glass-card overflow-hidden flex flex-col" style="max-height: calc(100vh - 260px);">
      <div class="overflow-x-auto overflow-y-auto" style="max-height: calc(100vh - 310px);">
        <table class="w-full min-w-[700px]">
          <thead class="sticky top-0 z-10">
            <tr class="border-b border-dark-700/50 bg-dark-900/95 backdrop-blur">
              <th class="px-4 py-3.5 text-left text-xs font-medium text-dark-500 uppercase tracking-wider w-12">
                <input type="checkbox" class="rounded border-dark-600 bg-dark-800" :checked="isAllSelected" @change="toggleSelectAll" />
              </th>
              <th class="px-4 py-3.5 text-left text-xs font-medium text-dark-500 uppercase tracking-wider w-36">商家名称</th>
              <th class="px-4 py-3.5 text-left text-xs font-medium text-dark-500 uppercase tracking-wider w-40">采集时间</th>
              <th class="px-4 py-3.5 text-left text-xs font-medium text-dark-500 uppercase tracking-wider w-20">数据量</th>
              <th class="px-4 py-3.5 text-right text-xs font-medium text-dark-500 uppercase tracking-wider w-24">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-dark-800/40">
            <template v-if="!loading && records.length > 0">
              <tr
                v-for="record in records"
                :key="record.id"
                class="hover:bg-dark-800/30 transition-colors group"
              >
                <td class="px-4 py-3">
                  <input type="checkbox" class="rounded border-dark-600 bg-dark-800" :checked="selectedIds.includes(record.id as unknown as number)" @change="toggleSelect(record.id as unknown as number)" />
                </td>
                <td class="px-4 py-3">
                  <span class="text-sm font-medium text-dark-200">{{ record.merchant_name }}</span>
                </td>
                <td class="px-4 py-3">
                  <span class="text-sm text-dark-400">{{ formatDate(record.collected_at) }}</span>
                </td>
                <td class="px-4 py-3">
                  <span class="inline-flex items-center px-2 py-0.5 rounded-md text-xs font-mono font-medium bg-emerald-500/10 text-emerald-400">
                    {{ getDataCount(record) }} 条
                  </span>
                </td>
                <td class="px-4 py-3 text-right">
                  <button
                    @click="handleDelete(record.id as unknown as number)"
                    class="p-1.5 rounded-lg opacity-0 group-hover:opacity-100 hover:bg-dark-700/50 text-dark-400 hover:text-rose-400 transition-all"
                    title="删除"
                  >
                    <Trash2 class="w-4 h-4" />
                  </button>
                </td>
              </tr>
            </template>

            <!-- 首次加载状态 -->
            <tr v-if="loading">
              <td colspan="5" class="px-4 py-16 text-center">
                <RefreshCw class="w-6 h-6 mx-auto animate-spin text-primary" />
                <p class="text-sm text-dark-500 mt-2">加载数据中...</p>
              </td>
            </tr>

            <!-- 空状态 -->
            <tr v-if="!loading && records.length === 0">
              <td colspan="5" class="px-4 py-16 text-center">
                <FileSpreadsheet class="w-12 h-12 mx-auto text-dark-700 mb-3" />
                <p class="text-dark-400">暂无采集数据</p>
                <p class="text-sm text-dark-600 mt-1">执行任务后结果将显示在此处</p>
              </td>
            </tr>

            <!-- 滚动加载更多 - 哨兵元素 -->
            <tr v-if="records.length > 0 && hasMore" ref="sentinelEl">
              <td colspan="5" class="px-4 py-8 text-center">
                <div ref="sentinelRef" class="h-1"></div>
                <template v-if="loadingMore">
                  <RefreshCw class="w-5 h-5 mx-auto animate-spin text-primary mb-1" />
                  <p class="text-xs text-dark-500">加载更多...</p>
                </template>
                <template v-else>
                  <p class="text-xs text-dark-600">向下滚动加载更多</p>
                </template>
              </td>
            </tr>

            <!-- 全部加载完毕提示 -->
            <tr v-if="records.length > 0 && !hasMore && records.length > filters.pageSize">
              <td colspan="5" class="px-4 py-6 text-center">
                <p class="text-xs text-dark-600">— 已加载全部 {{ records.length }} 条记录 —</p>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<style scoped>
.input-field {
  width: 100%;
  padding: 8px 12px;
  background: rgba(30,41,59,0.5);
  border: 1px solid rgba(51,65,85,0.5);
  border-radius: 8px;
  color: #e2e8f0;
  font-size: 13px;
  outline: none;
  transition: all 0.2s;
}
.input-field:focus {
  border-color: rgba(6,182,212,0.5);
  box-shadow: 0 0 0 1px rgba(6,182,212,0.1);
}
.input-field option {
  background: #0f172a;
}

/* 表头固定时的阴影效果 */
thead tr th {
  box-shadow: 0 1px 0 0 rgba(51,65,85,0.5);
}
</style>
