// Small pieces every place that shows tests shares: a test's status icon and
// score, and the checks of a copy in one line. Passing is green, at risk
// (some runs failed) yellow, failing crimson, all sparingly: the colour is on
// the icon and the number, never on a whole row.

import { CircleAlert, CircleCheck, CircleDashed, CircleX, Loader2 } from 'lucide-react'

import type { Checks } from '@/agents/types'
import { cn } from '@/lib/utils'

import { checksText, scoreText, verdict, type Score } from './model'

const TONE = {
  pass: 'text-emerald-600',
  risk: 'text-warn',
  fail: 'text-bad',
  running: 'text-muted-foreground',
}

export function TestIcon({ score, className }: { score: Score | null; className?: string }) {
  const base = cn('size-4 shrink-0', className)
  if (score === null) return <CircleDashed className={cn(base, 'text-muted-foreground/60')} />
  const shown = verdict(score)
  if (shown === 'running') return <Loader2 className={cn(base, 'animate-spin text-muted-foreground')} />
  if (shown === 'pass') return <CircleCheck className={cn(base, TONE.pass)} />
  if (shown === 'risk') return <CircleAlert className={cn(base, TONE.risk)} />
  return <CircleX className={cn(base, TONE.fail)} />
}

export function ScoreText({ score, className }: { score: Score | null; className?: string }) {
  if (score === null) return <span className={cn('text-muted-foreground', className)}>not run</span>
  return <span className={cn('tabular-nums', TONE[verdict(score)], className)}>{scoreText(score)}</span>
}

/** A copy's checks in one line: "✓ Checks 5/5", "✕ 2 tests failing", "Checks running…". */
export function ChecksLine({ checks, bare = false, className }: { checks: Checks | null; bare?: boolean; className?: string }) {
  const base = cn('flex items-center gap-1 whitespace-nowrap tabular-nums', className)
  if (checks === null) return <span className={cn(base, 'text-muted-foreground')}>{checksText(null, bare)}</span>
  if (checks.state === 'running') {
    return (
      <span className={cn(base, 'text-muted-foreground')}>
        <Loader2 className="size-3.5 animate-spin text-brand" /> {checksText(checks, bare)}
      </span>
    )
  }
  if (checks.state === 'passed') {
    return (
      <span className={cn(base, 'text-emerald-700 dark:text-emerald-500')}>
        <CircleCheck className="size-3.5" /> {checksText(checks, bare)}
      </span>
    )
  }
  return (
    <span className={cn(base, checks.state === 'stopped' ? 'text-warn' : 'text-bad')}>
      <CircleX className="size-3.5" /> {checksText(checks, bare)}
    </span>
  )
}
