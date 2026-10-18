// Rules, tests and their checks as the editor shows them, as pure functions.
//
// A test runs several times, because a simulated call does not always go the
// same way, so its result is a score ("2/3"), never a bare pass or fail: it
// passes at 3/3, is at risk below that and fails at 0/3. A copy's checks are
// the latest run of its whole suite (backend/store/runs.py); `summarize` says
// of a run what the backend says of it, so the bar and the lists agree while
// it is still coming in.
//
// A run's calls report their path the way a test call does, so one of them is
// drawn on the graph by turning it into a finished `Call` (call/path.ts).

import type { Checks, PullSummary, Rule, Suite, SuiteRun, Test, TestCall, TestRun } from '@/agents/types'
import type { Call } from '@/call/path'

/** How many runs of a test passed, of how many it gets, and how many are done. */
export type Score = { passed: number; done: number; of: number }

export type Verdict = 'running' | 'pass' | 'risk' | 'fail'

export function score(test: TestRun | undefined, repeats: number): Score {
  const runs = test?.runs ?? []
  return { passed: runs.filter((run) => run.passed).length, done: runs.length, of: repeats }
}

/** What a score says: every run passed, some did, none did, or not all are in yet. */
export function verdict({ passed, done, of }: Score): Verdict {
  if (done < of) return 'running'
  if (passed === of) return 'pass'
  return passed === 0 ? 'fail' : 'risk'
}

/** "2/3", or "…" while its runs are coming in. */
export function scoreText(s: Score): string {
  return s.done < s.of ? '…' : `${s.passed}/${s.of}`
}

/** What lists show of a run, as backend/store/runs.py `summary` says it. */
export function summarize(run: SuiteRun | null): Checks | null {
  if (run === null) return null
  const scores = run.tests.map((test) => score(test, run.repeats))
  const passed = scores.filter((s) => s.done === s.of && s.passed === s.of).length
  const failing = scores.filter((s) => s.passed < s.done).length
  const state = run.state === 'done' ? (failing ? 'failed' : 'passed') : run.state
  return { state, passed, failing, total: run.tests.length }
}

/** How many of a run's calls are done, of how many. */
export function progress(run: SuiteRun): { done: number; of: number } {
  return {
    done: run.tests.reduce((sum, test) => sum + test.runs.length, 0),
    of: run.tests.length * run.repeats,
  }
}

const tests = (n: number) => `${n} ${n === 1 ? 'test' : 'tests'}`

/** The checks in a few words: "Checks 5/5", "2 tests failing", "Checks running…". */
export function checksText(checks: Checks | null): string {
  if (checks === null) return 'No checks yet'
  if (checks.state === 'running') return 'Checks running…'
  if (checks.state === 'stopped') return "Checks didn't finish"
  if (checks.failing) return `${tests(checks.failing)} failing`
  return `Checks ${checks.passed}/${checks.total}`
}

/** Why checks in this state keep a copy from going live, or null if they pass. */
export function checksBlocker(checks: Checks | null): string | null {
  if (checks === null) return 'Checks have not run on the latest change yet.'
  if (checks.state === 'running') return 'Wait for the checks to finish.'
  if (checks.state === 'stopped') return "Its checks didn't finish: run them again."
  if (checks.failing) return `${tests(checks.failing)} failing.`
  return null
}

/** Whether the rule or test was added in the pull request `on`: there, it can be taken out. */
export function addedIn(item: Rule | Test, on: number | null): boolean {
  return on !== null && item.source.pull === on
}

/** Rules by where they apply: every step first, then each step in the agent's order. */
export function rulesByStep(rules: Rule[], steps: string[]): { step: string | null; rules: Rule[] }[] {
  return [null, ...steps]
    .map((step) => ({ step, rules: rules.filter((rule) => rule.step === step) }))
    .filter((group) => group.rules.length > 0)
}

/**
 * Tests in the order a list shows them: those added in the pull request `on`
 * first, newest first, then the rest as the suite has them.
 */
export function orderTests(list: Test[], on: number | null): Test[] {
  const mine = list.filter((test) => addedIn(test, on)).reverse()
  return [...mine, ...list.filter((test) => !addedIn(test, on))]
}

/** What a pull request's copy adds to and takes out of the rules and tests of its base. */
export function suiteChanges(base: Suite, copy: Suite) {
  const ids = (items: { id: string }[]) => new Set(items.map((item) => item.id))
  const [baseRules, baseTests, rules, testIds] = [ids(base.rules), ids(base.tests), ids(copy.rules), ids(copy.tests)]
  return {
    rulesAdded: copy.rules.filter((rule) => !baseRules.has(rule.id)),
    rulesRemoved: base.rules.filter((rule) => !rules.has(rule.id)),
    testsAdded: copy.tests.filter((test) => !baseTests.has(test.id)),
    testsRemoved: base.tests.filter((test) => !testIds.has(test.id)),
  }
}

/** How a call ended, in words. */
export function endedText(ended: string): string {
  switch (ended) {
    case 'agent_ended':
      return 'The agent ended the call'
    case 'caller_hung_up':
      return 'The caller hung up'
    case 'turn_cap':
      return 'Cut after 16 turns'
    case 'stuck':
      return 'The agent stopped answering'
    case 'end_not_reached':
      return 'The end step spoke, but the call went on'
    default:
      return "The call didn't run"
  }
}

/** A run's call as a finished test call, so the graph draws its path as it draws one. */
export function asCall(run: TestCall): Call {
  return {
    status: 'ended',
    steps: run.path.map((step) => ({
      node: step.node,
      at: 0,
      from: step.from,
      edge: step.edge,
      collected: Object.fromEntries(
        Object.entries(step.collected).map(([name, value]) => [name, typeof value === 'string' ? value : JSON.stringify(value)]),
      ),
    })),
    lines: run.transcript.map((line) => ({ who: line.role, text: line.text })),
    speaking: false,
    startedAt: 0,
    endedAt: Math.round(run.seconds * 1000),
    problem: null,
  }
}

/** Tokens a call used, everyone's together. */
export function tokensOf(run: TestCall): number {
  return Object.values(run.tokens).reduce((sum, used) => sum + (used.prompt ?? 0) + (used.completion ?? 0), 0)
}

/** A pull request's checks as lists show them, or null when there is nothing to say. */
export function pullChecks(pull: PullSummary): Checks | null {
  return pull.state === 'open' ? pull.checks : null
}
