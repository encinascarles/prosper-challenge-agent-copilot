// Calls to the agents API (backend/api/agents.py).
//
// Relative URLs: the dev server proxies /api to the backend, so the browser
// sees one origin. A failed request throws an ApiError whose message is the
// backend's own sentence ("No agent with id 'x'."), which is what the UI shows.
// Saving is one request with the agent and its layout.

import type { AgentConfig, AgentRecord, AgentSummary, Layout } from './types'

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

export function listAgents(): Promise<AgentSummary[]> {
  return request('')
}

export function getAgent(id: string): Promise<AgentRecord> {
  return request(`/${encodeURIComponent(id)}`)
}

/** Stores a new agent. The editor lays it out when it first opens. */
export function createAgent(config: AgentConfig): Promise<AgentRecord> {
  return request('', 'POST', { config })
}

/** Replaces the agent and its layout: both or neither, the backend validates the agent first. */
export function updateAgent(id: string, config: AgentConfig, layout: Layout): Promise<AgentRecord> {
  return request(`/${encodeURIComponent(id)}`, 'PUT', { config, layout })
}

/** Removes the agent for good. */
export function deleteAgent(id: string): Promise<void> {
  return request(`/${encodeURIComponent(id)}`, 'DELETE')
}
