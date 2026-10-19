// Calls and issues as the API returns them (backend/api/live.py).
//
// Calls are made on the live version by simulated callers, and Prosper AI
// reviews each one: the checks it applied and, for each that failed, a
// finding on the exact turn, grouped into an issue.

export type Outcome = 'booked' | 'rescheduled' | 'cancelled' | 'callback' | 'answered' | 'hung_up'
export type Severity = 'safety' | 'booking' | 'experience'
export type IssueState = 'open' | 'snoozed' | 'resolved' | 'ignored'
export type SnoozeFor = 'day' | 'week' | 'version'

/** A batch of simulated calls on the live version. */
export type Play = {
  id: number
  version: number
  state: 'working' | 'done' | 'failed' | 'stopped'
  callers: number // how many calls it makes; 0 until Prosper AI picked the callers
  usage: Record<string, number> // USD by part: callers, calls, reviews
  error: string | null
  started_at: string
  finished_at: string | null
}

export type CallSummary = {
  id: number
  play: number | null // the batch it came in
  version: number // the version that answered
  caller: string
  at: string
  seconds: number // estimated from the transcript: there was no audio
  ended: string
  review: 'pending' | 'done' | 'failed'
  outcome: Outcome | null
  issues: number[]
}

export type CallLine = { role: 'agent' | 'caller'; text: string; node: string | null }

export type CallCheck = { text: string; passed: boolean; rule: string }

export type CallFinding = {
  issue: number
  title: string
  state: IssueState
  check: string
  step: string
  turn: number
  quote: string
  why: string
}

export type Call = CallSummary & {
  situation: string
  path: { node: string; edge: string | null; collected: Record<string, unknown> }[]
  transcript: CallLine[]
  checks: CallCheck[]
  findings: CallFinding[]
  usage: Record<string, number>
}

/** A voice call placed from Build: on live, or on a pull request's copy. Never reviewed unless asked. */
export type TestCallSummary = {
  id: number
  pull: number | null
  version: number | null
  by: string
  at: string
  seconds: number // timed: it was a voice call
  ended: 'agent_ended' | 'caller_hung_up'
  review: 'none' | 'pending' | 'done' | 'failed'
  outcome: Outcome | null
  flagged: number // checks it failed, once reviewed
}

/** What Prosper AI found in a test call: like a call's finding, with no issue. */
export type TestCallFinding = Omit<CallFinding, 'issue' | 'state'> & { severity: Severity; description: string }

export type TestCall = TestCallSummary & {
  path: Call['path']
  transcript: CallLine[]
  checks: CallCheck[]
  findings: TestCallFinding[]
  usage: Record<string, number>
}

export type IssueSummary = {
  number: number
  title: string
  step: string
  severity: Severity
  description: string
  state: IssueState
  snooze: { until?: string; version?: number } | null
  fixed: { pull: number; version: number } | null // the fix that resolved it, while it stays so
  pulls: FixPull[] // the pull requests that fix it, newest first
  calls: number
  first_seen: string | null
  last_seen: string | null
  created_at: string
  updated_at: string
}

export type IssueCall = {
  call: number
  caller: string
  at: string
  seconds: number
  outcome: Outcome | null
  version: number
  check: string
  turn: number
  quote: string
  why: string
  lines: (CallLine & { index: number })[] // the bad turn, with the line before it
}

/** A pull request that fixes an issue, as the issue lists it. */
export type FixPull = {
  number: number
  title: string
  state: 'open' | 'merged' | 'closed'
  merged_version: number | null
}

export type IssueEvent = {
  type:
    | 'opened'
    | 'seen'
    | 'snoozed'
    | 'woke'
    | 'resolved'
    | 'ignored'
    | 'reopened'
    // A pull request fixing it: opened, closed, reopened, merged; and the
    // problem seen again on the version that fixed it.
    | 'fixing'
    | 'unlinked'
    | 'relinked'
    | 'fixed'
    | 'fix_merged' // merged while it was ignored or resolved: `text` says which
    | 'came_back'
  by: string
  at: string
  call?: number | null
  caller?: string | null
  text?: string | null
  pull?: number | null
  version?: number | null
}

export type Issue = IssueSummary & { findings: IssueCall[]; events: IssueEvent[] }
