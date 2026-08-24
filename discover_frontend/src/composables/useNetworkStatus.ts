import { onMounted, onUnmounted, type Ref, ref } from 'vue'

export interface NetworkStatus {
  isOnline: Ref<boolean>
}

/** 网络状态：断网时用于顶部提示 / 暂停发送（生产健壮性） */
export function useNetworkStatus(): NetworkStatus {
  const isOnline = ref<boolean>(navigator.onLine)

  function handleChange(): void {
    isOnline.value = navigator.onLine
  }

  onMounted(() => {
    window.addEventListener('online', handleChange)
    window.addEventListener('offline', handleChange)
  })

  onUnmounted(() => {
    window.removeEventListener('online', handleChange)
    window.removeEventListener('offline', handleChange)
  })

  return { isOnline }
}
