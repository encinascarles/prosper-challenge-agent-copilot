// Small pieces the Calls and Issues pages share: an issue's state and severity
// icons, the hover button style, and "Play calls". Open issues are crimson
// (broken), never the orange: orange is what Prosper AI did.

import { CalendarX, CircleCheck, CircleDot, CircleSlash, Clock, Loader2, MessageCircleWarning, Play, ShieldAlert } from 'lucide-react'

import { cn } from '@/lib/utils'

import { SEVERITIES } from './model'
import type { IssueState, Severity } from './types'

export function IssueStateIcon({ state, className }: { state: IssueState; className?: string }) {
  const base = cn('size-4 shrink-0', className)
  switch (state) {
    case 'open':
      return <CircleDot aria-label="Open" className={cn(base, 'text-bad')} />
    case 'snoozed':
      return <Clock aria-label="Snoozed" className={cn(base, 'text-muted-foreground')} />
    case 'resolved':
      return <CircleCheck aria-label="Resolved" className={cn(base, 'text-emerald-600')} />
    case 'ignored':
      return <CircleSlash aria-label="Ignored" className={cn(base, 'text-muted-foreground/70')} />
  }
}

const SEVERITY_ICONS = { safety: ShieldAlert, booking: CalendarX, experience: MessageCircleWarning }

export function SeverityIcon({ severity, className }: { severity: Severity; className?: string }) {
  const Icon = SEVERITY_ICONS[severity]
  return (
    <span title={SEVERITIES[severity]} className="flex shrink-0">
      <Icon aria-label={SEVERITIES[severity]} className={cn('size-3.5 text-muted-foreground', className)} />
    </span>
  )
}

export const smallButton =
  'flex h-7 items-center gap-1 rounded-md border bg-card px-2.5 text-[12.5px] outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring/50 data-[state=open]:bg-muted disabled:pointer-events-none disabled:opacity-50'

type PlayProps = {
  /** Calls in, of how many, while a batch is going. */
  arriving: { done: number; of: number } | null
  /** Why it cannot play now, if it cannot. */
  blocker: string | null
  onPlay: () => void
  className?: string
}

/** Starts a batch of simulated calls on the live version, and says how it is coming in. */
export function PlayButton({ arriving, blocker, onPlay, className }: PlayProps) {
  if (arriving) {
    return (
      <span className={cn(smallButton, 'pointer-events-none text-muted-foreground', className)}>
        <Loader2 className="size-3.5 animate-spin" />
        {arriving.of ? `Calls coming in · ${arriving.done} of ${arriving.of}` : 'Picking callers…'}
      </span>
    )
  }
  return (
    <span title={blocker ?? 'Simulated callers phone the live version; Prosper AI reviews every call'} className="flex">
      <button disabled={blocker !== null} onClick={onPlay} className={cn(smallButton, className)}>
        <Play className="size-3.5" /> Play calls
      </button>
    </span>
  )
}
