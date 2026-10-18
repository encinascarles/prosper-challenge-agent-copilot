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

/** Where a rule or a test came from: written by hand, in the pull request `pull`. */
export type Source = {
  kind: 'manual'
  pull?: number | null // the pull request it was added in; none for one older than them
}

/** A short instruction added to the agent's prompt, on every step (`step` null) or on one. */
export type Rule = {
  id: string
  step: string | null // the node's name
  text: string
  source: Source
}

/** A simulated call: who calls, and what must happen in it, one check per line. */
export type Test = {
  id: string
  name: string
  caller: string // who calls and what they want, as the simulated caller plays it
  checks: string[]
  source: Source
}

/** What a copy carries next to the agent JSON: its rules and tests. Versioned with it. */
export type Suite = {
  rules: Rule[]
  tests: Test[]
}

/** How the latest run of a copy's tests is going (backend/store/runs.py `summary`). */
export type Checks = {
  state: 'running' | 'passed' | 'failed' | 'stopped'
  passed: number // tests that passed every one of their runs
  failing: number // tests that failed at least one
  total: number
}

/** One check of one simulated call: decided from the path, or judged on the transcript. */
export type CheckResult = {
  text: string
  kind: 'reaches' | 'ends' | 'recorded' | 'judged'
  pass: boolean
  detail: string | null // why it failed, the value recorded, or the judge's reason
}

/** One of a test's simulated calls, checked. */
export type TestCall = {
  passed: boolean
  ended: string // agent_ended, caller_hung_up, turn_cap, stuck, end_not_reached or error
  seconds: number
  tokens: Record<string, { prompt: number; completion: number }>
  /** The nodes it entered, as a voice call reports them. */
  path: { node: string; from: string | null; edge: string | null; collected: Record<string, unknown> }[]
  transcript: { role: 'agent' | 'caller'; text: string; node: string | null }[]
  checks: CheckResult[]
}

/** A test's calls in a run, as they finish. */
export type TestRun = {
  id: string
  name: string
  runs: TestCall[]
}

/** A run of a copy's whole suite: each test `repeats` times. */
export type SuiteRun = {
  id: number
  pull: number | null
  version: number | null
  state: 'running' | 'done' | 'stopped'
  repeats: number
  tests: TestRun[]
  started_at: string
  finished_at: string | null
}

/** A row of an agent's history: the version and the pull request it came from. */
export type VersionSummary = {
  number: number
  pull: number | null // null for a version made before pull requests
  title: string | null // that pull request's title
  created_at: string
}

/** What callers get: an immutable snapshot of the agent. The latest version is live. */
export type Version = AgentCopy &
  Suite & {
  number: number
  pull: number | null
  created_at: string
}

export type PullEvent = {
  type: 'opened' | 'saved' | 'merged' | 'closed' | 'reopened' | 'updated' | 'rule' | 'test' | 'checks'
  by: string // "you", or "checks" for a run of its tests
  at: string
  version?: number | null // "opened": copied from; "merged": became; "updated": its new base
  summary?: string | null // "saved", "updated": one line on what changed
  step?: string | null // "rule": the step it is for; null for every step
  text?: string | null // "rule": its text; "test": its name
  removed?: boolean | null // the rule or test was taken out
  passed?: number | null // "checks": tests that passed, of `total`
  total?: number | null
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
  checks: Checks | null // its latest run of the tests; null if none ran
}

/** A pull request with its own copy of the agent, which is what the editor saves to. */
export type Pull = PullSummary &
  AgentCopy &
  Suite & {
    events: PullEvent[]
  }
