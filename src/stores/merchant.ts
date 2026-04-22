import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { merchantApi } from '@/api/merchant'
import type { MerchantConfig } from '@/types/electron'

export const useMerchantStore = defineStore('merchant', () => {
  const merchants = ref<MerchantConfig[]>([])
  const loading = ref(false)
  const currentMerchant = ref<MerchantConfig | null>(null)

  const merchantCount = computed(() => merchants.value.length)
  const activeMerchants = computed(() => merchants.value.filter(m => m.status === 'active'))
  const inactiveMerchants = computed(() => merchants.value.filter(m => m.status !== 'active'))

  async function fetchMerchants() {
    loading.value = true
    try {
      merchants.value = await merchantApi.list()
    } catch (e) {
      console.error('[MerchantStore] fetchMerchants error:', e)
      merchants.value = []
    } finally {
      loading.value = false
    }
  }

  async function addMerchant(merchant: Omit<MerchantConfig, 'id' | 'created_at' | 'updated_at'>) {
    const result = await merchantApi.create(merchant)
    await fetchMerchants()
    return result
  }

  async function updateMerchant(id: string, data: Partial<MerchantConfig>) {
    await merchantApi.update(id, data)
    await fetchMerchants()
  }

  async function deleteMerchant(id: string) {
    await merchantApi.delete(id)
    await fetchMerchants()
  }

  return {
    merchants,
    loading,
    currentMerchant,
    merchantCount,
    activeMerchants,
    inactiveMerchants,
    fetchMerchants,
    addMerchant,
    updateMerchant,
    deleteMerchant
  }
})
