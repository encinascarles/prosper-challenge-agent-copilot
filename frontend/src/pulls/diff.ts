// What a pull request changes, and its changes replayed on a newer live
// version. Pure functions over agent JSON, no React.
//
// - diffAgents: what changed between two copies of an agent, step by step, as
//   lines a person reads (the Changes tab, the summary a save logs).
// - rebase: a pull request's changes replayed on the version that went live
//   since it was opened (Update).
//
// Stored copies carry no ids, so a step is followed from one copy to another
// by its name, and a step that is not found by name by what it says: a step
// renamed in a pull request keeps its instructions and edges, so it is the
// same step, not one removed and one added. Edges within a step are followed
// by where they go and when.
//
// Words: "step" and "moves on", never node, edge or function. Function names
// are generated from the target, so they are never compared or shown.

import type { AgentConfig, AgentCopy, Edge, EdgeProperty, Layout, Node } from '@/agents/types'
import { fieldKind } from '@/draft/draft'
import { functionName, humanize } from '@/draft/names'

/** A piece of a text compared word by word. */
export type WordPart = { op: 'same' | 'add' | 'remove'; text: string }

export type DiffLine =
  | { op: 'add' | 'remove' | 'note'; label: string; text: string }
  | { op: 'words'; label: string; parts: WordPart[] }

/** What changed in one step, or in the agent's own settings. */
export type StepChange = {
  key: string // unique in a diff: "agent", or the step's name with its kind
  label: string // the step as people read it
  kind: 'added' | 'removed' | 'edited' | 'agent'
  lines: DiffLine[]
}

/** The agent of a pull request that is based on nothing yet: everything in it is added. */
export const NOTHING: AgentConfig = { name: '', initial_node: '', nodes: [] }

export const stepLabel = (name: string) => humanize(name) || 'Untitled step'
const instructionsOf = (node?: Node) => node?.task_messages?.[0]?.content ?? ''

// Equal as JSON whatever the order of their keys: copies from different
// sides may write the same object in another order.
function canon(value: unknown): string {
  return JSON.stringify(value, (_key, v: unknown) =>
    v && typeof v === 'object' && !Array.isArray(v)
      ? Object.fromEntries(Object.entries(v).sort(([a], [b]) => a.localeCompare(b)))
      : v,
  )
}
const same = (a: unknown, b: unknown) => a === b || canon(a) === canon(b)

/* ------------------------------------------------------------ matching steps */

// How alike two steps' texts are, from 0 to 1: the words they share.
function words(node: Node): Set<string> {
  const text = [instructionsOf(node), ...(node.edges ?? []).map((edge) => edge.description)].join(' ')
  return new Set(text.toLowerCase().match(/[\p{L}\p{N}']+/gu) ?? [])
}
function likeness(a: Node, b: Node): number {
  const wa = words(a)
  const wb = words(b)
  if (wa.size === 0 || wb.size === 0) return 0
  let shared = 0
  for (const word of wa) if (wb.has(word)) shared++
  return shared / (wa.size + wb.size - shared)
}
// Alike enough to be the same step renamed: most of what it says is the same.
const RENAMED = 0.5

/**
 * For each step of `next`, the index of the same step in `base`, or -1 for a
 * step `next` added. By name first; a step whose name is gone is matched to
 * the unmatched step of `base` that says most nearly the same.
 */
export function matchSteps(base: AgentConfig, next: AgentConfig): number[] {
  const byName = new Map(base.nodes.map((node, i) => [node.name, i]))
  const match = next.nodes.map((node) => byName.get(node.name) ?? -1)
  const taken = new Set(match.filter((i) => i >= 0))
  const pairs: [number, number, number][] = []
  next.nodes.forEach((node, j) => {
    if (match[j] >= 0) return
    base.nodes.forEach((old, i) => {
      if (taken.has(i)) return
      const score = likeness(old, node)
      if (score >= RENAMED) pairs.push([score, j, i])
    })
  })
  pairs.sort((a, b) => b[0] - a[0])
  for (const [, j, i] of pairs) {
    if (match[j] >= 0 || taken.has(i)) continue
    match[j] = i
    taken.add(i)
  }
  return match
}

/** For each of `length` items, the index matched to it in `match`, or -1. */
function invert(match: number[], length: number): number[] {
  const inverse = new Array<number>(length).fill(-1)
  match.forEach((i, j) => {
    if (i >= 0) inverse[i] = j
  })
  return inverse
}

/**
 * For each edge of `next`, the index of the same edge in `base`, or -1.
 * `target` reads a base target as `next` names it, so a step renamed on the
 * way does not make its edges look moved. Same target and condition first,
 * then same target, then same condition, then what is left in order: that
 * last one is an edge moved to another step.
 */
function matchEdges(base: Edge[], next: Edge[], target: (name: string) => string): number[] {
  const match = next.map(() => -1)
  const taken = new Set<number>()
  const tests: ((a: Edge, b: Edge) => boolean)[] = [
    (a, b) => target(a.target) === b.target && a.description === b.description,
    (a, b) => target(a.target) === b.target,
    (a, b) => a.description !== '' && a.description === b.description,
    () => true,
  ]
  for (const test of tests) {
    next.forEach((edge, j) => {
      if (match[j] >= 0) return
      const i = base.findIndex((old, k) => !taken.has(k) && test(old, edge))
      if (i < 0) return
      match[j] = i
      taken.add(i)
    })
  }
  return match
}

/* ------------------------------------------------------------ word diff */

// Past this many token pairs a text is shown as removed and added whole.
const WORD_DIFF_LIMIT = 250_000

/** `before` and `after` compared word by word: what stayed, what went, what came. */
export function wordDiff(before: string, after: string): WordPart[] {
  const a = before.split(/(\s+)/).filter(Boolean)
  const b = after.split(/(\s+)/).filter(Boolean)
  if (a.length * b.length > WORD_DIFF_LIMIT) {
    return [
      { op: 'remove', text: before },
      { op: 'add', text: after },
    ]
  }
  // Longest common subsequence, table filled from the end.
  const lcs = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0))
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1])
    }
  }
  const parts: WordPart[] = []
  const push = (op: WordPart['op'], text: string) => {
    const last = parts.at(-1)
    if (last?.op === op) last.text += text
    else parts.push({ op, text })
  }
  let i = 0
  let j = 0
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      push('same', a[i++])
      j++
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) push('remove', a[i++])
    else push('add', b[j++])
  }
  while (i < a.length) push('remove', a[i++])
  while (j < b.length) push('add', b[j++])
  return parts
}

/* ------------------------------------------------------------ the diff */

const KIND_WORDS: Record<string, string> = {
  text: 'text',
  number: 'a number',
  integer: 'a whole number',
  boolean: 'yes or no',
  choice: 'a choice',
}

function textLines(label: string, before: string, after: string): DiffLine[] {
  if (before === after) return []
  if (!before) return [{ op: 'add', label, text: after }]
  if (!after) return [{ op: 'remove', label, text: before }]
  return [{ op: 'words', label, parts: wordDiff(before, after) }]
}

// What changed in one field an edge collects, in a few words.
function fieldChange(name: string, before: EdgeProperty, after: EdgeProperty, wasRequired: boolean, isRequired: boolean): string | null {
  const what: string[] = []
  if (wasRequired !== isRequired) what.push(isRequired ? 'now required' : 'now optional')
  const kind = fieldKind(after)
  if (fieldKind(before) !== kind) what.push(`now ${KIND_WORDS[kind] ?? kind}`)
  else if (kind === 'choice' && !same(before.enum, after.enum)) {
    const added = (after.enum ?? []).filter((option) => !before.enum?.includes(option))
    const removed = (before.enum ?? []).filter((option) => !after.enum?.includes(option))
    what.push(
      [added.length ? `+ ${added.join(', ')}` : '', removed.length ? `− ${removed.join(', ')}` : '']
        .filter(Boolean)
        .join(' ') || 'options reordered',
    )
  }
  if ((before.description ?? '') !== (after.description ?? '')) what.push('new description')
  const { type: _t0, enum: _e0, description: _d0, ...rest0 } = before
  const { type: _t1, enum: _e1, description: _d1, ...rest1 } = after
  if (!same(rest0, rest1)) what.push('changed')
  return what.length ? `${humanize(name)}: ${what.join(', ')}` : null
}

function fieldLines(before: Edge | undefined, after: Edge | undefined, where: string): DiffLine[] {
  const lines: DiffLine[] = []
  const p0 = before?.properties ?? {}
  const p1 = after?.properties ?? {}
  for (const name of Object.keys(p1)) {
    if (!(name in p0)) lines.push({ op: 'add', label: 'Collects', text: humanize(name) + where })
  }
  for (const name of Object.keys(p0)) {
    if (!(name in p1)) lines.push({ op: 'remove', label: 'Collects', text: humanize(name) + where })
  }
  for (const name of Object.keys(p1)) {
    if (!(name in p0)) continue
    const change = fieldChange(
      name,
      p0[name],
      p1[name],
      before?.required?.includes(name) ?? false,
      after?.required?.includes(name) ?? false,
    )
    if (change) lines.push({ op: 'note', label: 'Collects', text: change + where })
  }
  return lines
}

const destination = (target: string) => (target ? stepLabel(target) : 'nowhere yet')

function edgeLines(before: Edge[], after: Edge[], target: (name: string) => string): DiffLine[] {
  const lines: DiffLine[] = []
  const match = matchEdges(before, after, target)
  // With more than one way out, each line says which one it is about.
  const where = (edge: Edge) => (Math.max(before.length, after.length) > 1 ? ` · to ${destination(edge.target)}` : '')
  after.forEach((edge, j) => {
    const old = match[j] < 0 ? undefined : before[match[j]]
    if (!old) {
      lines.push({ op: 'add', label: `Moves on to ${destination(edge.target)}`, text: edge.description })
      lines.push(...fieldLines(undefined, edge, where(edge)))
      return
    }
    if (target(old.target) !== edge.target) {
      lines.push({
        op: 'note',
        label: 'Moves on',
        text: `to ${destination(edge.target)} instead of ${destination(target(old.target))}`,
      })
    }
    lines.push(...textLines(`When${where(edge)}`, old.description, edge.description))
    lines.push(...fieldLines(old, edge, where(edge)))
  })
  const kept = new Set(match)
  before.forEach((old, i) => {
    if (!kept.has(i)) lines.push({ op: 'remove', label: `Moves on to ${destination(target(old.target))}`, text: old.description })
  })
  return lines
}

function stepLines(
  before: Node | undefined,
  after: Node,
  base: AgentConfig,
  next: AgentConfig,
  target: (name: string) => string,
): DiffLine[] {
  const lines: DiffLine[] = []
  if (before && before.name !== after.name) lines.push({ op: 'note', label: 'Renamed', text: `from ${stepLabel(before.name)}` })
  const wasStart = before !== undefined && base.initial_node === before.name
  const isStart = next.initial_node === after.name
  if (wasStart !== isStart) lines.push({ op: isStart ? 'add' : 'remove', label: 'Start', text: 'The call starts here' })
  if (Boolean(before?.end) !== Boolean(after.end)) lines.push({ op: after.end ? 'add' : 'remove', label: 'End', text: 'Ends the call' })
  lines.push(...textLines('Instructions', instructionsOf(before), instructionsOf(after)))
  lines.push(...textLines('Persona in this step', before?.role_message ?? '', after.role_message ?? ''))
  lines.push(...edgeLines(before?.edges ?? [], after.edges ?? [], target))
  // What the editor does not edit (actions, more task messages) is still a change.
  const rest = (node?: Node) => {
    const { name: _n, edges: _e, end: _d, role_message: _r, task_messages, ...other } = node ?? ({} as Node)
    return { ...other, more: task_messages?.slice(1) ?? [] }
  }
  if (before && !same(rest(before), rest(after))) lines.push({ op: 'note', label: 'Other settings', text: 'changed' })
  return lines
}

const AGENT_FIELDS = [
  ['name', 'Name'],
  ['persona', 'Persona'],
  ['model', 'Model'],
  ['voice_id', 'Voice'],
] as const

function agentLines(base: AgentConfig, next: AgentConfig): DiffLine[] {
  const lines: DiffLine[] = []
  for (const [key, label] of AGENT_FIELDS) {
    const before = base[key] ?? ''
    const after = next[key] ?? ''
    if (before === after) continue
    if (key === 'persona') lines.push(...textLines(label, before, after))
    else {
      if (before) lines.push({ op: 'remove', label, text: before })
      if (after) lines.push({ op: 'add', label, text: after })
    }
  }
  return lines
}

/**
 * What `next` changes compared with `base`, step by step: the agent's settings
 * first, then each step `next` has (added or edited), then the steps it
 * removed. `match` says which step of `base` each step of `next` is (see
 * matchSteps); the editor passes its own, which follows a step by id.
 */
export function diffAgents(base: AgentConfig, next: AgentConfig, match = matchSteps(base, next)): StepChange[] {
  if (base === next) return []
  const changes: StepChange[] = []
  const agent = base === NOTHING ? [] : agentLines(base, next)
  if (agent.length) changes.push({ key: 'agent', label: 'Agent settings', kind: 'agent', lines: agent })
  const renamed = new Map<string, string>()
  match.forEach((i, j) => {
    if (i >= 0) renamed.set(base.nodes[i].name, next.nodes[j].name)
  })
  const target = (name: string) => renamed.get(name) ?? name
  next.nodes.forEach((after, j) => {
    const before = match[j] < 0 ? undefined : base.nodes[match[j]]
    const lines = stepLines(before, after, base, next, before ? target : (name) => name)
    if (before && lines.length === 0) return
    changes.push({ key: `${after.name}:${before ? 'edited' : 'added'}`, label: stepLabel(after.name), kind: before ? 'edited' : 'added', lines })
  })
  const kept = new Set(match)
  base.nodes.forEach((gone, i) => {
    if (!kept.has(i)) changes.push({ key: `${gone.name}:removed`, label: stepLabel(gone.name), kind: 'removed', lines: [] })
  })
  return changes
}

/** "Confirm", "Confirm and Offer times", "Confirm, Greeting and Offer times". */
export function listNames(names: string[]): string {
  if (names.length <= 1) return names[0] ?? ''
  return `${names.slice(0, -1).join(', ')} and ${names.at(-1)}`
}

/** The steps (and the agent's settings) a diff touches, as one phrase. */
export function editedWhat(changes: StepChange[]): string {
  return listNames(changes.map((change) => (change.kind === 'agent' ? "the agent's settings" : change.label)))
}

/** One line on what a diff changes, for a save's event: "Edited Confirm · added Waitlist". Null if nothing. */
export function summarize(changes: StepChange[]): string | null {
  const of = (kind: StepChange['kind']) => changes.filter((change) => change.kind === kind).map((change) => change.label)
  const parts = [
    of('edited').length ? `edited ${listNames(of('edited'))}` : '',
    of('added').length ? `added ${listNames(of('added'))}` : '',
    of('removed').length ? `removed ${listNames(of('removed'))}` : '',
    of('agent').length ? "changed the agent's settings" : '',
  ].filter(Boolean)
  if (!parts.length) return null
  const line = parts.join(' · ')
  return line[0].toUpperCase() + line.slice(1)
}

/* ------------------------------------------------------------ rebase */

/** A pull request's changes replayed on a newer live version, and where both changed the same thing. */
export type Rebased = AgentCopy & {
  /** Steps both changed in the same place, where the pull request's change was kept. */
  kept: string[]
  /** Steps the pull request edited and the newer version removed: kept, with the edit. */
  restored: string[]
  /** Steps the pull request removed and the newer version changed: removed anyway. */
  dropped: string[]
}

// Of three versions of one thing: the one that changed it. Where both did,
// ours (the pull request's).
function pick<T>(base: T, ours: T, theirs: T): { value: T; clash: boolean } {
  if (same(ours, base)) return { value: theirs, clash: false }
  if (same(theirs, base) || same(ours, theirs)) return { value: ours, clash: false }
  return { value: ours, clash: true }
}

// An edge as compared: its function follows its target, so it is left out.
const bare = ({ function: _f, ...edge }: Edge) => edge
const bareNode = (node: Node) => ({ ...node, edges: (node.edges ?? []).map(bare) })

function mergeFields(base: Edge, ours: Edge, theirs: Edge): { edge: Partial<Edge>; clash: boolean } {
  let clash = false
  const properties: Record<string, EdgeProperty> = {}
  const required: string[] = []
  const has = (edge: Edge, name: string) => name in (edge.properties ?? {})
  const req = (edge: Edge, name: string) => edge.required?.includes(name) ?? false
  const names = [...Object.keys(ours.properties ?? {}), ...Object.keys(theirs.properties ?? {})]
  for (const name of new Set([...names, ...Object.keys(base.properties ?? {})])) {
    const field = (edge: Edge) => (has(edge, name) ? { property: edge.properties![name], required: req(edge, name) } : null)
    const b = field(base)
    const o = field(ours)
    const t = field(theirs)
    const chosen = pick(b, o, t)
    clash ||= chosen.clash
    if (!chosen.value) continue
    properties[name] = chosen.value.property
    if (chosen.value.required) required.push(name)
  }
  const any = (key: 'properties' | 'required') => [base, ours, theirs].some((edge) => edge[key] !== undefined)
  return {
    edge: { ...(any('properties') ? { properties } : {}), ...(any('required') ? { required } : {}) },
    clash,
  }
}

function mergeEdge(base: Edge, ours: Edge, theirs: Edge): { edge: Edge; clash: boolean } {
  let clash = false
  const out: Record<string, unknown> = {}
  const keys = new Set([...Object.keys(base), ...Object.keys(ours), ...Object.keys(theirs)])
  for (const key of keys) {
    if (key === 'function' || key === 'properties' || key === 'required') continue
    const k = key as keyof Edge
    const chosen = pick(base[k], ours[k], theirs[k])
    clash ||= chosen.clash
    if (chosen.value !== undefined) out[key] = chosen.value
  }
  // The function goes with the target it was named after.
  out.function = (same(ours.target, base.target) ? theirs : ours).function
  const fields = mergeFields(base, ours, theirs)
  return { edge: { ...(out as Edge), ...fields.edge }, clash: clash || fields.clash }
}

function mergeEdges(base: Edge[], ours: Edge[], theirs: Edge[]): { edges: Edge[]; clash: boolean } {
  if (same(ours.map(bare), base.map(bare))) return { edges: theirs, clash: false }
  if (same(theirs.map(bare), base.map(bare))) return { edges: ours, clash: false }
  const itself = (name: string) => name
  const oursOf = invert(matchEdges(base, ours, itself), base.length)
  const theirsOf = invert(matchEdges(base, theirs, itself), base.length)
  let clash = false
  const edges: Edge[] = []
  base.forEach((edge, i) => {
    const o = oursOf[i] < 0 ? undefined : ours[oursOf[i]]
    const t = theirsOf[i] < 0 ? undefined : theirs[theirsOf[i]]
    if (!o) return // ours removed it
    if (!t) {
      // Theirs removed it: gone, unless ours changed it.
      if (!same(bare(o), bare(edge))) edges.push(o)
      return
    }
    const merged = mergeEdge(edge, o, t)
    clash ||= merged.clash
    edges.push(merged.edge)
  })
  const added = (side: Edge[], of: number[]) => side.filter((_, j) => !of.includes(j))
  edges.push(...added(theirs, theirsOf), ...added(ours, oursOf))
  return { edges, clash }
}

// The function names of a step's edges, made right for where they go now: a
// generated one (go_to_<step>) follows its target's final name, and two edges
// never share one. A name someone chose (an agent made through the API) stays.
function nameFunctions(edges: Edge[]): Edge[] {
  const taken = new Set<string>()
  return edges.map((edge) => {
    const generated = edge.function.startsWith('go_to_')
    const fits = !generated || new RegExp(`^${functionName(edge.target, [])}(_\\d+)?$`).test(edge.function)
    const name = fits && !taken.has(edge.function) ? edge.function : functionName(edge.target, taken)
    taken.add(name)
    return name === edge.function ? edge : { ...edge, function: name }
  })
}

function mergeStep(base: Node, ours: Node, theirs: Node, name: string): { node: Node; clash: boolean } {
  let clash = false
  const out: Record<string, unknown> = {}
  const keys = new Set([...Object.keys(base), ...Object.keys(ours), ...Object.keys(theirs)])
  for (const key of keys) {
    if (key === 'name' || key === 'edges') continue
    const k = key as keyof Node
    const chosen = pick(base[k], ours[k], theirs[k])
    clash ||= chosen.clash
    if (chosen.value !== undefined) out[key] = chosen.value
  }
  const edges = mergeEdges(base.edges ?? [], ours.edges ?? [], theirs.edges ?? [])
  const node = { name, ...out } as Node
  if (edges.edges.length || [base, ours, theirs].some((n) => n.edges !== undefined)) node.edges = edges.edges
  return { node, clash: clash || edges.clash }
}

// A name that is no step: references to a step that is gone point here, and
// are dropped at the end.
const GONE = '\u0000gone'

/**
 * The changes `ours` made to `base`, replayed on `theirs`, a newer version of
 * the same agent. Step by step: what only one side changed is taken from it;
 * where both changed the same thing, ours wins and the step is listed in
 * `kept`. A step ours edited and theirs removed is kept; one ours removed is
 * removed. Edges left pointing at a step that is gone are dropped.
 */
export function rebase(base: AgentCopy, ours: AgentCopy, theirs: AgentCopy): Rebased {
  const B = base.config.nodes
  const O = ours.config.nodes
  const T = theirs.config.nodes
  const oMatch = matchSteps(base.config, ours.config)
  const tMatch = matchSteps(base.config, theirs.config)
  const oursOf = invert(oMatch, B.length)
  const theirsOf = invert(tMatch, B.length)

  // Every step of any side, once: theirs in their order, then what only base
  // and ours have, then what ours added.
  type Slot = { b: number; o: number; t: number; keep: boolean; name: string }
  const slots: Slot[] = [
    ...T.map((_, t) => ({ b: tMatch[t], o: tMatch[t] < 0 ? -1 : oursOf[tMatch[t]], t })),
    ...B.flatMap((_, b) => (theirsOf[b] < 0 ? [{ b, o: oursOf[b], t: -1 }] : [])),
    ...O.flatMap((_, o) => (oMatch[o] < 0 ? [{ b: -1, o, t: -1 }] : [])),
  ].map((slot) => ({ ...slot, keep: slot.b < 0 || slot.o >= 0, name: GONE }))

  // Final names: ours where ours renamed, else theirs, else what it was.
  const taken = new Set<string>()
  for (const slot of slots) {
    if (!slot.keep) continue
    const renamedByUs = slot.o >= 0 && slot.b >= 0 && O[slot.o].name !== B[slot.b].name
    let name = renamedByUs || slot.t < 0 ? (slot.o >= 0 ? O[slot.o].name : B[slot.b].name) : T[slot.t].name
    for (let n = 2; taken.has(name); n++) name = `${slot.o >= 0 ? O[slot.o].name : T[slot.t].name}_${n}`
    taken.add(name)
    slot.name = name
  }
  const namesOf = (side: Node[], index: (slot: Slot) => number) => {
    const map = new Map<string, string>()
    for (const slot of slots) if (index(slot) >= 0) map.set(side[index(slot)].name, slot.name)
    return (name: string) => map.get(name) ?? GONE
  }
  const fromBase = namesOf(B, (slot) => slot.b)
  const fromOurs = namesOf(O, (slot) => slot.o)
  const fromTheirs = namesOf(T, (slot) => slot.t)
  // A step with its name and its edges' targets in the final names.
  const translate = (node: Node, rename: (name: string) => string): Node => ({
    ...node,
    name: rename(node.name),
    ...(node.edges ? { edges: node.edges.map((edge) => ({ ...edge, target: edge.target ? rename(edge.target) : edge.target })) } : {}),
  })

  const kept: string[] = []
  const restored: string[] = []
  const dropped: string[] = []
  const nodes: Node[] = []
  const layout: Layout = {}
  for (const slot of slots) {
    const b = slot.b >= 0 ? translate(B[slot.b], fromBase) : undefined
    const o = slot.o >= 0 ? translate(O[slot.o], fromOurs) : undefined
    const t = slot.t >= 0 ? translate(T[slot.t], fromTheirs) : undefined
    const changed = (side: Node) => b !== undefined && !same(bareNode({ ...side, name: '' }), bareNode({ ...b, name: '' }))
    if (!slot.keep) {
      if (t && changed(t)) dropped.push(stepLabel(B[slot.b].name))
      continue
    }
    let node: Node
    if (!b) node = (o ?? t)!
    else if (!t) {
      // Theirs removed it; kept only if ours changed it.
      if (!changed(o!)) continue
      restored.push(stepLabel(slot.name))
      node = o!
    } else {
      const merged = mergeStep(b, o!, t, slot.name)
      if (merged.clash) kept.push(stepLabel(slot.name))
      node = merged.node
    }
    nodes.push({ ...node, name: slot.name })
    const at = (copy: AgentCopy, side: Node[], index: number) => (index >= 0 ? copy.layout[side[index].name] : undefined)
    const position = slot.b >= 0 && slot.o >= 0 && slot.t >= 0
      ? pick(at(base, B, slot.b), at(ours, O, slot.o), at(theirs, T, slot.t)).value
      : (at(ours, O, slot.o) ?? at(theirs, T, slot.t))
    if (position) layout[slot.name] = position
  }

  // Edges into a step that is gone go nowhere: dropped.
  const names = new Set(nodes.map((node) => node.name))
  const reachable = nodes.map((node) =>
    node.edges ? { ...node, edges: nameFunctions(node.edges.filter((edge) => names.has(edge.target))) } : node,
  )

  const config: Record<string, unknown> = {}
  const keys = new Set([...Object.keys(base.config), ...Object.keys(ours.config), ...Object.keys(theirs.config)])
  let settingsClash = false
  for (const key of keys) {
    if (key === 'nodes' || key === 'initial_node') continue
    const k = key as keyof AgentConfig
    const chosen = pick(base.config[k], ours.config[k], theirs.config[k])
    settingsClash ||= chosen.clash
    if (chosen.value !== undefined) config[key] = chosen.value
  }
  if (settingsClash) kept.unshift("the agent's settings")
  let start = pick(fromBase(base.config.initial_node), fromOurs(ours.config.initial_node), fromTheirs(theirs.config.initial_node)).value
  if (!names.has(start)) start = names.has(fromTheirs(theirs.config.initial_node)) ? fromTheirs(theirs.config.initial_node) : (nodes[0]?.name ?? '')
  config.initial_node = start
  config.nodes = reachable
  return { config: config as AgentConfig, layout, kept, restored, dropped }
}

/** What an update's event says beyond "Updated to v2": "kept your text in Confirm". Null if nothing to say. */
export function updateSummary(rebased: Rebased, onto: number): string | null {
  const parts = [
    rebased.kept.length ? `kept your text in ${listNames(rebased.kept)}` : '',
    rebased.restored.length ? `kept ${listNames(rebased.restored)}, which v${onto} removed` : '',
    rebased.dropped.length ? `removed ${listNames(rebased.dropped)}, which v${onto} had changed` : '',
  ].filter(Boolean)
  return parts.length ? parts.join(' · ') : null
}
