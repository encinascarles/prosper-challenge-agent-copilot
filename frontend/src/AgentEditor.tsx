// The editor of one agent: its draft, saving it, and the page that shows both
// (the top bar with the save control, and the canvas).
//
// Mounted with a `key` per agent, so opening another agent starts a new draft
// and a new undo history.
//
// Saving sends the whole agent and its layout, and the backend takes all of it
// or nothing. Two things can stop it, and both are things the backend refuses.
// What could only leave a call stuck (draft/checks.ts) is shown and never stops
// a save. Edges that go nowhere are caught here,
// before sending: the canvas can show them, and the backend would only refuse
// the first. Anything else the backend refuses comes back as its sentence and,
// when it is about one node, that node's name, which is where the card shows it.
//
// A test call runs the saved agent, so it is offered once there is nothing left
// to save. While its card is on screen, running or ended, the editor is
// read-only: the path it draws is over this very graph, by node and edge name,
// and an edit would leave it pointing at things that changed.
import { useEffect, useEffectEvent, useMemo, useState } from 'react'

import { ApiError, updateAgent } from '@/agents/api'
import type { AgentRecord, AgentSummary } from '@/agents/types'
import { CallCard } from '@/call/CallCard'
import { TestCallButton } from '@/call/TestCallButton'
import { CallContext, useTestCall } from '@/call/useCall'
import { AgentSettingsDialog } from '@/components/AgentSettingsDialog'
import { SaveControl } from '@/components/SaveControl'
import { TopBar } from '@/components/TopBar'
import { checkFlow } from '@/draft/checks'
import { toLayout, type Draft } from '@/draft/draft'
import { EditorContext, useNewEditor, type Refusal } from '@/draft/editor'
import { GraphCanvas } from '@/graph/GraphCanvas'
import { looseEdges, toGraph } from '@/graph/model'

type Props = {
  record: AgentRecord
  agents: AgentSummary[]
  onPick: (id: string) => void
  /** The gear of another agent's row: open it, with its settings. */
  onSettings: (id: string) => void
  onNew: () => void
  onDelete: () => void
  /** Open with the agent's settings showing: its gear was what opened it. */
  showSettings: boolean
  /** Whether there are changes that leaving would lose. */
  onDirty: (dirty: boolean) => void
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

export function AgentEditor(props: Props) {
  const { record, agents, onPick, onSettings, onNew, onDelete, showSettings, onDirty, onSaved } = props
  const open = useNewEditor(record.config, record.layout)
  const testCall = useTestCall(record.id)
  const locked = testCall.call !== null
  // Locked, the draft cannot change whatever asks: the cards are inert too,
  // but this is the one place every edit goes through.
  const core = useMemo(
    () => (locked ? { ...open, apply: () => {}, cancel: () => {}, undo: () => {}, redo: () => {} } : open),
    [open, locked],
  )
  const { draft, dirty, undo, redo, markSaved, seal } = core
  const [settingsOpen, setSettingsOpen] = useState(showSettings)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  // What the backend said about a draft, kept with that draft: it stops being
  // shown as soon as the draft is another one, and the next save asks again.
  const [refused, setRefused] = useState<{ draft: Draft; refusal: Refusal } | null>(null)
  const refusal = refused?.draft === draft ? refused.refusal : null
  const [framed, setFramed] = useState<{ ids: string[] } | null>(null)

  const loose = useMemo(() => looseEdges(toGraph(draft.config, draft.ids)), [draft.config, draft.ids])
  const showLoose = () => setFramed({ ids: [...new Set(loose.map((edge) => edge.card))] })
  // Where a call could get stuck. Shown, never in the way of saving: an agent
  // is saved many times before it is finished.
  const warnings = useMemo(() => checkFlow(draft), [draft])

  const save = async () => {
    if (saving || locked) return
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

  // The tab is named after the agent it has open, as it is being named.
  const name = draft.config.name
  useEffect(() => {
    document.title = `${name || 'Untitled agent'} · Prosper`
    return () => {
      document.title = 'Prosper'
    }
  }, [name])

  // Closing or reloading the tab with changes that were not saved asks first,
  // and whoever opens another agent in this tab needs to know to ask too.
  useEffect(() => {
    onDirty(dirty)
    if (!dirty) return
    const warn = (event: BeforeUnloadEvent) => event.preventDefault()
    window.addEventListener('beforeunload', warn)
    return () => {
      window.removeEventListener('beforeunload', warn)
      onDirty(false)
    }
  }, [dirty, onDirty])

  const editor = useMemo(
    () => ({ ...core, warnings, refusal, framed, readOnly: locked }),
    [core, warnings, refusal, framed, locked],
  )
  const shownCall = useMemo(
    () => (testCall.call ? { call: testCall.call, session: testCall.session } : null),
    [testCall.call, testCall.session],
  )
  // A step of the call names its node; the canvas frames cards by id.
  const showNode = (name: string) => {
    const at = draft.config.nodes.findIndex((node) => node.name === name)
    if (at >= 0) setFramed({ ids: [draft.ids[at]] })
  }
  return (
    <EditorContext value={editor}>
      <CallContext value={shownCall}>
        <div className="flex min-h-0 flex-1 flex-col">
          <TopBar
            agents={agents}
            agentId={record.id}
            // The name shown is the draft's, as it is being typed.
            name={draft.config.name}
            onPick={onPick}
            onSettings={(id) => {
              if (id !== record.id) onSettings(id)
              else if (!locked) setSettingsOpen(true)
            }}
            onNew={onNew}
          >
            <SaveControl
              dirty={dirty}
              saving={saving}
              saved={saved}
              loose={loose.length}
              warnings={warnings.length}
              problem={refusal && { message: refusal.message, onCard: refusal.node !== null }}
              onSave={() => void save()}
              onShowLoose={showLoose}
              onShowWarnings={() => setFramed({ ids: [...new Set(warnings.map((w) => w.node))] })}
              onShowProblem={() => refusal?.node && setFramed({ ids: [refusal.node] })}
            />
            <TestCallButton dirty={dirty} warnings={warnings} open={locked} onStart={testCall.start} />
          </TopBar>
          <main className="relative flex min-h-0 flex-1">
            <GraphCanvas />
            {testCall.call && (
              <CallCard
                call={testCall.call}
                onEnd={testCall.end}
                onAgain={testCall.start}
                onClose={testCall.close}
                onShow={showNode}
              />
            )}
          </main>
          <AgentSettingsDialog
            open={settingsOpen}
            onOpenChange={(open) => {
              setSettingsOpen(open)
              // Leaving the settings ends the run of typing in them, like leaving a field.
              if (!open) seal()
            }}
            onDelete={onDelete}
          />
        </div>
      </CallContext>
    </EditorContext>
  )
}
