<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router'
import { computed } from 'vue'
import { useAppStore } from '@/stores/app'
import qingflowLogo from '@/assets/qingflow-logo.png'
import { 
  Monitor, Store, PlayCircle, Database, 
  PanelLeftClose, PanelLeftOpen, Bug
} from 'lucide-vue-next'

const route = useRoute()
const router = useRouter()
const appStore = useAppStore()

const navItems = [
  { path: '/', name: '仪表盘', icon: Monitor },
  { path: '/merchants', name: '商家配置', icon: Store },
  { path: '/tasks', name: '任务调度', icon: PlayCircle },
  { path: '/data', name: '数据查看', icon: Database }
]

const currentPath = computed(() => route.path)

function navigateTo(path: string) {
  router.push(path)
}

function openDebugTools() {
  window.electronAPI.toggleDevTools()
}
</script>

<template>
  <aside
    class="flex-shrink-0 flex flex-col transition-all duration-300 bg-dark-900/95 border-r border-dark-800/80"
    :class="appStore.sidebarCollapsed ? 'w-[68px]' : 'w-[240px]'"
  >
    <!-- Logo 区域 -->
    <div class="sidebar-brand flex items-center px-4 border-b border-dark-800/80">
      <div class="flex items-center gap-2.5 overflow-hidden">
        <div class="w-9 h-9 rounded-xl overflow-hidden flex items-center justify-center flex-shrink-0 shadow-lg shadow-primary/20 ring-1 ring-primary/20">
          <img :src="qingflowLogo" alt="QingFlow" class="w-full h-full object-cover" />
        </div>
        <span 
          v-show="!appStore.sidebarCollapsed" 
          class="text-lg font-semibold bg-gradient-to-r from-primary to-cyan-300 bg-clip-text text-transparent whitespace-nowrap transition-opacity duration-200"
        >
          QingFlow
        </span>
      </div>
    </div>

    <!-- 导航菜单 -->
    <nav class="flex-1 py-3 px-2.5 space-y-0.5 overflow-y-auto">
      <button
        v-for="item in navItems"
        :key="item.path"
        @click="navigateTo(item.path)"
        class="nav-item w-full flex items-center gap-3 px-3 py-2.5 rounded-xl transition-all duration-200 group relative"
        :class="currentPath === item.path ? 'active' : ''"
      >
        <component 
          :is="item.icon" 
          class="w-5 h-5 flex-shrink-0 transition-colors duration-200"
          :class="currentPath === item.path ? 'text-primary' : 'text-dark-400 group-hover:text-dark-200'"
        />
        <span 
          v-show="!appStore.sidebarCollapsed"
          class="text-sm font-medium whitespace-nowrap transition-colors duration-200"
          :class="currentPath === item.path ? 'text-primary' : 'text-dark-300 group-hover:text-dark-100'"
        >
          {{ item.name }}
        </span>
        
        <!-- 激活指示条 -->
        <div 
          v-if="currentPath === item.path && !appStore.sidebarCollapsed"
          class="absolute right-1.5 w-1 h-4 rounded-full bg-primary"
        ></div>
      </button>
    </nav>

    <!-- 折叠按钮 -->
    <div class="p-2.5 border-t border-dark-800/80 space-y-1">
      <button
        @click="openDebugTools"
        class="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-dark-400 hover:text-dark-200 hover:bg-dark-800/50 transition-colors"
        title="打开调试"
      >
        <Bug class="w-4 h-4" />
        <span v-show="!appStore.sidebarCollapsed" class="text-xs">打开调试</span>
      </button>
      <button
        @click="appStore.toggleSidebar()"
        class="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-dark-400 hover:text-dark-200 hover:bg-dark-800/50 transition-colors"
      >
        <component 
          :is="appStore.sidebarCollapsed ? PanelLeftOpen : PanelLeftClose" 
          class="w-4 h-4" 
        />
        <span v-show="!appStore.sidebarCollapsed" class="text-xs">收起</span>
      </button>
    </div>
  </aside>
</template>

<style scoped>
.nav-item:hover {
  background-color: rgba(51,65,85,0.4);
}

.nav-item.active {
  background-color: rgba(6,182,212,0.08);
  border: 1px solid rgba(6,182,212,0.15);
}

.sidebar-brand {
  height: calc(56px + env(titlebar-area-height, 28px));
  padding-top: env(titlebar-area-height, 28px);
}
</style>
