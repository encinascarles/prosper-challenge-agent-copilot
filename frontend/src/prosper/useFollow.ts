// A pull request read again every second while something is happening on it:
// Prosper AI working, or its checks running. Each step Prosper AI finishes is
// written to the pull request as it lands (backend/copilot/setup.py), so this
// is how a screen shows it coming in. Polling, not a stream: a setup lasts
// about a minute, a read is one row, and both screens that follow it already
// poll their checks the same way.

import { useEffect, useState } from 'react'

import { ApiError, getPull } from '@/agents/api'
import type { Pull } from '@/agents/types'

const EVERY = 1000
const AFTER_FAILURE = 4000

const busy = (pull: Pull | null) => pull?.prosper?.state === 'working' || pull?.checks?.state === 'running'

/**
 * The pull request `number` of the agent, while `enabled`; null until read.
 * `put` replaces it with what an action answered, which starts the reading
 * again if that action set something going.
 */
export function useFollow(agentId: string, number: number | null, enabled: boolean) {
  // Kept with what it is of, so another agent's PR #1 is never taken for this one's.
  const key = `${agentId}:${number}`
  const [held, setHeld] = useState<{ key: string; pull: Pull } | null>(null)
  const pull = held?.key === key ? held.pull : null
  const setPull = (next: Pull) => setHeld({ key, pull: next })
  const [error, setError] = useState<string | null>(null)
  const [nudge, setNudge] = useState(0)
  const going = busy(pull)

  useEffect(() => {
    if (!enabled || number === null) return
    let stopped = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const read = () =>
      getPull(agentId, number).then(
        (fresh) => {
          if (stopped) return
          setPull(fresh)
          setError(null)
          if (busy(fresh)) timer = setTimeout(read, EVERY)
        },
        (failure: Error) => {
          if (stopped) return
          // One that is not there will not be: anything else (a restart) is tried again.
          if (failure instanceof ApiError && failure.status === 404) setError(failure.message)
          else timer = setTimeout(read, AFTER_FAILURE)
        },
      )
    // Once to start with; again only while something is going on.
    if (pull === null || going) void read()
    return () => {
      stopped = true
      clearTimeout(timer)
    }
    // `pull` is read only to know whether to start: following it would read in a loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentId, number, enabled, going, nudge])

  const put = (next: Pull) => {
    setPull(next)
    setNudge((n) => n + 1)
  }
  return { pull: enabled ? pull : null, put, error }
}
