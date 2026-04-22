import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { taskConfigApi } from '@/api/taskConfig'
import type { TaskConfig } from '@/types/electron'

export interface TaskRunStatus {
  taskId: string
  taskName: string
  merchantId: string
  merchantName: string
  status: 'idle' | 'running' | 'success' | 'error'
  progress: number
  message: string
  logs: { timestamp: number; level: string; message: string }[]
}

export const useTaskConfigStore = defineStore('taskConfig', () => {
  const tasks = ref<TaskConfig[]>([])
  const loading = ref(false)
  const runStatuses = ref<Map<string, TaskRunStatus>>(new Map())

  const taskCount = computed(() => tasks.value.length)
  const activeTasks = computed(() => tasks.value.filter(t => t.status !== 'disabled'))

  async function fetchTasks() {
    loading.value = true
    try {
      tasks.value = await taskConfigApi.list()
    } catch (e) {
      console.error('[TaskConfigStore] fetchTasks error:', e)
      tasks.value = []
    } finally {
      loading.value = false
    }
  }

  async function addTask(task: Partial<TaskConfig>) {
    const result = await taskConfigApi.create(task as any)
    await fetchTasks()
    return result
  }

  async function updateTask(id: string, data: Partial<TaskConfig>) {
    await taskConfigApi.update(id, data)
    await fetchTasks()
  }

  async function deleteTask(id: string) {
    await taskConfigApi.delete(id)
    await fetchTasks()
  }

  async function executeTask(id: string) {
    return await taskConfigApi.execute(id)
  }

  async function parseCurl(curl: string) {
    return await taskConfigApi.parseCurl(curl)
  }

  function initRunStatus(taskId: string, taskName: string, merchantId: string, merchantName: string) {
    runStatuses.value.set(taskId, {
      taskId,
      taskName,
      merchantId,
      merchantName,
      status: 'idle',
      progress: 0,
      message: '就绪',
      logs: []
    })
  }

  function updateRunStatus(taskId: string, update: Partial<TaskRunStatus>) {
    const status = runStatuses.value.get(taskId)
    if (status) {
      Object.assign(status, update)
    }
  }

  function addRunLog(taskId: string, level: string, message: string) {
    const status = runStatuses.value.get(taskId)
    if (status) {
      status.logs.push({ timestamp: Date.now(), level, message })
    }
  }

  function clearRunLogs(taskId: string) {
    const status = runStatuses.value.get(taskId)
    if (status) {
      status.logs = []
    }
  }

  return {
    tasks,
    loading,
    runStatuses,
    taskCount,
    activeTasks,
    fetchTasks,
    addTask,
    updateTask,
    deleteTask,
    executeTask,
    parseCurl,
    initRunStatus,
    updateRunStatus,
    addRunLog,
    clearRunLogs
  }
})
