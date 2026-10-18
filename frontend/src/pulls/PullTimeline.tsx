// The Conversation tab of a pull request: its log as a timeline, oldest first,
// newest at the bottom. Each event is one muted line on a rail, with who did
// it and when; a merge is the one solid mark. Prosper's own turns and the
// composer will join this same timeline.

import { GitMerge, GitPullRequestArrow, GitPullRequestClosed, Pencil, RefreshCw } from 'lucide-react'

import type { Pull, PullEvent } from '@/agents/types'
import { cn } from '@/lib/utils'

import { versionLabel, when } from './model'

type Props = {
  pull: Pull
  live: number
  agentName: string
  /** The Changes tab, which a save's line points to. */
  onShowChanges: () => void
}

function Who({ event }: { event: PullEvent }) {
  return <b className="font-medium text-foreground">{event.by === 'you' ? 'You' : event.by}</b>
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

function Event({ event, pull, live, agentName, onShowChanges }: Props & { event: PullEvent }) {
  const icon = 'size-3 text-foreground/70'
  let mark = <GitPullRequestArrow className={cn(icon, 'text-brand')} />
  let solid = false
  let text: React.ReactNode
  switch (event.type) {
    case 'opened':
      text =
        pull.kind === 'setup' ? (
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

// A summary is written to stand alone ("Edited Confirm"); after "You" it reads lower case.
const lower = (text: string) => text[0].toLowerCase() + text.slice(1)

export function PullTimeline(props: Props) {
  return (
    <div className="relative space-y-4">
      <div className="absolute top-3 bottom-3 left-[11px] w-px bg-border" />
      {props.pull.events.map((event, i) => (
        <Event key={i} event={event} {...props} />
      ))}
    </div>
  )
}
