// A test call as the editor shows it: the path it took through the graph and
// what was said, built from what the bot reports while the call runs.
//
// One pure reducer over the call's events. The bot sends a `node` message when
// the call starts and on every node change (backend/bot.py), which is all the
// path is made of: nothing here guesses a transition from a function name. The
// same reducer keeps the transcript, so the card and the canvas read one state.
//
// Nodes and edges are named as the agent JSON names them, the node by its name
// and the edge by its function, because that is what the bot knows. The call
// runs the saved agent and the editor is read-only while its path is shown, so
// those names are the draft's.

/** What the bot sends on the RTVI channel each time the call enters a node. */
export type NodeMessage = {
  type: 'node'
  node: string // the node the call is in now
  from: string | null // the node it left; null for the start node
  edge: string | null // the edge function the model called to get here
  collected: Record<string, unknown> // the arguments it passed
}

/** A node the call entered, in order. */
export type Step = {
  node: string
  at: number // seconds into the call
  from: string | null
  edge: string | null
  collected: Record<string, string> // what the edge that led here collected
}

export type Line = { who: 'agent' | 'caller'; text: string }

export type Call = {
  /** connecting: no bot yet. live: talking. ended: over. failed: it never started, or broke. */
  status: 'connecting' | 'live' | 'ended' | 'failed'
  steps: Step[]
  lines: Line[]
  /** Whether the last agent line is still being said: more text joins it. */
  speaking: boolean
  startedAt: number | null // ms, when the bot answered
  endedAt: number | null
  problem: string | null // why it failed, as a sentence
}

export type CallEvent =
  | { type: 'ready'; now: number }
  | { type: 'node'; message: NodeMessage; now: number }
  /** The agent starts a new turn: what it says next is a new line. */
  | { type: 'agent-turn' }
  | { type: 'agent-text'; text: string }
  | { type: 'caller-text'; text: string }
  | { type: 'ended'; now: number }
  | { type: 'failed'; problem: string; now: number }

export const newCall: Call = {
  status: 'connecting',
  steps: [],
  lines: [],
  speaking: false,
  startedAt: null,
  endedAt: null,
  problem: null,
}

/** A collected value as text: the model passes strings, numbers and booleans. */
function shown(value: unknown): string {
  return typeof value === 'string' ? value : JSON.stringify(value)
}

/** Whether `data` is a node message: the channel also carries whatever else a bot sends. */
export function isNodeMessage(data: unknown): data is NodeMessage {
  const message = data as Partial<NodeMessage> | null
  return (
    typeof message === 'object' &&
    message !== null &&
    message.type === 'node' &&
    typeof message.node === 'string'
  )
}

export function callReducer(call: Call, event: CallEvent): Call {
  // A call that is over stays as it ended: a late message changes nothing.
  if (call.status === 'ended' || call.status === 'failed') return call
  switch (event.type) {
    case 'ready':
      return call.status === 'live' ? call : { ...call, status: 'live', startedAt: event.now }
    case 'node': {
      const { node, from, edge, collected } = event.message
      // The start node can arrive before the client says the bot is ready.
      const startedAt = call.startedAt ?? event.now
      const step: Step = {
        node,
        at: Math.max(0, Math.round((event.now - startedAt) / 1000)),
        from: from ?? null,
        edge: edge ?? null,
        collected: Object.fromEntries(
          Object.entries(collected ?? {}).map(([name, value]) => [name, shown(value)]),
        ),
      }
      return { ...call, status: 'live', startedAt, steps: [...call.steps, step] }
    }
    case 'agent-turn':
      return call.speaking ? { ...call, speaking: false } : call
    case 'agent-text': {
      if (!event.text) return call
      const last = call.lines.at(-1)
      // The model's text arrives in pieces, spaces included: they join as they are.
      const lines =
        call.speaking && last?.who === 'agent'
          ? [...call.lines.slice(0, -1), { ...last, text: last.text + event.text }]
          : [...call.lines, { who: 'agent' as const, text: event.text.trimStart() }]
      return { ...call, lines, speaking: true }
    }
    case 'caller-text': {
      const text = event.text.trim()
      if (!text) return call
      const last = call.lines.at(-1)
      // One turn can be transcribed as several sentences: they are one bubble.
      const lines =
        last?.who === 'caller'
          ? [...call.lines.slice(0, -1), { ...last, text: `${last.text} ${text}` }]
          : [...call.lines, { who: 'caller' as const, text }]
      return { ...call, lines, speaking: false }
    }
    case 'ended':
      return { ...call, status: 'ended', speaking: false, endedAt: event.now }
    case 'failed':
      return {
        ...call,
        status: 'failed',
        speaking: false,
        endedAt: event.now,
        problem: event.problem,
      }
  }
}

/** The node the call is in, while it is live. */
export function currentNode(call: Call): string | null {
  return call.status === 'live' ? (call.steps.at(-1)?.node ?? null) : null
}

/** Where a node stands in the call. */
export type NodeView = {
  /** The number of the step that last entered it, from 1, or null if the call has not been there. */
  step: number | null
  current: boolean
  /** Its edges the call left through, by function, with what each collected. */
  fired: Record<string, Record<string, string>>
}

export function nodeView(call: Call, node: string): NodeView {
  const fired: NodeView['fired'] = {}
  for (const step of call.steps) {
    if (step.from === node && step.edge !== null) fired[step.edge] = step.collected
  }
  const last = call.steps.findLastIndex((step) => step.node === node)
  return { step: last < 0 ? null : last + 1, current: currentNode(call) === node, fired }
}

/** Whether the call went through the edge `edge` of `node`, and whether it was its last move. */
export function edgeTaken(call: Call, node: string, edge: string): 'latest' | 'taken' | null {
  const at = call.steps.findLastIndex((step) => step.from === node && step.edge === edge)
  if (at < 0) return null
  return at === call.steps.length - 1 ? 'latest' : 'taken'
}

/** What was collected in each step: the values of the edge the call left it through. */
export function collectedAt(call: Call, index: number): Record<string, string> {
  const next = call.steps[index + 1]
  return next && next.from === call.steps[index].node ? next.collected : {}
}

/** Seconds as a call clock: 42 is "0:42". */
export function clock(seconds: number): string {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

/** How long the call has run at `now`, in seconds: it stops counting when it ends. */
export function elapsed(call: Call, now: number): number {
  if (call.startedAt === null) return 0
  return Math.max(0, Math.floor(((call.endedAt ?? now) - call.startedAt) / 1000))
}
