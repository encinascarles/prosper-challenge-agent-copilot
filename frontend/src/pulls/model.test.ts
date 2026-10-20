import { describe, expect, it } from 'vitest'

import type { PullSummary } from '@/agents/types'
import { NEW_AGENT } from '@/agents/template'
import { moveNode, openDraft, renameNode } from '@/draft/draft'

import {
  basedOn,
  callsNote,
  changesAgent,
  isStale,
  mergeBlocker,
  mergeLabel,
  mergeStep,
  openedForEdits,
  pullMeta,
  testCallLabel,
  when,
} from './model'

const pull = (fields: Partial<PullSummary> = {}): PullSummary => ({
  number: 2,
  title: 'Your edits',
  kind: 'edit',
  state: 'open',
  base_version: 1,
  merged_version: null,
  fixes: null,
  chat: null,
  created_at: '',
  updated_at: '',
  checks: { state: 'passed', passed: 1, flaky: 0, failing: 0, total: 1 },
  prosper: null,
  warnings: [],
  ...fields,
})
const setup = pull({ number: 1, title: 'Set up Anna', kind: 'setup', base_version: 0 })

describe('merging', () => {
  it('puts a new agent live with PR #1', () => {
    expect(mergeLabel(setup, 0)).toBe('Merge & go live as v1')
  })

  it('makes any other pull request the next version', () => {
    expect(mergeLabel(pull(), 1)).toBe('Merge as v2')
    expect(mergeLabel(pull({ base_version: 4 }), 4)).toBe('Merge as v5')
  })

  it('is open to an open pull request based on live, once it is saved', () => {
    expect(mergeBlocker(pull(), 1, false)).toBeNull()
    expect(mergeBlocker(setup, 0, false)).toBeNull()
    expect(mergeBlocker(pull(), 1, true)).toBe('Save your changes first.')
  })

  it('is closed once live has moved past what the pull request was based on', () => {
    expect(isStale(pull(), 2)).toBe(true)
    expect(isStale(pull(), 1)).toBe(false)
    expect(mergeBlocker(pull(), 2, false)).toBe(
      'Live is v2 now, and this was based on v1. It needs updating before it can merge.',
    )
  })

  it('is closed to a pull request that is not open', () => {
    expect(mergeBlocker(pull({ state: 'merged' }), 2, false)).toBe('PR #2 is merged.')
    expect(isStale(pull({ state: 'merged' }), 2)).toBe(false)
  })

  it('waits for the checks to pass on the saved copy', () => {
    const failing = { state: 'failed', passed: 3, flaky: 0, failing: 2, total: 5 } as const
    expect(mergeBlocker(pull(), 1, false, failing)).toBe('2 tests failing.')
    expect(mergeBlocker(pull(), 1, false, { ...failing, state: 'running', failing: 0 })).toBe(
      'Checks are still running.',
    )
    expect(mergeBlocker(pull({ checks: null }), 1, false)).toBe(
      'Checks have not run on the latest change yet.',
    )
    // Unsaved changes first: saving them runs the checks again anyway.
    expect(mergeBlocker(pull(), 1, true, failing)).toBe('Save your changes first.')
  })
})

describe('merging a fix that may not fix its issue', () => {
  const warned = pull({ kind: 'fix', fixes: 4, warnings: ['The test for Issue #4 passes 2 of 3: the problem may still happen in some calls.'] })

  it('merges at once when there is nothing to warn of', () => {
    expect(mergeStep(pull(), false)).toEqual({ anyway: false })
  })

  it('asks to confirm the warnings first, and is never refused for them', () => {
    expect(mergeStep(warned, false)).toEqual({ confirm: warned.warnings })
    expect(mergeBlocker(warned, 1, false)).toBeNull()
  })

  it('merges anyway once confirmed', () => {
    expect(mergeStep(warned, true)).toEqual({ anyway: true })
  })
})

describe('what a pull request is based on', () => {
  it('names the version, or says a setup is not live yet', () => {
    expect(basedOn(pull())).toBe('based on v1')
    expect(basedOn(setup)).toBe('not live yet')
  })
})

describe('editing live', () => {
  const draft = openDraft(NEW_AGENT)
  const greeting = draft.ids[0]

  it('opens a pull request for a change to the agent', () => {
    expect(changesAgent(draft, renameNode(draft, greeting, 'hello'))).toBe(true)
  })

  it('does not for moving a card', () => {
    expect(changesAgent(draft, moveNode(draft, greeting, { x: 10, y: 20 }))).toBe(false)
  })

  it('says where the edit went and that live did not move', () => {
    expect(openedForEdits(3, 2)).toBe('Opened PR #3 for your edits · live stays on v2')
  })
})

describe('the test call', () => {
  it('says whether it calls live or the pull request', () => {
    expect(testCallLabel(null)).toBe('Test call')
    expect(testCallLabel(5)).toBe('Test call · PR #5')
  })
})

describe('pull request lists', () => {
  it('say what each one is based on, or what became of it', () => {
    expect(pullMeta(pull(), 1)).toBe('based on v1')
    expect(pullMeta(pull(), 2)).toBe('Needs update · based on v1')
    expect(pullMeta(pull({ state: 'merged', merged_version: 2 }), 2)).toBe('merged as v2')
    expect(pullMeta(pull({ state: 'closed' }), 3)).toBe('closed · based on v1')
    expect(pullMeta(setup, 0)).toBe('not live yet')
  })

  it('say which issue a fix is for', () => {
    expect(pullMeta(pull({ kind: 'fix', fixes: 3 }), 1)).toBe('Fixes Issue #3 · based on v1')
    expect(pullMeta(pull({ kind: 'fix', fixes: 3 }), 2)).toBe('Needs update · Fixes Issue #3 · based on v1')
  })

  it('say what an open one means for calls', () => {
    expect(callsNote(pull(), 1)).toBe('Calls keep using v1 until you merge')
    expect(callsNote(setup, 0)).toBe('Nobody can call it until you merge')
    expect(callsNote(pull({ state: 'merged' }), 2)).toBeNull()
  })

  it('give the time today and the day before', () => {
    const now = new Date(2026, 9, 18, 15, 0)
    expect(when(new Date(2026, 9, 18, 9, 5).toISOString(), now)).toBe('9:05 AM')
    expect(when(new Date(2026, 9, 2, 9, 5).toISOString(), now)).toBe('Oct 2')
    expect(when(new Date(2025, 11, 30).toISOString(), now)).toBe('Dec 30, 2025')
  })
})
