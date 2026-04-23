export interface MerchantConfig {
  id: string
  name: string
  url: string
  login_url: string
  username?: string
  password?: string
  username_selector?: string
  password_selector?: string
  submit_selector?: string
  status: 'active' | 'inactive' | 'error'
  last_login_at?: number
  credential_expires_at?: number
  created_at: number
  updated_at: number
}

/** 单个 操作+监听 一体化单元 */
export interface ApiListenerConfig {
  /** 操作配置：何时触发监听 */
  action: {
    type: 'immediate' | 'click'    // immediate=进入页面立即监听 | click=点击元素后监听
    selector?: string              // click 模式的选择器
    value?: string                 // 保留字段，可用于延迟时间
  }
  /** 监听的接口 URL 关键字 */
  api_url: string
  /** 监听模式：capture=抓包生成CURL / extract=拦截响应提取数据 */
  mode: 'capture' | 'extract'
  /** 动态参数映射：执行时替换请求 body/params 中同名参数的值 */
  field_mapping?: Record<string, string>
  /** 响应数据提取配置 */
  response_extract?: {
    enabled: boolean
    list_path: string                    // 数据列表路径，如 data.records
    fields: { target: string; source: string }[]  // 目标字段 ← 源路径映射
  }
  /** 自动分页循环配置（extract: 分页参数重新请求; capture: DOM翻页按钮循环） */
  pagination?: {
    enabled: boolean
    page_field: string                   // extract: 页码参数名
    size_field: string                   // extract: 每页数量参数名
    total_field: string                  // extract: 总数字段路径
    is_total_page: boolean               // extract: total_field 是总页数？
  }
}

export interface TaskConfig {
  id: string
  name: string
  merchant_id: string
  merchant_name?: string
  merchant_ids: string[]
  curl_command: string
  method: string
  url: string
  headers: Record<string, string>
  params: Record<string, any>
  body: string
  inject_credential: number
  field_mapping: Record<string, string>
  cron_expression: string
  status: 'idle' | 'running' | 'success' | 'error' | 'disabled'
  last_run_at: number
  last_result: string
  created_at: number
  updated_at: number
  task_type?: 'curl' | 'browser'
  browser_config?: {
    target_url: string
    /** 操作+监听一体化列表（替代原来的 actions + api_listeners） */
    api_listeners?: ApiListenerConfig[]
    /** 兼容旧版单一 api_url */
    api_url?: string
    /** 兼容旧版独立 actions */
    actions?: { type: string; selector?: string; value?: string }[]
    wait_after_load?: number
  }
}
