// The editor's state, for the components that draw it: the current draft and
// the ways to change it. One editor per open agent, shared through context so a
// card deep in the canvas can edit without props threaded through React Flow.

import { createContext, use, useMemo, useReducer } from 'react'

import type { AgentConfig, Layout } from '@/agents/types'

import { openDraft, type Draft, type Point } from './draft'
import { historyReducer, startHistory } from './history'

export type Editor = {
  draft: Draft
  /** Makes an edit. Edits with the same `merge` key are undone together. */
  apply: (edit: (draft: Draft) => Draft, merge?: string) => void
  /** Ends the run of merged edits: the field was left. */
  seal: () => void
  /** Takes back the run of edits merged under `merge`: the field was left in a state that cannot stay. */
  cancel: (merge: string) => void
  /** Puts the cards of a just opened agent that have no position yet where the layout says. */
  place: (positions: Record<string, Point>) => void
  undo: () => void
  redo: () => void
  /** Whether the draft differs from what was loaded or last saved. */
  dirty: boolean
  /** Records that `draft` reached the backend. */
  markSaved: (draft: Draft) => void
}

export const EditorContext = createContext<Editor | null>(null)

export function useEditor(): Editor {
  const editor = use(EditorContext)
  if (!editor) throw new Error('useEditor needs an EditorContext above it.')
  return editor
}

/** An editor over the draft of a loaded agent and its layout. Create one per open agent. */
export function useNewEditor(config: AgentConfig, layout: Layout): Editor {
  const [history, dispatch] = useReducer(historyReducer, null, () =>
    startHistory(openDraft(config, layout)),
  )
  const actions = useMemo(
    () => ({
      apply: (edit: (draft: Draft) => Draft, merge?: string) =>
        dispatch({ type: 'apply', edit, merge }),
      seal: () => dispatch({ type: 'seal' }),
      cancel: (merge: string) => dispatch({ type: 'cancel', merge }),
      place: (positions: Record<string, Point>) => dispatch({ type: 'place', positions }),
      undo: () => dispatch({ type: 'undo' }),
      redo: () => dispatch({ type: 'redo' }),
      markSaved: (draft: Draft) => dispatch({ type: 'saved', draft }),
    }),
    [],
  )
  const dirty = history.present !== history.saved
  return useMemo(
    () => ({ draft: history.present, dirty, ...actions }),
    [history.present, dirty, actions],
  )
}
