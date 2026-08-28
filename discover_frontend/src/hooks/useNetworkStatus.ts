import { useEffect, useState } from 'react'

export interface UseNetworkStatusResult {
  isOnline: boolean
}

/** 网络状态：断网时用于顶部提示 / 暂停发送（生产健壮性） */
export function useNetworkStatus(): UseNetworkStatusResult {
  const [isOnline, setIsOnline] = useState<boolean>(navigator.onLine)

  useEffect(() => {
    const handleChange = (): void => setIsOnline(navigator.onLine)
    window.addEventListener('online', handleChange)
    window.addEventListener('offline', handleChange)
    return () => {
      window.removeEventListener('online', handleChange)
      window.removeEventListener('offline', handleChange)
    }
  }, [])

  return { isOnline }
}
