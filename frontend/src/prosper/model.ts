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
export function prosperStatus(pull: PullSummary): 'building' | 'working' | 'waiting' | null {
  if (pull.state !== 'open' || pull.prosper === null) return null
  // Building is a new agent's setup; on anything else it works on a change.
  if (pull.prosper.state === 'working') return pull.kind === 'setup' ? 'building' : 'working'
  if (pull.prosper.state === 'waiting') return 'waiting'
  return null
}

export type Status = NonNullable<ReturnType<typeof prosperStatus>>

/** The status in words, as the top bar says it. */
export function statusText(status: Status): string {
  if (status === 'building') return 'Prosper AI is building'
  return status === 'working' ? 'Prosper AI is working' : 'Waiting for your answer'
}

/** Why Prosper AI's work keeps `pull` from merging, or null. */
export function prosperBlocker(pull: PullSummary): string | null {
  const status = prosperStatus(pull)
  if (status === 'building' || status === 'working') return 'Prosper AI is still working on it.'
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

/**
 * A conversation as it is read, one entry per turn rather than one per change:
 * Prosper AI's steps in a row are one list with its progress; what one of its
 * messages changed (rules and tests added, rewritten, taken out) is folded
 * under that message; and a run of changes by one person is one entry too.
 */
export type Item =
  | { kind: 'steps'; steps: PullEvent[]; at: string }
  | { kind: 'event'; event: PullEvent; changes: PullEvent[] }
  | { kind: 'batch'; by: string; changes: PullEvent[]; at: string }

const isChange = (event: PullEvent) => event.type === 'rule' || event.type === 'test'
// Turns whose changes (rules and tests added right after) are folded under them.
const FOLDS = new Set<PullEvent['type']>(['message', 'proposed'])

export function conversation(events: PullEvent[]): Item[] {
  const items: Item[] = []
  for (const event of events) {
    const last = items.at(-1)
    if (event.type === 'step') {
      if (last?.kind === 'steps') last.steps.push(event)
      else items.push({ kind: 'steps', steps: [event], at: event.at })
    } else if (isChange(event) && last?.kind === 'event' && FOLDS.has(last.event.type) && last.event.by === event.by) {
      last.changes.push(event)
    } else if (isChange(event) && last?.kind === 'batch' && last.by === event.by) {
      last.changes.push(event)
    } else if (isChange(event)) {
      items.push({ kind: 'batch', by: event.by, changes: [event], at: event.at })
    } else if (event.type !== 'answer' || !events.some((e) => e.type === 'question' && e.question === event.question)) {
      // An answer is shown on its question's card.
      items.push({ kind: 'event', event, changes: [] })
    }
  }
  return items
}

const plural = (n: number, one: string) => `${n} ${one}${n === 1 ? '' : 's'}`

/** One line for a batch of changes: "added 2 rules and took out 5 tests". */
export function batchText(changes: PullEvent[]): string {
  const counts = new Map<string, number>()
  for (const change of changes) {
    const verb = change.removed ? 'took out' : change.rewritten ? 'rewrote' : 'added'
    const key = `${verb}|${change.type}`
    counts.set(key, (counts.get(key) ?? 0) + 1)
  }
  const parts = [...counts].map(([key, n]) => {
    const [verb, type] = key.split('|')
    return `${verb} ${plural(n, type)}`
  })
  return parts.length > 1 ? `${parts.slice(0, -1).join(', ')} and ${parts.at(-1)}` : (parts[0] ?? '')
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
  if (source.kind === 'check') return `A failing test${where}`
  if (source.kind === 'issue') return `Issue #${source.issue}${where}`
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
