import { describe, expect, it } from 'vitest'

import type { AgentConfig, PullEvent, PullSummary } from '@/agents/types'

import { batchText, conversation, eventsInWords, inWords, openQuestions, prosperBlocker, prosperStatus, sourceText, statusText } from './model'

const at = '2026-10-18T10:00:00.000Z'
const event = (type: PullEvent['type'], more: Partial<PullEvent> = {}): PullEvent => ({ type, by: 'Prosper AI', at, ...more })

const pull = (prosper: PullSummary['prosper'], state: PullSummary['state'] = 'open'): PullSummary => ({
  number: 1,
  title: 'Set up Anna',
  kind: 'setup',
  fixes: null,
  chat: null,
  state,
  base_version: 0,
  merged_version: null,
  created_at: at,
  updated_at: at,
  checks: null,
  warnings: [],
  prosper,
})

describe('prosperStatus', () => {
  it('is building while it works and waiting while it asks', () => {
    expect(prosperStatus(pull({ state: 'working', doing: 'Drawing the steps', usage: null }))).toBe('building')
    expect(prosperStatus(pull({ state: 'waiting', doing: null, usage: null }))).toBe('waiting')
    expect(statusText('waiting')).toBe('Waiting for your answer')
  })

  it('is working, not building, on anything but a setup', () => {
    const fix = { ...pull({ state: 'working', doing: 'Reproducing it on v1', usage: null }), kind: 'fix' as const }
    expect(prosperStatus(fix)).toBe('working')
    expect(statusText('working')).toBe('Prosper AI is working')
    expect(prosperBlocker(fix)).toBe('Prosper AI is still working on it.')
  })

  it('says nothing once it is done, failed, merged, or never involved', () => {
    expect(prosperStatus(pull({ state: 'done', doing: null, usage: null }))).toBeNull()
    expect(prosperStatus(pull({ state: 'failed', doing: null, usage: null }))).toBeNull()
    expect(prosperStatus(pull({ state: 'working', doing: null, usage: null }, 'merged'))).toBeNull()
    expect(prosperStatus(pull(null))).toBeNull()
  })

  it('keeps a merge waiting for it', () => {
    expect(prosperBlocker(pull({ state: 'waiting', doing: null, usage: null }))).toBe('Prosper AI needs your answer in PR #1.')
    expect(prosperBlocker(pull(null))).toBeNull()
  })
})

describe('the conversation', () => {
  const events = [
    event('request', { by: 'you' }),
    event('opened'),
    event('step', { text: 'Read 2 files' }),
    event('step', { text: 'Drew 4 steps' }),
    event('question', { question: 'q1', text: 'Waitlist?', options: ['Yes', 'No'] }),
    event('question', { question: 'q2', text: 'Saturdays?', options: ['Yes', 'No'] }),
    event('answer', { by: 'you', question: 'q1', text: 'Yes' }),
    event('step', { text: 'Ran the checks' }),
  ]

  it('groups steps in a row into one turn and shows answers on their questions', () => {
    const items = conversation(events)

    expect(items.map((item) => (item.kind === 'steps' ? `steps:${item.steps.length}` : item.kind === 'batch' ? 'batch' : item.event.type))).toEqual([
      'request',
      'opened',
      'steps:2',
      'question',
      'question',
      'steps:1',
    ])
  })

  it('folds what a message changed under it, and a run of your changes into one entry', () => {
    const items = conversation([
      event('message', { text: 'Rewrote 2 tests', details: ['Books · the test asked for more'] }),
      event('test', { text: 'Books', rewritten: true }),
      event('rule', { text: 'Ask the date of birth here', step: 'change_details' }),
      event('checks', { by: 'checks', passed: 5, total: 5 }),
      event('test', { by: 'you', text: 'A', removed: true }),
      event('test', { by: 'you', text: 'B', removed: true }),
      event('rule', { by: 'you', text: 'C' }),
    ])

    expect(items.map((item) => item.kind)).toEqual(['event', 'event', 'batch'])
    const [turn, , batch] = items
    expect(turn.kind === 'event' && turn.changes.length).toBe(2)
    expect(batch.kind === 'batch' && batchText(batch.changes)).toBe('took out 2 tests and added 1 rule')
  })

  it('knows which questions are still open', () => {
    expect(openQuestions(events).map((e) => e.question)).toEqual(['q2'])
  })
})

describe('sourceText', () => {
  it('names the file a rule quotes, or the answer it came from', () => {
    expect(sourceText({ kind: 'guidelines', pull: 1, file: 'Guidelines.pdf', quote: 'x' })).toBe('Guidelines.pdf')
    expect(sourceText({ kind: 'guidelines', pull: 1, file: 'your notes', quote: 'x' })).toBe('Your notes')
    expect(sourceText({ kind: 'answer', pull: 1, quote: 'Waitlist' })).toBe('Your answer in PR #1')
    expect(sourceText({ kind: 'request', pull: 1, quote: 'Shorter' })).toBe('Your request in PR #1')
    expect(sourceText({ kind: 'manual', pull: 2 })).toBeNull()
  })
})

describe('fixing an issue', () => {
  it('folds the rules of a proposed change under it', () => {
    const items = conversation([event('reproduced'), event('proposed'), event('rule', { text: 'Ask first.' }), event('checks', { by: 'checks' })])
    expect(items.map((item) => item.kind)).toEqual(['event', 'event', 'event'])
    expect(items[1].kind === 'event' && items[1].changes.map((c) => c.text)).toEqual(['Ask first.'])
  })

  it('says a rule came from the issue', () => {
    expect(sourceText({ kind: 'issue', pull: 5, issue: 3 })).toBe('Issue #3 in PR #5')
  })
})

describe('names in what Prosper AI wrote', () => {
  const names = ['offer_times', 'nurse_callback', 'goodbye', 'callback_number']

  it('says stored step and field names as words', () => {
    expect(inWords('Added an edge in offer_times that routes to nurse_callback.', names)).toBe(
      'Added an edge in Offer times that routes to Nurse callback.',
    )
    expect(inWords('Reaches nurse_callback · callback_number is recorded', names)).toBe('Reaches Nurse callback · Callback number is recorded')
  })

  it('leaves one-word names and other words alone', () => {
    expect(inWords('Say goodbye after offer_timesheet.', names)).toBe('Say goodbye after offer_timesheet.')
  })

  it('reads every text of an old event that way', () => {
    const config = {
      name: 'Anna',
      initial_node: 'offer_times',
      nodes: [{ name: 'offer_times', task_messages: [], edges: [{ function: 'f', description: '', target: 'nurse_callback' }] }, { name: 'nurse_callback', task_messages: [] }],
    } as unknown as AgentConfig
    const [said] = eventsInWords([event('proposed', { text: 'Changed offer_times.', details: ['Changed when offer_times moves on'] })], config)
    expect([said.text, said.details]).toEqual(['Changed Offer times.', ['Changed when Offer times moves on']])
  })
})
