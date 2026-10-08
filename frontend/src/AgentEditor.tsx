// The editor of one agent: its draft, and the canvas that draws and edits it.
//
// Mounted with a `key` per agent, so opening another agent starts a new draft
// and a new undo history.
import { useEffect } from 'react'

import type { AgentConfig } from '@/agents/types'
import { EditorContext, useNewEditor } from '@/draft/editor'
import { GraphCanvas } from '@/graph/GraphCanvas'

export function AgentEditor({ config }: { config: AgentConfig }) {
  const editor = useNewEditor(config)
  const { undo, redo } = editor

  // One undo for the whole editor, also while typing: the browser's own undo
  // only knows the text of one field, and would leave the draft behind.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || event.altKey || event.key.toLowerCase() !== 'z') {
        return
      }
      event.preventDefault()
      if (event.shiftKey) redo()
      else undo()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [undo, redo])

  return (
    <EditorContext value={editor}>
      <GraphCanvas />
    </EditorContext>
  )
}
