import type { MerchantConfig, TaskConfig } from './electron'

export interface ElectronAPI {
  // Python 引擎状态
  pythonStart: () => Promise<{ success: boolean; status: string }>
  pythonStatus: () => Promise<string>
  onPythonStatusChanged: (callback: (status: string) => void) => void

  // 商家管理
  merchantList: () => Promise<MerchantConfig[]>
  merchantCreate: (data: any) => Promise<MerchantConfig>
  merchantUpdate: (data: any) => Promise<void>
  merchantDelete: (id: string) => Promise<void>
  merchantTestLogin: (id: string) => Promise<{ success: boolean; message: string }>

  // 任务管理（旧接口，保留兼容）
  taskStart: (merchantId?: string) => Promise<any>
  taskStop: (merchantId?: string) => Promise<any>
  taskStartAll: () => Promise<any>
  taskStopAll: () => Promise<any>

  // 任务配置
  taskConfigList: () => Promise<TaskConfig[]>
  taskConfigListByMerchant: (merchantId: string) => Promise<TaskConfig[]>
  taskConfigCreate: (data: any) => Promise<TaskConfig>
  taskConfigUpdate: (data: any) => Promise<void>
  taskConfigDelete: (id: string) => Promise<void>
  taskConfigExecute: (taskId: string) => Promise<{ success: boolean; message: string }>
  taskConfigParseCurl: (curl: string) => Promise<{
    method: string
    url: string
    headers: Record<string, string>
    params: Record<string, any>
    body: string
    inject_credential: boolean
  }>

  // 数据管理
  dataList: (params?: any) => Promise<any[]>
  dataExport: (merchantId?: string, ids?: number[]) => Promise<any>
  dataDelete: (id: string) => Promise<void>
  showSaveDialog: (options?: any) => Promise<{ canceled: boolean; filePath?: string }>
  copyFile: (srcPath: string, destPath: string) => Promise<string>

  // 事件监听
  onPythonEvent: (callback: (event: string, data: any) => void) => void

  // 窗口控制
  minimizeWindow: () => Promise<void>
  maximizeWindow: () => Promise<void>
  closeWindow: () => Promise<void>
}
