import { describe, expect, it } from 'vitest'

import type { PullSummary } from '@/agents/types'
import type { CallSummary, IssueSummary } from '@/live/types'

import { actionOutcome, chatMeta, linkText, offerWhere, suggestions, withQuestion } from './model'
import type { Action } from './types'

const NOW = new Date('2026-10-19T12:00:00')

describe('chatMeta', () => {
  it('names the pull request a chat opened, else when it last moved', () => {
    expect(chatMeta({ pulls: [4, 6], updated_at: '2026-10-19T09:30:00' }, NOW)).toBe('Opened PR #6')
    expect(chatMeta({ pulls: [], updated_at: '2026-10-19T09:30:00' }, NOW)).toBe('9:30 AM')
  })
})

describe('withQuestion', () => {
  it('adds the question being answered after what the chat said', () => {
    const messages = withQuestion(null, 'Can Anna book for a child?', 'now')
    expect(messages).toEqual([
      { by: 'you', at: 'now', text: 'Can Anna book for a child?', about: null, links: [], reads: [], action: null, offer: null, failed: false },
    ])
  })
})

describe('linkText', () => {
  const known = {
    issues: [{ number: 3, title: 'Offers Thursday afternoons' } as IssueSummary],
    pulls: [{ number: 5, title: 'Fix: Offers Thursday afternoons' } as PullSummary],
    calls: [{ id: 12, caller: 'Maria Lopez', at: new Date().toISOString() } as CallSummary],
  }

  it('says an issue and a pull request by their labels, with their titles', () => {
    expect(linkText({ kind: 'issue', number: 3 }, known)).toEqual({ label: 'Issue #3', detail: 'Offers Thursday afternoons' })
    expect(linkText({ kind: 'pull', number: 5 }, known).label).toBe('PR #5')
  })

  it("says a call by its caller, and by its number when it is not known", () => {
    expect(linkText({ kind: 'call', number: 12 }, known).label).toBe("Maria Lopez's call")
    expect(linkText({ kind: 'call', number: 99 }, known)).toEqual({ label: 'Call 99', detail: null })
  })
})

describe('suggestions', () => {
  it('asks about calls, and offers to play some, only once the agent is live', () => {
    expect(suggestions('Anna', true).slice(1)).toEqual(['Which calls went wrong today?', 'Play a batch of calls'])
    expect(suggestions('Anna', false).slice(1)).toEqual(['What is left before Anna can go live?', 'Run all the tests again'])
  })
})

describe('actionOutcome', () => {
  const card: Action = { tool: 'merge_pull', title: 'Merge PR #5 as v3', what: 'Fix', meta: [], stored: [], state: 'pending', result: null, error: null }
  it('says nothing while the card waits or runs', () => {
    expect(actionOutcome(card)).toBeNull()
    expect(actionOutcome({ ...card, state: 'running' })).toBeNull()
  })
  it('says what happened, why it was refused, or that it was not done', () => {
    const result = { text: 'Merged PR #5 · v3 is live', link: { kind: 'pull' as const, number: 5 } }
    expect(actionOutcome({ ...card, state: 'done', result })).toBe('Merged PR #5 · v3 is live')
    expect(actionOutcome({ ...card, state: 'failed', error: 'PR #5 cannot merge: its checks are still running.' })).toBe(
      'PR #5 cannot merge: its checks are still running.',
    )
    expect(actionOutcome({ ...card, state: 'declined' })).toBe('Cancelled · nothing changed')
    expect(actionOutcome({ ...card, state: 'skipped' })).toBe('Not done · you asked something else')
  })
})

describe('offerWhere', () => {
  it('says the pull request opens on live', () => {
    expect(offerWhere(2)).toBe('Opens a pull request on v2 · nothing goes live until you merge')
    expect(offerWhere(0)).toBe('Nothing goes live until you merge')
  })
})
