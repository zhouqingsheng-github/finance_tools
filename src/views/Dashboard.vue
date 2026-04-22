<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useMerchantStore } from '@/stores/merchant'
import { useTaskStore } from '@/stores/task'
import { useAppStore } from '@/stores/app'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart, PieChart } from 'echarts/charts'
import {
  TitleComponent,
  TooltipComponent,
  LegendComponent,
  GridComponent
} from 'echarts/components'
import {
  Store, PlayCircle, CheckCircle2, XCircle, 
  Database, TrendingUp, Clock, Activity,
  Zap, ArrowRight
} from 'lucide-vue-next'

use([
  CanvasRenderer,
  LineChart,
  PieChart,
  TitleComponent,
  TooltipComponent,
  LegendComponent,
  GridComponent
])

const merchantStore = useMerchantStore()
const taskStore = useTaskStore()
const appStore = useAppStore()

onMounted(async () => {
  await merchantStore.fetchMerchants()
})

const stats = computed(() => ({
  totalMerchants: merchantStore.merchantCount,
  activeMerchants: merchantStore.activeMerchants.length,
  todayTasks: taskStore.successCount + taskStore.errorCount,
  successRate: taskStore.successCount > 0 
    ? Math.round((taskStore.successCount / (taskStore.successCount + taskStore.errorCount)) * 100)
    : 0,
  dataCount: 0 // 模拟数据总量
}))

const chartOption = computed(() => ({
  tooltip: {
    trigger: 'axis',
    backgroundColor: 'rgba(15,23,42,0.95)',
    borderColor: 'rgba(6,182,212,0.3)',
    textStyle: { color: '#e2e8f0' }
  },
  grid: {
    top: 20,
    right: 20,
    bottom: 30,
    left: 40
  },
  xAxis: {
    type: 'category',
    boundaryGap: false,
    data: ['00:00', '04:00', '08:00', '12:00', '16:00', '20:00'],
    axisLine: { lineStyle: { color: '#334155' } },
    axisLabel: { color: '#64748b', fontSize: 11 }
  },
  yAxis: {
    type: 'value',
    splitLine: { lineStyle: { color: 'rgba(51,65,85,0.3)' } },
    axisLabel: { color: '#64748b', fontSize: 11 }
  },
  series: [
    {
      name: '采集次数',
      type: 'line',
      smooth: true,
      symbol: 'none',
      lineStyle: { color: '#06b6d4', width: 3 },
      areaStyle: {
        color: {
          type: 'linear',
          x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: 'rgba(6,182,212,0.25)' },
            { offset: 1, color: 'rgba(6,182,212,0)' }
          ]
        }
      },
      data: [12, 8, 24, 35, 28, 42]
    }
  ]
}))

const recentActivities = ref([
  { id: 1, merchant: '美团商家后台', action: '数据采集完成', time: '10分钟前', status: 'success' },
  { id: 2, merchant: '携程商户中心', action: '登录凭证刷新', time: '25分钟前', status: 'success' },
  { id: 3, merchant: '飞猪酒店后台', action: '滑块验证码处理', time: '1小时前', status: 'warning' },
  { id: 4, merchant: '抖音来客', action: '数据采集失败', time: '2小时前', status: 'error' }
])

const statCards = [
  { key: 'totalMerchants', label: '已配置商家', icon: Store, color: 'from-primary to-cyan-400' },
  { key: 'todayTasks', label: '今日采集任务', icon: Activity, color: 'from-violet-500 to-purple-500' },
  { key: 'successRate', label: '成功率', suffix: '%', icon: CheckCircle2, color: 'from-emerald-500 to-green-400' },
  { key: 'dataCount', label: '数据总量', icon: Database, color: 'from-amber-500 to-orange-400' }
]
</script>

<template>
  <div class="space-y-6">
    <!-- 页面标题 -->
    <div class="flex items-center justify-between">
      <div>
        <h1 class="text-xl font-semibold text-dark-100">仪表盘</h1>
        <p class="text-sm text-dark-400 mt-1">数据采集工具总览与实时状态监控</p>
      </div>
      <div class="flex items-center gap-2 px-3 py-1.5 rounded-full text-xs"
        :class="appStore.pythonStatus === 'running' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-dark-800/50 text-dark-400'"
      >
        <span class="pulse-dot" :class="appStore.pythonStatus === 'running' ? 'status-online' : 'status-offline'"></span>
        {{ appStore.pythonStatus === 'running' ? '引擎运行中' : '引擎未启动' }}
      </div>
    </div>

    <!-- 统计卡片 -->
    <div class="grid grid-cols-4 gap-5">
      <div 
        v-for="card in statCards" 
        :key="card.key"
        class="glass-card-hover p-5 relative overflow-hidden group cursor-pointer"
      >
        <!-- 背景装饰 -->
        <div class="absolute -right-4 -top-4 w-24 h-24 rounded-full opacity-10 bg-gradient-to-br transition-opacity group-hover:opacity-20"
          :class="card.color"
        ></div>
        
        <div class="flex items-start justify-between relative z-10">
          <div>
            <p class="text-sm text-dark-400 mb-1">{{ card.label }}</p>
            <p class="text-2xl font-bold text-dark-100">
              {{ (stats as any)[card.key] }}{{ card.suffix || '' }}
            </p>
          </div>
          <div class="w-11 h-11 rounded-xl bg-gradient-to-br flex items-center justify-center shadow-lg"
            :class="card.color"
          >
            <component :is="card.icon" class="w-5 h-5 text-white" />
          </div>
        </div>
      </div>
    </div>

    <!-- 图表和活动区域 -->
    <div class="grid grid-cols-3 gap-5">
      <!-- 趋势图表 -->
      <div class="col-span-2 glass-card p-5">
        <div class="flex items-center justify-between mb-4">
          <h2 class="text-base font-medium text-dark-100">采集趋势（近24h）</h2>
          <button class="text-xs text-dark-400 hover:text-primary transition-colors flex items-center gap-1">
            查看详情 <ArrowRight class="w-3 h-3" />
          </button>
        </div>
        <VChart :option="chartOption" autoresize class="w-full h-[260px]" />
      </div>

      <!-- 最近活动 -->
      <div class="glass-card p-5">
        <div class="flex items-center justify-between mb-4">
          <h2 class="text-base font-medium text-dark-100">最近活动</h2>
          <Clock class="w-4 h-4 text-dark-500" />
        </div>
        <div class="space-y-3">
          <div 
            v-for="activity in recentActivities" 
            :key="activity.id"
            class="flex items-start gap-3 p-2.5 rounded-lg hover:bg-dark-800/30 transition-colors"
          >
            <div class="mt-0.5 w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0"
              :class="{
                'bg-emerald-500/10': activity.status === 'success',
                'bg-amber-500/10': activity.status === 'warning',
                'bg-rose-500/10': activity.status === 'error'
              }"
            >
              <component 
                :is="activity.status === 'success' ? CheckCircle2 : activity.status === 'warning' ? Zap : XCircle"
                class="w-3.5 h-3.5"
                :class="{
                  'text-emerald-400': activity.status === 'success',
                  'text-amber-400': activity.status === 'warning',
                  'text-rose-400': activity.status === 'error'
                }"
              />
            </div>
            <div class="min-w-0 flex-1">
              <p class="text-sm text-dark-200 truncate">{{ activity.merchant }}</p>
              <p class="text-xs text-dark-500 mt-0.5">{{ activity.action }} · {{ activity.time }}</p>
            </div>
          </div>
        </div>

        <!-- 快捷操作 -->
        <div class="mt-4 pt-4 border-t border-dark-700/50 space-y-2">
          <button 
            @click="$router.push('/tasks')"
            class="w-full flex items-center justify-center gap-2 py-2.5 rounded-lg bg-primary/10 text-primary hover:bg-primary/20 transition-colors text-sm font-medium"
          >
            <PlayCircle class="w-4 h-4" /> 开始全部采集
          </button>
          <button 
            @click="$router.push('/merchants')"
            class="w-full flex items-center justify-center gap-2 py-2.5 rounded-lg bg-dark-800/50 text-dark-300 hover:bg-dark-700/50 transition-colors text-sm"
          >
            <TrendingUp class="w-4 h-4" /> 配置新商家
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
