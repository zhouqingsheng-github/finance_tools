import type { MerchantConfig } from '@/types/electron'

export const merchantApi = {
  async list(): Promise<MerchantConfig[]> {
    return (await window.electronAPI.merchantList()) || []
  },

  async create(data: Omit<MerchantConfig, 'id' | 'created_at' | 'updated_at'>): Promise<MerchantConfig> {
    // 转为普通对象，避免 Vue Proxy 无法通过 IPC structured clone
    return await window.electronAPI.merchantCreate(JSON.parse(JSON.stringify(data)))
  },

  async update(id: string, data: Partial<MerchantConfig>): Promise<void> {
    await window.electronAPI.merchantUpdate({ id, ...JSON.parse(JSON.stringify(data)) })
  },

  async delete(id: string): Promise<void> {
    await window.electronAPI.merchantDelete(id)
  },

  async testLogin(id: string): Promise<{ success: boolean; message: string }> {
    return await window.electronAPI.merchantTestLogin(id)
  }
}
