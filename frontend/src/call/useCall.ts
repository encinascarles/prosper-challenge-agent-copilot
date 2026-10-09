// The test call of the open agent: its state, and starting and closing it.
//
// One call at a time. `call` is null until one is placed and stays after it
// ends, so its path and transcript can be read; `close` clears it. The cards
// and wires of the canvas read it through CallContext, the same way they read
// the draft, so nothing is threaded through React Flow.

import { createContext, use, useCallback, useEffect, useReducer, useRef, useState } from 'react'

import type { LiveCall } from './client'
import { callReducer, newCall, type Call, type CallEvent } from './path'

export type TestCall = {
  call: Call | null
  /** Which call this is: a new number is a new call. */
  session: number
  start: () => void
  /** Hangs up. The call stays on screen as it ended. */
  end: () => void
  /** Hangs up if needed and clears the call from the screen. */
  close: () => void
}

/** The call whose path the canvas shows and which call it is, or null when there is none. */
export const CallContext = createContext<{ call: Call; session: number } | null>(null)

/** The call on screen, running or ended, or null. */
export function useShownCall(): Call | null {
  return use(CallContext)?.call ?? null
}

type State = { call: Call | null; session: number }
type Action = { type: 'start'; session: number } | { type: 'close' } | { type: 'event'; session: number; event: CallEvent }

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case 'start':
      return { call: newCall, session: action.session }
    case 'close':
      return { ...state, call: null }
    case 'event':
      // What a call that was closed or replaced still says is not about this one.
      if (state.call === null || action.session !== state.session) return state
      return { ...state, call: callReducer(state.call, action.event) }
  }
}

/** The test call of the saved agent `agentId`. */
export function useTestCall(agentId: string): TestCall {
  const [state, dispatch] = useReducer(reducer, { call: null, session: 0 })
  const live = useRef<LiveCall | null>(null)
  const session = useRef(0)

  // Hangs up and disowns whatever the call still says or is still loading.
  const drop = useCallback(() => {
    session.current += 1
    live.current?.end()
    live.current = null
  }, [])
  const start = useCallback(() => {
    drop()
    const mine = session.current
    const emit = (event: CallEvent) => dispatch({ type: 'event', session: mine, event })
    dispatch({ type: 'start', session: mine })
    // Pipecat's client is half the size of the editor and only a call needs
    // it: it is loaded when the first one is placed.
    import('./client').then(
      ({ startCall }) => {
        if (session.current === mine) live.current = startCall(agentId, emit)
      },
      () => emit({ type: 'failed', problem: "The call couldn't start. Reload the page and try again.", now: Date.now() }),
    )
  }, [agentId, drop])
  const end = useCallback(() => live.current?.end(), [])
  const close = useCallback(() => {
    drop()
    dispatch({ type: 'close' })
  }, [drop])
  // Leaving the agent hangs up: a call must not go on with nothing showing it.
  useEffect(() => drop, [drop])

  return { call: state.call, session: state.session, start, end, close }
}

/** The time, once a second while `ticking`: what the call clock counts with. */
export function useNow(ticking: boolean): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!ticking) return
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [ticking])
  return now
}
