// The Calls section of an agent: the calls its live version answered, and one
// call's page. The list is on the left (All · With issues), the call in the
// middle (its path as chips, its transcript cut by step, the bad turns marked)
// and, on the right, what Prosper AI checked on it, each failed check linking
// to its issue.
//
// The callers are simulated: "Play calls" asks Prosper AI for a morning's mix
// of callers and phones the live version with them. The list is read again
// every second and a half while calls come in or wait for their review, the
// way the checks are followed.

import { ArrowRight, ChevronRight, CircleCheck, CircleX, Loader2 } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'

import { getCall, listCalls, playCalls } from '@/agents/api'
import type { Agent } from '@/agents/types'
import { Mark } from '@/components/Mark'
import { humanize } from '@/draft/names'
import { cn } from '@/lib/utils'

import { PlayButton } from './bits'
import { arriving, around, byStep, callMeta, duration, issueLabel, outcomeText, playCost } from './model'
import type { Call, CallSummary, Play } from './types'

const EVERY = 1500

type Props = {
  agent: Agent
  /** The call whose page is shown, or null. */
  page: number | null
  onPage: (call: number | null) => void
  onIssue: (number: number) => void
  /** A batch finished: the issues it opened change what the top bar counts. */
  onChanged: () => void
  onToast: (text: string) => void
}

const busy = (play: Play | null, calls: CallSummary[]) =>
  play?.state === 'working' || calls.some((call) => call.review === 'pending')

/** The agent's calls and its latest batch, read again while anything is coming in. */
function useCalls(agentId: string, onDone: () => void) {
  const [data, setData] = useState<{ play: Play | null; calls: CallSummary[] } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [nudge, setNudge] = useState(0)
  const going = data ? busy(data.play, data.calls) : false
  const was = useRef(false)

  useEffect(() => {
    let stopped = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const read = () =>
      listCalls(agentId).then(
        (fresh) => {
          if (stopped) return
          const now = busy(fresh.play, fresh.calls)
          if (was.current && !now) onDone()
          was.current = now
          setData(fresh)
          setError(null)
          if (now) timer = setTimeout(read, EVERY)
        },
        (failure: Error) => !stopped && setError(failure.message),
      )
    void read()
    return () => {
      stopped = true
      clearTimeout(timer)
    }
    // `onDone` is the caller's callback, read when a batch ends; following it would read in a loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentId, going, nudge])

  return { data, error, again: () => setNudge((n) => n + 1) }
}

export function CallsView({ agent, page, onPage, onIssue, onChanged, onToast }: Props) {
  const { data, error, again } = useCalls(agent.id, onChanged)
  const [filter, setFilter] = useState<'all' | 'issues'>('all')

  useEffect(() => {
    document.title = `Calls · ${agent.name || 'Untitled agent'} · Prosper`
    return () => {
      document.title = 'Prosper'
    }
  }, [agent.name])

  const play = async () => {
    try {
      await playCalls(agent.id)
      again()
    } catch (failure) {
      onToast((failure as Error).message)
    }
  }

  if (error) return <p className="m-auto text-sm text-bad">{error}</p>
  const calls = data?.calls ?? []
  const withIssues = calls.filter((call) => call.issues.length > 0)
  const shown = filter === 'issues' ? withIssues : calls
  const summary = calls.find((call) => call.id === page) ?? null
  const coming = arriving(data?.play ?? null, calls)
  const blocker = agent.live_version === 0 ? 'Nobody can call it until PR #1 is merged.' : null
  const last = data?.play

  return (
    <div className="flex min-h-0 min-w-0 flex-1">
      <aside className="flex w-[320px] shrink-0 flex-col border-r bg-card">
        <div className="flex h-11 shrink-0 items-center gap-0.5 border-b px-3">
          {(
            [
              ['all', 'All', calls.length],
              ['issues', 'With issues', withIssues.length],
            ] as const
          ).map(([key, label, count]) => (
            <button
              key={key}
              onClick={() => setFilter(key)}
              className={cn(
                'flex h-7 items-center gap-1.5 rounded-md px-2 text-[12.5px] outline-none focus-visible:ring-2 focus-visible:ring-ring/50',
                filter === key ? 'bg-muted font-medium' : 'text-muted-foreground hover:text-foreground',
              )}
            >
              {label}
              <span className="font-normal text-muted-foreground tabular-nums">{count}</span>
            </button>
          ))}
          <PlayButton arriving={coming} blocker={blocker} onPlay={() => void play()} className="ml-auto" />
        </div>
        {last && (
          <p
            className={cn('border-b px-4 py-2 text-[11.5px] text-muted-foreground tabular-nums', last.state === 'failed' && 'text-bad')}
            title="Simulated callers, picked by Prosper AI from the clinic's guidelines, phoning the live version in text"
          >
            {last.state === 'failed'
              ? `The last batch stopped: ${last.error}`
              : `Simulated callers on v${last.version} · last batch USD ${playCost(last).toFixed(2)}`}
          </p>
        )}
        <div className="min-h-0 flex-1 overflow-auto">
          {shown.map((call) => {
            const flagged = call.issues.length > 0
            return (
              <button
                key={call.id}
                onClick={() => onPage(call.id)}
                className={cn(
                  'flex w-full animate-in items-center gap-3 border-b border-border/60 px-4 py-2.5 text-left outline-none fade-in slide-in-from-top-1 hover:bg-muted/50 focus-visible:bg-muted/50',
                  page === call.id && 'bg-muted',
                )}
              >
                {call.review === 'pending' ? (
                  <Loader2 aria-label="Reviewing" className="size-4 shrink-0 animate-spin text-muted-foreground" />
                ) : flagged ? (
                  <CircleX aria-label="Something went wrong" className="size-4 shrink-0 text-bad" />
                ) : (
                  <CircleCheck aria-label="Nothing went wrong" className="size-4 shrink-0 text-muted-foreground/50" />
                )}
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13.5px]">{call.caller}</span>
                  <span className="block truncate text-[12px] text-muted-foreground tabular-nums">{callMeta(call)}</span>
                </span>
                {flagged && (
                  <span className="shrink-0 text-[12px] font-medium whitespace-nowrap text-bad tabular-nums">
                    {issueLabel(call.issues[0])}
                    {call.issues.length > 1 && ` +${call.issues.length - 1}`}
                  </span>
                )}
              </button>
            )
          })}
          {data === null ? (
            <p className="px-4 py-5 text-[13px] text-muted-foreground">Loading…</p>
          ) : calls.length === 0 ? (
            <p className="px-4 py-5 text-[13px] leading-relaxed text-muted-foreground">
              No calls yet. Play calls phones {agent.name || 'the agent'} with a morning of simulated callers, and Prosper AI
              reviews each one as it ends.
            </p>
          ) : (
            shown.length === 0 && <p className="px-4 py-5 text-[13px] text-muted-foreground">No calls with issues.</p>
          )}
        </div>
      </aside>
      {summary ? (
        <CallPage key={summary.id} agent={agent} summary={summary} onIssue={onIssue} />
      ) : (
        <div className="flex flex-1 items-center justify-center text-[13px] text-muted-foreground">
          {calls.length ? 'Pick a call.' : ''}
        </div>
      )}
    </div>
  )
}

/** One call: what was said, step by step, and what Prosper AI checked on it. */
function CallPage({ agent, summary, onIssue }: { agent: Agent; summary: CallSummary; onIssue: (n: number) => void }) {
  const [call, setCall] = useState<Call | null>(null)
  const [error, setError] = useState<string | null>(null)
  const load = useCallback(() => {
    getCall(agent.id, summary.id).then(setCall, (failure: Error) => setError(failure.message))
  }, [agent.id, summary.id])
  // Again when its review lands.
  useEffect(load, [load, summary.review, summary.issues.length])

  if (error) return <p className="m-auto text-sm text-bad">{error}</p>
  if (!call) return <div className="flex-1" />
  const name = 'Agent'
  const bad = new Map(call.findings.map((finding) => [finding.turn, finding]))
  const badSteps = new Set(call.findings.map((finding) => finding.step))

  return (
    <>
      <div className="min-w-0 flex-1 overflow-auto">
        <div className="px-8 pt-6 pb-4">
          <h1 className="text-[18px] font-semibold tracking-[-0.01em]">{call.caller}</h1>
          <div className="mt-0.5 text-[12.5px] text-muted-foreground tabular-nums">
            {new Date(call.at).toLocaleString('en-US', { weekday: 'short', hour: 'numeric', minute: '2-digit' })} ·{' '}
            {duration(call.seconds)} · {outcomeText(call)} · answered by v{call.version}
          </div>
          <details className="mt-1.5 text-[12.5px] text-muted-foreground">
            <summary className="w-fit cursor-pointer select-none hover:text-foreground">Simulated caller</summary>
            <p className="mt-1 max-w-[640px] leading-snug">{call.situation}</p>
          </details>
          <div className="mt-3.5 flex flex-wrap items-center gap-1.5">
            {call.path.map((step, i) => {
              const wrong = badSteps.has(step.node)
              return (
                <span key={i} className="flex items-center gap-1.5">
                  {i > 0 && <ChevronRight className="size-3.5 text-muted-foreground/60" />}
                  <span
                    className={cn(
                      'flex h-7 items-center gap-1.5 rounded-md border px-2 text-[12.5px]',
                      wrong ? 'border-bad/40 bg-bad/5 text-bad' : 'bg-card',
                    )}
                  >
                    {wrong ? <CircleX className="size-3.5" /> : <CircleCheck className="size-3.5 text-emerald-600" />}
                    {humanize(step.node)}
                  </span>
                </span>
              )
            })}
          </div>
        </div>
        <div className="border-t px-6 py-4">
          {byStep(call.transcript).map((group, g) => (
            <div key={g}>
              <div className="px-2 pt-3 pb-1 text-[10.5px] font-medium tracking-wide text-muted-foreground uppercase">
                {group.step ? humanize(group.step) : 'Start'}
              </div>
              {group.lines.map((line) => {
                const finding = bad.get(line.index)
                const [before, quoted, after] = finding ? around(line.text, finding.quote) : ['', line.text, '']
                return (
                  <div
                    key={line.index}
                    data-flagged={finding ? true : undefined}
                    className={cn(
                      'grid grid-cols-[64px_1fr] gap-x-3 rounded-md px-2 py-1.5',
                      finding && 'bg-bad/[0.06] shadow-[inset_2px_0_0_var(--bad)]',
                    )}
                  >
                    <span className="truncate text-[12.5px] text-muted-foreground">{line.role === 'agent' ? name : 'Caller'}</span>
                    <div className="min-w-0">
                      <div className="text-[13.5px] leading-snug">
                        {before}
                        {finding && before + after ? <mark className="rounded-sm bg-bad/15 px-0.5 text-inherit">{quoted}</mark> : quoted}
                        {after}
                      </div>
                      {finding && (
                        <div className="mt-1 flex items-start gap-1.5 text-[12px]">
                          <Mark className="mt-[3px] h-[11px]" />
                          <span className="min-w-0 flex-1 text-foreground/75">
                            <span className="font-medium text-brand">Prosper AI:</span> {finding.why}
                          </span>
                          <button
                            onClick={() => onIssue(finding.issue)}
                            className="flex shrink-0 items-center gap-1 font-medium whitespace-nowrap hover:underline"
                          >
                            Part of {issueLabel(finding.issue)} <ArrowRight className="size-3" />
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          ))}
        </div>
      </div>
      <Checks call={call} onIssue={onIssue} />
    </>
  )
}

function Checks({ call, onIssue }: { call: Call; onIssue: (n: number) => void }) {
  const heading = <div className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">Checks</div>
  if (call.review !== 'done') {
    return (
      <aside className="w-[264px] shrink-0 overflow-auto border-l bg-card px-4 pt-6">
        {heading}
        <p className="mt-1.5 flex items-center gap-2 text-[13px] text-muted-foreground">
          {call.review === 'pending' ? (
            <>
              <Loader2 className="size-3.5 animate-spin" /> Prosper AI is reviewing this call
            </>
          ) : (
            "Prosper AI couldn't review this call."
          )}
        </p>
      </aside>
    )
  }
  const issueOf = new Map(call.findings.map((finding) => [finding.check, finding.issue]))
  const passed = call.checks.filter((check) => check.passed).length
  return (
    <aside className="w-[264px] shrink-0 overflow-auto border-l bg-card">
      <div className="px-4 pt-6 pb-2">
        {heading}
        <div className="mt-0.5 text-[13.5px] font-medium tabular-nums">
          {passed} of {call.checks.length} passed
        </div>
        <p className="mt-0.5 flex items-center gap-1.5 text-[11.5px] text-muted-foreground">
          <Mark className="h-[10px]" /> What Prosper AI checked on this call
        </p>
      </div>
      <div className="px-2 pb-4">
        {call.checks.map((check) => {
          const issue = issueOf.get(check.text)
          return (
            <div key={check.text} className={cn('flex items-start gap-2 rounded-md px-2 py-1.5', !check.passed && 'bg-bad/[0.05]')}>
              {check.passed ? (
                <CircleCheck className="mt-px size-4 shrink-0 text-emerald-600" />
              ) : (
                <CircleX className="mt-px size-4 shrink-0 text-bad" />
              )}
              <div className="min-w-0 flex-1">
                <div className={cn('text-[12.5px] leading-snug', !check.passed && 'text-bad')}>{check.text}</div>
                <div className="text-[11px] text-muted-foreground">
                  {check.rule ? 'Rule' : 'From the guidelines'}
                  {issue !== undefined && (
                    <button onClick={() => onIssue(issue)} className="ml-1.5 font-medium text-foreground hover:underline">
                      {issueLabel(issue)} →
                    </button>
                  )}
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </aside>
  )
}
