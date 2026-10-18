import { describe, expect, it } from 'vitest'

import type { Rule, SuiteRun, Test, TestCall } from '@/agents/types'
import { nodeView } from '@/call/path'

import {
  asCall,
  checksText,
  orderTests,
  rulesByStep,
  score,
  scoreText,
  suiteChanges,
  summarize,
  verdict,
} from './model'

const call = (passed: boolean): TestCall => ({
  passed,
  ended: 'agent_ended',
  seconds: 8.2,
  tokens: { agent: { prompt: 100, completion: 10 } },
  path: [
    { node: 'greeting', from: null, edge: null, collected: {} },
    { node: 'confirm', from: 'greeting', edge: 'go_to_confirm', collected: { slot: 'Tuesday 10 AM', n: 2 } },
  ],
  transcript: [
    { role: 'agent', text: 'Hi.', node: 'greeting' },
    { role: 'caller', text: 'Tuesday.', node: 'greeting' },
  ],
  checks: [],
})

const run = (results: boolean[][], state: SuiteRun['state'] = 'done'): SuiteRun => ({
  id: 1,
  pull: 2,
  version: null,
  state,
  repeats: 3,
  tests: results.map((runs, i) => ({ id: `t${i}`, name: `Test ${i}`, runs: runs.map(call) })),
  started_at: '',
  finished_at: null,
})

const rule = (id: string, step: string | null, pull?: number): Rule => ({
  id,
  step,
  text: id,
  source: { kind: 'manual', pull },
})

const test = (id: string, pull?: number): Test => ({
  id,
  name: id,
  caller: '',
  checks: ['Ends the call'],
  source: { kind: 'manual', pull },
})

describe('a test result', () => {
  it('is a score out of its runs, never a bare pass or fail', () => {
    const [passing, risky, failing, running] = run([
      [true, true, true],
      [true, false, true],
      [false, false, false],
      [true],
    ]).tests.map((t) => score(t, 3))
    expect([passing, risky, failing, running].map(verdict)).toEqual(['pass', 'risk', 'fail', 'running'])
    expect(scoreText(risky)).toBe('2/3')
    expect(scoreText(running)).toBe('…')
  })
})

describe('a run of the suite', () => {
  it('fails as soon as one run of a test fails, and passes once all are in', () => {
    expect(summarize(run([[true, true, true], [true, false]], 'running'))).toEqual({
      state: 'running',
      passed: 1,
      failing: 1,
      total: 2,
    })
    expect(summarize(run([[true, true, true], [true, false, true]]))?.state).toBe('failed')
    expect(summarize(run([[true, true, true]]))?.state).toBe('passed')
    expect(summarize(null)).toBeNull()
  })

  it('says how it went in a few words', () => {
    expect(checksText(summarize(run([[true, true, true], [true, true, true]])))).toBe('Checks 2/2')
    expect(checksText(summarize(run([[true, false, true], [false, false, false]])))).toBe('2 tests failing')
    expect(checksText(summarize(run([[true]], 'running')))).toBe('Checks running…')
  })

  it("draws a run's path on the graph as a finished call", () => {
    const shown = asCall(call(true))
    expect(shown.status).toBe('ended')
    expect(nodeView(shown, 'greeting').fired).toEqual({ go_to_confirm: { slot: 'Tuesday 10 AM', n: '2' } })
    expect(nodeView(shown, 'confirm').step).toBe(2)
    expect(shown.lines).toEqual([
      { who: 'agent', text: 'Hi.' },
      { who: 'caller', text: 'Tuesday.' },
    ])
  })
})

describe('rules and tests', () => {
  it('groups rules by step, every step first and steps in the agent’s order', () => {
    const rules = [rule('a', 'confirm'), rule('b', null), rule('c', 'greeting'), rule('d', 'confirm')]
    expect(rulesByStep(rules, ['greeting', 'offer_times', 'confirm'])).toEqual([
      { step: null, rules: [rules[1]] },
      { step: 'greeting', rules: [rules[2]] },
      { step: 'confirm', rules: [rules[0], rules[3]] },
    ])
  })

  it('lists the tests added in this pull request first, newest first', () => {
    const tests = [test('old'), test('first', 3), test('other'), test('second', 3)]
    expect(orderTests(tests, 3).map((t) => t.id)).toEqual(['second', 'first', 'old', 'other'])
    expect(orderTests(tests, null).map((t) => t.id)).toEqual(['old', 'first', 'other', 'second'])
  })

  it('tells what a copy adds to its base and takes out of it', () => {
    const base = { rules: [rule('kept', null), rule('gone', 'confirm')], tests: [test('t1')] }
    const copy = { rules: [rule('kept', null), rule('new', 'greeting', 2)], tests: [test('t1'), test('t2', 2)] }
    expect(suiteChanges(base, copy)).toEqual({
      rulesAdded: [copy.rules[1]],
      rulesRemoved: [base.rules[1]],
      testsAdded: [copy.tests[1]],
      testsRemoved: [],
    })
  })
})
