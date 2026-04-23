import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('electronAPI', {
  // Python 引擎状态
  pythonStart: () => ipcRenderer.invoke('python:start'),
  pythonStatus: () => ipcRenderer.invoke('python:status'),
  onPythonStatusChanged: (callback: (status: string) => void) => {
    ipcRenderer.on('python:status-changed', (_event, status) => callback(status))
  },

  // 商家管理
  merchantList: () => ipcRenderer.invoke('merchant:list'),
  merchantCreate: (data: any) => ipcRenderer.invoke('merchant:create', data),
  merchantUpdate: (data: any) => ipcRenderer.invoke('merchant:update', data),
  merchantDelete: (id: string) => ipcRenderer.invoke('merchant:delete', id),
  merchantTestLogin: (id: string) => ipcRenderer.invoke('merchant:test-login', id),

  // 任务管理
  taskStart: (merchantId?: string) => ipcRenderer.invoke('task:start', merchantId),
  taskStop: (merchantId?: string) => ipcRenderer.invoke('task:stop', merchantId),
  taskStartAll: () => ipcRenderer.invoke('task:start-all'),
  taskStopAll: () => ipcRenderer.invoke('task:stop-all'),

  // 任务配置
  taskConfigList: () => ipcRenderer.invoke('taskConfig:list'),
  taskConfigListByMerchant: (merchantId: string) => ipcRenderer.invoke('taskConfig:listByMerchant', merchantId),
  taskConfigCreate: (data: any) => ipcRenderer.invoke('taskConfig:create', data),
  taskConfigUpdate: (data: any) => ipcRenderer.invoke('taskConfig:update', data),
  taskConfigDelete: (id: string) => ipcRenderer.invoke('taskConfig:delete', id),
  taskConfigExecute: (taskId: string) => ipcRenderer.invoke('taskConfig:execute', taskId),
  taskConfigParseCurl: (curl: string) => ipcRenderer.invoke('taskConfig:parseCurl', curl),

  // 数据管理
  dataList: (params?: any) => ipcRenderer.invoke('data:list', params),
  dataExport: (merchantId?: string, ids?: number[]): Promise<any> => ipcRenderer.invoke('data:export', { merchantId, ids }),
  dataDelete: (id: string) => ipcRenderer.invoke('data:delete', id),
  showSaveDialog: (options?: any) => ipcRenderer.invoke('dialog:save', options),
  copyFile: (srcPath: string, destPath: string) => ipcRenderer.invoke('file:copy', srcPath, destPath),

  // 事件监听
  onPythonEvent: (callback: (event: string, data: any) => void) => {
    ipcRenderer.on('python-event', (_event, data) => callback(data.event, data.data))
  },

  // 窗口控制
  minimizeWindow: () => ipcRenderer.invoke('window:minimize'),
  maximizeWindow: () => ipcRenderer.invoke('window:maximize'),
  closeWindow: () => ipcRenderer.invoke('window:close'),
})
