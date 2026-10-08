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

/** A row of the agent list. */
export type AgentSummary = {
  id: string
  name: string
  nodes: number
  updated_at: string
}

/** A stored agent: its id and the agent JSON. */
export type AgentRecord = {
  id: string
  config: AgentConfig
  created_at: string
  updated_at: string
}
