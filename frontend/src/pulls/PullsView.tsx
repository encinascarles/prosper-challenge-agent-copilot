// The Pull requests section of an agent: the list of them or, with a number,
// one pull request's page. It loads what it shows itself; whoever holds the
// agent hears when something here changed it (a merge, a close), and gives a
// new `agent` back.

import { useEffect, useState } from 'react'

import { listPulls } from '@/agents/api'
import type { Agent, PullSummary } from '@/agents/types'

import { PullList } from './PullList'
import { PullPage } from './PullPage'

type Props = {
  agent: Agent
  /** The pull request whose page is shown, or null for the list. */
  page: number | null
  onPage: (number: number | null) => void
  onOpenInBuild: (number: number) => void
  onTry: (number: number) => void
  onNew: () => void
  onChanged: () => void
  onToast: (text: string) => void
}

export function PullsView({ agent, page, onPage, onOpenInBuild, onTry, onNew, onChanged, onToast }: Props) {
  const [pulls, setPulls] = useState<{ agent: Agent; list: PullSummary[] } | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Again whenever the agent is another record: something about its pull
  // requests changed (it is touched by every one of them).
  useEffect(() => {
    if (page !== null) return
    let stale = false
    listPulls(agent.id).then(
      (list) => !stale && setPulls({ agent, list }),
      (failure: Error) => !stale && setError(failure.message),
    )
    return () => {
      stale = true
    }
  }, [agent, page])

  useEffect(() => {
    document.title = `Pull requests · ${agent.name || 'Untitled agent'} · Prosper`
    return () => {
      document.title = 'Prosper'
    }
  }, [agent.name])

  if (error) return <p className="m-auto text-sm text-bad">{error}</p>
  if (page !== null) {
    return (
      <PullPage
        key={page}
        agent={agent}
        number={page}
        onBack={() => onPage(null)}
        onOpenInBuild={onOpenInBuild}
        onTry={onTry}
        onChanged={onChanged}
        onToast={onToast}
      />
    )
  }
  return (
    <PullList
      agent={agent}
      pulls={pulls?.agent.id === agent.id ? pulls.list : null}
      onOpen={(number) => onPage(number)}
      onNew={onNew}
    />
  )
}
