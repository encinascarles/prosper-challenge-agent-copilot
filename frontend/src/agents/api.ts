// Calls to the agents API (backend/api/agents.py).
//
// Relative URLs: the dev server proxies /api to the backend, so the browser
// sees one origin. A failed request throws an ApiError whose message is the
// backend's own sentence ("No agent with id 'x'."), which is what the UI shows.

import type { AgentRecord, AgentSummary } from './types'

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

// The backend answers errors with `{ detail }`: a sentence for a missing or
// invalid agent, and FastAPI's list of problems when the request itself has
// the wrong shape. Anything else (a proxy error page) gets a generic message.
async function problem(response: Response): Promise<string> {
  const body: unknown = await response.json().catch(() => null)
  const detail = (body as { detail?: unknown } | null)?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const messages = detail.map((item: { msg?: unknown }) => item?.msg)
    if (messages.every((msg) => typeof msg === 'string')) return messages.join(' ')
  }
  return `Request failed (${response.status}).`
}

async function request<T>(path: string): Promise<T> {
  const response = await fetch(`/api/agents${path}`)
  if (!response.ok) throw new ApiError(response.status, await problem(response))
  return response.json() as Promise<T>
}

export function listAgents(): Promise<AgentSummary[]> {
  return request('')
}

export function getAgent(id: string): Promise<AgentRecord> {
  return request(`/${encodeURIComponent(id)}`)
}
