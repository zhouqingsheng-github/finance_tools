<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { Shield, Send, Image, GripVertical } from 'lucide-vue-next'

const props = defineProps<{
  visible: boolean
  type: 'slider' | 'sms'
  merchantName: string
  captchaImage?: string // base64 encoded image for slider
}>()

const emit = defineEmits<{
  (e: 'submit', value: string): void
  (e: 'cancel'): void
  (e: 'slider-move', distance: number): void
}>()

const smsCode = ref('')
const sliderPosition = ref(0)
const isDragging = ref(false)
const dragStartX = ref(0)

const sliderTrackWidth = computed(() => 280)
const sliderMaxOffset = computed(() => sliderTrackWidth.value - 40)

function handleSmsSubmit() {
  if (smsCode.value) {
    emit('submit', smsCode.value)
    smsCode.value = ''
  }
}

function handleSliderMouseDown(e: MouseEvent) {
  if (props.type !== 'slider') return
  isDragging.value = true
  dragStartX.value = e.clientX
}

function handleMouseMove(e: MouseEvent) {
  if (!isDragging.value) return
  const delta = e.clientX - dragStartX.value
  const newPosition = Math.max(0, Math.min(sliderMaxOffset.value, sliderPosition.value + delta))
  sliderPosition.value = newPosition
  dragStartX.value = e.clientX
}

function handleMouseUp() {
  if (!isDragging.value) return
  isDragging.value = false
  emit('slider-move', sliderPosition.value)
}

watch(() => props.visible, (val) => {
  if (val && props.type === 'slider') {
    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)
  }
  if (!val) {
    document.removeEventListener('mousemove', handleMouseMove)
    document.removeEventListener('mouseup', handleMouseUp)
    sliderPosition.value = 0
    smsCode.value = ''
    isDragging.value = false
  }
})
</script>

<template>
  <Teleport to="body">
    <Transition name="captcha-modal">
      <div v-if="visible" class="fixed inset-0 z-[100] flex items-center justify-center p-4" @click.self="emit('cancel')">
        <div class="absolute inset-0 bg-black/70 backdrop-blur-md"></div>
        
        <!-- 弹窗主体 -->
        <div class="relative w-full max-w-[420px] glass-card p-6 border border-primary/20 shadow-2xl shadow-primary/10">
          <!-- 标题 -->
          <div class="flex items-center gap-3 mb-5">
            <div class="w-10 h-10 rounded-xl bg-primary/15 flex items-center justify-center">
              <Shield class="w-5 h-5 text-primary" />
            </div>
            <div>
              <h3 class="text-base font-semibold text-dark-100">验证码验证</h3>
              <p class="text-xs text-dark-500">{{ merchantName }} - 需要完成验证</p>
            </div>
          </div>

          <!-- 滑块验证码模式 -->
          <div v-if="type === 'slider'" class="space-y-5">
            <!-- 验证码图片预览 -->
            <div v-if="captchaImage" class="relative rounded-xl overflow-hidden bg-dark-800/50 border border-dark-700/50">
              <img 
                :src="captchaImage" 
                alt="验证码"
                class="w-full h-auto"
              />
              <!-- 滑块指示器 -->
              <div 
                class="absolute top-1/2 -translate-y-1/2 w-2 h-12 bg-gradient-to-b from-primary to-cyan-400 rounded-sm shadow-lg"
                :style="{ left: `${sliderPosition + 40}px` }"
              ></div>
            </div>
            <div v-else class="flex items-center justify-center h-36 rounded-xl bg-dark-800/30 border border-dashed border-dark-700">
              <Image class="w-8 h-8 text-dark-600" />
            </div>

            <!-- 滑块控件 -->
            <div class="space-y-2">
              <p class="text-xs text-dark-500 text-center">拖动滑块完成验证</p>
              <div 
                class="relative h-11 rounded-lg bg-dark-800/60 border border-dark-700/50 cursor-pointer select-none"
                @mousedown="handleSliderMouseDown"
              >
                <!-- 滑块轨道 -->
                <div 
                  class="absolute inset-y-0 left-0 rounded-lg transition-colors"
                  :style="{ 
                    width: `${sliderPosition + 40}px`, 
                    background: 'linear-gradient(to right, rgba(6,182,212,0.3), rgba(6,182,212,0.15))' 
                  }"
                ></div>
                
                <!-- 滑块手柄 -->
                <div 
                  class="absolute top-1/2 -translate-y-1/2 w-10 h-9 rounded-lg bg-gradient-to-r from-primary to-cyan-400 flex items-center justify-center shadow-lg cursor-grab active:cursor-grabbing transition-shadow hover:shadow-primary/40"
                  :style="{ left: `${sliderPosition}px` }"
                  :class="{ 'scale-105': isDragging }"
                >
                  <GripVertical class="w-4 h-4 text-white" />
                </div>
                
                <!-- 提示文字 -->
                <span 
                  class="absolute inset-0 flex items-center justify-center text-sm pointer-events-none transition-opacity"
                  :class="sliderPosition > 10 ? 'opacity-0' : 'opacity-100 text-dark-500'"
                >
                  向右滑动完成验证
                </span>
              </div>
            </div>
          </div>

          <!-- 短信验证码模式 -->
          <div v-if="type === 'sms'" class="space-y-4">
            <div class="p-4 rounded-xl bg-amber-500/5 border border-amber-500/20">
              <p class="text-sm text-dark-300 mb-1">
                已向您的手机发送短信验证码，请在下方输入收到的验证码。
              </p>
              <p class="text-xs text-dark-600">
                商家：{{ merchantName }}
              </p>
            </div>

            <div>
              <label class="block text-sm font-medium text-dark-300 mb-2">短信验证码</label>
              <input 
                v-model="smsCode"
                type="text"
                maxlength="6"
                inputmode="numeric"
                pattern="[0-9]*"
                placeholder="请输入 6 位验证码"
                @keyup.enter="handleSmsSubmit"
                autofocus
                class="input-field text-center text-2xl tracking-[0.5em] font-mono font-bold"
              />
            </div>
          </div>

          <!-- 底部操作按钮 -->
          <div class="flex items-center justify-end gap-3 mt-6 pt-4 border-t border-dark-700/50">
            <button 
              @click="emit('cancel')"
              class="px-4 py-2 rounded-lg text-dark-400 hover:text-dark-200 hover:bg-dark-800/50 transition-colors text-sm"
            >
              取消
            </button>
            <button 
              v-if="type === 'sms'"
              @click="handleSmsSubmit"
              :disabled="!smsCode || smsCode.length !== 6"
              class="flex items-center gap-2 px-5 py-2 rounded-lg bg-primary hover:bg-primary/90 text-white font-medium transition-all shadow-lg shadow-primary/25 disabled:opacity-50 disabled:cursor-not-allowed active:scale-[0.98] text-sm"
            >
              <Send class="w-4 h-4" /> 提交验证
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.input-field {
  width: 100%;
  padding: 14px 16px;
  background: rgba(15,23,42,0.7);
  border: 2px solid rgba(51,65,85,0.5);
  border-radius: 12px;
  color: #f1f5f9;
  outline: none;
  transition: all 0.25s;
}
.input-field:focus {
  border-color: rgba(6,182,212,0.6);
  box-shadow: 0 0 0 4px rgba(6,182,212,0.08);
}
.input-field::placeholder {
  color: #475569;
  letter-spacing: normal;
  font-size: 13px;
  font-weight: normal;
}

.captcha-modal-enter-active,
.captcha-modal-leave-active {
  transition: opacity 0.25s ease;
}
.captcha-modal-enter-active .glass-card,
.captcha-modal-leave-active .glass-card {
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.captcha-modal-enter-from,
.captcha-modal-leave-to {
  opacity: 0;
}
.captcha-modal-enter-from .glass-card,
.captcha-modal-leave-to .glass-card {
  transform: scale(0.92) translateY(16px);
}
</style>