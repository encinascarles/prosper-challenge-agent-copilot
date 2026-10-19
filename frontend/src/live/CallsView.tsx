// The Calls section of an agent, in two tabs. Calls: what its live version
// answered, each reviewed by Prosper AI into issues. Test calls: the voice
// calls a person placed from Build, kept apart, never filed as issues, and
// reviewed only when asked. The list is on the left, the call in the middle
// (its path as chips, its transcript cut by step, the bad turns marked) and,
// on the right, what Prosper AI checked on it.
//
// There is no phone line behind this demo, so "Play calls" stands in for one:
// Prosper AI picks a morning's mix of callers and phones the live version with
// them. A slim banner says so, once. The list is read again every second and a
// half while calls come in or wait for their review, the way the checks are
// followed.

import { ArrowRight, ChevronRight, CircleCheck, CircleX, Loader2, Phone } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'

import { getCall, getTestCall, listCalls, listTestCalls, playCalls, reviewTestCall } from '@/agents/api'
import type { Agent } from '@/agents/types'
import { Mark } from '@/components/Mark'
import { humanize } from '@/draft/names'
import { cn } from '@/lib/utils'

import { PlayButton, smallButton } from './bits'
import {
  arriving,
  around,
  byStep,
  callMeta,
  duration,
  endedText,
  issueLabel,
  outcomeText,
  playCostText,
  testCallMeta,
  testCallTitle,
} from './model'
import type { Call, CallCheck, CallLine, CallSummary, Play, TestCall, TestCallSummary } from './types'

const EVERY = 1500

export type CallsTab = 'calls' | 'test'

type Props = {
  agent: Agent
  /** The call whose page is shown, or null: a call, or a test call on the Test calls tab. */
  page: number | null
  tab: CallsTab
  onPage: (call: number | null, tab: CallsTab) => void
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

/** The test calls placed from Build, read again while Prosper AI reviews one. */
function useTestCalls(agentId: string, nudge: number) {
  const [calls, setCalls] = useState<TestCallSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const going = calls?.some((call) => call.review === 'pending') ?? false
  useEffect(() => {
    let stopped = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const read = () =>
      listTestCalls(agentId).then(
        (fresh) => {
          if (stopped) return
          setCalls(fresh)
          setError(null)
          if (fresh.some((call) => call.review === 'pending')) timer = setTimeout(read, EVERY)
        },
        (failure: Error) => !stopped && setError(failure.message),
      )
    void read()
    return () => {
      stopped = true
      clearTimeout(timer)
    }
  }, [agentId, going, nudge])
  return { calls, error }
}

const tabButton = (on: boolean) =>
  cn(
    'flex h-7 items-center gap-1.5 rounded-md px-2 text-[12.5px] outline-none focus-visible:ring-2 focus-visible:ring-ring/50',
    on ? 'bg-muted font-medium' : 'text-muted-foreground hover:text-foreground',
  )

export function CallsView({ agent, page, tab, onPage, onIssue, onChanged, onToast }: Props) {
  const { data, error, again } = useCalls(agent.id, onChanged)
  const [reviewed, setReviewed] = useState(0)
  const tests = useTestCalls(agent.id, reviewed)
  const [withIssues, setWithIssues] = useState(false)

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
  const flagged = calls.filter((call) => call.issues.length > 0)
  const shown = withIssues ? flagged : calls
  const summary = tab === 'calls' ? (calls.find((call) => call.id === page) ?? null) : null
  const testSummary = tab === 'test' ? (tests.calls?.find((call) => call.id === page) ?? null) : null
  const coming = arriving(data?.play ?? null, calls)
  const blocker = agent.live_version === 0 ? 'Nobody can call it until PR #1 is merged.' : null
  const last = data?.play

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      {tab === 'calls' && (
        // Said once, here: where these calls come from in a demo with no phone line.
        <div className="shrink-0 border-b bg-muted/40 px-4 py-1.5 text-[12px] leading-snug text-muted-foreground">
          <span className="font-medium text-foreground/80">Demo</span> · There is no phone line here, so Play calls
          phones the live version with simulated callers. Prosper AI reviews every call.
          {last && last.state !== 'failed' && <span className="block tabular-nums">{playCostText(last)}</span>}
        </div>
      )}
      <div className="flex min-h-0 min-w-0 flex-1">
        <aside className="flex w-[320px] shrink-0 flex-col border-r bg-card">
          <div role="tablist" className="flex h-11 shrink-0 items-center gap-0.5 border-b px-3">
            <button role="tab" aria-selected={tab === 'calls'} onClick={() => onPage(null, 'calls')} className={tabButton(tab === 'calls')}>
              Calls <span className="font-normal text-muted-foreground tabular-nums">{calls.length}</span>
            </button>
            <button role="tab" aria-selected={tab === 'test'} onClick={() => onPage(null, 'test')} className={tabButton(tab === 'test')}>
              Test calls <span className="font-normal text-muted-foreground tabular-nums">{tests.calls?.length ?? ''}</span>
            </button>
          </div>
          {tab === 'calls' ? (
            <>
              <div className="flex shrink-0 items-center gap-2 border-b px-3 py-2">
                <PlayButton arriving={coming} blocker={blocker} onPlay={() => void play()} />
                <button
                  aria-pressed={withIssues}
                  onClick={() => setWithIssues(!withIssues)}
                  className={cn(tabButton(withIssues), 'ml-auto')}
                >
                  With issues <span className="font-normal text-muted-foreground tabular-nums">{flagged.length}</span>
                </button>
              </div>
              {last?.state === 'failed' && (
                // Whole, not cut: it is the only place that says why no calls came in.
                <p role="alert" className="border-b bg-bad/[0.04] px-4 py-2 text-[12px] leading-snug text-bad">
                  The last batch failed: {last.error ?? 'no reason given'}
                </p>
              )}
              <div className="min-h-0 flex-1 overflow-auto">
                {shown.map((call) => (
                  <CallRow key={call.id} call={call} active={page === call.id} onClick={() => onPage(call.id, 'calls')} />
                ))}
                {data === null ? (
                  <p className="px-4 py-5 text-[13px] text-muted-foreground">Loading…</p>
                ) : calls.length === 0 ? (
                  <p className="px-4 py-5 text-[13px] leading-relaxed text-muted-foreground">
                    No calls yet. Play calls phones {agent.name || 'the agent'} with a morning of simulated callers.
                  </p>
                ) : (
                  shown.length === 0 && <p className="px-4 py-5 text-[13px] text-muted-foreground">No calls with issues.</p>
                )}
              </div>
            </>
          ) : (
            <div className="min-h-0 flex-1 overflow-auto">
              {tests.error && <p className="px-4 py-5 text-[13px] text-bad">{tests.error}</p>}
              {(tests.calls ?? []).map((call) => (
                <button
                  key={call.id}
                  onClick={() => onPage(call.id, 'test')}
                  className={cn(
                    'flex w-full items-center gap-3 border-b border-border/60 px-4 py-2.5 text-left outline-none hover:bg-muted/50 focus-visible:bg-muted/50',
                    page === call.id && 'bg-muted',
                  )}
                >
                  {call.review === 'pending' ? (
                    <Loader2 aria-label="Reviewing" className="size-4 shrink-0 animate-spin text-muted-foreground" />
                  ) : (
                    <Phone className={cn('size-4 shrink-0', call.flagged ? 'text-bad' : 'text-muted-foreground/60')} />
                  )}
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13.5px]">{testCallTitle(call)}</span>
                    <span className="block truncate text-[12px] text-muted-foreground tabular-nums">{testCallMeta(call)}</span>
                  </span>
                </button>
              ))}
              {tests.calls?.length === 0 && (
                <p className="px-4 py-5 text-[13px] leading-relaxed text-muted-foreground">
                  No test calls yet. A Test call placed in Build is kept here, with its transcript and path. Prosper AI
                  reviews one only if you ask, and never files an issue from it.
                </p>
              )}
            </div>
          )}
        </aside>
        {summary ? (
          <CallPage key={summary.id} agent={agent} summary={summary} onIssue={onIssue} />
        ) : testSummary ? (
          <TestCallPage key={testSummary.id} agent={agent} summary={testSummary} onReviewed={() => setReviewed((n) => n + 1)} onToast={onToast} />
        ) : (
          <div className="flex flex-1 items-center justify-center text-[13px] text-muted-foreground">
            {(tab === 'calls' ? calls.length : tests.calls?.length) ? 'Pick a call.' : ''}
          </div>
        )}
      </div>
    </div>
  )
}

function CallRow({ call, active, onClick }: { call: CallSummary; active: boolean; onClick: () => void }) {
  const flagged = call.issues.length > 0
  return (
    <button
      onClick={onClick}
      className={cn(
        'flex w-full animate-in items-center gap-3 border-b border-border/60 px-4 py-2.5 text-left outline-none fade-in slide-in-from-top-1 hover:bg-muted/50 focus-visible:bg-muted/50',
        active && 'bg-muted',
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
}

/** A bad turn, as the transcript marks it: the words quoted, why, and the issue it is part of if any. */
type Flag = { quote: string; why: string; issue?: number }

type BodyProps = {
  header: React.ReactNode
  path: Call['path']
  transcript: CallLine[]
  /** The steps where something went wrong, and the bad turns by their index. */
  badSteps: Set<string>
  flags: Map<number, Flag>
  /** What the person on the line is called in the transcript. */
  caller: string
  onIssue?: (n: number) => void
}

/** What a call's page shows of any call: its header, its path as chips and its transcript by step. */
function CallBody({ header, path, transcript, badSteps, flags, caller, onIssue }: BodyProps) {
  return (
    <div className="min-w-0 flex-1 overflow-auto">
      <div className="px-8 pt-6 pb-4">
        {header}
        <div className="mt-3.5 flex flex-wrap items-center gap-1.5">
          {path.map((step, i) => {
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
        {byStep(transcript).map((group, g) => (
          <div key={g}>
            <div className="px-2 pt-3 pb-1 text-[10.5px] font-medium tracking-wide text-muted-foreground uppercase">
              {group.step ? humanize(group.step) : 'Start'}
            </div>
            {group.lines.map((line) => {
              const flag = flags.get(line.index)
              const [before, quoted, after] = flag ? around(line.text, flag.quote) : ['', line.text, '']
              return (
                <div
                  key={line.index}
                  data-flagged={flag ? true : undefined}
                  className={cn(
                    'grid grid-cols-[64px_1fr] gap-x-3 rounded-md px-2 py-1.5',
                    flag && 'bg-bad/[0.06] shadow-[inset_2px_0_0_var(--bad)]',
                  )}
                >
                  <span className="truncate text-[12.5px] text-muted-foreground">{line.role === 'agent' ? 'Agent' : caller}</span>
                  <div className="min-w-0">
                    <div className="text-[13.5px] leading-snug">
                      {before}
                      {flag && before + after ? <mark className="rounded-sm bg-bad/15 px-0.5 text-inherit">{quoted}</mark> : quoted}
                      {after}
                    </div>
                    {flag && (
                      <div className="mt-1 flex items-start gap-1.5 text-[12px]">
                        <Mark className="mt-[3px] h-[11px]" />
                        <span className="min-w-0 flex-1 text-foreground/75">
                          <span className="font-medium text-brand">Prosper AI:</span> {flag.why}
                        </span>
                        {flag.issue !== undefined && onIssue && (
                          <button
                            onClick={() => onIssue(flag.issue!)}
                            className="flex shrink-0 items-center gap-1 font-medium whitespace-nowrap hover:underline"
                          >
                            Part of {issueLabel(flag.issue)} <ArrowRight className="size-3" />
                          </button>
                        )}
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
  const header = (
    <>
      <h1 className="text-[18px] font-semibold tracking-[-0.01em]">{call.caller}</h1>
      <div className="mt-0.5 text-[12.5px] text-muted-foreground tabular-nums">
        {new Date(call.at).toLocaleString('en-US', { weekday: 'short', hour: 'numeric', minute: '2-digit' })} ·{' '}
        {duration(call.seconds)} · {outcomeText(call)} · answered by v{call.version}
      </div>
      <details className="mt-1.5 text-[12.5px] text-muted-foreground">
        <summary className="w-fit cursor-pointer select-none hover:text-foreground">Simulated caller</summary>
        <p className="mt-1 max-w-[640px] leading-snug">{call.situation}</p>
      </details>
    </>
  )
  const issueOf = new Map(call.findings.map((finding) => [finding.check, finding.issue]))
  return (
    <>
      <CallBody
        header={header}
        path={call.path}
        transcript={call.transcript}
        badSteps={new Set(call.findings.map((finding) => finding.step))}
        flags={new Map(call.findings.map((f) => [f.turn, { quote: f.quote, why: f.why, issue: f.issue }]))}
        caller="Caller"
        onIssue={onIssue}
      />
      <aside className="w-[264px] shrink-0 overflow-auto border-l bg-card">
        {call.review === 'done' ? (
          <Checks checks={call.checks} issueOf={issueOf} onIssue={onIssue} />
        ) : (
          <ChecksNote>
            {call.review === 'pending' ? (
              <>
                <Loader2 className="size-3.5 animate-spin" /> Prosper AI is reviewing this call
              </>
            ) : (
              "Prosper AI couldn't review this call."
            )}
          </ChecksNote>
        )}
      </aside>
    </>
  )
}

/** A test call: the same page as a call's, said to be one, reviewed only when asked. */
function TestCallPage({ agent, summary, onReviewed, onToast }: {
  agent: Agent
  summary: TestCallSummary
  onReviewed: () => void
  onToast: (text: string) => void
}) {
  const [call, setCall] = useState<TestCall | null>(null)
  const [error, setError] = useState<string | null>(null)
  const load = useCallback(() => {
    getTestCall(agent.id, summary.id).then(setCall, (failure: Error) => setError(failure.message))
  }, [agent.id, summary.id])
  useEffect(load, [load, summary.review])

  const review = async () => {
    try {
      setCall(await reviewTestCall(agent.id, summary.id))
      onReviewed()
    } catch (failure) {
      onToast((failure as Error).message)
    }
  }

  if (error) return <p className="m-auto text-sm text-bad">{error}</p>
  if (!call) return <div className="flex-1" />
  const header = (
    <>
      <h1 className="text-[18px] font-semibold tracking-[-0.01em]">
        {testCallTitle(call)} · by {call.by}
      </h1>
      <div className="mt-0.5 text-[12.5px] text-muted-foreground tabular-nums">
        {new Date(call.at).toLocaleString('en-US', { weekday: 'short', hour: 'numeric', minute: '2-digit' })} ·{' '}
        {duration(call.seconds)} · {endedText(call)}
        {call.outcome && ` · ${outcomeText({ outcome: call.outcome, review: 'done' })}`} · a voice call placed from Build
      </div>
    </>
  )
  const reviewButton = (label: string) => (
    <button onClick={() => void review()} className={cn(smallButton, 'mt-2.5')}>
      <Mark className="h-[11px]" /> {label}
    </button>
  )
  return (
    <>
      <CallBody
        header={header}
        path={call.path}
        transcript={call.transcript}
        badSteps={new Set(call.findings.map((finding) => finding.step))}
        flags={new Map(call.findings.map((f) => [f.turn, { quote: f.quote, why: f.why }]))}
        caller="You"
      />
      <aside className="w-[264px] shrink-0 overflow-auto border-l bg-card">
        {call.review === 'done' ? (
          <>
            <Checks checks={call.checks} />
            <p className="px-4 pb-4 text-[11.5px] leading-snug text-muted-foreground">
              Shown here only: a test call never opens an issue.
              {reviewButton('Review again')}
            </p>
          </>
        ) : call.review === 'pending' ? (
          <ChecksNote>
            <Loader2 className="size-3.5 animate-spin" /> Prosper AI is reviewing this call
          </ChecksNote>
        ) : (
          <ChecksNote>
            <span className="block">
              {call.review === 'failed'
                ? "Prosper AI couldn't review this call."
                : 'Test calls are not reviewed on their own, and never open issues.'}
              <span className="block">{reviewButton(call.review === 'failed' ? 'Try again' : 'Review with Prosper AI')}</span>
            </span>
          </ChecksNote>
        )}
      </aside>
    </>
  )
}

const checksHeading = <div className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">Checks</div>

function ChecksNote({ children }: { children: React.ReactNode }) {
  return (
    <div className="px-4 pt-6">
      {checksHeading}
      <div className="mt-1.5 flex items-center gap-2 text-[13px] leading-snug text-muted-foreground">{children}</div>
    </div>
  )
}

function Checks({ checks, issueOf, onIssue }: {
  checks: CallCheck[]
  /** The issue each failed check's finding is part of, by the check's text: calls only. */
  issueOf?: Map<string, number>
  onIssue?: (n: number) => void
}) {
  const passed = checks.filter((check) => check.passed).length
  return (
    <>
      <div className="px-4 pt-6 pb-2">
        {checksHeading}
        <div className="mt-0.5 text-[13.5px] font-medium tabular-nums">
          {passed} of {checks.length} passed
        </div>
        <p className="mt-0.5 flex items-center gap-1.5 text-[11.5px] text-muted-foreground">
          <Mark className="h-[10px]" /> What Prosper AI checked on this call
        </p>
      </div>
      <div className="px-2 pb-4">
        {checks.map((check) => {
          const issue = issueOf?.get(check.text)
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
                  {issue !== undefined && onIssue && (
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
    </>
  )
}
