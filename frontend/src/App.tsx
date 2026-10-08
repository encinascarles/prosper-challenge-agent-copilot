// App shell: the top bar with the agent picker, and the editor of the open agent.
//
// Which agent is open lives in the URL (?agent=<id>), so a reload or a shared
// link opens the same one. Without it, the first agent of the list opens.
import { useCallback, useEffect, useState } from 'react'

import { AgentEditor } from '@/AgentEditor'
import { getAgent, listAgents } from '@/agents/api'
import type { AgentRecord, AgentSummary } from '@/agents/types'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { TopBar } from '@/components/TopBar'


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

  const pick = (id: string) => {
    setError(null)
    setPicked(id)
    const url = new URL(location.href)
    url.searchParams.set(AGENT_PARAM, id)
    history.replaceState(null, '', url)
  }

  const open = record?.id === agentId ? record : null
  // An open agent is the editor's page: it has the top bar too, with saving in it.
  if (open && !error) {
    return (
      // Keyed like the editor: opening another agent is a fresh start for both.
      <div key={open.id} className="flex h-dvh flex-col">
        <ErrorBoundary>
          <AgentEditor record={open} agents={agents ?? []} onPick={pick} onSaved={loadAgents} />
        </ErrorBoundary>
      </div>
    )
  }
  return (
    <div className="flex h-dvh flex-col">
      <TopBar agents={agents ?? []} agentId={agentId} onPick={pick} />
      <main className="flex min-h-0 flex-1">
        {error ? (
          <Notice error>{error}</Notice>
        ) : agents?.length === 0 ? (
          <Notice>No agents yet.</Notice>
        ) : (
          <Notice>Loading…</Notice>
        )}
      </main>
    </div>
  )
}
