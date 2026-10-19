// What a chat with Prosper AI is made of, as backend/api/ask.py serves it.

/** Something an answer names that can be opened: an issue, a pull request or a call. */
export type Link = { kind: 'issue' | 'pull' | 'call'; number: number }

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
  offer: Offer | null
  failed: boolean // Prosper AI could not answer
}

export type ChatSummary = {
  id: number
  title: string // its first question
  pulls: number[] // the pull requests its offers opened
  count: number // of messages
  created_at: string
  updated_at: string
}

export type Chat = Omit<ChatSummary, 'count'> & { messages: ChatMessage[] }
