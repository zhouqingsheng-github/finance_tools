import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useAppStore = defineStore('app', () => {
  const sidebarCollapsed = ref(false)
  const pythonStatus = ref<'stopped' | 'starting' | 'running' | 'error'>('stopped')
  const pythonMessage = ref('')

  function toggleSidebar() {
    sidebarCollapsed.value = !sidebarCollapsed.value
  }

  function setPythonStatus(status: typeof pythonStatus.value, message?: string) {
    pythonStatus.value = status
    if (message) pythonMessage.value = message
  }

  async function checkPythonStatus() {
    try {
      const status = await window.electronAPI.pythonStatus()
      pythonStatus.value = status as any
    } catch {
      pythonStatus.value = 'stopped'
    }
  }

  async function startPython() {
    try {
      pythonStatus.value = 'starting'
      const result = await window.electronAPI.pythonStart()
      pythonStatus.value = (result.status as any) || 'stopped'
    } catch {
      pythonStatus.value = 'error'
    }
  }

  function listenStatusChange() {
    window.electronAPI.onPythonStatusChanged((status: string) => {
      pythonStatus.value = status as any
    })
  }

  return {
    sidebarCollapsed,
    pythonStatus,
    pythonMessage,
    toggleSidebar,
    setPythonStatus,
    checkPythonStatus,
    startPython,
    listenStatusChange
  }
})
