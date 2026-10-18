// What the editor says about versions and pull requests, as pure functions.
//
// The editor is always on one of two things: the live version (what callers
// get, read-only) or one open pull request (a proposed change with its own copy
// of the agent). These decide the words for each, whether an edit has to open
// a pull request first, and what stands in the way of a merge, so the top bar,
// the bar under it and the tests all say the same thing.
//
// Words: "PR #5" and "v2", always prefixed, so a number never stands alone.

import type { PullSummary } from '@/agents/types'
import type { Draft } from '@/draft/draft'

/** The pull request the editor is on, or null for live. */
export type On = number | null

/** The title of the pull request the first edit of live opens. */
export const EDITS_TITLE = 'Your edits'

export const pullLabel = (number: number) => `PR #${number}`
export const versionLabel = (number: number) => `v${number}`

/** What the merge button of `pull` says: PR #1 is what puts the agent live. */
export function mergeLabel(pull: PullSummary, live: number): string {
  if (pull.kind === 'setup' && live === 0) return `Merge & go live as ${versionLabel(1)}`
  return `Merge as ${versionLabel(live + 1)}`
}

/** Whether live moved on since `pull` was copied from it: its copy is of an older agent. */
export function isStale(pull: PullSummary, live: number): boolean {
  return pull.state === 'open' && pull.base_version !== live
}

/** "based on v1", or what a setup is based on: nothing yet. */
export function basedOn(pull: PullSummary): string {
  return pull.base_version === 0 ? 'not live yet' : `based on ${versionLabel(pull.base_version)}`
}

/**
 * Why `pull` cannot be merged now, or null if it can. A merge takes the saved
 * copy, so changes that are not saved stand in the way: merging would quietly
 * leave them out.
 */
export function mergeBlocker(pull: PullSummary, live: number, dirty: boolean): string | null {
  if (pull.state !== 'open') return `${pullLabel(pull.number)} is ${pull.state}.`
  if (isStale(pull, live)) {
    return `Live is ${versionLabel(live)} now, and this was ${basedOn(pull)}. It needs updating before it can merge.`
  }
  if (dirty) return 'Save your changes first.'
  return null
}

/**
 * Whether the edit from `before` to `after` changes the agent, and so has to
 * go to a pull request when the editor is on live. Moving cards or tidying
 * them up changes where they are drawn, not the agent: those stay on live.
 */
export function changesAgent(before: Draft, after: Draft): boolean {
  return after.config !== before.config
}

/** What the toast says when the first edit of live opened a pull request. */
export function openedForEdits(number: number, live: number): string {
  return `Opened ${pullLabel(number)} for your edits · live stays on ${versionLabel(live)}`
}

/** What the test call button says it calls: live, or the pull request the editor is on. */
export function testCallLabel(on: On): string {
  return on === null ? 'Test call' : `Test call · ${pullLabel(on)}`
}
