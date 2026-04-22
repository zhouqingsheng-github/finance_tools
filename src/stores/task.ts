import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export interface TaskStatus {
  id: string
  merchantId: string
  merchantName: string
  status: 'idle' | 'logging_in' | 'collecting' | 'success' | 'error'
  progress: number
  message: string
  startTime?: number
  endTime?: number
  logs: LogEntry[]
}

export interface LogEntry {
  timestamp: number
  level: 'info' | 'warn' | 'error' | 'debug'
  message: string
}

export const useTaskStore = defineStore('task', () => {
  const tasks = ref<Map<string, TaskStatus>>(new Map())
  const isRunningGlobal = ref(false)

  const runningTasks = computed(() =>
    Array.from(tasks.value.values()).filter(t => 
      t.status === 'logging_in' || t.status === 'collecting'
    )
  )

  const successCount = computed(() =>
    Array.from(tasks.value.values()).filter(t => t.status === 'success').length
  )

  const errorCount = computed(() =>
    Array.from(tasks.value.values()).filter(t => t.status === 'error').length
  )

  function initTask(merchantId: string, merchantName: string) {
    tasks.value.set(merchantId, {
      id: merchantId,
      merchantId,
      merchantName,
      status: 'idle',
      progress: 0,
      message: '就绪',
      logs: []
    })
  }

  function updateTaskStatus(merchantId: string, update: Partial<TaskStatus>) {
    const task = tasks.value.get(merchantId)
    if (task) {
      Object.assign(task, update)
    }
  }

  function addLog(merchantId: string, level: LogEntry['level'], message: string) {
    const task = tasks.value.get(merchantId)
    if (task) {
      task.logs.push({ timestamp: Date.now(), level, message })
    }
  }

  function clearLogs(merchantId: string) {
    const task = tasks.value.get(merchantId)
    if (task) {
      task.logs = []
    }
  }

  return {
    tasks,
    isRunningGlobal,
    runningTasks,
    successCount,
    errorCount,
    initTask,
    updateTaskStatus,
    addLog,
    clearLogs
  }
})
