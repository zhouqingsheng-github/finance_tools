<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { RouterView } from 'vue-router'
import AppSidebar from './components/AppSidebar.vue'
import { useAppStore } from '@/stores/app'
import { Minus, Square, X } from 'lucide-vue-next'

const appStore = useAppStore()
const showWindowControls = computed(() => window.electronAPI.platform !== 'darwin')
const usageExpiresAt = new Date('2026-12-31T23:59:59+08:00')
const now = ref(Date.now())
const isUsageExpired = computed(() => now.value > usageExpiresAt.getTime())
const usageExpireText = '2026年12月31日 23:59:59'
let usageTimer: number | undefined

onMounted(async () => {
  usageTimer = window.setInterval(() => {
    now.value = Date.now()
  }, 10_000)
  appStore.listenStatusChange()
  await appStore.checkPythonStatus()
})

onUnmounted(() => {
  window.clearInterval(usageTimer)
})

function minimizeWindow() {
  window.electronAPI.minimizeWindow()
}

function maximizeWindow() {
  window.electronAPI.maximizeWindow()
}

function closeWindow() {
  window.electronAPI.closeWindow()
}

function quitApp() {
  window.electronAPI.quitApp()
}
</script>

<template>
  <div class="relative flex h-screen overflow-hidden bg-dark-950">
    <div class="window-drag-region absolute left-0 right-0 top-0 z-40 h-[28px]"></div>
    <div v-if="showWindowControls" class="window-controls absolute right-2 top-1 z-50 flex items-center">
      <button class="window-control" title="最小化" @click="minimizeWindow">
        <Minus class="h-3.5 w-3.5" />
      </button>
      <button class="window-control" title="最大化" @click="maximizeWindow">
        <Square class="h-3 w-3" />
      </button>
      <button class="window-control close" title="关闭" @click="closeWindow">
        <X class="h-3.5 w-3.5" />
      </button>
    </div>
    <div
      v-if="isUsageExpired"
      class="fixed inset-0 z-[100] flex items-center justify-center bg-slate-950/90 backdrop-blur-sm"
    >
      <div class="w-[420px] max-w-[calc(100vw-32px)] rounded-xl border border-cyan-500/20 bg-dark-900 p-6 text-center shadow-2xl shadow-black/40">
        <h1 class="text-xl font-semibold text-dark-100">使用期限已到期</h1>
        <p class="mt-3 text-sm leading-6 text-dark-400">
          QingFlow 清流当前授权使用截止时间为 {{ usageExpireText }}。
        </p>
        <p class="mt-2 text-sm text-dark-500">续期后继续使用。</p>
        <button
          type="button"
          class="mt-5 rounded-lg bg-primary/10 px-4 py-2 text-sm font-medium text-primary transition-colors hover:bg-primary/20"
          @click.stop="quitApp"
        >
          关闭应用
        </button>
      </div>
    </div>

    <!-- 侧边导航栏 -->
    <AppSidebar />

    <!-- 主内容区 -->
    <main class="flex-1 min-w-0 overflow-hidden bg-dark-950" style="padding-top: env(titlebar-area-height, 28px);">
      <div class="h-full overflow-y-auto p-6">
        <RouterView v-slot="{ Component }">
          <transition name="page-fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </RouterView>
      </div>
    </main>
  </div>
</template>

<style>
.page-fade-enter-active,
.page-fade-leave-active {
  transition: opacity 0.2s ease;
}

.page-fade-enter-from,
.page-fade-leave-to {
  opacity: 0;
}

.window-drag-region {
  -webkit-app-region: drag;
}

.window-controls {
  -webkit-app-region: no-drag;
}

.window-control {
  width: 38px;
  height: 26px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #94a3b8;
  border-radius: 6px;
  transition: color 0.15s ease, background-color 0.15s ease;
}

.window-control:hover {
  color: #e2e8f0;
  background: rgba(51, 65, 85, 0.55);
}

.window-control.close:hover {
  color: #fff;
  background: rgba(239, 68, 68, 0.9);
}
</style>
