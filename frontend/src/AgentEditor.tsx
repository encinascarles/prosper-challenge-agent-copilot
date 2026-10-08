// The editor of one agent: its draft, saving it, and the page that shows both
// (the top bar with the save control, and the canvas).
//
// Mounted with a `key` per agent, so opening another agent starts a new draft
// and a new undo history.
//
// Saving sends the whole agent and its layout, and the backend takes all of it
// or nothing. Two things can stop it. Edges that go nowhere are caught here,
// before sending: the canvas can show them, and the backend would only refuse
// the first. Anything else the backend refuses comes back as its sentence and,
// when it is about one node, that node's name, which is where the card shows it.
import { useEffect, useEffectEvent, useMemo, useState } from 'react'

import { ApiError, updateAgent } from '@/agents/api'
import type { AgentRecord, AgentSummary } from '@/agents/types'
import { SaveControl } from '@/components/SaveControl'
import { TopBar } from '@/components/TopBar'
import { toLayout, type Draft } from '@/draft/draft'
import { EditorContext, useNewEditor, type Refusal } from '@/draft/editor'
import { GraphCanvas } from '@/graph/GraphCanvas'
import { looseEdges, toGraph } from '@/graph/model'

type Props = {
  record: AgentRecord
  agents: AgentSummary[]
  onPick: (id: string) => void
  /** The agent was saved: what lists it may be out of date. */
  onSaved: () => void
}

// Where in the draft that was sent the backend's names point: the node by its
// name, the edge by its function within the node.
function locate(sent: Draft, error: unknown): Refusal {
  const message = error instanceof Error ? error.message : String(error)
  const named = error instanceof ApiError ? error : null
  const at = named?.node == null ? -1 : sent.config.nodes.findIndex((node) => node.name === named.node)
  if (at < 0) return { message, node: null, edge: null }
  const edge = (sent.config.nodes[at].edges ?? []).findIndex((edge) => edge.function === named?.edge)
  return { message, node: sent.ids[at], edge: edge < 0 ? null : edge }
}

export function AgentEditor({ record, agents, onPick, onSaved }: Props) {
  const core = useNewEditor(record.config, record.layout)
  const { draft, dirty, undo, redo, markSaved } = core
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  // What the backend said about a draft, kept with that draft: it stops being
  // shown as soon as the draft is another one, and the next save asks again.
  const [refused, setRefused] = useState<{ draft: Draft; refusal: Refusal } | null>(null)
  const refusal = refused?.draft === draft ? refused.refusal : null
  const [framed, setFramed] = useState<{ ids: string[] } | null>(null)

  const loose = useMemo(() => looseEdges(toGraph(draft.config, draft.ids)), [draft.config, draft.ids])
  const showLoose = () => setFramed({ ids: [...new Set(loose.map((edge) => edge.card))] })

  const save = async () => {
    if (saving) return
    if (loose.length > 0) return showLoose()
    if (!dirty) return
    const sent = draft
    setSaving(true)
    try {
      await updateAgent(record.id, sent.config, toLayout(sent))
      markSaved(sent)
      setSaved(true)
      setRefused(null)
      onSaved()
    } catch (error) {
      setRefused({ draft: sent, refusal: locate(sent, error) })
    } finally {
      setSaving(false)
    }
  }

  // One undo for the whole editor, also while typing: the browser's own undo
  // only knows the text of one field, and would leave the draft behind. And
  // Cmd/Ctrl+S saves the agent instead of the page.
  const onKeyDown = useEffectEvent((event: KeyboardEvent) => {
    if (!(event.metaKey || event.ctrlKey) || event.altKey) return
    const key = event.key.toLowerCase()
    if (key === 'z') {
      event.preventDefault()
      if (event.shiftKey) redo()
      else undo()
    } else if (key === 's') {
      event.preventDefault()
      void save()
    }
  })
  useEffect(() => {
    const listener = (event: KeyboardEvent) => onKeyDown(event)
    window.addEventListener('keydown', listener)
    return () => window.removeEventListener('keydown', listener)
  }, [])

  // Closing or reloading the tab with changes that were not saved asks first.
  useEffect(() => {
    if (!dirty) return
    const warn = (event: BeforeUnloadEvent) => event.preventDefault()
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])

  const editor = useMemo(() => ({ ...core, refusal, framed }), [core, refusal, framed])
  return (
    <EditorContext value={editor}>
      <div className="flex h-dvh flex-col">
        <TopBar
          agents={agents}
          agentId={record.id}
          // Opening another agent drops this draft, like closing the tab would.
          onPick={(id) => {
            if (id !== record.id && (!dirty || window.confirm('Leave without saving your changes?'))) {
              onPick(id)
            }
          }}
        >
          <SaveControl
            dirty={dirty}
            saving={saving}
            saved={saved}
            loose={loose.length}
            problem={refusal && { message: refusal.message, onCard: refusal.node !== null }}
            onSave={() => void save()}
            onShowLoose={showLoose}
            onShowProblem={() => refusal?.node && setFramed({ ids: [refusal.node] })}
          />
        </TopBar>
        <main className="flex min-h-0 flex-1">
          <GraphCanvas />
        </main>
      </div>
    </EditorContext>
  )
}
