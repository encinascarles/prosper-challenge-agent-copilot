// App shell: the top bar with the agent picker, and the editor of the open agent.
//
// Which agent is open lives in the URL (?agent=<id>), so a reload or a shared
// link opens the same one. Without it, the first agent of the list opens. So
// does what the editor is on (&pr=<n>): the live version, or one open pull
// request. An agent that is not live yet opens on its PR #1.
import { useCallback, useEffect, useRef, useState } from 'react'

import { AgentEditor } from '@/AgentEditor'
import {
  ApiError,
  createAgent,
  deleteAgent,
  getAgent,
  getPull,
  getVersion,
  listAgents,
  listOpenPulls,
  listVersions,
  openPull,
} from '@/agents/api'
import { NEW_AGENT } from '@/agents/template'
import type { Agent, AgentCopy, Pull, PullSummary, VersionSummary } from '@/agents/types'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { NewAgentDialog } from '@/components/NewAgentDialog'
import { Toast } from '@/components/Toast'
import { TopBar } from '@/components/TopBar'
import { useToast } from '@/components/useToast'
import { Button } from '@/components/ui/button'
import { EDITS_TITLE, openedForEdits, pullLabel, versionLabel, type On } from '@/pulls/model'

const AGENT_PARAM = 'agent'
const PULL_PARAM = 'pr'

/** The open agent and the copy of it the editor is on. */
type Opened = {
  agent: Agent
  pulls: PullSummary[] // the open ones, newest first
  versions: VersionSummary[] // live first
  on: On
  copy: AgentCopy // what the editor starts from: the live version or the PR's copy
  // A new number is a new editor: another copy was loaded. Opening a PR for
  // the first edit of live keeps the number, so the edit and its undo stay.
  session: number
}

function Notice({ children, error }: { children: React.ReactNode; error?: boolean }) {
  return (
    <p className={`m-auto text-sm ${error ? 'text-bad' : 'text-muted-foreground'}`}>{children}</p>
  )
}

/** The agent `id`, on the open PR `wanted` if there is one, else on live (or PR #1 before it is live). */
async function load(id: string, wanted: On): Promise<Omit<Opened, 'session'>> {
  const [agent, pulls, versions] = await Promise.all([getAgent(id), listOpenPulls(id), listVersions(id)])
  let on = wanted !== null && pulls.some((pull) => pull.number === wanted) ? wanted : null
  if (on === null && agent.live_version === 0) {
    on = (pulls.find((pull) => pull.kind === 'setup') ?? pulls.at(-1))?.number ?? null
    if (on === null) throw new Error(`${agent.name} is not live and has no open pull request.`)
  }
  const { config, layout } = on === null ? await getVersion(id, agent.live_version) : await getPull(id, on)
  return { agent, pulls, versions, on, copy: { config, layout } }
}

function writeUrl(id: string | null, on: On) {
  const url = new URL(location.href)
  if (id === null) url.searchParams.delete(AGENT_PARAM)
  else url.searchParams.set(AGENT_PARAM, id)
  if (on === null) url.searchParams.delete(PULL_PARAM)
  else url.searchParams.set(PULL_PARAM, String(on))
  history.replaceState(null, '', url)
}

export default function App() {
  const [agents, setAgents] = useState<Agent[] | null>(null)
  const [picked, setPicked] = useState(() =>
    new URLSearchParams(location.search).get(AGENT_PARAM),
  )
  const [opened, setOpened] = useState<Opened | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [withSettings, setWithSettings] = useState<string | null>(null)
  const toast = useToast()

  const loadAgents = useCallback(() => {
    listAgents().then(setAgents, (failure: Error) => setError(failure.message))
  }, [])
  useEffect(loadAgents, [loadAgents])

  // Only the answer to the latest request is shown: its number is the session.
  const request = useRef(0)
  const open = useCallback((id: string, wanted: On) => {
    const mine = ++request.current
    load(id, wanted).then(
      (loaded) => {
        if (request.current !== mine) return
        setOpened({ ...loaded, session: mine })
        writeUrl(id, loaded.on)
      },
      (failure: Error) => {
        if (request.current !== mine) return
        // A link to an agent that was deleted since opens the first agent
        // instead of a dead end.
        const url = new URL(location.href)
        if (failure instanceof ApiError && failure.status === 404 && url.searchParams.get(AGENT_PARAM) === id) {
          writeUrl(null, null)
          setPicked(null)
          return
        }
        setError(failure.message)
      },
    )
  }, [])

  const agentId = picked ?? agents?.[0]?.id ?? null
  useEffect(() => {
    if (agentId === null) return
    const wanted = Number(new URLSearchParams(location.search).get(PULL_PARAM)) || null
    open(agentId, wanted)
  }, [agentId, open])

  // Whether the open editor has changes that leaving it would lose. The editor
  // reports it; whatever takes this tab to another agent or copy asks first.
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
    writeUrl(id, null)
  }
  const pick = (id: string, settings = false) => {
    if (id !== agentId && leave()) go(id, settings)
  }

  // A new agent is named, stored with its PR #1 and opened on it.
  const [naming, setNaming] = useState(false)
  const create = async (name: string) => {
    if (!leave()) return
    const created = await createAgent({ ...NEW_AGENT, name })
    setNaming(false)
    loadAgents()
    go(created.agent.id)
  }

  // Deleting the open agent opens the first one left, or the empty screen.
  const remove = (id: string) => {
    deleteAgent(id)
      .then(listAgents)
      .then(
        (left) => {
          setAgents(left)
          setOpened(null)
          go(left[0]?.id ?? null)
        },
        (failure: Error) => setError(failure.message),
      )
  }

  const shown = opened?.agent.id === agentId ? opened : null

  // Another copy of the same agent: live, or one of its open PRs.
  const switchTo = (on: On) => {
    if (!shown || on === shown.on || !leave()) return
    open(shown.agent.id, on)
  }

  // The first edit of live goes to a new PR. The editor stays as it is, edit
  // and undo included, and from now on saves to that PR.
  const openForEdits = async () => {
    if (!shown) return
    const { agent } = shown
    const pull = await openPull(agent.id, EDITS_TITLE)
    setOpened((now) =>
      now && now.agent.id === agent.id
        ? { ...now, on: pull.number, pulls: [pull, ...now.pulls], agent: { ...now.agent, open_pulls: now.agent.open_pulls + 1 } }
        : now,
    )
    writeUrl(agent.id, pull.number)
    toast.show(openedForEdits(pull.number, agent.live_version))
    loadAgents()
  }

  const newPull = async () => {
    if (!shown || !leave()) return
    const { agent } = shown
    try {
      const pull = await openPull(agent.id, 'Your changes')
      toast.show(`Opened ${pullLabel(pull.number)} · live stays on ${versionLabel(agent.live_version)}`)
      loadAgents()
      open(agent.id, pull.number)
    } catch (failure) {
      toast.show((failure as Error).message)
    }
  }

  const saved = (pull: Pull) => {
    setOpened((now) =>
      now && now.agent.id === shown?.agent.id
        ? { ...now, pulls: now.pulls.map((p) => (p.number === pull.number ? pull : p)) }
        : now,
    )
    // Before the agent is live, PR #1's name is the agent's.
    loadAgents()
  }

  const merged = (pull: Pull) => {
    if (!shown) return
    toast.show(`${pullLabel(pull.number)} merged · ${versionLabel(pull.merged_version ?? 0)} is live`)
    loadAgents()
    open(shown.agent.id, null)
  }

  return (
    <>
      {shown && !error ? (
        // An open agent is the editor's page: it has the top bar too, with saving
        // in it. Keyed like the editor: another agent or copy is a fresh start.
        <div key={`${shown.agent.id}:${shown.session}`} className="flex h-dvh flex-col">
          <ErrorBoundary>
            <AgentEditor
              agent={shown.agent}
              pulls={shown.pulls}
              versions={shown.versions}
              on={shown.on}
              copy={shown.copy}
              agents={agents ?? []}
              onPick={pick}
              onSettings={(id) => pick(id, true)}
              onNew={() => setNaming(true)}
              onDelete={() => remove(shown.agent.id)}
              showSettings={withSettings === shown.agent.id}
              onDirty={onDirty}
              onSaved={saved}
              onSwitch={switchTo}
              onOpenForEdits={openForEdits}
              onNewPull={() => void newPull()}
              onMerged={merged}
              onProblem={toast.show}
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
      <Toast text={toast.text} />
    </>
  )
}
