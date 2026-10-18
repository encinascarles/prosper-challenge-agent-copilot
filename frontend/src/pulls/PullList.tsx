// The agent's pull requests: every proposed change, open, merged or closed, as
// a dense list. A row is the pull request's number and title, one muted line
// on what it is based on (or what became of it), its checks while it is open,
// and when it last changed.

import { GitMerge, GitPullRequestArrow, GitPullRequestClosed, Plus } from 'lucide-react'
import { useState } from 'react'

import type { Agent, PullSummary } from '@/agents/types'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { ChecksLine } from '@/suite/bits'
import { pullChecks } from '@/suite/model'

import { PullIcon } from './bits'
import { isStale, pullLabel, pullMeta, versionLabel, when } from './model'

type State = PullSummary['state']

const TABS: [State, string, React.ReactNode][] = [
  ['open', 'Open', <GitPullRequestArrow key="open" className="size-3.5" />],
  ['merged', 'Merged', <GitMerge key="merged" className="size-3.5" />],
  ['closed', 'Closed', <GitPullRequestClosed key="closed" className="size-3.5" />],
]

type Props = {
  agent: Agent
  /** Null while they load. */
  pulls: PullSummary[] | null
  onOpen: (number: number) => void
  onNew: () => void
}

export function PullList({ agent, pulls, onOpen, onNew }: Props) {
  const [tab, setTab] = useState<State>('open')
  const live = agent.live_version
  const rows = (pulls ?? []).filter((pull) => pull.state === tab)
  const newBlocker = live === 0 ? 'Merge PR #1 first: it puts the agent live as v1.' : null
  return (
    <div className="min-w-0 flex-1 overflow-auto bg-muted/20">
      <div className="mx-auto max-w-[980px] px-8 pt-7 pb-16">
        <div className="flex items-start gap-4">
          <div className="min-w-0 flex-1">
            <h1 className="text-[18px] font-semibold tracking-[-0.01em]">Pull requests</h1>
            <p className="mt-0.5 text-[13px] text-muted-foreground">
              Proposed changes to {agent.name || 'this agent'}. Calls keep using the live version until you merge.
            </p>
          </div>
          <span title={newBlocker ?? `Based on ${versionLabel(live)}: edit it in Build`} className="flex shrink-0">
            <Button size="sm" disabled={newBlocker !== null} onClick={onNew}>
              <Plus className="size-3.5" /> New pull request
            </Button>
          </span>
        </div>
        <div className="mt-5 overflow-hidden rounded-xl border bg-card shadow-xs">
          <div role="tablist" className="flex h-11 items-center gap-1 border-b bg-muted/30 px-3">
            {TABS.map(([state, label, icon]) => (
              <button
                key={state}
                role="tab"
                aria-selected={tab === state}
                onClick={() => setTab(state)}
                className={cn(
                  'flex h-7 items-center gap-1.5 rounded-md px-2.5 text-[13px] outline-none focus-visible:ring-2 focus-visible:ring-ring/50',
                  tab === state ? 'bg-background font-medium shadow-xs ring-1 ring-border' : 'text-muted-foreground hover:text-foreground',
                )}
              >
                {icon}
                {label}
                <span className="font-normal text-muted-foreground tabular-nums">
                  {(pulls ?? []).filter((pull) => pull.state === state).length}
                </span>
              </button>
            ))}
          </div>
          {rows.map((pull) => (
            <button
              key={pull.number}
              onClick={() => onOpen(pull.number)}
              className="flex w-full items-start gap-3 border-b px-4 py-2.5 text-left outline-none last:border-b-0 hover:bg-muted/40 focus-visible:bg-muted/40"
            >
              <PullIcon pull={pull} className="mt-0.5" />
              <span className="min-w-0 flex-1">
                <span className="flex items-baseline gap-2">
                  <span className="shrink-0 text-[12.5px] text-muted-foreground tabular-nums">{pullLabel(pull.number)}</span>
                  <span className="truncate text-[13.5px] font-medium">{pull.title}</span>
                </span>
                <span
                  className={cn(
                    'mt-0.5 block truncate text-[12px] text-muted-foreground tabular-nums',
                    isStale(pull, live) && 'text-warn',
                  )}
                >
                  {pullMeta(pull, live)}
                </span>
              </span>
              {pullChecks(pull) && <ChecksLine checks={pullChecks(pull)} className="shrink-0 pt-0.5 text-[12px]" />}
              <span className="w-16 shrink-0 pt-0.5 text-right text-[12px] text-muted-foreground tabular-nums">
                {when(pull.updated_at)}
              </span>
            </button>
          ))}
          {pulls === null ? (
            <p className="px-4 py-8 text-center text-[13px] text-muted-foreground">Loading…</p>
          ) : (
            rows.length === 0 && (
              <p className="px-4 py-8 text-center text-[13px] text-muted-foreground">
                No {tab} pull requests.
                {tab === 'open' && live > 0 ? ' Edit the flow in Build, or start one with New pull request.' : ''}
              </p>
            )
          )}
        </div>
      </div>
    </div>
  )
}
