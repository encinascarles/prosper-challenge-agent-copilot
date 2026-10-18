// The editor of one agent: its draft, saving it, and the page that shows both
// (the top bar with the save control, and the canvas).
//
// The editor is on one copy of the agent: the live version, or an open pull
// request's copy. It only ever saves to a pull request. On live, the first edit
// that changes the agent opens one ("Your edits") and the edit lands there;
// the draft and its undo carry on, now saved to that pull request. Moving cards
// or tidying up on live is not a change to the agent: it opens nothing and
// there is nothing to save. Merging, from the bar under the top bar, makes the
// pull request's saved copy the next live version.
//
// Mounted with a `key` per agent and copy, so opening another one starts a new
// draft and a new undo history.
//
// Saving sends the whole agent and its layout, and the backend takes all of it
// or nothing. Two things can stop it, and both are things the backend refuses.
// What could only leave a call stuck (draft/checks.ts) is shown and never stops
// a save. Edges that go nowhere are caught here,
// before sending: the canvas can show them, and the backend would only refuse
// the first. Anything else the backend refuses comes back as its sentence and,
// when it is about one node, that node's name, which is where the card shows it.
//
// A test call runs what the editor is on as it was saved: live, or the pull
// request's copy. So on a pull request it is offered once there is nothing
// left to save. While its card is on screen, running or ended, the editor is
// read-only: the path it draws is over this very graph, by node and edge name,
// and an edit would leave it pointing at things that changed.
import { useEffect, useEffectEvent, useMemo, useState } from 'react'

import { ApiError, mergePull, savePull } from '@/agents/api'
import type { Agent, AgentCopy, Pull, PullSummary, VersionSummary } from '@/agents/types'
import { CallCard } from '@/call/CallCard'
import { TestCallButton } from '@/call/TestCallButton'
import { CallContext, useTestCall } from '@/call/useCall'
import { AgentSettingsDialog } from '@/components/AgentSettingsDialog'
import { PullBar } from '@/components/PullBar'
import { SaveControl } from '@/components/SaveControl'
import { TopBar } from '@/components/TopBar'
import { VersionPill } from '@/components/VersionPill'
import { callBlocker, checkFlow } from '@/draft/checks'
import { toLayout, type Draft } from '@/draft/draft'
import { EditorContext, useNewEditor, type EditorCore, type Refusal } from '@/draft/editor'
import { GraphCanvas } from '@/graph/GraphCanvas'
import { looseEdges, toGraph } from '@/graph/model'
import { diffAgents, summarize } from '@/pulls/diff'
import { changesAgent, testCallLabel, type On } from '@/pulls/model'

type Props = {
  agent: Agent
  pulls: PullSummary[] // the open ones, newest first
  versions: VersionSummary[]
  /** What the editor is on: an open pull request, or null for live. */
  on: On
  /** What it starts from: the live version, or that pull request's copy. */
  copy: AgentCopy
  agents: Agent[]
  onPick: (id: string) => void
  /** The gear of another agent's row: open it, with its settings. */
  onSettings: (id: string) => void
  onNew: () => void
  onDelete: () => void
  /** Open with the agent's settings showing: its gear was what opened it. */
  showSettings: boolean
  /** Whether there are changes that leaving would lose. */
  onDirty: (dirty: boolean) => void
  /** The pull request's copy was saved: what lists it may be out of date. */
  onSaved: (pull: Pull) => void
  /** Show live or another open pull request. */
  onSwitch: (on: On) => void
  /** Open a pull request for the first edit of live; resolves once the editor is on it. */
  onOpenForEdits: () => Promise<void>
  onNewPull: () => void
  /** The pull request went live. */
  onMerged: (pull: Pull) => void
  /** Say something went wrong that has no place on screen. */
  onProblem: (message: string) => void
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
  const { agent, pulls, versions, on, copy, agents, onPick, onSettings, onNew, onDelete, showSettings } = props
  const { onDirty, onSaved, onSwitch, onOpenForEdits, onNewPull, onMerged, onProblem } = props
  const pull = on === null ? null : (pulls.find((p) => p.number === on) ?? null)
  const open = useNewEditor(copy.config, copy.layout)
  const testCall = useTestCall(agent.id, on)
  const locked = testCall.call !== null

  // On live, the first edit that changes the agent opens a pull request and
  // goes on into the same draft. Until the editor is on it, further edits
  // wait in the draft and open nothing more. React finishes a click's or a
  // keystroke's render before the next one, so state is enough to tell.
  const [opening, setOpening] = useState(false)
  const openingPull = opening && on === null
  const gated: EditorCore = useMemo(
    () => ({
      ...open,
      apply: (edit, merge) => {
        if (on === null && !openingPull && changesAgent(open.draft, edit(open.draft))) {
          setOpening(true)
          onOpenForEdits().catch((error: Error) => {
            setOpening(false)
            onProblem(`Couldn't open a pull request for your edit: ${error.message}`)
          })
        }
        open.apply(edit, merge)
      },
    }),
    [open, on, openingPull, onOpenForEdits, onProblem],
  )

  // Locked, the draft cannot change whatever asks: the cards are inert too,
  // but this is the one place every edit goes through.
  const core = useMemo(
    () => (locked ? { ...gated, apply: () => {}, cancel: () => {}, undo: () => {}, redo: () => {} } : gated),
    [gated, locked],
  )
  const { draft, undo, redo, markSaved, seal, saved: lastSaved } = core
  // Only a pull request has something to save. On live the draft can differ
  // from what was loaded by where cards were moved, which is not saved.
  const dirty = on !== null && core.dirty
  const [settingsOpen, setSettingsOpen] = useState(showSettings)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [merging, setMerging] = useState(false)
  // What the backend said about a draft, kept with that draft: it stops being
  // shown as soon as the draft is another one, and the next save asks again.
  const [refused, setRefused] = useState<{ draft: Draft; refusal: Refusal } | null>(null)
  const refusal = refused?.draft === draft ? refused.refusal : null
  const [mergeRefused, setMergeRefused] = useState<{ draft: Draft; message: string } | null>(null)
  const mergeProblem = mergeRefused?.draft === draft ? mergeRefused.message : null
  const [framed, setFramed] = useState<{ ids: string[] } | null>(null)

  const loose = useMemo(() => looseEdges(toGraph(draft.config, draft.ids)), [draft.config, draft.ids])
  const showLoose = () => setFramed({ ids: [...new Set(loose.map((edge) => edge.card))] })
  // Where a call could get stuck. Shown, never in the way of saving: an agent
  // is saved many times before it is finished.
  const warnings = useMemo(() => checkFlow(draft), [draft])

  const save = async () => {
    if (saving || locked || on === null) return
    if (loose.length > 0) return showLoose()
    if (!dirty) return
    const sent = draft
    // What this save changes, for the pull request's log. The draft follows a
    // step by id, so a step renamed and rewritten in one go is still one step.
    const changes = diffAgents(lastSaved.config, sent.config, sent.ids.map((id) => lastSaved.ids.indexOf(id)))
    setSaving(true)
    try {
      const stored = await savePull(agent.id, on, sent.config, toLayout(sent), summarize(changes))
      markSaved(sent)
      setSaved(true)
      setRefused(null)
      onSaved(stored)
    } catch (error) {
      setRefused({ draft: sent, refusal: locate(sent, error) })
    } finally {
      setSaving(false)
    }
  }

  // A merge takes the saved copy, which is this draft: a refusal about a card
  // is shown on it, like a refused save.
  const merge = async () => {
    if (!pull || merging || dirty) return
    const sent = draft
    setMerging(true)
    try {
      onMerged(await mergePull(agent.id, pull.number))
    } catch (error) {
      const located = locate(sent, error)
      if (located.node !== null) setRefused({ draft: sent, refusal: located })
      else setMergeRefused({ draft: sent, message: located.message })
      setMerging(false)
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
  const unsaved = dirty || openingPull
  useEffect(() => {
    onDirty(unsaved)
    if (!unsaved) return
    const warn = (event: BeforeUnloadEvent) => event.preventDefault()
    window.addEventListener('beforeunload', warn)
    return () => {
      window.removeEventListener('beforeunload', warn)
      onDirty(false)
    }
  }, [unsaved, onDirty])

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
            agentId={agent.id}
            // The name shown is the draft's, as it is being typed.
            name={draft.config.name}
            onPick={onPick}
            onSettings={(id) => {
              if (id !== agent.id) onSettings(id)
              else if (!locked) setSettingsOpen(true)
            }}
            onNew={onNew}
            pill={
              <VersionPill
                agent={agent}
                pulls={pulls}
                versions={versions}
                on={on}
                onSwitch={onSwitch}
                onNewPull={onNewPull}
              />
            }
          >
            <SaveControl
              live={on === null}
              opening={openingPull}
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
            <TestCallButton label={testCallLabel(on)} dirty={unsaved} warnings={warnings} open={locked} onStart={testCall.start} />
          </TopBar>
          {pull && (
            <PullBar
              pull={pull}
              live={agent.live_version}
              dirty={dirty}
              merging={merging}
              callOpen={locked}
              problem={mergeProblem}
              callBlocker={locked ? 'The test call is on screen' : callBlocker(unsaved, warnings)}
              onTry={testCall.start}
              onMerge={() => void merge()}
              onBack={() => onSwitch(null)}
            />
          )}
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
