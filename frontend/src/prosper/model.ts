// What the screens say about Prosper AI's work on a pull request, as pure
// functions: whether it is building or waiting for you, which of its questions
// are still open, the conversation in the order it is read, and where a rule
// or a test came from.
//
// Prosper AI's work is in the pull request itself (backend/store/prosper.py):
// its state, and its events in the log like anyone else's. So the Build
// screen, the pull request's page and the top bar read the same thing.

import type { AgentConfig, FileRead, PullEvent, PullSummary, Rule, Source, Test } from '@/agents/types'

import { pullLabel } from '@/pulls/model'

/** Who Prosper AI is in a pull request's log. */
export const PROSPER = 'Prosper AI'

export const isProsper = (event: PullEvent) => event.by === PROSPER

/** What Prosper AI is doing on `pull` that the person has to know: building, or waiting for them. */
export function prosperStatus(pull: PullSummary): 'building' | 'waiting' | null {
  if (pull.state !== 'open' || pull.prosper === null) return null
  if (pull.prosper.state === 'working') return 'building'
  if (pull.prosper.state === 'waiting') return 'waiting'
  return null
}

/** The status in words, as the top bar says it. */
export function statusText(status: 'building' | 'waiting'): string {
  return status === 'building' ? 'Prosper AI is building' : 'Waiting for your answer'
}

/** Why Prosper AI's work keeps `pull` from merging, or null. */
export function prosperBlocker(pull: PullSummary): string | null {
  const status = prosperStatus(pull)
  if (status === 'building') return 'Prosper AI is still working on it.'
  if (status === 'waiting') return `Prosper AI needs your answer in ${pullLabel(pull.number)}.`
  return null
}

/** Prosper AI's questions in `events` that have no answer yet, oldest first. */
export function openQuestions(events: PullEvent[]): PullEvent[] {
  const answered = new Set(events.filter((e) => e.type === 'answer').map((e) => e.question))
  return events.filter((e) => e.type === 'question' && !answered.has(e.question))
}

/** The answer given to the question `event`, if any. */
export function answerTo(events: PullEvent[], event: PullEvent): PullEvent | null {
  return events.find((e) => e.type === 'answer' && e.question === event.question) ?? null
}

/** A conversation as it is read: Prosper AI's steps in a row are one turn, with its progress. */
export type Item = { kind: 'steps'; steps: PullEvent[]; at: string } | { kind: 'event'; event: PullEvent }

export function conversation(events: PullEvent[]): Item[] {
  const items: Item[] = []
  for (const event of events) {
    const last = items.at(-1)
    if (event.type === 'step' && last?.kind === 'steps') last.steps.push(event)
    else if (event.type === 'step') items.push({ kind: 'steps', steps: [event], at: event.at })
    // An answer is shown on its question's card.
    else if (event.type !== 'answer' || !events.some((e) => e.type === 'question' && e.question === event.question))
      items.push({ kind: 'event', event })
  }
  return items
}

/** What a file's chip says next to its name: its pages, for a PDF. */
export function fileMeta(file: FileRead): string | null {
  return file.pages ? `${file.pages} ${file.pages === 1 ? 'page' : 'pages'}` : null
}

/** Lines in pasted notes, as their card counts them. */
export function lineCount(text: string): string {
  const n = text.split('\n').filter((line) => line.trim()).length
  return `${n} ${n === 1 ? 'line' : 'lines'}`
}

/**
 * Where a rule or a test came from, in a few words: the file it quotes, or
 * "Your answer in PR #1". Null for one written by hand: the list says that
 * another way.
 */
export function sourceText(source: Source): string | null {
  const where = source.pull ? ` in ${pullLabel(source.pull)}` : ''
  if (source.kind === 'guidelines') return source.file === 'your notes' ? 'Your notes' : (source.file ?? 'The guidelines')
  if (source.kind === 'answer') return `Your answer${where}`
  if (source.kind === 'request') return `Your request${where}`
  return null
}

/** Whether two copies are the same agent with the same rules and tests (where cards sit aside). */
export function sameCopy(
  a: { config: AgentConfig; rules: Rule[]; tests: Test[] },
  b: { config: AgentConfig; rules: Rule[]; tests: Test[] },
): boolean {
  const key = (copy: typeof a) => JSON.stringify([copy.config, copy.rules, copy.tests])
  return key(a) === key(b)
}
