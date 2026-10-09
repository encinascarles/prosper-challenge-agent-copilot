import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError, UNREACHABLE, getAgent } from './api'

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
