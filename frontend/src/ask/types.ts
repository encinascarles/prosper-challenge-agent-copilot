// What a chat with Prosper AI is made of, as backend/api/ask.py serves it.

/**
 * Something a message names that can be opened: an issue, a pull request or
 * a call; or what an action led to: the tests of PR `number` (0: live), or
 * the list of calls or of issues.
 */
export type Link = { kind: 'issue' | 'pull' | 'call' | 'tests' | 'calls' | 'issues'; number: number }

/** Something Prosper AI proposes to do, done only when the person says so. */
export type Action = {
  tool: string
  title: string // "Merge PR #5 as v3"
  what: string // its subject: the issue's or pull request's title, the rule
  meta: string[] // what follows from it: "Calls will use v3 from then on"
  stored: string[] // the words it will keep, a line each: a test's caller and checks
  // running: being done; skipped: the person wrote again instead
  state: 'pending' | 'running' | 'done' | 'failed' | 'declined' | 'skipped'
  result: { text: string; link: Link | null } | null // once done: "Opened Issue #14"
  error: string | null // why it was refused, once failed
}

/** A change asked for in a chat, as the pull request it can open. */
export type Offer = {
  title: string // one line: "Ask who the visit is for"
  what: string // what it would change
  pull: number | null // the pull request it opened, once taken
}

export type ChatMessage = {
  by: string // "you" or "Prosper AI"
  at: string
  text: string
  about: string | null // Prosper AI's: what it answered from, "v2" or "PR #5"
  links: Link[]
  reads: string[] // what it read to answer, a line each: "Read Issue #5"
  action: Action | null
  offer: Offer | null // older chats: a pull request it offered
  failed: boolean // Prosper AI could not answer
}

export type ChatSummary = {
  id: number
  title: string // its first question
  pulls: number[] // the pull requests it opened
  count: number // of messages
  created_at: string
  updated_at: string
}

export type Chat = Omit<ChatSummary, 'count'> & { messages: ChatMessage[] }
