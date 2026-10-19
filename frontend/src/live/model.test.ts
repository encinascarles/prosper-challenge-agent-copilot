import { describe, expect, it } from 'vitest'

import { arriving, around, byStep, callMeta, duration, eventText, issueMeta, outcomeText, snoozeText, stateText, tabOf } from './model'
import type { CallSummary, IssueSummary, Play } from './types'

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
  state: 'open',
  snooze: null,
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
