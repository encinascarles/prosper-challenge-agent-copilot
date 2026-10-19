// The checks of the copy the editor is on: its latest run, read again while
// it runs.
//
// The backend runs a copy's tests after every change to it and writes each
// result as it comes (backend/api/checks.py). This reads that run, and while
// it is running reads it again every second and a half, so the scores fill in
// as calls finish. Polling and not a stream: a run lasts under a minute, the
// reads are a single row, and one stream per open editor would be more moving
// parts than the screen needs. `revision` is bumped by whoever changed the
// copy, so a new run is read as soon as it starts.

import { useCallback, useEffect, useState } from 'react'

import { getChecks, runChecks, runTest, type ChecksOf } from '@/agents/api'
import type { SuiteRun } from '@/agents/types'

const EVERY = 1500
const AFTER_FAILURE = 5000

export type ChecksState = {
  /** The latest run; null if none ran, undefined while it loads. */
  run: SuiteRun | null | undefined
  /** Run the tests again. */
  rerun: () => Promise<void>
  /** Run one test again, into the latest run. Resolves to why it ran alone instead, or null. */
  runOne: (test: string) => Promise<string | null>
}

/** The checks of the pull request `pull`'s copy, or of the version `version` when `pull` is null. */
export function useChecks(agentId: string, pull: number | null, version: number, revision: number): ChecksState {
  const [run, setRun] = useState<SuiteRun | null | undefined>(undefined)
  const [asked, setAsked] = useState(0)

  useEffect(() => {
    const of: ChecksOf = pull === null ? { version } : { pull }
    let stopped = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const read = () =>
      getChecks(agentId, of).then(
        (latest) => {
          if (stopped) return
          setRun(latest)
          if (latest?.state === 'running') timer = setTimeout(read, EVERY)
        },
        () => {
          if (!stopped) timer = setTimeout(read, AFTER_FAILURE)
        },
      )
    void read()
    return () => {
      stopped = true
      clearTimeout(timer)
    }
  }, [agentId, pull, version, revision, asked])

  const rerun = useCallback(async () => {
    setRun(await runChecks(agentId, pull === null ? { version } : { pull }))
    setAsked((n) => n + 1)
  }, [agentId, pull, version])

  const runOne = useCallback(
    async (test: string) => {
      const { alone, ...started } = await runTest(agentId, pull === null ? { version } : { pull }, test)
      setRun(started)
      setAsked((n) => n + 1)
      return alone
    },
    [agentId, pull, version],
  )

  return { run, rerun, runOne }
}
