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
  // The draft as it was loaded or last saved. Saving moves this and nothing
  // else: what can be undone is the same before and after a save, and undoing
  // back to this draft is back to "nothing to save".
  saved: Draft
}

export type Action =
  | { type: 'apply'; edit: (draft: Draft) => Draft; merge?: string }
  // Where the layout puts the cards of a just opened agent that have no
  // position yet: not an edit, and nothing to save.
  | { type: 'place'; positions: Record<string, Point> }
  // `draft` reached the backend.
  | { type: 'saved'; draft: Draft }
  | { type: 'seal' }
  // Takes back the run of edits merged under `merge`, as if never typed.
  | { type: 'cancel'; merge: string }
  | { type: 'undo' }
  | { type: 'redo' }

const LIMIT = 200

export function startHistory(draft: Draft): History {
  return { past: [], present: draft, future: [], merging: null, saved: draft }
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
      return { ...history, past: [...past, present].slice(-LIMIT), present: next, future: [], merging }
    }
    case 'place': {
      // A position the agent was saved with wins over the layout's.
      const placed = { ...present, positions: { ...action.positions, ...present.positions } }
      return { ...history, present: placed, saved: history.saved === present ? placed : history.saved }
    }
    case 'saved':
      return history.saved === action.draft ? history : { ...history, saved: action.draft }
    case 'seal':
      return history.merging === null ? history : { ...history, merging: null }
    case 'cancel':
      if (history.merging !== action.merge || past.length === 0) return history
      return { ...history, past: past.slice(0, -1), present: past[past.length - 1], merging: null }
    case 'undo':
      if (past.length === 0) return history
      return {
        ...history,
        past: past.slice(0, -1),
        present: past[past.length - 1],
        future: [present, ...future],
        merging: null,
      }
    case 'redo':
      if (future.length === 0) return history
      return {
        ...history,
        past: [...past, present],
        present: future[0],
        future: future.slice(1),
        merging: null,
      }
  }
}
