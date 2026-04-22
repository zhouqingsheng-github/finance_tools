import type { LogEntry } from '@/stores/task'

export const taskApi = {
  async start(merchantId?: string): Promise<void> {
    await window.electronAPI.taskStart(merchantId)
  },

  async stop(merchantId?: string): Promise<void> {
    await window.electronAPI.taskStop(merchantId)
  },

  async startAll(): Promise<void> {
    await window.electronAPI.taskStartAll()
  },

  async stopAll(): Promise<void> {
    await window.electronAPI.taskStopAll()
  },

  onTaskProgress(callback: (data: { 
    merchantId: string; status: string; progress: number; message: string 
  }) => void) {
    window.electronAPI.onPythonEvent((event, data) => {
      if (event === 'task:progress') callback(data)
    })
  },

  onTaskLog(callback: (data: { merchantId: string; log: LogEntry }) => void) {
    window.electronAPI.onPythonEvent((event, data) => {
      if (event === 'task:log') callback(data)
    })
  }
}
