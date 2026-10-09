// App shell: the top bar with the agent picker, and the editor of the open agent.
//
// Which agent is open lives in the URL (?agent=<id>), so a reload or a shared
// link opens the same one. Without it, the first agent of the list opens.
import { useCallback, useEffect, useRef, useState } from 'react'

import { AgentEditor } from '@/AgentEditor'
import { createAgent, deleteAgent, getAgent, listAgents } from '@/agents/api'
import { NEW_AGENT } from '@/agents/template'
import type { AgentRecord, AgentSummary } from '@/agents/types'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { NewAgentDialog } from '@/components/NewAgentDialog'
import { TopBar } from '@/components/TopBar'
import { Button } from '@/components/ui/button'


const AGENT_PARAM = 'agent'

function Notice({ children, error }: { children: React.ReactNode; error?: boolean }) {
  return (
    <p className={`m-auto text-sm ${error ? 'text-bad' : 'text-muted-foreground'}`}>{children}</p>
  )
}

export default function App() {
  const [agents, setAgents] = useState<AgentSummary[] | null>(null)
  const [picked, setPicked] = useState(() =>
    new URLSearchParams(location.search).get(AGENT_PARAM),
  )
  const [record, setRecord] = useState<AgentRecord | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [withSettings, setWithSettings] = useState<string | null>(null)

  const loadAgents = useCallback(() => {
    listAgents().then(setAgents, (failure: Error) => setError(failure.message))
  }, [])
  useEffect(loadAgents, [loadAgents])

  const agentId = picked ?? agents?.[0]?.id ?? null
  useEffect(() => {
    if (agentId === null) return
    // An answer for an agent that is no longer the open one is dropped.
    let current = true
    getAgent(agentId).then(
      (loaded) => current && setRecord(loaded),
      (failure: Error) => current && setError(failure.message),
    )
    return () => {
      current = false
    }
  }, [agentId])

  // Whether the open editor has changes that leaving it would lose. The editor
  // reports it; whatever takes this tab to another agent asks first.
  const dirty = useRef(false)
  const onDirty = useCallback((value: boolean) => {
    dirty.current = value
  }, [])
  const leave = () => !dirty.current || window.confirm('Leave without saving your changes?')

  // `settings`: the agent was reached by its gear, and opens with its settings showing.
  const go = (id: string | null, settings = false) => {
    setError(null)
    setPicked(id)
    setWithSettings(settings ? id : null)
    const url = new URL(location.href)
    if (id === null) url.searchParams.delete(AGENT_PARAM)
    else url.searchParams.set(AGENT_PARAM, id)
    history.replaceState(null, '', url)
  }
  const pick = (id: string, settings = false) => {
    if (id !== agentId && leave()) go(id, settings)
  }

  // A new agent is named, stored and then opened like any other: it has an id,
  // it is in the list, and its first save is an ordinary save.
  const [naming, setNaming] = useState(false)
  const create = async (name: string) => {
    if (!leave()) return
    const created = await createAgent({ ...NEW_AGENT, name })
    setNaming(false)
    loadAgents()
    go(created.id)
  }

  // Deleting the open agent opens the first one left, or the empty screen.
  const remove = (id: string) => {
    deleteAgent(id)
      .then(listAgents)
      .then(
        (left) => {
          setAgents(left)
          setRecord(null)
          go(left[0]?.id ?? null)
        },
        (failure: Error) => setError(failure.message),
      )
  }

  const open = record?.id === agentId ? record : null
  return (
    <>
      {open && !error ? (
        // An open agent is the editor's page: it has the top bar too, with saving
        // in it. Keyed like the editor: another agent is a fresh start for both.
        <div key={open.id} className="flex h-dvh flex-col">
          <ErrorBoundary>
            <AgentEditor
              record={open}
              agents={agents ?? []}
              onPick={pick}
              onSettings={(id) => pick(id, true)}
              onNew={() => setNaming(true)}
              onDelete={() => remove(open.id)}
              showSettings={withSettings === open.id}
              onDirty={onDirty}
              onSaved={loadAgents}
            />
          </ErrorBoundary>
        </div>
      ) : (
        <div className="flex h-dvh flex-col">
          <TopBar
            agents={agents ?? []}
            agentId={agentId}
            onPick={pick}
            onSettings={(id) => pick(id, true)}
            onNew={() => setNaming(true)}
          />
          <main className="flex min-h-0 flex-1">
            {error ? (
              <Notice error>{error}</Notice>
            ) : agents?.length === 0 ? (
              <div className="m-auto flex flex-col items-center gap-3">
                <p className="text-sm text-muted-foreground">No agents yet.</p>
                <Button size="sm" onClick={() => setNaming(true)}>
                  New agent
                </Button>
              </div>
            ) : (
              <Notice>Loading…</Notice>
            )}
          </main>
        </div>
      )}
      <NewAgentDialog open={naming} onOpenChange={setNaming} onCreate={create} />
    </>
  )
}
