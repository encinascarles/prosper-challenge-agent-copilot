// A pull request's page: where a proposed change is read and decided on. Its
// title (yours to rename while it is open), its state and what it is based
// on, what to do with it (open it in Build, try it, merge it, update it if live
// moved on, close or reopen it), and three tabs: the Conversation, its log;
// the Changes, what it changes compared with the version it is based on,
// rules and tests included; and the Checks, how its tests went on its copy. A
// merge waits for those.
//
// Updating replays the pull request's changes on the live version (see
// pulls/diff.ts) and sends the result: where both changed the same text, the
// pull request's text is kept, and its event says where.

import { ArrowLeft, GitMerge, GitPullRequestArrow, GitPullRequestClosed, MoreHorizontal, Phone, RefreshCw } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'

import { closePull, getPull, getVersion, mergePull, renamePull, reopenPull, updatePull } from '@/agents/api'
import type { Agent, AgentCopy, Pull, Suite } from '@/agents/types'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { callBlocker, checkFlow } from '@/draft/checks'
import { openDraft } from '@/draft/draft'
import { cn } from '@/lib/utils'
import { ChecksLine } from '@/suite/bits'
import { suiteChanges, summarize } from '@/suite/model'
import { useChecks } from '@/suite/useChecks'

import { Dot, StateBadge } from './bits'
import { diffAgents, NOTHING, rebase, updateSummary } from './diff'
import { basedOn, callsNote, isStale, mergeBlocker, mergeLabel, pullLabel, versionLabel } from './model'
import { PullChanges } from './PullChanges'
import { PullChecks } from './PullChecks'
import { PullTimeline } from './PullTimeline'

type Props = {
  agent: Agent
  number: number
  onBack: () => void
  onOpenInBuild: (number: number) => void
  onTry: (number: number) => void
  /** The pull request changed: what lists it, and the agent, may be out of date. */
  onChanged: () => void
  onToast: (text: string) => void
}

type Tab = 'conversation' | 'changes' | 'checks'

type Copy = AgentCopy & Suite

const EMPTY: Copy = { config: NOTHING, layout: {}, rules: [], tests: [] }

/** The title, renamed in place: Enter or leaving it keeps it, Escape takes it back. */
function TitleInput({ title, onRename }: { title: string; onRename: (title: string) => void }) {
  const [text, setText] = useState(title)
  const undo = useRef(false)
  return (
    <input
        aria-label="Pull request title"
        value={text}
        onChange={(event) => setText(event.target.value)}
        onBlur={() => {
          if (undo.current || !text.trim()) setText(title)
          else if (text.trim() !== title) onRename(text.trim())
          undo.current = false
        }}
        onKeyDown={(event) => {
          if (event.key === 'Enter') event.currentTarget.blur()
          if (event.key === 'Escape') {
            undo.current = true
            event.currentTarget.blur()
          }
        }}
        title="Rename"
        className="field-sizing-content -ml-1.5 max-w-[560px] min-w-[6ch] rounded-md border border-transparent bg-transparent px-1.5 font-semibold outline-none hover:border-border focus:border-foreground/30 focus:bg-card"
      />
  )
}

export function PullPage({ agent, number, onBack, onOpenInBuild, onTry, onChanged, onToast }: Props) {
  const live = agent.live_version
  const [pull, setPull] = useState<Pull | null>(null)
  // The version it is based on, which its changes are compared with.
  const [fetched, setFetched] = useState<{ number: number; copy: Copy } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('conversation')
  // Its checks, read again while they run. An update starts them again.
  const [revision, setRevision] = useState(0)
  const checks = useChecks(agent.id, number, 0, revision)

  useEffect(() => {
    let stale = false
    getPull(agent.id, number).then(
      (loaded) => !stale && setPull(loaded),
      (failure: Error) => !stale && setError(failure.message),
    )
    return () => {
      stale = true
    }
  }, [agent.id, number])

  const baseVersion = pull?.base_version ?? null
  useEffect(() => {
    if (!baseVersion) return
    let stale = false
    getVersion(agent.id, baseVersion).then(
      (version) => !stale && setFetched({ number: baseVersion, copy: version }),
      (failure: Error) => !stale && setError(failure.message),
    )
    return () => {
      stale = true
    }
  }, [agent.id, baseVersion])
  // A setup is based on nothing: everything in it is new.
  const base = baseVersion === 0 ? EMPTY : fetched?.number === baseVersion ? fetched.copy : null

  const changes = useMemo(() => (pull && base ? diffAgents(base.config, pull.config) : null), [pull, base])
  const suite = useMemo(() => (pull && base ? suiteChanges(base, pull) : null), [pull, base])
  // What would stop a test call of its copy, as the editor would say it.
  const callStop = useMemo(() => (pull ? callBlocker(false, checkFlow(openDraft(pull.config))) : null), [pull])

  if (error) return <p className="m-auto text-sm text-bad">{error}</p>
  if (!pull) return <p className="m-auto text-sm text-muted-foreground">Loading…</p>

  // One action at a time; what it answers replaces the pull request shown.
  const act = async (name: string, action: () => Promise<Pull>, done?: (pull: Pull) => string) => {
    if (busy) return
    setBusy(name)
    setProblem(null)
    try {
      const changed = await action()
      setPull(changed)
      setRevision((n) => n + 1)
      onChanged()
      if (done) onToast(done(changed))
    } catch (failure) {
      setProblem((failure as Error).message)
    } finally {
      setBusy(null)
    }
  }

  // Its changes since its base, replayed on live.
  const update = () =>
    act(
      'update',
      async () => {
        const [from, onto] = await Promise.all([
          base ?? getVersion(agent.id, pull.base_version),
          getVersion(agent.id, live),
        ])
        const rebased = rebase(from, pull, onto)
        const updated = await updatePull(agent.id, number, rebased, live, updateSummary(rebased, live))
        setFetched({ number: live, copy: onto })
        return updated
      },
      (updated) => {
        const said = updated.events.at(-1)?.summary
        return `${pullLabel(number)} updated to ${versionLabel(live)}${said ? ` · ${said}` : ''}`
      },
    )

  const open = pull.state === 'open'
  const stale = isStale(pull, live)
  const checksNow = checks.run === undefined ? pull.checks : summarize(checks.run)
  const blocker = mergeBlocker(pull, live, false, checksNow)
  const note = callsNote(pull, live)
  // PR #1 of an agent not live yet is how it goes live: it is not closed.
  const closable = open && !(pull.kind === 'setup' && live === 0)
  const suiteCount = suite
    ? suite.rulesAdded.length + suite.rulesRemoved.length + suite.testsAdded.length + suite.testsRemoved.length
    : 0
  const tabs: [Tab, string, React.ReactNode][] = [
    ['conversation', 'Conversation', null],
    ['changes', 'Changes', (changes?.length ?? 0) + suiteCount || null],
    ['checks', 'Checks', pull.tests.length ? <ChecksLine key="checks" checks={checksNow} className="text-[12px]" /> : null],
  ]

  return (
    <div className="min-w-0 flex-1 overflow-auto bg-muted/20">
      <div className="sticky top-0 z-30 border-b bg-background">
        <div className="mx-auto max-w-[980px] px-8 pt-5">
          <button
            onClick={onBack}
            className="-ml-1.5 flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[12.5px] text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <ArrowLeft className="size-3.5" /> Pull requests
          </button>
          <div className="mt-3 flex items-start gap-4">
            <div className="min-w-0 flex-1">
              <h1 className="flex items-baseline gap-2 text-[20px] font-semibold tracking-[-0.015em]">
                {open ? (
                  <TitleInput
                    key={pull.title}
                    title={pull.title}
                    onRename={(title) => void act('rename', () => renamePull(agent.id, number, title))}
                  />
                ) : (
                  <span className="min-w-0 truncate">{pull.title}</span>
                )}
                <span className="shrink-0 font-normal text-muted-foreground tabular-nums">{pullLabel(number)}</span>
              </h1>
              <div className="mt-1.5 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[12.5px] text-muted-foreground tabular-nums">
                <StateBadge pull={pull} />
                <span className={cn('ml-1', stale && 'font-medium text-warn')}>
                  {stale ? `Needs update · ${basedOn(pull)}` : basedOn(pull)}
                </span>
                {note && (
                  <>
                    <Dot />
                    <span>{note}</span>
                  </>
                )}
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              {open && (
                <>
                  <Button size="sm" variant="outline" onClick={() => onOpenInBuild(number)}>
                    Open in Build
                  </Button>
                  <span title={callStop ?? undefined} className="flex">
                    <Button size="sm" variant="outline" disabled={callStop !== null} onClick={() => onTry(number)}>
                      <Phone className="size-3.5" /> Try it
                    </Button>
                  </span>
                  {stale ? (
                    <Button size="sm" disabled={busy !== null} onClick={() => void update()}>
                      <RefreshCw className={cn('size-3.5', busy === 'update' && 'animate-spin')} />
                      {busy === 'update' ? 'Updating…' : 'Update'}
                    </Button>
                  ) : (
                    <span title={blocker ?? undefined} className="flex">
                      <Button
                        size="sm"
                        disabled={blocker !== null || busy !== null}
                        onClick={() =>
                          void act('merge', () => mergePull(agent.id, number), (merged) =>
                            `${pullLabel(number)} merged · ${versionLabel(merged.merged_version ?? 0)} is live`,
                          )
                        }
                      >
                        <GitMerge className="size-3.5" /> {busy === 'merge' ? 'Merging…' : mergeLabel(pull, live)}
                      </Button>
                    </span>
                  )}
                </>
              )}
              {pull.state === 'closed' && (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={busy !== null}
                  onClick={() => void act('reopen', () => reopenPull(agent.id, number), () => `${pullLabel(number)} reopened`)}
                >
                  <GitPullRequestArrow className="size-3.5" /> Reopen
                </Button>
              )}
              {closable && (
                <DropdownMenu>
                  <DropdownMenuTrigger
                    aria-label="More"
                    className="flex size-8 items-center justify-center rounded-md border bg-card outline-none hover:bg-muted data-[state=open]:bg-muted"
                  >
                    <MoreHorizontal className="size-4" />
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end" className="w-52">
                    <DropdownMenuItem
                      onSelect={() => void act('close', () => closePull(agent.id, number), () => `${pullLabel(number)} closed`)}
                    >
                      <GitPullRequestClosed /> Close pull request
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              )}
            </div>
          </div>
          {problem && (
            <p role="alert" className="mt-3 text-[12.5px] text-bad">
              {problem}
            </p>
          )}
          <nav role="tablist" className="mt-4 -mb-px flex gap-1">
            {tabs.map(([key, label, count]) => (
              <button
                key={key}
                role="tab"
                aria-selected={tab === key}
                onClick={() => setTab(key)}
                className={cn(
                  'flex h-9 items-center gap-1.5 border-b-2 px-3 text-[13px]',
                  tab === key ? 'border-foreground font-medium' : 'border-transparent text-muted-foreground hover:text-foreground',
                )}
              >
                {label}
                {typeof count === 'number' ? (
                  <span className="rounded-full bg-muted px-1.5 text-[11px] font-normal text-muted-foreground tabular-nums">{count}</span>
                ) : (
                  count
                )}
              </button>
            ))}
          </nav>
        </div>
      </div>
      <div className="mx-auto max-w-[980px] px-8 pt-6 pb-16">
        {tab === 'conversation' ? (
          <div className="max-w-[720px]">
            <PullTimeline
              pull={pull}
              live={live}
              agentName={agent.name}
              onShowChanges={() => setTab('changes')}
              onShowChecks={() => setTab('checks')}
            />
          </div>
        ) : tab === 'checks' ? (
          <PullChecks
            pull={pull}
            run={checks.run}
            onRerun={() => void checks.rerun().catch((failure: Error) => setProblem(failure.message))}
          />
        ) : changes === null || suite === null ? (
          <p className="py-10 text-center text-[13px] text-muted-foreground">Loading…</p>
        ) : (
          <PullChanges
            changes={changes}
            suite={suite}
            base={pull.base_version ? versionLabel(pull.base_version) : null}
            open={open}
          />
        )}
      </div>
    </div>
  )
}
