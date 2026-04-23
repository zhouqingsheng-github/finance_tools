import type { TaskConfig } from '@/types/electron'
import type { LogEntry } from '@/stores/task'

export const taskConfigApi = {
  async list(): Promise<TaskConfig[]> {
    return (await window.electronAPI.taskConfigList()) || []
  },

  async listByMerchant(merchantId: string): Promise<TaskConfig[]> {
    return (await window.electronAPI.taskConfigListByMerchant(merchantId)) || []
  },

  async create(data: Omit<TaskConfig, 'id' | 'created_at' | 'updated_at'>): Promise<TaskConfig> {
    return await window.electronAPI.taskConfigCreate(JSON.parse(JSON.stringify(data)))
  },

  async update(id: string, data: Partial<TaskConfig>): Promise<void> {
    await window.electronAPI.taskConfigUpdate({ id, ...JSON.parse(JSON.stringify(data)) })
  },

  async delete(id: string): Promise<void> {
    await window.electronAPI.taskConfigDelete(id)
  },

  async execute(taskId: string): Promise<{ success: boolean; message: string }> {
    return await window.electronAPI.taskConfigExecute(taskId)
  },

  async stopAll(): Promise<void> {
    await window.electronAPI.taskStopAll()
  },

  async parseCurl(curl: string): Promise<{
    method: string
    url: string
    headers: Record<string, string>
    params: Record<string, any>
    body: string
    inject_credential: boolean
  }> {
    return await window.electronAPI.taskConfigParseCurl(curl)
  },

  onTaskProgress(callback: (data: { 
    taskId?: string; merchantId: string; status: string; progress: number; message: string 
  }) => void) {
    window.electronAPI.onPythonEvent((event, data) => {
      if (event === 'task:progress') callback(data)
    })
  },

  onTaskLog(callback: (data: { taskId?: string; merchantId: string; log: LogEntry }) => void) {
    window.electronAPI.onPythonEvent((event, data) => {
      if (event === 'task:log') callback(data)
    })
  }
}
