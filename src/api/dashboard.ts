import type { DashboardSummary } from '@/types/electron-api'

export const emptyDashboardSummary = (): DashboardSummary => ({
  stats: {
    totalMerchants: 0,
    activeMerchants: 0,
    todayTasks: 0,
    successRate: 0,
    dataCount: 0,
  },
  trend: [
    { label: '00:00', value: 0 },
    { label: '04:00', value: 0 },
    { label: '08:00', value: 0 },
    { label: '12:00', value: 0 },
    { label: '16:00', value: 0 },
    { label: '20:00', value: 0 },
  ],
  recentActivities: [],
})

export const dashboardApi = {
  async summary(): Promise<DashboardSummary> {
    return await window.electronAPI.dashboardSummary()
  },
}
