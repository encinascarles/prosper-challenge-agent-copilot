// What the Ask Prosper AI panel says, as plain functions the tests read.

import type { PullSummary } from '@/agents/types'
import type { CallSummary, IssueSummary } from '@/live/types'
import { versionLabel, when } from '@/pulls/model'

import type { Action, Chat, ChatMessage, ChatSummary, Link } from './types'

/** What a chat's row says at its right: the pull request it opened, or when it last moved. */
export function chatMeta(chat: Pick<ChatSummary, 'pulls' | 'updated_at'>, now = new Date()): string {
  const last = chat.pulls.at(-1)
  return last ? `Opened PR #${last}` : when(chat.updated_at, now)
}

/** The chat with `text` added as the person's question, while Prosper AI answers it. */
export function withQuestion(chat: Chat | null, text: string, at = new Date().toISOString()): ChatMessage[] {
  const asked: ChatMessage = { by: 'you', at, text, about: null, links: [], reads: [], action: null, offer: null, failed: false }
  return [...(chat?.messages ?? []), asked]
}

/** What the things an answer links to are called, from the lists the panel has. */
export type Known = {
  issues: IssueSummary[]
  pulls: PullSummary[]
  calls: CallSummary[]
}

/** A link as its chip reads: its label and, when known, what it is. */
export function linkText(link: Link, known: Known): { label: string; detail: string | null } {
  if (link.kind === 'issue') {
    return { label: `Issue #${link.number}`, detail: known.issues.find((i) => i.number === link.number)?.title ?? null }
  }
  if (link.kind === 'pull') {
    return { label: `PR #${link.number}`, detail: known.pulls.find((p) => p.number === link.number)?.title ?? null }
  }
  if (link.kind === 'tests') return { label: link.number ? `Tests on PR #${link.number}` : 'Tests on live', detail: null }
  if (link.kind === 'calls') return { label: 'Calls', detail: null }
  if (link.kind === 'issues') return { label: 'Issues', detail: null }
  const call = known.calls.find((c) => c.id === link.number)
  return call ? { label: `${call.caller}'s call`, detail: when(call.at) } : { label: `Call ${link.number}`, detail: null }
}

/** What an empty chat suggests: a question about the agent, one about its tests or calls, and something to do. */
export function suggestions(name: string, live: boolean): string[] {
  const agent = name || 'the agent'
  return [
    `What does ${agent} ask before booking?`,
    live ? 'Which calls went wrong today?' : `What is left before ${agent} can go live?`,
    live ? 'Play a batch of calls' : 'Run all the tests again',
  ]
}

/** Where the pull request an offer opens goes: always on live, "Opens a pull request on v2". */
export function offerWhere(live: number): string {
  return live ? `Opens a pull request on ${versionLabel(live)} · nothing goes live until you merge` : 'Nothing goes live until you merge'
}

/** What a card says once it is no longer waiting: what happened, or why not. */
export function actionOutcome(action: Action): string | null {
  switch (action.state) {
    case 'done':
      return action.result?.text ?? 'Done'
    case 'failed':
      return action.error ?? 'It could not be done.'
    case 'declined':
      return 'Cancelled · nothing changed'
    case 'skipped':
      return 'Not done · you asked something else'
    default:
      return null
  }
}
