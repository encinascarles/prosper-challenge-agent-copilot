// The Issues section of an agent: what Prosper AI found going wrong in its
// calls, each problem once with all the calls that hit it. A dense list (Open ·
// Snoozed · Resolved, a Step filter, Snooze and Resolve on hover) and an
// issue's page: what goes wrong, the calls with the bad turn highlighted, and
// what happened to it. From the page, an issue is fixed in a pull request:
// with Prosper AI, which reproduces it and proposes the change, or by hand.

import { ArrowLeft, ArrowRight, ChevronDown, CircleCheck, CircleSlash, Clock, Loader2, MoreHorizontal, Phone } from 'lucide-react'
import { useEffect, useState } from 'react'

import { changeIssue, fixIssue, getIssue, listIssues } from '@/agents/api'
import type { Agent, Pull } from '@/agents/types'
import { Mark } from '@/components/Mark'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { humanize } from '@/draft/names'
import { cn } from '@/lib/utils'
import { Dot, PullIcon } from '@/pulls/bits'
import { pullLabel, versionLabel, when } from '@/pulls/model'

import { IssueStateIcon, SeverityIcon, smallButton } from './bits'
import { around, duration, eventText, fixing, fixText, issueLabel, issueMeta, outcomeText, SEVERITIES, stateText, tabOf, type IssueTab } from './model'
import type { Issue, IssueSummary, SnoozeFor } from './types'

type Action = 'snooze' | 'resolve' | 'ignore' | 'reopen'

type Props = {
  agent: Agent
  /** The issue whose page is shown, or null for the list. */
  page: number | null
  onPage: (number: number | null) => void
  onCall: (call: number) => void
  /** A pull request's page. */
  onPull: (number: number) => void
  /** A fix was opened for an issue: its page with Prosper AI, Build without. */
  onFixing: (pull: Pull, prosper: boolean) => void
  /** An issue changed state: what the top bar counts changes with it. */
  onChanged: () => void
  onToast: (text: string) => void
}

export function IssuesView({ agent, page, onPage, onCall, onPull, onFixing, onChanged, onToast }: Props) {
  const [issues, setIssues] = useState<{ agent: string; list: IssueSummary[] } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [nudge, setNudge] = useState(0)

  useEffect(() => {
    if (page !== null) return
    let stale = false
    listIssues(agent.id).then(
      (list) => !stale && setIssues({ agent: agent.id, list }),
      (failure: Error) => !stale && setError(failure.message),
    )
    return () => {
      stale = true
    }
  }, [agent.id, page, nudge])

  useEffect(() => {
    document.title = `Issues · ${agent.name || 'Untitled agent'} · Prosper`
    return () => {
      document.title = 'Prosper'
    }
  }, [agent.name])

  const act = async (number: number, action: Action, until?: SnoozeFor): Promise<Issue | null> => {
    try {
      const issue = await changeIssue(agent.id, number, action, until)
      setNudge((n) => n + 1)
      onChanged()
      return issue
    } catch (failure) {
      onToast((failure as Error).message)
      return null
    }
  }

  if (error) return <p className="m-auto text-sm text-bad">{error}</p>
  if (page !== null) {
    const fix = async (number: number, prosper: boolean) => {
      try {
        onFixing(await fixIssue(agent.id, number, prosper), prosper)
      } catch (failure) {
        onToast((failure as Error).message)
      }
    }
    return (
      <IssuePage
        key={page}
        agent={agent}
        number={page}
        onBack={() => onPage(null)}
        onCall={onCall}
        onPull={onPull}
        onFix={fix}
        onAct={act}
      />
    )
  }
  return <IssueList list={issues?.agent === agent.id ? issues.list : null} onOpen={onPage} onAct={act} />
}

function SnoozeItems({ onPick }: { onPick: (until: SnoozeFor) => void }) {
  const item = (until: SnoozeFor, label: string) => (
    <DropdownMenuItem className="text-[13px]" onSelect={() => onPick(until)}>
      {label}
    </DropdownMenuItem>
  )
  return (
    <>
      {item('day', 'For a day')}
      {item('week', 'For a week')}
      {item('version', 'Until the next version')}
    </>
  )
}

type Act = (number: number, action: Action, until?: SnoozeFor) => Promise<Issue | null>

function IssueList({ list, onOpen, onAct }: { list: IssueSummary[] | null; onOpen: (n: number) => void; onAct: Act }) {
  const [tab, setTab] = useState<IssueTab>('open')
  const [step, setStep] = useState('all')
  const all = list ?? []
  const steps = [...new Set(all.map((issue) => issue.step))]
  const inStep = all.filter((issue) => step === 'all' || issue.step === step)
  const rows = inStep.filter((issue) => tabOf(issue.state) === tab)
  return (
    <div className="min-w-0 flex-1 overflow-auto bg-muted/20">
      <div className="mx-auto max-w-[980px] px-8 pt-7 pb-16">
        <h1 className="text-[18px] font-semibold tracking-[-0.01em]">Issues</h1>
        <p className="mt-0.5 text-[13px] text-muted-foreground">
          What Prosper AI found going wrong in the calls. Calls with the same problem join one issue.
        </p>
        <div className="mt-5 overflow-hidden rounded-xl border bg-card shadow-xs">
          <div role="tablist" className="flex h-11 items-center gap-1 border-b bg-muted/30 px-3">
            {(['open', 'snoozed', 'resolved'] as IssueTab[]).map((key) => (
              <button
                key={key}
                role="tab"
                aria-selected={tab === key}
                onClick={() => setTab(key)}
                className={cn(
                  'flex h-7 items-center gap-1.5 rounded-md px-2.5 text-[13px] capitalize outline-none focus-visible:ring-2 focus-visible:ring-ring/50',
                  tab === key ? 'bg-background font-medium shadow-xs ring-1 ring-border' : 'text-muted-foreground hover:text-foreground',
                )}
              >
                {key}
                <span className="font-normal text-muted-foreground tabular-nums">
                  {inStep.filter((issue) => tabOf(issue.state) === key).length}
                </span>
              </button>
            ))}
            <DropdownMenu>
              <DropdownMenuTrigger
                className={cn(
                  'ml-auto flex h-7 items-center gap-1 rounded-md px-2.5 text-[13px] outline-none hover:bg-muted data-[state=open]:bg-muted',
                  step !== 'all' ? 'font-medium' : 'text-muted-foreground',
                )}
              >
                {step === 'all' ? 'Step' : humanize(step)} <ChevronDown className="size-3.5" />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-52">
                <DropdownMenuRadioGroup value={step} onValueChange={setStep}>
                  <DropdownMenuRadioItem value="all" className="text-[13px]">
                    Any step
                  </DropdownMenuRadioItem>
                  {steps.map((name) => (
                    <DropdownMenuRadioItem key={name} value={name} className="text-[13px]">
                      {humanize(name)}
                    </DropdownMenuRadioItem>
                  ))}
                </DropdownMenuRadioGroup>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
          {rows.map((issue) => (
            <IssueRow key={issue.number} issue={issue} onOpen={onOpen} onAct={onAct} />
          ))}
          {list === null ? (
            <p className="px-4 py-8 text-center text-[13px] text-muted-foreground">Loading…</p>
          ) : (
            rows.length === 0 && (
              <p className="px-4 py-8 text-center text-[13px] text-muted-foreground">
                {all.length === 0
                  ? 'No issues. Prosper AI reviews every call as it ends: play calls from Calls.'
                  : `No ${tab} issues${step !== 'all' ? ' in this step' : ''}.`}
              </p>
            )
          )}
        </div>
      </div>
    </div>
  )
}

function IssueRow({ issue, onOpen, onAct }: { issue: IssueSummary; onOpen: (n: number) => void; onAct: Act }) {
  const [menu, setMenu] = useState(false)
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onOpen(issue.number)}
      onKeyDown={(event) => event.key === 'Enter' && onOpen(issue.number)}
      className="group flex w-full cursor-pointer items-center gap-3 border-b px-4 py-2.5 text-left outline-none last:border-b-0 hover:bg-muted/40 focus-visible:bg-muted/40"
    >
      <IssueStateIcon state={issue.state} />
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className="shrink-0 text-[12.5px] text-muted-foreground tabular-nums">{issueLabel(issue.number)}</span>
          <span className="truncate text-[13.5px] font-medium">{issue.title}</span>
        </div>
        <div className="mt-0.5 truncate text-[12px] text-muted-foreground tabular-nums">{issueMeta(issue)}</div>
      </div>
      <div
        onClick={(event) => event.stopPropagation()}
        className={cn(
          'flex items-center gap-1.5 opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100',
          menu && 'opacity-100',
        )}
      >
        {issue.state === 'open' && (
          <>
            <DropdownMenu open={menu} onOpenChange={setMenu}>
              <DropdownMenuTrigger className={smallButton}>
                <Clock className="size-3.5 text-muted-foreground" /> Snooze <ChevronDown className="size-3 text-muted-foreground" />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-52">
                <SnoozeItems onPick={(until) => void onAct(issue.number, 'snooze', until)} />
              </DropdownMenuContent>
            </DropdownMenu>
            <button onClick={() => void onAct(issue.number, 'resolve')} className={smallButton}>
              <CircleCheck className="size-3.5 text-muted-foreground" /> Resolve
            </button>
          </>
        )}
        {issue.state !== 'open' && (
          <button onClick={() => void onAct(issue.number, 'reopen')} className={smallButton}>
            {issue.state === 'snoozed' ? 'Unsnooze' : 'Reopen'}
          </button>
        )}
      </div>
      <SeverityIcon severity={issue.severity} />
    </div>
  )
}

type PageProps = {
  agent: Agent
  number: number
  onBack: () => void
  onCall: (call: number) => void
  onPull: (number: number) => void
  onFix: (number: number, prosper: boolean) => Promise<void>
  onAct: Act
}

function IssuePage({ agent, number, onBack, onCall, onPull, onFix, onAct }: PageProps) {
  const [opening, setOpening] = useState<'prosper' | 'yourself' | null>(null)
  const [issue, setIssue] = useState<Issue | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    getIssue(agent.id, number).then(setIssue, (failure: Error) => setError(failure.message))
  }, [agent.id, number])

  if (error) return <p className="m-auto text-sm text-bad">{error}</p>
  if (!issue) return <div className="flex-1" />
  const act = async (action: Action, until?: SnoozeFor) => {
    const changed = await onAct(issue.number, action, until)
    if (changed) setIssue(changed)
  }
  const closed = issue.state === 'resolved' || issue.state === 'ignored'
  const open = fixing(issue)
  const chip = fixText(issue)
  const fix = async (prosper: boolean) => {
    if (opening) return
    setOpening(prosper ? 'prosper' : 'yourself')
    await onFix(issue.number, prosper)
    setOpening(null)
  }
  const heading = 'mb-2 text-[11px] font-medium tracking-wide text-muted-foreground uppercase'
  const button =
    'flex h-8 items-center gap-1.5 rounded-lg border bg-card px-3 text-[13px] outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring/50 data-[state=open]:bg-muted'
  const name = 'Agent'

  return (
    <div className="min-w-0 flex-1 overflow-auto">
      <div className="mx-auto max-w-[980px] px-8 pt-5 pb-12">
        <button
          onClick={onBack}
          className="-ml-1.5 flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[12.5px] text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          <ArrowLeft className="size-3.5" /> Issues
        </button>
        <div className="mt-3 flex items-start gap-4">
          <div className="min-w-0 flex-1">
            <h1 className="text-[20px] font-semibold tracking-[-0.015em]">
              {issue.title} <span className="font-normal text-muted-foreground tabular-nums">{issueLabel(issue.number)}</span>
            </h1>
            <div className="mt-1 flex flex-wrap items-center gap-x-1.5 text-[12.5px] text-muted-foreground tabular-nums">
              <IssueStateIcon state={issue.state} className="size-3.5" />
              <span className="text-foreground">{stateText(issue)}</span>
              <Dot />
              <span>{humanize(issue.step)}</span>
              <Dot />
              <span>
                {issue.calls} {issue.calls === 1 ? 'call' : 'calls'}
                {issue.first_seen && `, since ${when(issue.first_seen)}`}
              </span>
              <Dot />
              <span className="flex items-center gap-1">
                <SeverityIcon severity={issue.severity} /> {SEVERITIES[issue.severity]}
              </span>
              {chip && (
                <button
                  onClick={() => onPull(open?.number ?? issue.fixed!.pull)}
                  className="ml-1 inline-flex h-6 items-center gap-1 rounded-full border bg-card px-2 text-[12px] font-medium text-foreground hover:bg-muted"
                >
                  <PullIcon pull={open ?? { state: 'merged' }} className="size-3.5" /> {chip}
                </button>
              )}
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {!closed && !open && (
              <>
                <button
                  onClick={() => void fix(true)}
                  disabled={opening !== null}
                  className="flex h-8 items-center gap-2 rounded-lg bg-foreground px-3.5 text-[13px] font-medium text-background outline-none hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-ring/50 disabled:opacity-70"
                >
                  {opening === 'prosper' ? (
                    <Loader2 className="size-3.5 animate-spin" />
                  ) : (
                    <Mark className="h-[13px] [&_polygon:first-child]:fill-background" />
                  )}
                  Fix with Prosper AI
                </button>
                <button
                  onClick={() => void fix(false)}
                  disabled={opening !== null}
                  title="A pull request of yours that fixes it: change the flow, add a rule or a test in Build, then merge"
                  className={button}
                >
                  Fix it yourself
                </button>
              </>
            )}
            {issue.state === 'open' && (
              <DropdownMenu>
                <DropdownMenuTrigger className={button}>
                  Snooze <ChevronDown className="size-3.5 text-muted-foreground" />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-52">
                  <SnoozeItems onPick={(until) => void act('snooze', until)} />
                </DropdownMenuContent>
              </DropdownMenu>
            )}
            {issue.state === 'snoozed' && (
              <button onClick={() => void act('reopen')} className={button}>
                Unsnooze
              </button>
            )}
            {closed ? (
              <button onClick={() => void act('reopen')} className={button}>
                Reopen
              </button>
            ) : (
              <button onClick={() => void act('resolve')} className={button}>
                Resolve
              </button>
            )}
            {!closed && (
              <DropdownMenu>
                <DropdownMenuTrigger aria-label="More" className={cn(button, 'w-8 justify-center px-0')}>
                  <MoreHorizontal className="size-4" />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-60">
                  <DropdownMenuItem className="text-[13px]" onSelect={() => void act('ignore')}>
                    <CircleSlash /> Ignore · keep counting its calls
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            )}
          </div>
        </div>

        <div className="mt-6 flex gap-2.5">
          <Mark className="mt-[3px] h-[14px]" />
          <p className="text-[14px] leading-relaxed">{issue.description}</p>
        </div>

        {issue.pulls.length > 0 && (
          <div className="mt-8">
            <div className={heading}>Pull requests · {issue.pulls.length}</div>
            <div className="divide-y overflow-hidden rounded-xl border bg-card">
              {issue.pulls.map((pull) => (
                <button
                  key={pull.number}
                  onClick={() => onPull(pull.number)}
                  className="flex w-full items-center gap-2.5 px-4 py-2.5 text-left outline-none hover:bg-muted/40 focus-visible:bg-muted/40"
                >
                  <PullIcon pull={pull} />
                  <span className="text-[12.5px] text-muted-foreground tabular-nums">{pullLabel(pull.number)}</span>
                  <span className="min-w-0 flex-1 truncate text-[13.5px] font-medium">{pull.title}</span>
                  <span className="text-[12.5px] text-muted-foreground tabular-nums">
                    {pull.state === 'merged'
                      ? `Merged as ${versionLabel(pull.merged_version ?? 0)}`
                      : pull.state === 'closed'
                        ? 'Closed'
                        : 'Open'}
                  </span>
                  <ArrowRight className="size-3.5 text-muted-foreground" />
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="mt-8">
          <div className={heading}>Calls in this issue · {issue.findings.length}</div>
          <div className="divide-y rounded-xl border bg-card">
            {issue.findings.map((found) => (
              <div key={`${found.call}:${found.turn}`} className="px-4 py-3">
                <div className="flex items-center gap-2 text-[13px]">
                  <Phone className="size-3.5 text-muted-foreground" />
                  <span className="font-medium">{found.caller}</span>
                  <span className="text-muted-foreground tabular-nums">
                    {when(found.at)} · {duration(found.seconds)} · {outcomeText({ outcome: found.outcome, review: 'done' })} · v
                    {found.version}
                  </span>
                  <button
                    onClick={() => onCall(found.call)}
                    className="ml-auto flex items-center gap-1 text-[12.5px] text-muted-foreground hover:text-foreground"
                  >
                    Open call <ArrowRight className="size-3" />
                  </button>
                </div>
                <div className="mt-2 space-y-1 pl-[22px]">
                  {found.lines.map((line) => {
                    const isBad = line.index === found.turn
                    const [before, quoted, after] = isBad ? around(line.text, found.quote) : ['', line.text, '']
                    return (
                      <div key={line.index} className="flex gap-3 text-[13px] leading-snug">
                        <span className="w-16 shrink-0 truncate text-[12px] text-muted-foreground">
                          {line.role === 'agent' ? name : 'Caller'}
                        </span>
                        <span className={cn(isBad && 'rounded bg-bad/[0.06] px-1 shadow-[inset_2px_0_0_var(--bad)]')}>
                          {before}
                          {isBad ? <mark className="rounded-sm bg-bad/15 px-0.5 text-bad">{quoted}</mark> : quoted}
                          {after}
                        </span>
                      </div>
                    )
                  })}
                  <p className="pt-0.5 text-[12px] text-muted-foreground">{found.why}</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="mt-8">
          <div className={heading}>Activity</div>
          <div className="space-y-2">
            {issue.events.map((event, i) => (
              <div key={i} className="flex items-center gap-2.5 text-[13px]">
                {event.by === 'Prosper AI' ? (
                  <Mark className="h-[12px] w-3" />
                ) : (
                  <span className="flex size-3 items-center justify-center">
                    <span className="size-1.5 rounded-full bg-foreground/50" />
                  </span>
                )}
                <span className={event.by === 'Prosper AI' ? '' : 'text-foreground/80'}>
                  {event.by === 'you' ? 'You · ' : event.by === 'Prosper AI' ? 'Prosper AI · ' : ''}
                  {eventText(event)}
                </span>
                <span className="ml-auto text-[12px] text-muted-foreground tabular-nums">{when(event.at)}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
