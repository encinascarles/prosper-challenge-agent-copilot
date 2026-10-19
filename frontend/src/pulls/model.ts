// What the editor says about versions and pull requests, as pure functions.
//
// The editor is always on one of two things: the live version (what callers
// get, read-only) or one open pull request (a proposed change with its own copy
// of the agent). These decide the words for each, whether an edit has to open
// a pull request first, and what stands in the way of a merge, so the top bar,
// the bar under it and the tests all say the same thing.
//
// Words: "PR #5" and "v2", always prefixed, so a number never stands alone.

import type { Checks, PullSummary } from '@/agents/types'
import type { Draft } from '@/draft/draft'
import { prosperBlocker } from '@/prosper/model'
import { checksBlocker } from '@/suite/model'

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
 * leave them out. Nor while Prosper AI works on it or waits for an answer.
 * And its checks must have passed on that copy: `checks`, the latest run as
 * the caller has it (by default, as the list had it).
 */
export function mergeBlocker(
  pull: PullSummary,
  live: number,
  dirty: boolean,
  checks: Checks | null = pull.checks,
): string | null {
  if (pull.state !== 'open') return `${pullLabel(pull.number)} is ${pull.state}.`
  const prosper = prosperBlocker(pull)
  if (prosper) return prosper
  if (isStale(pull, live)) {
    return `Live is ${versionLabel(live)} now, and this was ${basedOn(pull)}. It needs updating before it can merge.`
  }
  if (dirty) return 'Save your changes first.'
  return checksBlocker(checks)
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

/**
 * The muted line under a pull request's title in lists: what it is based on,
 * or what became of it. A stale one says first that it needs an update.
 */
export function pullMeta(pull: PullSummary, live: number): string {
  const fixes = pull.fixes ? `Fixes Issue #${pull.fixes} · ` : pull.chat ? `From your chat “${pull.chat.title}” · ` : ''
  if (pull.state === 'merged') return `${fixes}merged as ${versionLabel(pull.merged_version ?? 0)}`
  if (pull.state === 'closed') return `${fixes}closed · ${basedOn(pull)}`
  return isStale(pull, live) ? `Needs update · ${fixes}${basedOn(pull)}` : `${fixes}${basedOn(pull)}`
}

/** What an open pull request means for calls, on its page. Null once it is merged or closed. */
export function callsNote(pull: PullSummary, live: number): string | null {
  if (pull.state !== 'open') return null
  if (live === 0) return 'Nobody can call it until you merge'
  return `Calls keep using ${versionLabel(live)} until you merge`
}

/** When something happened, as short as lists want it: the time today, the day before. */
export function when(at: string, now = new Date()): string {
  const date = new Date(at)
  if (date.toDateString() === now.toDateString()) {
    return date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
  }
  return date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    ...(date.getFullYear() === now.getFullYear() ? {} : { year: 'numeric' }),
  })
}
