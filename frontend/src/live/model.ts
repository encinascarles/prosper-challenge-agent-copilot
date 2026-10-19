// What the Calls and Issues pages say about calls and issues, as pure
// functions: the words, the meta lines, the transcript in steps.

import { humanize } from '@/draft/names'
import { when } from '@/pulls/model'

import type { CallLine, CallSummary, IssueEvent, IssueState, IssueSummary, Outcome, Play, Reporter, Severity, TestCallSummary } from './types'

export const issueLabel = (number: number) => `Issue #${number}`

const OUTCOMES: Record<Outcome, string> = {
  booked: 'Booked',
  rescheduled: 'Rescheduled',
  cancelled: 'Cancelled',
  callback: 'Callback',
  answered: 'Question answered',
  hung_up: 'Hung up',
}

export const SEVERITIES: Record<Severity, string> = {
  safety: 'Safety',
  booking: 'Booking',
  experience: 'Experience',
}

/** A call's outcome as a list shows it; before the review, what is happening to it. */
export function outcomeText(call: Pick<CallSummary, 'outcome' | 'review'>): string {
  if (call.outcome) return OUTCOMES[call.outcome]
  return call.review === 'failed' ? 'Not reviewed' : 'Reviewing…'
}

/** Seconds as a call's length: "1:07". */
export function duration(seconds: number): string {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

/** The muted line under a call's caller: time · length · outcome · version. */
export function callMeta(call: CallSummary, now = new Date()): string {
  return `${when(call.at, now)} · ${duration(call.seconds)} · ${outcomeText(call)} · v${call.version}`
}

/** How many calls of the batch are in, of how many; null when there is no batch going. */
export function arriving(play: Play | null, calls: CallSummary[]): { done: number; of: number } | null {
  if (!play || play.state !== 'working') return null
  return { done: calls.filter((call) => call.play === play.id).length, of: play.callers }
}

/** What a batch cost, in USD, from what each part spent. */
export const playCost = (play: Play) => Object.values(play.usage).reduce((sum, usd) => sum + usd, 0)

/** What a batch cost, said under the Calls banner: never cut, never a pill. */
export function playCostText(play: Play): string {
  const usd = `USD ${playCost(play).toFixed(2)}`
  if (play.state === 'working') return `This batch so far: ${usd}`
  const calls = play.callers ? `${play.callers} ${play.callers === 1 ? 'call' : 'calls'} · ` : ''
  return `Last batch: ${calls}${usd}`
}

/** What a test call ran on: "Test call · PR #3", or "Test call · v2" on live. */
export function testCallTitle(call: Pick<TestCallSummary, 'pull' | 'version'>): string {
  return `Test call · ${call.pull !== null ? `PR #${call.pull}` : `v${call.version}`}`
}

/** How a test call ended, in words. */
export const endedText = (call: Pick<TestCallSummary, 'ended'>) =>
  call.ended === 'agent_ended' ? 'The agent ended it' : 'Hung up'

/**
 * The muted line under a test call in the list: when · length · how it ended
 * · what Prosper AI flagged. Short enough for the list; who placed it is in
 * the page's title.
 */
export function testCallMeta(call: TestCallSummary, now = new Date()): string {
  const parts = [when(call.at, now), duration(call.seconds), call.ended === 'agent_ended' ? 'Agent ended' : 'Hung up']
  if (call.review === 'done' && call.flagged) parts.push(`${call.flagged} flagged`)
  return parts.join(' · ')
}

/** A transcript cut where the step changes, each line with its index in the whole call. */
export function byStep(lines: CallLine[]): { step: string | null; lines: (CallLine & { index: number })[] }[] {
  const groups: { step: string | null; lines: (CallLine & { index: number })[] }[] = []
  lines.forEach((line, index) => {
    const last = groups.at(-1)
    if (last && last.step === line.node) last.lines.push({ ...line, index })
    else groups.push({ step: line.node, lines: [{ ...line, index }] })
  })
  return groups
}

/** `text` cut around `quote` (any case), to highlight it; the whole text if it is not there. */
export function around(text: string, quote: string): [string, string, string] {
  const at = quote ? text.toLowerCase().indexOf(quote.toLowerCase()) : -1
  if (at < 0) return ['', text, '']
  return [text.slice(0, at), text.slice(at, at + quote.length), text.slice(at + quote.length)]
}

export type IssueTab = 'open' | 'snoozed' | 'resolved'

/** The tab an issue is listed under: an ignored one is with the resolved. */
export const tabOf = (state: IssueState): IssueTab => (state === 'ignored' ? 'resolved' : state)

/** Until when an issue is snoozed. */
export function snoozeText(issue: Pick<IssueSummary, 'snooze'>, now = new Date()): string {
  const snooze = issue.snooze
  if (!snooze) return ''
  if (snooze.version !== undefined) return 'until the next version'
  if (!snooze.until) return ''
  const date = new Date(snooze.until)
  const sameDay = date.toDateString() === now.toDateString()
  const day = date.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })
  const time = date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
  return `until ${sameDay ? '' : `${day}, `}${time}`
}

export function stateText(issue: Pick<IssueSummary, 'state' | 'snooze'>, now = new Date()): string {
  switch (issue.state) {
    case 'open':
      return 'Open'
    case 'snoozed':
      return `Snoozed ${snoozeText(issue, now)}`
    case 'resolved':
      return 'Resolved'
    case 'ignored':
      return 'Ignored · still counts its calls'
  }
}

const plural = (n: number, one: string) => `${n} ${one}${n === 1 ? '' : 's'}`

/** Who flagged an issue a person reported, as the issue says it. */
export const reporterText = (reported: Reporter) => (reported === 'clinic' ? 'Flagged by the clinic' : 'Reported by you')

/** Whether the issue form can be saved: what happened is enough for a new issue (Prosper AI writes an empty title); an edit keeps one. */
export const reportReady = (editing: boolean, title: string, description: string) =>
  description.trim() !== '' && (!editing || title.trim() !== '')

/** The muted line under an issue's title: who reported it · step · calls · last seen, and why it is not open. */
export function issueMeta(issue: IssueSummary, now = new Date()): string {
  const parts = []
  if (issue.reported) parts.push(reporterText(issue.reported))
  if (issue.step) parts.push(humanize(issue.step))
  parts.push(plural(issue.calls, 'call'))
  if (issue.last_seen) parts.push(`last ${when(issue.last_seen, now)}`)
  const fix = fixText(issue)
  if (fix) parts.push(fix)
  if (issue.state === 'snoozed') parts.push(`snoozed ${snoozeText(issue, now)}`)
  if (issue.state === 'ignored') parts.push('ignored')
  return parts.join(' · ')
}

/** One entry of an issue's activity. */
export function eventText(event: IssueEvent): string {
  const from = event.caller ? `${event.caller}’s call` : 'a call'
  switch (event.type) {
    case 'opened':
      return `Found it in ${from}`
    case 'reported':
      return event.text === 'clinic' ? 'Reported it for the clinic' : 'Reported it'
    case 'edited':
      return 'Edited it'
    case 'tidied':
      return 'Tidied it: plain title, step and severity, kept by you'
    case 'titled':
      return 'Wrote the title from what happened'
    case 'seen':
      return `Found it again in ${from}`
    case 'snoozed':
      return `Snoozed it ${event.text ?? ''}`.trim()
    case 'woke':
      return `Back from snooze: ${event.text ?? 'its snooze ended'}`
    case 'resolved':
      return 'Resolved it'
    case 'ignored':
      return 'Ignored it · its calls are still counted'
    case 'reopened':
      return 'Reopened it'
    case 'fixing':
      return `Opened ${pull(event)} to fix it`
    case 'unlinked':
      return `Closed ${pull(event)} without merging · still open`
    case 'relinked':
      return `Reopened ${pull(event)} to fix it`
    case 'fixed':
      return `Resolved by ${pull(event)} in v${event.version}`
    case 'fix_merged':
      return `${pull(event)} merged as v${event.version} · issue ${event.text === 'ignored' ? 'left ignored' : 'already resolved'}`
    case 'came_back':
      return `Came back in ${event.text ?? 'the fixed version'}: ${from}`
  }
}

const pull = (event: IssueEvent) => `PR #${event.pull}`

/** The pull request fixing the issue now, if one is open. */
export const fixing = (issue: Pick<IssueSummary, 'pulls'>) => issue.pulls.find((p) => p.state === 'open') ?? null

/** What the issue's chip says about the pull requests fixing it: "PR #5 open", "Fixed in v2". */
export function fixText(issue: Pick<IssueSummary, 'pulls' | 'fixed'>): string | null {
  const open = fixing(issue)
  if (open) return `PR #${open.number} open`
  if (issue.fixed) return `Fixed in v${issue.fixed.version} by PR #${issue.fixed.pull}`
  return null
}
