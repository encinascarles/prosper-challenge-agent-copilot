// The editor's state, for the components that draw it: the current draft and
// the ways to change it. One editor per open agent, shared through context so a
// card deep in the canvas can edit without props threaded through React Flow.

import { createContext, use, useMemo, useReducer } from 'react'

import type { AgentConfig } from '@/agents/types'

import { openDraft, type Draft, type Point } from './draft'
import { historyReducer, startHistory } from './history'

export type Editor = {
  draft: Draft
  /** Makes an edit. Edits with the same `merge` key are undone together. */
  apply: (edit: (draft: Draft) => Draft, merge?: string) => void
  /** Ends the run of merged edits: the field was left. */
  seal: () => void
  /** Puts the cards of a just opened agent in their first positions. */
  place: (layout: Record<string, Point>) => void
  undo: () => void
  redo: () => void
}

export const EditorContext = createContext<Editor | null>(null)

export function useEditor(): Editor {
  const editor = use(EditorContext)
  if (!editor) throw new Error('useEditor needs an EditorContext above it.')
  return editor
}

/** An editor over the draft of `config`. Create one per open agent. */
export function useNewEditor(config: AgentConfig): Editor {
  const [history, dispatch] = useReducer(historyReducer, config, (loaded) =>
    startHistory(openDraft(loaded)),
  )
  const actions = useMemo(
    () => ({
      apply: (edit: (draft: Draft) => Draft, merge?: string) =>
        dispatch({ type: 'apply', edit, merge }),
      seal: () => dispatch({ type: 'seal' }),
      place: (layout: Record<string, Point>) => dispatch({ type: 'place', layout }),
      undo: () => dispatch({ type: 'undo' }),
      redo: () => dispatch({ type: 'redo' }),
    }),
    [],
  )
  return useMemo(() => ({ draft: history.present, ...actions }), [history.present, actions])
}
