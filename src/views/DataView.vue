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
const loading = ref(false)
const exporting = ref(false)
const selectedIds = ref<number[]>([])

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
  page: 1,
  pageSize: 15
})

onMounted(async () => {
  await Promise.all([
    fetchRecords(),
    merchantStore.fetchMerchants()
  ])
})

async function fetchRecords() {
  loading.value = true
  try {
    const result = await dataApi.list({
      merchantId: filters.merchantId || undefined,
      page: filters.page,
      pageSize: filters.pageSize
    })
    records.value = result.records || []
    total.value = result.total || 0
    selectedIds.value = [] // 切换页清空选择
  } finally {
    loading.value = false
  }
}

function handleSearch() {
  filters.page = 1
  fetchRecords()
}

function handlePageChange(page: number) {
  filters.page = page
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
    await fetchRecords()
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
    selectedIds.value = []
    await fetchRecords()
  } catch (e: any) {
    alert(`批量删除失败：${e.message}`)
  }
}

function formatDate(timestamp: number) {
  // 后端存储的是秒级 Unix 时间戳，JS Date 需要毫秒
  return new Date(timestamp * 1000).toLocaleString('zh-CN')
}

/** 获取原始数据预览文本 */
function getRawPreview(record: CollectedRecord): string {
  const raw = (record as any).raw_data
  if (!raw) return '-'
  if (typeof raw === 'string') return raw.substring(0, 100)
  try {
    const str = JSON.stringify(raw)
    return str.length > 100 ? str.substring(0, 100) + '...' : str
  } catch {
    return String(raw).substring(0, 100)
  }
}

async function handleExport() {
  exporting.value = true
  try {
    // 1. 弹出"另存为"对话框让用户选择保存位置
    const now = new Date()
    const defaultName = `数据导出_${now.getFullYear()}${(now.getMonth()+1).toString().padStart(2,'0')}${now.getDate().toString().padStart(2,'0')}.xlsx`
    const result = await window.electronAPI.showSaveDialog({
      title: '导出 Excel 文件',
      defaultPath: defaultName,
      filters: [{ name: 'Excel 工作簿', extensions: ['xlsx'] }, { name: '所有文件', extensions: ['*'] }],
    })

    if (result.canceled || !result.filePath) return

    // 2. 调用后端生成文件（返回临时路径）
    const srcPath = await dataApi.exportToExcel(filters.merchantId || undefined)

    // 3. 将生成的文件复制到用户选择的路径
    const savedPath = await window.electronAPI.copyFile(srcPath, result.filePath)
    alert(`导出成功！\n${savedPath}`)
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

        <!-- 操作按钮 -->
        <div class="flex gap-2 ml-auto">
          <span v-if="total > 0" class="text-xs text-dark-500 self-center">
            共 {{ total }} 条执行记录
          </span>
        </div>
      </div>
    </div>

    <!-- 数据表格 -->
    <div class="glass-card overflow-hidden">
      <div class="overflow-x-auto">
        <table class="w-full min-w-[700px]">
          <thead>
            <tr class="border-b border-dark-700/50">
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
            
            <!-- 加载状态 -->
            <tr v-if="loading">
              <td colspan="5" class="px-4 py-12 text-center">
                <RefreshCw class="w-6 h-6 mx-auto animate-spin text-primary" />
                <p class="text-sm text-dark-500 mt-2">加载数据中...</p>
              </td>
            </tr>

            <!-- 空状态 -->
            <tr v-if="!loading && records.length === 0">
              <td colspan="5" class="px-4 py-16 text-center">
                <FileSpreadsheet class="w-12 h-12 mx-auto text-dark-700 mb-3" />
                <p class="text-dark-400">暂无采集数据</p>
                <p class="text-sm text-dark-600 mt-1">执行任务后结果将显示在此处（每次执行一条记录）</p>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 分页 -->
      <div v-if="total > filters.pageSize" class="flex items-center justify-between px-4 py-3 border-t border-dark-700/50">
        <span class="text-xs text-dark-500">
          共 {{ total }} 条记录
        </span>
        <div class="flex items-center gap-1.5">
          <button 
            v-for="page in Math.ceil(total / filters.pageSize)" 
            :key="page"
            @click="handlePageChange(page)"
            class="w-8 h-8 rounded-lg text-xs font-medium transition-colors"
            :class="page === filters.page ? 'bg-primary text-white' : 'text-dark-400 hover:bg-dark-800/50'"
          >
            {{ page }}
          </button>
        </div>
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
</style>
