import { Camera, Loader2 } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { PASSWORD_MIN_LENGTH } from '@/env'
import { avatarUrl, changePassword, fetchAvatarConfig, uploadAvatar } from '@/lib/api'
import { mapHttpError } from '@/lib/errors'
import { useAuthStore } from '@/stores/auth'
import type { AvatarConfig } from '@/types'

/**
 * 个人中心内容区（用户中心左导航「个人中心」菜单切换进入，非独立页面）：
 * - 账号卡模仿侧栏底部账号区：头像 + 昵称 + 手机号横排；
 * - 账号信息只读展示：账号 ID / 昵称 / 手机号 / 注册时间 / 最近登录；
 * - 点相机展开「更换头像」面板（格式 / 体积 / 边长约束在此显示，不常驻）；
 * - 修改密码：仅提供入口按钮，点击后才展开表单（不常驻）。
 * 变更成功后经 auth store applyAccount 同步侧栏账号展示。
 */

/** 加载图片真实宽高；读不出返回 null */
function loadImageDimensions(file: File): Promise<{ width: number; height: number } | null> {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file)
    const img = new Image()
    img.onload = () => {
      URL.revokeObjectURL(url)
      resolve({ width: img.naturalWidth, height: img.naturalHeight })
    }
    img.onerror = () => {
      URL.revokeObjectURL(url)
      resolve(null)
    }
    img.src = url
  })
}

/** ISO 时间 → `YYYY-MM-DD HH:mm`（本地时区） */
function formatDateTime(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  const pad = (n: number): string => `${n}`.padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

/** 账号信息只读行：左侧标签 + 右侧值 */
function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4 px-5 py-3">
      <span className="flex-shrink-0 text-[13px] text-text-3">{label}</span>
      <span className="min-w-0 truncate text-[13px] text-text-1" title={value}>
        {value}
      </span>
    </div>
  )
}

export function ProfilePage() {
  const account = useAuthStore((s) => s.account)
  const applyAccount = useAuthStore((s) => s.applyAccount)

  const [avatarConfig, setAvatarConfig] = useState<AvatarConfig | null>(null)
  const [uploading, setUploading] = useState(false)
  const [avatarPickerOpen, setAvatarPickerOpen] = useState(false)
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  const [showPasswordForm, setShowPasswordForm] = useState(false)
  const [oldPassword, setOldPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [changingPassword, setChangingPassword] = useState(false)

  // 进入页面即拉取头像约束（失败静默，界面降级为占位文案）
  useEffect(() => {
    void fetchAvatarConfig()
      .then(setAvatarConfig)
      .catch(() => {})
  }, [])

  const handleAvatarFile = useCallback(
    async (file: File | null) => {
      if (file === null || avatarConfig === null) return
      const dot = file.name.lastIndexOf('.')
      const ext = dot >= 0 ? file.name.slice(dot + 1).toLowerCase() : ''
      if (!avatarConfig.allowed_extensions.includes(ext)) {
        toast.warning(`头像仅支持 ${avatarConfig.allowed_extensions.join(' / ')} 格式`)
        return
      }
      if (file.size > avatarConfig.max_size_bytes) {
        toast.warning(`头像不能超过 ${(avatarConfig.max_size_bytes / 1024 / 1024).toFixed(1)} MB`)
        return
      }
      const dims = await loadImageDimensions(file)
      if (dims === null) {
        toast.error('无法读取图片内容，请换一张图片')
        return
      }
      const smaller = Math.min(dims.width, dims.height)
      const larger = Math.max(dims.width, dims.height)
      if (smaller < avatarConfig.min_dimension || larger > avatarConfig.max_dimension) {
        toast.warning(
          `图片边长须在 ${avatarConfig.min_dimension}~${avatarConfig.max_dimension}px 之间（当前 ${dims.width}×${dims.height}）`,
        )
        return
      }
      setUploading(true)
      try {
        const updated = await uploadAvatar(file)
        applyAccount(updated)
        toast.success('头像已更新')
        setAvatarPickerOpen(false)
      } catch (error) {
        toast.error(mapHttpError(error).message)
      } finally {
        setUploading(false)
        if (fileInputRef.current !== null) fileInputRef.current.value = ''
      }
    },
    [avatarConfig, applyAccount],
  )

  const handleChangePassword = useCallback(async () => {
    if (oldPassword === '') {
      toast.warning('请填写原密码')
      return
    }
    if (newPassword.length < PASSWORD_MIN_LENGTH) {
      toast.warning(`新密码至少 ${PASSWORD_MIN_LENGTH} 位`)
      return
    }
    if (newPassword !== confirmPassword) {
      toast.warning('两次输入的新密码不一致')
      return
    }
    setChangingPassword(true)
    try {
      const updated = await changePassword({ old_password: oldPassword, new_password: newPassword })
      applyAccount(updated)
      toast.success('密码已修改')
      setShowPasswordForm(false)
      setOldPassword('')
      setNewPassword('')
      setConfirmPassword('')
    } catch (error) {
      toast.error(mapHttpError(error).message)
    } finally {
      setChangingPassword(false)
    }
  }, [oldPassword, newPassword, confirmPassword, applyAccount])

  if (account === null) return null

  const avatarSrc = avatarUrl(account.avatar)
  const initial = (account.name ?? '').trim().charAt(0) || '?'

  return (
    <div className="mx-auto w-full max-w-[600px] px-4 pb-10 pt-6 sm:px-6">
      {/* 账号卡：模仿侧栏底部账号区（头像 + 昵称 + 手机号横排） */}
      <section className="rounded-xl border border-border bg-surface-1 p-5">
        <div className="flex items-center gap-4">
          <div className="relative flex-shrink-0">
            {avatarSrc !== null ? (
              <img
                src={avatarSrc}
                alt="头像"
                className="h-16 w-16 rounded-full object-cover ring-1 ring-border"
              />
            ) : (
              <span className="flex h-16 w-16 items-center justify-center rounded-full bg-brand-gradient text-xl font-semibold text-white">
                {initial}
              </span>
            )}
            <button
              type="button"
              onClick={() => setAvatarPickerOpen((open) => !open)}
              disabled={uploading}
              className="absolute -bottom-1 -right-1 flex h-7 w-7 cursor-pointer items-center justify-center rounded-full bg-surface-2 text-text-2 ring-1 ring-border transition-colors hover:bg-surface-hover hover:text-text-1 disabled:cursor-not-allowed disabled:opacity-50"
              title="更换头像"
            >
              <Camera className="h-3.5 w-3.5" />
            </button>
          </div>
          <div className="min-w-0">
            <p className="truncate text-lg font-semibold text-text-1">{account.name}</p>
            <p className="mt-0.5 text-[13px] text-text-3">{account.phone}</p>
          </div>
        </div>

        {/* 更换头像面板（点相机展开，约束文案仅在此显示） */}
        {avatarPickerOpen && (
          <div className="mt-4 border-t border-border pt-4">
            <p className="text-[12px] text-text-3">
              {avatarConfig === null
                ? '头像：图片，≤2MB，边长 32~512px'
                : `头像：${avatarConfig.allowed_extensions.join('/')}，≤${(avatarConfig.max_size_bytes / 1024 / 1024).toFixed(1)}MB，边长 ${avatarConfig.min_dimension}~${avatarConfig.max_dimension}px`}
            </p>
            <div className="mt-2.5 flex gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => fileInputRef.current?.click()}
                disabled={uploading}
              >
                {uploading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : '选择图片'}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setAvatarPickerOpen(false)}
                disabled={uploading}
              >
                取消
              </Button>
            </div>
            <input
              ref={fileInputRef}
              type="file"
              accept={avatarConfig?.allowed_extensions.map((e) => `.${e}`).join(',')}
              className="hidden"
              onChange={(event) => {
                void handleAvatarFile(event.target.files?.[0] ?? null)
              }}
            />
          </div>
        )}
      </section>

      {/* 账号信息（只读展示） */}
      <section className="mt-4 overflow-hidden rounded-xl border border-border bg-surface-1">
        <div className="divide-y divide-border">
          <InfoRow label="昵称" value={account.name} />
          <InfoRow label="手机号" value={account.phone} />
          <InfoRow label="注册时间" value={formatDateTime(account.created_at)} />
          <InfoRow
            label="最近登录"
            value={account.last_login_at === null ? '—' : formatDateTime(account.last_login_at)}
          />
        </div>
      </section>

      {/* 修改密码（点击展开，不常驻） */}
      <section className="mt-4 rounded-xl border border-border bg-surface-1 p-5">
        <Button
          variant="outline"
          className="w-full"
          onClick={() => setShowPasswordForm((open) => !open)}
        >
          {showPasswordForm ? '收起修改' : '修改密码'}
        </Button>
        {showPasswordForm && (
          <div className="mt-3 flex flex-col gap-2.5">
            <Input
              type="password"
              value={oldPassword}
              onChange={(event) => setOldPassword(event.target.value)}
              placeholder="原密码"
              autoComplete="current-password"
            />
            <Input
              type="password"
              value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)}
              placeholder={`新密码（至少 ${PASSWORD_MIN_LENGTH} 位）`}
              autoComplete="new-password"
            />
            <Input
              type="password"
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
              placeholder="确认新密码"
              autoComplete="new-password"
            />
            <Button onClick={handleChangePassword} disabled={changingPassword}>
              {changingPassword ? (
                <>
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  修改中…
                </>
              ) : (
                '确认修改'
              )}
            </Button>
          </div>
        )}
      </section>
    </div>
  )
}
