// The Conversation tab of a pull request: its log as a timeline, oldest first,
// newest at the bottom. Each event is one muted line on a rail, with who did
// it and when; a merge is the one solid mark. Rules and tests added or taken
// out are logged with what they say, and each finished run of the checks with
// how it went. Prosper AI takes part in the same timeline, in turns: what it
// was asked (the notes and files), its progress, its questions with their
// options, and its messages. The composer under it is the pull request's page's.

import {
  CircleCheck,
  CircleX,
  FlaskConical,
  GitMerge,
  GitPullRequestArrow,
  GitPullRequestClosed,
  ChevronRight,
  ListChecks,
  Loader2,
  Pencil,
  RefreshCw,
} from 'lucide-react'

import { useState } from 'react'

import type { Pull, PullEvent } from '@/agents/types'
import { humanize } from '@/draft/names'
import { cn } from '@/lib/utils'
import { answerTo, batchText, conversation, isProsper } from '@/prosper/model'
import { FileChips, Notes, Question, Steps, Turn } from '@/prosper/parts'

import { versionLabel, when } from './model'

type Props = {
  pull: Pull
  live: number
  agentName: string
  /** The Changes tab, which a save's line points to. */
  onShowChanges: () => void
  /** The Checks tab, which a run's line points to. */
  onShowChecks: () => void
  /** Pick an option of Prosper AI's question; the option being sent, while it is. */
  onPick?: (question: string, option: number) => void
  picking?: number | null
  /** While the checks run: how many of their calls are done, of how many. */
  running?: { done: number; of: number } | null
}

function Who({ event }: { event: PullEvent }) {
  return <b className="font-medium text-foreground">{event.by === 'you' ? 'You' : event.by}</b>
}

/** One change, as a line under the turn or batch it belongs to. */
function changeText(event: PullEvent): React.ReactNode {
  const verb = event.removed ? 'Took out' : event.rewritten ? 'Rewrote' : 'Added'
  const where = event.type === 'rule' ? (event.step ? ` in ${humanize(event.step)}` : ' for every step') : ''
  return (
    <>
      {verb} a {event.type}
      {where}:{' '}
      <span className={cn('text-foreground', event.removed && 'line-through decoration-muted-foreground/50')}>“{event.text}”</span>
      {event.why && <span> · {event.why}</span>}
    </>
  )
}

/** The details of a turn, folded until opened: what it decided, then what it changed. */
function Folded({ lines, changes }: { lines: string[]; changes: PullEvent[] }) {
  const [open, setOpen] = useState(false)
  const count = lines.length + changes.length
  if (count === 0) return null
  return (
    <div className="text-[12.5px] text-muted-foreground">
      <button onClick={() => setOpen((now) => !now)} className="flex items-center gap-1 font-medium text-foreground/75 hover:text-foreground">
        <ChevronRight className={cn('size-3.5 transition-transform', open && 'rotate-90')} />
        {open ? 'Hide details' : `${count} ${count === 1 ? 'detail' : 'details'}`}
      </button>
      {open && (
        <ul className="mt-1.5 space-y-1 border-l pl-3">
          {lines.map((line, i) => (
            <li key={`l${i}`} className="leading-snug text-foreground/85">
              {line}
            </li>
          ))}
          {changes.map((change, i) => (
            <li key={`c${i}`} className="leading-snug">
              {changeText(change)}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// Events that are turns of the conversation rather than lines on the rail.
const TURNS = new Set<PullEvent['type']>(['request', 'question', 'message', 'answer'])

/** An event that is a turn of the conversation: what was said, by whom, and what it changed. */
function TurnOf({ event, changes, pull, onShowChanges, onPick, picking }: Props & { event: PullEvent; changes: PullEvent[] }) {
  switch (event.type) {
    case 'request':
      return (
        <Turn who={event.by} at={event.at}>
          <p className="text-[13px] leading-relaxed">{event.text}</p>
          {event.notes && <Notes text={event.notes} />}
          {event.files && event.files.length > 0 && <FileChips files={event.files} />}
        </Turn>
      )
    case 'question': {
      const answer = answerTo(pull.events, event)
      const open = pull.state === 'open' && answer === null
      return (
        <Turn who={event.by} at={event.at} title={open ? <span className="font-medium text-brand">needs your answer</span> : undefined}>
          <Question
            event={event}
            answer={answer}
            busy={picking ?? null}
            onPick={open && onPick ? (option) => onPick(event.question ?? '', option) : undefined}
          />
          {open && <p className="text-[12px] text-muted-foreground">Or write your answer below.</p>}
        </Turn>
      )
    }
    case 'message':
    case 'answer':
      return (
        <Turn who={event.by} at={event.at}>
          <p className="text-[13px] leading-relaxed whitespace-pre-wrap">{event.text}</p>
          <Folded lines={event.details ?? []} changes={changes} />
          {event.changed && (
            <button onClick={onShowChanges} className="text-[12.5px] font-medium text-foreground/80 hover:underline">
              Changes →
            </button>
          )}
        </Turn>
      )
    default:
      return null
  }
}

function Mark({ children, solid }: { children: React.ReactNode; solid?: boolean }) {
  return (
    <span
      className={cn(
        'relative z-10 flex size-[22px] shrink-0 items-center justify-center rounded-full border',
        solid ? 'border-foreground bg-foreground' : 'bg-card',
      )}
    >
      {children}
    </span>
  )
}

function Event({ event, pull, live, agentName, onShowChanges, onShowChecks }: Props & { event: PullEvent }) {
  const icon = 'size-3 text-foreground/70'
  let mark = <GitPullRequestArrow className={cn(icon, 'text-brand')} />
  let solid = false
  let text: React.ReactNode
  switch (event.type) {
    case 'opened':
      text = isProsper(event) ? (
        <>
          <Who event={event} /> opened this pull request from your guidelines · it goes live when you merge it
        </>
      ) : pull.kind === 'setup' ? (
          <>
            <Who event={event} /> started {agentName}: it goes live when this is merged
          </>
        ) : (
          <>
            <Who event={event} /> opened this
            {event.version ? (
              <>
                {' '}
                on <span className="text-foreground">{versionLabel(event.version)}</span>
              </>
            ) : null}{' '}
            · live stays as it is until you merge
          </>
        )
      break
    case 'saved':
      mark = <Pencil className={icon} />
      text = (
        <>
          <Who event={event} /> {event.summary ? <span className="text-foreground">{lower(event.summary)}</span> : 'saved changes'}
          <button onClick={onShowChanges} className="ml-2 font-medium text-foreground/80 hover:underline">
            Changes →
          </button>
        </>
      )
      break
    case 'merged':
      mark = <GitMerge className="size-3 text-background" />
      solid = true
      text = (
        <span className="text-foreground">
          <Who event={event} /> merged this as <b className="font-semibold">{versionLabel(event.version ?? 0)}</b>
          <span className="text-muted-foreground"> · calls now run {versionLabel(event.version ?? 0)}</span>
        </span>
      )
      break
    case 'closed':
      mark = <GitPullRequestClosed className="size-3 text-muted-foreground" />
      text = (
        <>
          <Who event={event} /> closed this without merging
        </>
      )
      break
    case 'reopened':
      text = (
        <>
          <Who event={event} /> reopened this
        </>
      )
      break
    case 'updated':
      mark = <RefreshCw className={icon} />
      text = (
        <>
          <Who event={event} /> updated it to <span className="text-foreground">{versionLabel(event.version ?? 0)}</span>
          {event.summary ? <> · {event.summary}</> : ' · nothing of yours clashed with it'}
        </>
      )
      break
    case 'rule':
      mark = <ListChecks className={cn(icon, isProsper(event) && 'text-brand')} />
      text = (
        <>
          <Who event={event} /> {event.removed ? 'took out' : 'added'} a rule{' '}
          {event.step ? `in ${humanize(event.step)}` : 'for every step'}:{' '}
          <span className={cn('text-foreground', event.removed && 'line-through decoration-muted-foreground/50')}>
            “{event.text}”
          </span>
        </>
      )
      break
    case 'test':
      mark = <FlaskConical className={cn(icon, isProsper(event) && 'text-brand')} />
      text = (
        <>
          <Who event={event} /> {event.removed ? 'took out' : 'added'} a test:{' '}
          <span className={cn('text-foreground', event.removed && 'line-through decoration-muted-foreground/50')}>
            “{event.text}”
          </span>
        </>
      )
      break
    case 'interrupted':
      mark = <CircleX className="size-3 text-warn" />
      text = (
        <>
          <Who event={event} /> was interrupted when the server restarted · write to it to try again
        </>
      )
      break
    case 'checks': {
      const failing = (event.total ?? 0) - (event.passed ?? 0)
      mark = failing ? <CircleX className="size-3 text-bad" /> : <CircleCheck className="size-3 text-emerald-600" />
      text = (
        <>
          <span className={cn('font-medium tabular-nums', failing ? 'text-bad' : 'text-emerald-700 dark:text-emerald-500')}>
            Checks {event.passed}/{event.total}
          </span>
          {failing ? ` · ${failing} ${failing === 1 ? 'test' : 'tests'} failing` : ''} · 3 runs each
          <button onClick={onShowChecks} className="ml-2 font-medium text-foreground/80 hover:underline">
            Details →
          </button>
        </>
      )
      break
    }
  }
  // The last event of an open pull request left behind says what is next.
  const behind = pull.state === 'open' && pull.base_version !== live && event === pull.events.at(-1)
  return (
    <div className="relative flex items-start gap-2.5 text-[12.5px] text-muted-foreground">
      <Mark solid={solid}>{mark}</Mark>
      <span className="min-w-0 flex-1 pt-0.5 leading-relaxed">
        {text}
        {behind && (
          <span className="block text-warn">
            {versionLabel(live)} went live since: this is based on {versionLabel(pull.base_version)} and needs an update
            before it can merge.
          </span>
        )}
      </span>
      <span className="shrink-0 pt-0.5 text-[11.5px] tabular-nums" title={new Date(event.at).toLocaleString('en-US')}>
        {when(event.at)}
      </span>
    </div>
  )
}

/** A run of changes by one person (or Prosper AI after an answer): one line, details folded. */
function Batch({ by, changes, at }: { by: string; changes: PullEvent[]; at: string }) {
  const icon = cn('size-3', by === 'Prosper AI' ? 'text-brand' : 'text-foreground/70')
  return (
    <div className="relative flex items-start gap-2.5 text-[12.5px] text-muted-foreground">
      <Mark>{changes.every((c) => c.type === 'test') ? <FlaskConical className={icon} /> : <ListChecks className={icon} />}</Mark>
      <span className="min-w-0 flex-1 space-y-1 pt-0.5 leading-relaxed">
        <span className="block">
          <b className="font-medium text-foreground">{by === 'you' ? 'You' : by}</b> {batchText(changes)}
          {changes.length === 1 && <>: {changeText(changes[0])}</>}
        </span>
        {changes.length > 1 && <Folded lines={[]} changes={changes} />}
      </span>
      <span className="shrink-0 pt-0.5 text-[11.5px] tabular-nums" title={new Date(at).toLocaleString('en-US')}>
        {when(at)}
      </span>
    </div>
  )
}

// A summary is written to stand alone ("Edited Confirm"); after "You" it reads lower case.
const lower = (text: string) => text[0].toLowerCase() + text.slice(1)

export function PullTimeline(props: Props) {
  const { pull, running } = props
  const items = conversation(pull.events)
  const doing = pull.prosper?.state === 'working' ? pull.prosper.doing : null
  // The spinner goes on Prosper AI's last turn of steps, if that is where it is.
  const lastSteps = items.findLastIndex((item) => item.kind === 'steps')
  return (
    <div className="relative space-y-4">
      <div className="absolute top-3 bottom-3 left-[11px] w-px bg-border" />
      {items.map((item, i) =>
        item.kind === 'steps' ? (
          <Turn key={i} who={item.steps[0].by} at={item.at}>
            <Steps steps={item.steps} doing={i === lastSteps && i === items.length - 1 ? doing : null} />
          </Turn>
        ) : (
          item.kind === 'batch' ? (
            <Batch key={i} by={item.by} changes={item.changes} at={item.at} />
          ) : TURNS.has(item.event.type) ? (
            <TurnOf key={i} {...props} event={item.event} changes={item.changes} />
          ) : (
            <Event key={i} event={item.event} {...props} />
          )
        ),
      )}
      {doing && lastSteps !== items.length - 1 && (
        <Turn who="Prosper AI">
          <Steps steps={[]} doing={doing} />
        </Turn>
      )}
      {running && (
        <div className="relative flex items-center gap-2.5 text-[12.5px] text-muted-foreground">
          <span className="relative z-10 flex size-[22px] shrink-0 items-center justify-center rounded-full border bg-card">
            <Loader2 className="size-3 animate-spin text-brand" />
          </span>
          <span className="tabular-nums">
            Running every test, 3 times each · <span className="text-foreground">{running.done}/{running.of}</span>
          </span>
        </div>
      )}
    </div>
  )
}
