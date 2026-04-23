export interface CollectedRecord {
    id: string
    task_id: string
    merchant_id: string
    merchant_name: string
    raw_data: Record<string, unknown>
    collected_at: number
}

export const dataApi = {
    async list(params?: {
        merchantId?: string;
        startDate?: number;
        endDate?: number;
        page?: number;
        pageSize?: number;
    }): Promise<{ records: CollectedRecord[]; total: number }> {
        return await window.electronAPI.dataList(params || {})
    },

    async exportToExcel(merchantId?: string, ids?: number[]): Promise<string> {
        return await window.electronAPI.dataExport(merchantId, ids)
    },

    async delete(id: string): Promise<void> {
        await window.electronAPI.dataDelete(id)
    }
}
