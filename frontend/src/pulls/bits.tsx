// Small pieces every place that shows a pull request shares: its icon and its
// state badge. Open is the orange of a proposed change; merged and closed are
// history, in greys.

import { GitMerge, GitPullRequestArrow, GitPullRequestClosed } from 'lucide-react'

import type { PullSummary } from '@/agents/types'
import { cn } from '@/lib/utils'

import { versionLabel } from './model'

export function PullIcon({ pull, className }: { pull: Pick<PullSummary, 'state'>; className?: string }) {
  const base = cn('size-4 shrink-0', className)
  if (pull.state === 'merged') return <GitMerge className={cn(base, 'text-foreground/70')} />
  if (pull.state === 'closed') return <GitPullRequestClosed className={cn(base, 'text-muted-foreground')} />
  return <GitPullRequestArrow className={cn(base, 'text-brand')} />
}

export function StateBadge({ pull }: { pull: PullSummary }) {
  const base = 'inline-flex h-6 shrink-0 items-center gap-1 rounded-full px-2 text-[12px] font-medium tabular-nums'
  if (pull.state === 'merged') {
    return (
      <span className={cn(base, 'bg-foreground text-background')}>
        <GitMerge className="size-3.5" /> Merged as {versionLabel(pull.merged_version ?? 0)}
      </span>
    )
  }
  if (pull.state === 'closed') {
    return (
      <span className={cn(base, 'bg-muted text-muted-foreground')}>
        <GitPullRequestClosed className="size-3.5" /> Closed
      </span>
    )
  }
  return (
    <span className={cn(base, 'border bg-card')}>
      <PullIcon pull={pull} className="size-3.5" /> Open
    </span>
  )
}

export const Dot = () => <span className="text-muted-foreground/60">·</span>
