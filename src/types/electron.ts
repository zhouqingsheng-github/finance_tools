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
}
