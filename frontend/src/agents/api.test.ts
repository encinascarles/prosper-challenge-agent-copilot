import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError, UNREACHABLE, getAgent, mergePull, reopenPull, savePull, updatePull } from './api'
import { NEW_AGENT } from './template'

const answer = (status: number, body: unknown) =>
  vi.fn().mockResolvedValue(
    new Response(typeof body === 'string' ? body : JSON.stringify(body), { status }),
  )

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('a failed request', () => {
  it("says the server can't be reached when there is no answer at all", async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    const error = await getAgent('a').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).message).toBe(UNREACHABLE)
    expect((error as ApiError).node).toBeNull()
  })

  it("says the same when the proxy answers for a backend that is down", async () => {
    vi.stubGlobal('fetch', answer(502, 'Bad Gateway'))
    await expect(getAgent('a')).rejects.toThrow(UNREACHABLE)
  })

  it("keeps the backend's own sentence and where it points", async () => {
    vi.stubGlobal('fetch', answer(422, { detail: 'Edge x is wrong.', node: 'greeting', edge: 'go_to_x' }))
    const error = (await getAgent('a').catch((e: unknown) => e)) as ApiError
    expect([error.message, error.node, error.edge]).toEqual(['Edge x is wrong.', 'greeting', 'go_to_x'])
  })
})

describe('pull requests', () => {
  it('save to the pull request, never to the agent', async () => {
    const fetch = answer(200, {})
    vi.stubGlobal('fetch', fetch)
    await savePull('a b', 2, NEW_AGENT, { greeting: { x: 1, y: 2 } })
    const [url, init] = fetch.mock.calls[0] as [string, RequestInit]
    expect([url, init.method]).toEqual(['/api/agents/a%20b/pulls/2', 'PUT'])
    expect(JSON.parse(init.body as string)).toEqual({
      config: NEW_AGENT,
      layout: { greeting: { x: 1, y: 2 } },
      summary: null,
    })
  })

  it('merge with a POST to the merge of that pull request', async () => {
    const fetch = answer(200, {})
    vi.stubGlobal('fetch', fetch)
    await mergePull('a', 5)
    const [url, init] = fetch.mock.calls[0] as [string, RequestInit]
    expect([url, init.method]).toEqual(['/api/agents/a/pulls/5/merge', 'POST'])
  })

  it('keep the reason a merge was refused', async () => {
    vi.stubGlobal('fetch', answer(409, { detail: 'PR #3 is based on v1, but live is now v2.' }))
    const error = (await mergePull('a', 3).catch((e: unknown) => e)) as ApiError
    expect([error.status, error.message]).toEqual([409, 'PR #3 is based on v1, but live is now v2.'])
  })

  it('reopen and update with a POST to that pull request', async () => {
    const fetch = vi.fn().mockImplementation(async () => new Response('{}', { status: 200 }))
    vi.stubGlobal('fetch', fetch)
    await reopenPull('a', 4)
    await updatePull('a', 4, { config: NEW_AGENT, layout: {} }, 2, 'kept your text in Greeting')
    const calls = fetch.mock.calls as [string, RequestInit][]
    expect(calls.map(([url, init]) => [url, init.method])).toEqual([
      ['/api/agents/a/pulls/4/reopen', 'POST'],
      ['/api/agents/a/pulls/4/update', 'POST'],
    ])
    expect(JSON.parse(calls[1][1].body as string)).toEqual({
      config: NEW_AGENT,
      layout: {},
      onto: 2,
      summary: 'kept your text in Greeting',
    })
  })
})
