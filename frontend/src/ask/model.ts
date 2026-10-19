// What the Ask Prosper AI panel says, as plain functions the tests read.

import type { PullSummary } from '@/agents/types'
import type { CallSummary, IssueSummary } from '@/live/types'
import { when } from '@/pulls/model'

import type { Chat, ChatMessage, ChatSummary, Link } from './types'

/** What a chat's row says at its right: the pull request it opened, or when it last moved. */
export function chatMeta(chat: Pick<ChatSummary, 'pulls' | 'updated_at'>, now = new Date()): string {
  const last = chat.pulls.at(-1)
  return last ? `Opened PR #${last}` : when(chat.updated_at, now)
}

/** The chat with `text` added as the person's question, while Prosper AI answers it. */
export function withQuestion(chat: Chat | null, text: string, at = new Date().toISOString()): ChatMessage[] {
  const asked: ChatMessage = { by: 'you', at, text, about: null, links: [], offer: null, failed: false }
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
  const call = known.calls.find((c) => c.id === link.number)
  return call ? { label: `${call.caller}'s call`, detail: when(call.at) } : { label: `Call ${link.number}`, detail: null }
}

/** Questions an empty chat suggests: one about the agent, one about its tests, one about its calls. */
export function suggestions(name: string, live: boolean): string[] {
  const agent = name || 'the agent'
  return [
    `What does ${agent} ask before booking?`,
    'Which tests are not passing, and why?',
    live ? 'Which calls went wrong today?' : `What is left before ${agent} can go live?`,
  ]
}
