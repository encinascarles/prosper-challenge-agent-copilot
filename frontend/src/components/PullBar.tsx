// The slim bar under the top bar while the editor is on a pull request: which
// one, what it is based on, and what to do with it (try it, merge it, or go
// back to live).
//
// Merging takes the saved copy, so it waits for the save. A pull request based
// on a version that is no longer live cannot merge: its copy is of an older
// agent, and merging it would undo what was merged since. The bar says so
// where the button is.

import { ArrowLeft, GitMerge, GitPullRequestArrow, Phone } from 'lucide-react'

import type { PullSummary } from '@/agents/types'
import { Button } from '@/components/ui/button'
import { basedOn, isStale, mergeBlocker, mergeLabel, pullLabel } from '@/pulls/model'

type Props = {
  pull: PullSummary
  live: number
  dirty: boolean
  merging: boolean
  /** A test call is on screen: merging would end it and change the graph under it. */
  callOpen: boolean
  /** Why the last merge was refused, when it was not about a card. */
  problem: string | null
  /** Why a test call cannot be placed now, or null. */
  callBlocker: string | null
  onTry: () => void
  onMerge: () => void
  onBack: () => void
}

const dot = <span className="text-muted-foreground/60">·</span>

export function PullBar({ pull, live, dirty, merging, callOpen, problem, callBlocker, onTry, onMerge, onBack }: Props) {
  const stale = isStale(pull, live)
  const blocker = mergeBlocker(pull, live, dirty) ?? (callOpen ? 'Close the test call first.' : null)
  return (
    <div className="flex h-10 shrink-0 items-center gap-2 border-b bg-brand-tint/40 px-4 text-[12.5px]">
      <GitPullRequestArrow className="size-3.5 shrink-0 text-brand" />
      <span className="shrink-0 font-semibold tabular-nums">{pullLabel(pull.number)}</span>
      {dot}
      <span className="max-w-[320px] truncate">{pull.title}</span>
      {dot}
      <span className="shrink-0 text-muted-foreground tabular-nums">
        {stale && <span className="font-medium text-warn">Needs update · </span>}
        {basedOn(pull)}
      </span>
      <div className="ml-auto flex shrink-0 items-center gap-1.5">
        {problem && (
          <span role="alert" className="mr-1 max-w-[44ch] truncate text-bad" title={problem}>
            {problem}
          </span>
        )}
        <span title={callBlocker ?? undefined} className="flex">
          <Button size="sm" variant="outline" className="h-7 bg-card text-[12.5px]" disabled={callBlocker !== null} onClick={onTry}>
            <Phone className="size-3.5" /> Try it
          </Button>
        </span>
        <span title={blocker ?? undefined} className="flex">
          <Button size="sm" className="h-7 text-[12.5px]" disabled={blocker !== null || merging} onClick={onMerge}>
            <GitMerge className="size-3.5" /> {merging ? 'Merging…' : mergeLabel(pull, live)}
          </Button>
        </span>
        {live > 0 && (
          <>
            <span className="mx-1 h-4 w-px bg-border" />
            <Button size="sm" variant="ghost" className="h-7 text-[12.5px] text-muted-foreground" onClick={onBack}>
              <ArrowLeft className="size-3.5" /> Back to live
            </Button>
          </>
        )}
      </div>
    </div>
  )
}
