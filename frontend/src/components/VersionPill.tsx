// The pill next to the agent's name: what the editor is on, and the way to
// move to something else.
//
// It reads `v2 · live` on the live version and `PR #5 · <title>`, with the
// orange pull request icon, on a pull request: the orange says this is a
// proposed change, not what callers get. Its popover lists live, the open pull
// requests and "New pull request", which needs a live version to copy.

import { Check, ChevronsUpDown, GitPullRequestArrow, Plus } from 'lucide-react'
import { useState } from 'react'

import type { Agent, PullSummary, VersionSummary } from '@/agents/types'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { cn } from '@/lib/utils'
import { basedOn, isStale, pullLabel, versionLabel, type On } from '@/pulls/model'

type Props = {
  agent: Agent
  pulls: PullSummary[] // the open ones, newest first
  versions: VersionSummary[] // live first
  on: On
  onSwitch: (on: On) => void
  onNewPull: () => void
}

const head = 'px-2 pt-2 pb-1 text-[11px] font-medium tracking-wide text-muted-foreground uppercase'
const row = 'flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left outline-none hover:bg-muted focus-visible:bg-muted'

export function VersionPill({ agent, pulls, versions, on, onSwitch, onNewPull }: Props) {
  const [open, setOpen] = useState(false)
  const pull = on === null ? undefined : pulls.find((p) => p.number === on)
  const live = agent.live_version
  const current = versions.find((version) => version.number === live)
  const go = (then: () => void) => {
    setOpen(false)
    then()
  }
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        aria-label="Version"
        className={cn(
          'ml-1 flex h-7 max-w-[340px] min-w-0 items-center gap-1.5 rounded-full border px-2.5 text-[12px] font-medium tabular-nums outline-none hover:bg-muted focus-visible:bg-muted data-[state=open]:bg-muted',
          pull && 'border-brand/40 bg-brand-tint/60 hover:bg-brand-tint data-[state=open]:bg-brand-tint',
        )}
      >
        {pull ? (
          <>
            <GitPullRequestArrow className="size-3.5 shrink-0 text-brand" />
            <span className="shrink-0">{pullLabel(pull.number)}</span>
            <span className="truncate font-normal text-foreground/80">· {pull.title}</span>
          </>
        ) : (
          <>
            <span className="size-1.5 rounded-full bg-emerald-500" /> {versionLabel(live)} · live
          </>
        )}
        <ChevronsUpDown className="size-3 shrink-0 text-muted-foreground" />
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[360px] p-1.5">
        <div className={head}>Live</div>
        {live > 0 ? (
          <button className={row} onClick={() => go(() => onSwitch(null))}>
            <span className="flex size-4 items-center justify-center">
              <span className="size-2 rounded-full bg-emerald-500" />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-[13px] font-medium tabular-nums">{versionLabel(live)} · answering calls</span>
              {current?.pull != null && (
                <span className="block truncate text-[11.5px] text-muted-foreground tabular-nums">
                  From {pullLabel(current.pull)} · {current.title}
                </span>
              )}
            </span>
            {on === null && <Check className="size-3.5 text-muted-foreground" />}
          </button>
        ) : (
          <p className="px-2 pb-1.5 text-[12.5px] text-muted-foreground">
            Not live yet. Merging PR #1 puts it live as v1.
          </p>
        )}
        <div className={cn(head, 'mt-1 border-t pt-2.5')}>
          Open pull requests <span className="font-normal tabular-nums">{pulls.length}</span>
        </div>
        {pulls.length === 0 && <p className="px-2 pb-1 text-[12.5px] text-muted-foreground">None.</p>}
        {pulls.map((p) => (
          <button key={p.number} className={row} onClick={() => go(() => onSwitch(p.number))}>
            <GitPullRequestArrow className="size-4 shrink-0 text-brand" />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[13px]">
                <span className="font-medium tabular-nums">{pullLabel(p.number)}</span> · {p.title}
              </span>
              <span className="block truncate text-[11.5px] text-muted-foreground tabular-nums">
                {isStale(p, live) ? <span className="font-medium text-warn">Needs update · </span> : null}
                {basedOn(p)}
              </span>
            </span>
            {on === p.number && <Check className="size-3.5 text-muted-foreground" />}
          </button>
        ))}
        <button
          className={cn(row, 'mt-1 text-[13px] text-muted-foreground hover:text-foreground disabled:pointer-events-none disabled:opacity-50')}
          disabled={live === 0}
          onClick={() => go(onNewPull)}
        >
          <span className="flex size-4 items-center justify-center">
            <Plus className="size-3.5" />
          </span>
          New pull request
          <span className="ml-auto text-[11.5px] tabular-nums">
            {live === 0 ? 'Merge PR #1 first' : `based on ${versionLabel(live)}`}
          </span>
        </button>
      </PopoverContent>
    </Popover>
  )
}
