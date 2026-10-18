// The agent as the backend defines it, and the records the API returns.
//
// Mirrors backend/agent_builder/schema.py field by field, with the same names:
// the editor reads and writes the JSON the bot runs, so there is no second
// model to map to. Fields the schema gives a default are optional here too,
// because a stored agent may leave them out. If the schema changes, this file
// changes with it.

/** One of a node's instructions to the LLM. */
export type TaskMessage = {
  role: string
  content: string
}

/** A Pipecat Flows action run before or after a node. Only `type` is checked. */
export type Action = {
  type: string
  [key: string]: unknown
}

/** A field an edge collects: one JSON-schema property of the tool the LLM calls. */
export type EdgeProperty = {
  type?: string
  description?: string
  enum?: string[]
  [key: string]: unknown
}

/** A transition out of a node, exposed to the LLM as a tool. */
export type Edge = {
  function: string // tool name the LLM calls to take this edge
  description: string // when the model should call it
  target: string // node to go to, by name
  properties?: Record<string, EdgeProperty>
  required?: string[]
}

export type Node = {
  name: string
  task_messages?: TaskMessage[]
  role_message?: string | null // overrides the agent's persona
  edges?: Edge[]
  pre_actions?: Action[]
  post_actions?: Action[]
  end?: boolean // terminal: ends the call
}

export type AgentConfig = {
  name: string
  initial_node: string
  nodes: Node[]
  persona?: string
  voice_id?: string
  model?: string
}

/** Where the editor drew each node, by node name. Stored next to the agent, never in it. */
export type Layout = Record<string, { x: number; y: number }>

/** An agent as a whole. What it is made of is in its versions and pull requests. */
export type Agent = {
  id: string
  name: string // the live version's, or PR #1's before the agent is live
  live_version: number // what calls run on; 0 until PR #1 is merged
  open_pulls: number
  created_at: string
  updated_at: string
}

/** One copy of the agent: the agent JSON and, next to it, its layout. */
export type AgentCopy = {
  config: AgentConfig
  layout: Layout
}

/** A row of an agent's history: the version and the pull request it came from. */
export type VersionSummary = {
  number: number
  pull: number | null // null for a version made before pull requests
  title: string | null // that pull request's title
  created_at: string
}

/** What callers get: an immutable snapshot of the agent. The latest version is live. */
export type Version = AgentCopy & {
  number: number
  pull: number | null
  created_at: string
}

export type PullEvent = {
  type: 'opened' | 'saved' | 'merged' | 'closed' | 'reopened' | 'updated'
  by: string
  at: string
  version?: number | null // "merged": the version it became; "updated": its new base
  summary?: string | null // "saved", "updated": one line on what changed
}

/** A proposed change to an agent, as lists show it. */
export type PullSummary = {
  number: number // per agent, shown as "PR #3"
  title: string
  kind: 'setup' | 'edit' // setup: PR #1 of a new agent
  state: 'open' | 'merged' | 'closed'
  base_version: number // the live version it was copied from; 0 for a setup
  merged_version: number | null
  created_at: string
  updated_at: string
}

/** A pull request with its own copy of the agent, which is what the editor saves to. */
export type Pull = PullSummary &
  AgentCopy & {
    events: PullEvent[]
  }
