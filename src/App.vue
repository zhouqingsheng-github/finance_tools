<script setup lang="ts">
import { onMounted } from 'vue'
import { RouterView } from 'vue-router'
import AppSidebar from './components/AppSidebar.vue'
import { useAppStore } from '@/stores/app'

const appStore = useAppStore()

onMounted(async () => {
  appStore.listenStatusChange()
  await appStore.checkPythonStatus()
})
</script>

<template>
  <div class="flex h-screen overflow-hidden bg-dark-950">
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
</style>
