// The draft over time: undo and redo.
//
// The editor keeps whole drafts, not inverse operations. An edit returns a new
// draft that shares everything it did not touch with the one before, so a
// snapshot costs little, and undo cannot disagree with the edit it undoes.
//
// Typing is one edit per keystroke. Edits that carry the same `merge` key
// (the same text field) replace each other until the field is left (`seal`),
// so one undo takes back what was typed there, not one letter.

import type { Draft, Point } from './draft'

export type History = {
  past: Draft[]
  present: Draft
  future: Draft[]
  merging: string | null // the merge key of the last edit, while it can still grow
}

export type Action =
  | { type: 'apply'; edit: (draft: Draft) => Draft; merge?: string }
  // The first layout of a just opened agent: where the cards are, not an edit.
  | { type: 'place'; layout: Record<string, Point> }
  | { type: 'seal' }
  | { type: 'undo' }
  | { type: 'redo' }

const LIMIT = 200

export function startHistory(draft: Draft): History {
  return { past: [], present: draft, future: [], merging: null }
}

export function historyReducer(history: History, action: Action): History {
  const { past, present, future } = history
  switch (action.type) {
    case 'apply': {
      const next = action.edit(present)
      if (next === present) return history
      const merging = action.merge ?? null
      if (merging !== null && merging === history.merging) {
        return { ...history, present: next }
      }
      return { past: [...past, present].slice(-LIMIT), present: next, future: [], merging }
    }
    case 'place':
      return { ...history, present: { ...present, layout: action.layout } }
    case 'seal':
      return history.merging === null ? history : { ...history, merging: null }
    case 'undo':
      if (past.length === 0) return history
      return {
        past: past.slice(0, -1),
        present: past[past.length - 1],
        future: [present, ...future],
        merging: null,
      }
    case 'redo':
      if (future.length === 0) return history
      return {
        past: [...past, present],
        present: future[0],
        future: future.slice(1),
        merging: null,
      }
  }
}
