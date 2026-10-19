import { describe, expect, it } from 'vitest'

import {
  arriving,
  around,
  byStep,
  callMeta,
  duration,
  eventText,
  fixText,
  issueMeta,
  outcomeText,
  playCostText,
  reportReady,
  reporterText,
  snoozeText,
  stateText,
  tabOf,
  testCallMeta,
  testCallTitle,
} from './model'
import type { CallSummary, IssueSummary, Play, TestCallSummary } from './types'

const NOW = new Date('2026-10-19T10:50:00')

const call: CallSummary = {
  id: 1,
  play: 7,
  version: 2,
  caller: 'Ana Ruiz',
  at: new Date('2026-10-19T10:42:00').toISOString(),
  seconds: 67,
  ended: 'agent_ended',
  review: 'done',
  outcome: 'booked',
  issues: [],
}

const issue: IssueSummary = {
  number: 3,
  title: 'Opens the chart with the name only',
  step: 'collect_details',
  severity: 'booking',
  description: '',
  reported: null,
  state: 'open',
  snooze: null,
  fixed: null,
  pulls: [],
  calls: 3,
  first_seen: call.at,
  last_seen: call.at,
  created_at: call.at,
  updated_at: call.at,
}

describe('calls', () => {
  it('reads a call as a list line', () => {
    expect(duration(67)).toBe('1:07')
    expect(callMeta(call, NOW)).toBe('10:42 AM · 1:07 · Booked · v2')
    expect(outcomeText({ outcome: null, review: 'pending' })).toBe('Reviewing…')
    expect(outcomeText({ outcome: null, review: 'failed' })).toBe('Not reviewed')
  })

  it('counts the calls of the batch coming in', () => {
    const play = { id: 7, state: 'working', callers: 12 } as Play
    expect(arriving(play, [call, { ...call, play: 6 }])).toEqual({ done: 1, of: 12 })
    expect(arriving({ ...play, state: 'done' }, [call])).toBeNull()
  })

  it('cuts a transcript where the step changes, keeping each line’s index', () => {
    const groups = byStep([
      { role: 'agent', text: 'Hi', node: 'greeting' },
      { role: 'caller', text: 'Book', node: 'greeting' },
      { role: 'agent', text: 'Name?', node: 'collect_details' },
    ])
    expect(groups.map((g) => [g.step, g.lines.map((l) => l.index)])).toEqual([
      ['greeting', [0, 1]],
      ['collect_details', [2]],
    ])
  })

  it('finds the quote in its line, whatever its case', () => {
    expect(around('I can offer Thursday at 2 PM.', 'thursday at 2 pm')).toEqual(['I can offer ', 'Thursday at 2 PM', '.'])
    expect(around('Hello', 'nope')).toEqual(['', 'Hello', ''])
  })
})

describe('issues', () => {
  it('lists ignored issues with the resolved ones', () => {
    expect(tabOf('ignored')).toBe('resolved')
    expect(tabOf('snoozed')).toBe('snoozed')
  })

  it('says where an issue is, how often and when', () => {
    expect(issueMeta(issue, NOW)).toBe('Collect details · 3 calls · last 10:42 AM')
    const snoozed = { ...issue, state: 'snoozed' as const, snooze: { version: 2 } }
    expect(issueMeta(snoozed, NOW)).toBe('Collect details · 3 calls · last 10:42 AM · snoozed until the next version')
    expect(stateText(snoozed, NOW)).toBe('Snoozed until the next version')
  })

  it('says until when a snooze lasts', () => {
    const later = new Date('2026-10-20T10:50:00')
    expect(snoozeText({ snooze: { until: later.toISOString() } }, NOW)).toBe('until Tue, Oct 20, 10:50 AM')
  })

  it('tells its activity in plain words', () => {
    expect(eventText({ type: 'opened', by: 'Prosper AI', at: '', caller: 'Ana Ruiz' })).toBe('Found it in Ana Ruiz’s call')
    expect(eventText({ type: 'snoozed', by: 'you', at: '', text: 'for a week' })).toBe('Snoozed it for a week')
  })
})

describe('fixing an issue', () => {
  const fix = { number: 5, title: 'Fix: Opens the chart', state: 'open' as const, merged_version: null }

  it('shows the pull request fixing it, then the version that did', () => {
    expect(fixText({ pulls: [fix], fixed: null })).toBe('PR #5 open')
    expect(fixText({ pulls: [{ ...fix, state: 'merged', merged_version: 2 }], fixed: { pull: 5, version: 2 } })).toBe('Fixed in v2 by PR #5')
    expect(fixText({ pulls: [{ ...fix, state: 'closed' }], fixed: null })).toBeNull()
    expect(issueMeta({ ...issue, pulls: [fix] }, NOW)).toBe('Collect details · 3 calls · last 10:42 AM · PR #5 open')
  })

  it('tells what happened to its fix', () => {
    const at = ''
    expect(eventText({ type: 'fixing', by: 'Prosper AI', at, pull: 5 })).toBe('Opened PR #5 to fix it')
    expect(eventText({ type: 'unlinked', by: 'you', at, pull: 5 })).toBe('Closed PR #5 without merging · still open')
    expect(eventText({ type: 'fixed', by: 'you', at, pull: 5, version: 2 })).toBe('Resolved by PR #5 in v2')
    expect(eventText({ type: 'fix_merged', by: 'you', at, pull: 5, version: 2, text: 'ignored' })).toBe('PR #5 merged as v2 · issue left ignored')
    expect(eventText({ type: 'fix_merged', by: 'you', at, pull: 5, version: 2, text: 'resolved' })).toBe('PR #5 merged as v2 · issue already resolved')
    expect(eventText({ type: 'came_back', by: 'Prosper AI', at, text: 'v2', caller: 'Ana' })).toBe('Came back in v2: Ana’s call')
  })
})

describe('test calls', () => {
  const test: TestCallSummary = {
    id: 4,
    pull: 3,
    version: null,
    by: 'you',
    at: new Date('2026-10-19T10:45:00').toISOString(),
    seconds: 42,
    ended: 'caller_hung_up',
    review: 'none',
    outcome: null,
    flagged: 0,
  }

  it('says what it ran on: a pull request, or the live version', () => {
    expect(testCallTitle(test)).toBe('Test call · PR #3')
    expect(testCallTitle({ pull: null, version: 2 })).toBe('Test call · v2')
  })

  it('says its real length, how it ended and, once reviewed, what was flagged, short enough for the list', () => {
    expect(testCallMeta(test, NOW)).toBe('10:45 AM · 0:42 · Hung up')
    expect(testCallMeta({ ...test, ended: 'agent_ended', review: 'done', flagged: 2 }, NOW)).toBe(
      '10:45 AM · 0:42 · Agent ended · 2 flagged',
    )
  })
})

describe('the cost of a batch', () => {
  const play: Play = {
    id: 7,
    version: 2,
    state: 'done',
    callers: 11,
    usage: { callers: 0.02, calls: 0.31, reviews: 0.15 },
    error: null,
    started_at: '',
    finished_at: '',
  }

  it('is said whole, with its calls, and "so far" while it comes in', () => {
    expect(playCostText(play)).toBe('Last batch: 11 calls · USD 0.48')
    expect(playCostText({ ...play, state: 'working' })).toBe('This batch so far: USD 0.48')
  })
})

describe('reported issues', () => {
  it('says who flagged it, and leaves out a step nobody knows', () => {
    const reported = { ...issue, reported: 'clinic' as const, step: '', severity: null, calls: 0, last_seen: null }
    expect(issueMeta(reported, NOW)).toBe('Flagged by the clinic · 0 calls')
    expect(issueMeta({ ...reported, reported: 'you', step: 'offer_times', calls: 1 }, NOW)).toBe('Reported by you · Offer times · 1 call')
    expect(reporterText('you')).toBe('Reported by you')
  })

  it('logs who reported it and what Prosper AI tidied', () => {
    expect(eventText({ type: 'reported', by: 'you', at: '', text: 'clinic' })).toBe('Reported it for the clinic')
    expect(eventText({ type: 'reported', by: 'you', at: '', text: 'you' })).toBe('Reported it')
    expect(eventText({ type: 'tidied', by: 'Prosper AI', at: '' })).toBe('Tidied it: plain title, step and severity, kept by you')
    expect(eventText({ type: 'titled', by: 'Prosper AI', at: '' })).toBe('Wrote the title from what happened')
  })

  it('opens an issue from what happened alone, and keeps a title once it has one', () => {
    expect(reportReady(false, '', 'Booked under the mother’s name')).toBe(true)
    expect(reportReady(false, 'Wrong patient', '  ')).toBe(false)
    expect(reportReady(true, ' ', 'Booked under the mother’s name')).toBe(false)
    expect(reportReady(true, 'Wrong patient', 'Booked under the mother’s name')).toBe(true)
  })
})
