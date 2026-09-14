import { useState } from 'react'
import { Navigate, useNavigate } from 'react-router'
import { PackageEditor } from '@/components/admin/PackageEditor'
import { PackageList } from '@/components/admin/PackageList'
import { PageHeader } from '@/components/PageHeader'
import { FEATURE_ADMIN_PACKAGES } from '@/env'

/**
 * 管理端技能包页（/admin/packages，仅超级用户；后端非超级用户返回 403）。
 * 列表 ↔ 编辑器切换为页面内状态，不另造路由状态；刷新 / 深链回到列表。
 */
export default function AdminPackagesPage() {
  const navigate = useNavigate()
  const [selectedPackageId, setSelectedPackageId] = useState<string | null>(null)

  if (!FEATURE_ADMIN_PACKAGES) {
    return <Navigate to="/" replace />
  }

  return (
    <div className="relative flex h-full min-h-0 min-w-0">
      <div className="chat-bg" aria-hidden="true" />
      <main className="relative z-10 flex min-w-0 flex-1 flex-col">
        <PageHeader
          title={selectedPackageId === null ? '技能包管理' : '编辑技能包'}
          onBack={
            selectedPackageId === null ? () => navigate('/') : () => setSelectedPackageId(null)
          }
        />
        <div className="flex-1 overflow-y-auto">
          {selectedPackageId === null ? (
            <PackageList onOpen={setSelectedPackageId} />
          ) : (
            <PackageEditor packageId={selectedPackageId} />
          )}
        </div>
      </main>
    </div>
  )
}
