import { describe, expect, it } from 'vitest'

import type { PullSummary } from '@/agents/types'
import type { CallSummary, IssueSummary } from '@/live/types'

import { chatMeta, linkText, suggestions, withQuestion } from './model'

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
      { by: 'you', at: 'now', text: 'Can Anna book for a child?', about: null, links: [], offer: null, failed: false },
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
  it('asks about calls only once the agent is live', () => {
    expect(suggestions('Anna', true)[2]).toBe('Which calls went wrong today?')
    expect(suggestions('Anna', false)[2]).toBe('What is left before Anna can go live?')
  })
})
