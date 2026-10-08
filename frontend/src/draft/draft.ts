// The draft: the agent being edited, held in the browser.
//
// Every edit the editor offers is a function here that takes a draft and
// returns the next one. They are pure (no React, no network), so each rule of
// the editor is in one place and can be tested: what a rename drags along,
// what becoming the start node disconnects, how function names are kept valid.
// An edit that changes nothing returns the draft it was given.
//
// The draft changes only what the editor edits. Whatever else a node carries
// (role_message, pre and post actions, task messages after the first) passes
// through untouched, so opening and saving an agent never loses what the
// Copilot or the API put there.

import type { AgentConfig, Edge, EdgeProperty, Node } from '@/agents/types'

import { functionName } from './names'

export type Point = { x: number; y: number }

export type Draft = {
  config: AgentConfig
  // One id per node, in the order of `config.nodes`. A name is text being
  // edited; the id is what stays the same while it is.
  ids: string[]
  // Where each card is, by node id: a rename then carries the position along
  // without anyone moving it. It is saved by node name (see `toLayout`).
  positions: Record<string, Point>
}

/** Card positions as they are stored and sent: by node name. */
export type Layout = Record<string, Point>

/** A target that is no node: the edge is not connected. */
export const NOWHERE = ''

let lastId = 0

/** An id for a node. Not pure, so it is made by the caller and passed to the edit. */
export function newNodeId(): string {
  return `node-${++lastId}`
}

/** The draft of a loaded agent, with its cards where `layout` says. A node it does not place has no position yet. */
export function openDraft(config: AgentConfig, layout: Layout = {}): Draft {
  const ids = config.nodes.map(newNodeId)
  const positions: Draft['positions'] = {}
  config.nodes.forEach((node, i) => {
    if (layout[node.name]) positions[ids[i]] = layout[node.name]
  })
  return { config, ids, positions }
}

/** The draft's card positions by node name, to save next to the agent. */
export function toLayout(draft: Draft): Layout {
  const layout: Layout = {}
  draft.config.nodes.forEach((node, i) => {
    const position = draft.positions[draft.ids[i]]
    if (position) layout[node.name] = position
  })
  return layout
}

export function nodeOf(draft: Draft, id: string): Node | undefined {
  return draft.config.nodes[draft.ids.indexOf(id)]
}

/** Whether another node of the agent is already called `name`. */
export function nameTaken(draft: Draft, id: string, name: string): boolean {
  return draft.config.nodes.some((node, i) => node.name === name && draft.ids[i] !== id)
}

/** Whether the edge already collects another field called `name`. */
export function fieldTaken(edge: Edge, field: string, name: string): boolean {
  return name !== field && name in (edge.properties ?? {})
}

function withNodes(draft: Draft, nodes: Node[]): Draft {
  return { ...draft, config: { ...draft.config, nodes } }
}

function updateNode(draft: Draft, id: string, change: (node: Node) => Node): Draft {
  const index = draft.ids.indexOf(id)
  const node = draft.config.nodes[index]
  if (!node) return draft
  const changed = change(node)
  if (changed === node) return draft
  return withNodes(draft, draft.config.nodes.with(index, changed))
}

function updateEdge(draft: Draft, id: string, index: number, change: (edge: Edge) => Edge): Draft {
  return updateNode(draft, id, (node) => {
    const edge = node.edges?.[index]
    if (!edge) return node
    const changed = change(edge)
    return changed === edge ? node : { ...node, edges: node.edges!.with(index, changed) }
  })
}

// Points every edge that goes to `from` at `to`, with the function name that
// goes with its new target.
function retarget(nodes: Node[], from: string, to: string): Node[] {
  return nodes.map((node) => {
    if (!node.edges?.some((edge) => edge.target === from)) return node
    const taken = new Set(
      node.edges.filter((edge) => edge.target !== from).map((edge) => edge.function),
    )
    const edges = node.edges.map((edge) => {
      if (edge.target !== from) return edge
      const name = functionName(to, taken)
      taken.add(name)
      return { ...edge, target: to, function: name }
    })
    return { ...node, edges }
  })
}

/**
 * Renames a node. The edges into it and the start of the agent follow the
 * name; its position is kept by id, so it needs no following. Refused (nothing
 * changes) if the name is empty or another node has it.
 */
export function renameNode(draft: Draft, id: string, name: string): Draft {
  const old = nodeOf(draft, id)?.name
  if (old === undefined || name === old || name === NOWHERE || nameTaken(draft, id, name)) {
    return draft
  }
  const nodes = retarget(draft.config.nodes, old, name).map((node, i) =>
    draft.ids[i] === id ? { ...node, name } : node,
  )
  return {
    ...draft,
    config: {
      ...draft.config,
      nodes,
      initial_node: draft.config.initial_node === old ? name : draft.config.initial_node,
    },
  }
}

/** Sets what the node tells the model: the content of its first task message. */
export function setInstructions(draft: Draft, id: string, content: string): Draft {
  return updateNode(draft, id, (node) => {
    const [first, ...rest] = node.task_messages ?? []
    if (first?.content === content) return node
    // The role Pipecat Flows' own examples give a node's task.
    const message = first ? { ...first, content } : { role: 'developer', content }
    return { ...node, task_messages: [message, ...rest] }
  })
}

/** Sets when the model should take the edge. */
export function setEdgeDescription(
  draft: Draft,
  id: string,
  index: number,
  description: string,
): Draft {
  return updateEdge(draft, id, index, (edge) =>
    edge.description === description ? edge : { ...edge, description },
  )
}

/** Adds a field for the edge to collect: required text, to be named. */
export function addField(draft: Draft, id: string, index: number): Draft {
  return updateEdge(draft, id, index, (edge) => {
    const properties = edge.properties ?? {}
    let name = 'new_field'
    for (let n = 2; name in properties; n++) name = `new_field_${n}`
    return {
      ...edge,
      properties: { ...properties, [name]: { type: 'string' } },
      required: [...(edge.required ?? []), name],
    }
  })
}

/**
 * What a field is, as the editor offers it: text, number, boolean or choice.
 * The agent JSON has no "choice": it is text with an `enum`, the list of the
 * only values allowed, so that is what makes a field a choice here, with or
 * without options yet. A type the editor does not offer is its own kind and
 * stays as it was loaded.
 */
export function fieldKind(property: EdgeProperty): string {
  // A property with no type takes any value; as a field to collect it is text.
  const type = property.type ?? 'string'
  if (type !== 'string') return type
  return property.enum ? 'choice' : 'text'
}

// The property as a field of `kind`: the reverse of `fieldKind`. Only a choice
// has options, so any other kind drops them.
function asKind(property: EdgeProperty, kind: string): EdgeProperty {
  const { enum: options, ...rest } = property
  if (kind === 'choice') return { ...rest, type: 'string', enum: options ?? [] }
  return { ...rest, type: kind === 'text' ? 'string' : kind }
}

export type FieldChange = {
  name?: string
  description?: string
  kind?: string // see fieldKind
  required?: boolean
  options?: string[] // of a choice: the only values allowed
}

/**
 * Changes a field an edge collects. A new name keeps the field's place and its
 * "required"; it is refused if empty or already a field of the edge. Options
 * are only kept by a choice.
 */
export function updateField(
  draft: Draft,
  id: string,
  index: number,
  field: string,
  change: FieldChange,
): Draft {
  return updateEdge(draft, id, index, (edge) => {
    const current = edge.properties?.[field]
    if (!current) return edge
    const name = change.name ?? field
    if (name === '' || fieldTaken(edge, field, name)) return edge

    let property: EdgeProperty = { ...current }
    if (change.description !== undefined) {
      if (change.description) property.description = change.description
      else delete property.description
    }
    if (change.kind !== undefined && change.kind !== fieldKind(property)) {
      property = asKind(property, change.kind)
    }
    if (change.options !== undefined && fieldKind(property) === 'choice') {
      property.enum = change.options
    }

    const required = (edge.required ?? []).filter((other) => other !== field)
    if (change.required ?? edge.required?.includes(field)) required.push(name)
    return {
      ...edge,
      // Rebuilt in order, so a renamed field stays where it was.
      properties: Object.fromEntries(
        Object.entries(edge.properties!).map(([key, value]) =>
          key === field ? [name, property] : [key, value],
        ),
      ),
      required,
    }
  })
}

export function removeField(draft: Draft, id: string, index: number, field: string): Draft {
  return updateEdge(draft, id, index, (edge) => {
    if (!edge.properties || !(field in edge.properties)) return edge
    const { [field]: _removed, ...properties } = edge.properties
    return {
      ...edge,
      properties,
      required: (edge.required ?? []).filter((other) => other !== field),
    }
  })
}

/**
 * Makes the node the one a call starts at. Nothing leads into the start node,
 * so the edges that went to it are disconnected.
 */
export function setStart(draft: Draft, id: string): Draft {
  const name = nodeOf(draft, id)?.name
  if (name === undefined || name === draft.config.initial_node) return draft
  return {
    ...draft,
    config: {
      ...draft.config,
      initial_node: name,
      nodes: retarget(draft.config.nodes, name, NOWHERE),
    },
  }
}

/** Makes the node end the call, or not. A node that ends the call has no edges. */
export function setEnd(draft: Draft, id: string, end: boolean): Draft {
  return updateNode(draft, id, (node) => {
    if (Boolean(node.end) === end) return node
    if (!end) {
      const { end: _removed, ...rest } = node
      return rest
    }
    return node.edges?.length ? { ...node, end, edges: [] } : { ...node, end }
  })
}

/**
 * Deletes a node. The edges that went to it are disconnected, not removed:
 * each is a condition someone wrote, now waiting for a target. If it was the
 * start node, the first node left becomes the start.
 */
export function deleteNode(draft: Draft, id: string): Draft {
  const index = draft.ids.indexOf(id)
  const node = draft.config.nodes[index]
  if (!node) return draft
  const { [id]: _removed, ...positions } = draft.positions
  const rest: Draft = {
    config: {
      ...draft.config,
      nodes: retarget(draft.config.nodes.toSpliced(index, 1), node.name, NOWHERE),
    },
    ids: draft.ids.toSpliced(index, 1),
    positions,
  }
  if (draft.config.initial_node !== node.name) return rest
  const next = rest.ids[0]
  return next === undefined
    ? { ...rest, config: { ...rest.config, initial_node: NOWHERE } }
    : setStart(rest, next)
}

/** Adds a way out of the node: an edge with nothing written and no target yet. */
export function addEdge(draft: Draft, id: string): Draft {
  return updateNode(draft, id, (node) => {
    // A node that ends the call has no way out.
    if (node.end) return node
    const edges = node.edges ?? []
    const name = functionName(NOWHERE, edges.map((edge) => edge.function))
    return { ...node, edges: [...edges, { function: name, description: '', target: NOWHERE }] }
  })
}

/** Whether removing the edge loses nothing someone wrote: no condition and no fields. */
export function edgeIsEmpty(edge: Edge): boolean {
  return edge.description.trim() === '' && Object.keys(edge.properties ?? {}).length === 0
}

export function removeEdge(draft: Draft, id: string, index: number): Draft {
  return updateNode(draft, id, (node) =>
    node.edges?.[index] ? { ...node, edges: node.edges.toSpliced(index, 1) } : node,
  )
}

/**
 * Points an edge at the node `target`, or at nothing (null). Refused if the
 * target is the start node, which nothing leads into, or the edge's own node.
 */
export function connect(draft: Draft, id: string, index: number, target: string | null): Draft {
  const to = target === null ? NOWHERE : nodeOf(draft, target)?.name
  if (to === undefined || target === id) return draft
  if (to !== NOWHERE && to === draft.config.initial_node) return draft
  return updateNode(draft, id, (node) => {
    const edge = node.edges?.[index]
    if (!edge || edge.target === to) return node
    const others = node.edges!.filter((_, at) => at !== index).map((other) => other.function)
    return {
      ...node,
      edges: node.edges!.with(index, { ...edge, target: to, function: functionName(to, others) }),
    }
  })
}

/**
 * Adds an empty node called step_N, with the card at `position`. With `from`,
 * that edge is connected to it in the same edit, so one undo takes back both.
 */
export function addNode(
  draft: Draft,
  id: string,
  position: Point,
  from?: { id: string; index: number },
): Draft {
  if (draft.ids.includes(id)) return draft
  const names = new Set(draft.config.nodes.map((node) => node.name))
  let number = draft.config.nodes.length + 1
  while (names.has(`step_${number}`)) number++
  const name = `step_${number}`
  const added: Draft = {
    config: {
      ...draft.config,
      nodes: [...draft.config.nodes, { name }],
      // The first node of an agent is where its calls start.
      initial_node: draft.config.nodes.length === 0 ? name : draft.config.initial_node,
    },
    ids: [...draft.ids, id],
    positions: { ...draft.positions, [id]: position },
  }
  return from ? connect(added, from.id, from.index, id) : added
}

/** Puts a node's card at `position`. */
export function moveNode(draft: Draft, id: string, position: Point): Draft {
  if (!draft.ids.includes(id)) return draft
  const current = draft.positions[id]
  if (current?.x === position.x && current.y === position.y) return draft
  return { ...draft, positions: { ...draft.positions, [id]: position } }
}

/** Puts every card where `positions` says, by node id. */
export function setPositions(draft: Draft, positions: Record<string, Point>): Draft {
  return { ...draft, positions }
}
