// Calls to the agents API (backend/api/agents.py and backend/api/pulls.py).
//
// Relative URLs: the dev server proxies /api to the backend, so the browser
// sees one origin. A failed request throws an ApiError whose message is the
// backend's own sentence ("No agent with id 'x'."), which is what the UI shows.
// Saving is one request with the agent and its layout, to a pull request's
// copy: nothing here writes to a live version.

import type {
  Agent,
  AgentConfig,
  AgentCopy,
  Layout,
  Pull,
  PullSummary,
  SuiteRun,
  Version,
  VersionSummary,
} from './types'

export class ApiError extends Error {
  status: number
  // Where an invalid agent's problem is, when the backend says: the node's
  // name and the edge's function within it.
  node: string | null
  edge: string | null

  constructor(status: number, message: string, node: string | null = null, edge: string | null = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.node = node
    this.edge = edge
  }
}

// Said when the backend can't be reached: the request never got an answer, or
// the dev server's proxy answered for a backend that is down.
export const UNREACHABLE = "Couldn't reach the server."

// The backend answers errors with `{ detail }`: a sentence for a missing or
// invalid agent (with `node` and `edge` when it is about one), and FastAPI's
// list of problems when the request itself has the wrong shape. Anything else
// is a proxy's error page: a 5xx means the backend is not there, other
// statuses get a generic message.
async function failure(response: Response): Promise<ApiError> {
  const body = (await response.json().catch(() => null)) as {
    detail?: unknown
    node?: unknown
    edge?: unknown
  } | null
  const name = (value: unknown) => (typeof value === 'string' ? value : null)
  const detail = body?.detail
  let message = response.status >= 500 ? UNREACHABLE : `Request failed (${response.status}).`
  if (typeof detail === 'string') {
    message = detail
  } else if (Array.isArray(detail)) {
    const messages = detail.map((item: { msg?: unknown }) => item?.msg)
    if (messages.every((msg) => typeof msg === 'string')) message = messages.join(' ')
  }
  return new ApiError(response.status, message, name(body?.node), name(body?.edge))
}

async function request<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  let response: Response
  try {
    response = await fetch(`/api/agents${path}`, {
      method,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    // No answer at all (offline, server stopped): the browser's own message,
    // "Failed to fetch", says nothing to a person.
    throw new ApiError(0, UNREACHABLE)
  }
  if (!response.ok) throw await failure(response)
  // A delete answers with no body.
  return (response.status === 204 ? undefined : response.json()) as Promise<T>
}

const agentPath = (id: string) => `/${encodeURIComponent(id)}`
const pullPath = (id: string, number: number) => `${agentPath(id)}/pulls/${number}`

export function listAgents(): Promise<Agent[]> {
  return request('')
}

export function getAgent(id: string): Promise<Agent> {
  return request(agentPath(id))
}

/** Stores a new agent with its PR #1 holding `config`. It is not live until that PR is merged. */
export function createAgent(config: AgentConfig): Promise<{ agent: Agent; pull: Pull }> {
  return request('', 'POST', { config })
}

/** Removes the agent for good, its versions and pull requests included. */
export function deleteAgent(id: string): Promise<void> {
  return request(agentPath(id), 'DELETE')
}

/** The agent's versions, live first. */
export function listVersions(id: string): Promise<VersionSummary[]> {
  return request(`${agentPath(id)}/versions`)
}

export function getVersion(id: string, number: number): Promise<Version> {
  return request(`${agentPath(id)}/versions/${number}`)
}

/** The agent's open pull requests, newest first. */
export function listOpenPulls(id: string): Promise<PullSummary[]> {
  return request(`${agentPath(id)}/pulls?state=open`)
}

/** All the agent's pull requests, open, merged and closed, newest first. */
export function listPulls(id: string): Promise<PullSummary[]> {
  return request(`${agentPath(id)}/pulls`)
}

export function getPull(id: string, number: number): Promise<Pull> {
  return request(pullPath(id, number))
}

/** Opens a pull request on a copy of the live version. */
export function openPull(id: string, title: string): Promise<Pull> {
  return request(`${agentPath(id)}/pulls`, 'POST', { title, kind: 'edit' })
}

/**
 * Replaces the pull request's copy and its layout: both or neither, the
 * backend validates the agent first. `summary`, one line on what changed, goes
 * in the pull request's log. `renames` are the steps this save renamed, old
 * name to new: their rules follow them. Every save runs its checks again.
 */
export function savePull(
  id: string,
  number: number,
  config: AgentConfig,
  layout: Layout,
  summary: string | null = null,
  renames: Record<string, string> = {},
): Promise<Pull> {
  return request(pullPath(id, number), 'PUT', { config, layout, summary, renames })
}

/** Adds a rule to the pull request's copy: for the step `step`, or every step if null. */
export function addRule(id: string, number: number, step: string | null, text: string): Promise<Pull> {
  return request(`${pullPath(id, number)}/rules`, 'POST', { step, text })
}

/** Takes out a rule the pull request added. */
export function removeRule(id: string, number: number, rule: string): Promise<Pull> {
  return request(`${pullPath(id, number)}/rules/${encodeURIComponent(rule)}`, 'DELETE')
}

export function addTest(
  id: string,
  number: number,
  test: { name: string; caller: string; checks: string[] },
): Promise<Pull> {
  return request(`${pullPath(id, number)}/tests`, 'POST', test)
}

/** Takes out a test the pull request added. */
export function removeTest(id: string, number: number, test: string): Promise<Pull> {
  return request(`${pullPath(id, number)}/tests/${encodeURIComponent(test)}`, 'DELETE')
}

/** Where a copy's checks are: a pull request's, or a version's. */
export type ChecksOf = { pull: number } | { version: number }

const checksPath = (id: string, of: ChecksOf) =>
  'pull' in of ? `${pullPath(id, of.pull)}/checks` : `${agentPath(id)}/versions/${of.version}/checks`

/** The latest run of the copy's tests, finished or not; null if none ran. */
export function getChecks(id: string, of: ChecksOf): Promise<SuiteRun | null> {
  return request(checksPath(id, of))
}

/** Runs the copy's tests again, replacing the latest run. */
export function runChecks(id: string, of: ChecksOf): Promise<SuiteRun> {
  return request(checksPath(id, of), 'POST')
}

/** Makes the pull request's copy the next version, which goes live. */
export function mergePull(id: string, number: number): Promise<Pull> {
  return request(`${pullPath(id, number)}/merge`, 'POST')
}

export function renamePull(id: string, number: number, title: string): Promise<Pull> {
  return request(pullPath(id, number), 'PATCH', { title })
}

export function closePull(id: string, number: number): Promise<Pull> {
  return request(`${pullPath(id, number)}/close`, 'POST')
}

export function reopenPull(id: string, number: number): Promise<Pull> {
  return request(`${pullPath(id, number)}/reopen`, 'POST')
}

/**
 * Bases the pull request on live version `onto`, with `copy` (its changes
 * replayed on that version) as its copy. Refused if live is no longer `onto`.
 */
export function updatePull(
  id: string,
  number: number,
  copy: AgentCopy,
  onto: number,
  summary: string | null,
): Promise<Pull> {
  return request(`${pullPath(id, number)}/update`, 'POST', { ...copy, onto, summary })
}
