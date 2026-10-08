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
  // Where each card is, by node name: the shape it will be saved in.
  layout: Record<string, Point>
}

/** A target that is no node: the edge is not connected. */
export const NOWHERE = ''

let lastId = 0

/** The draft of a loaded agent. */
export function openDraft(config: AgentConfig): Draft {
  return { config, ids: config.nodes.map(() => `node-${++lastId}`), layout: {} }
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
 * Renames a node. Its edges, its position and the start of the agent follow
 * the name. Refused (nothing changes) if the name is empty or another node has it.
 */
export function renameNode(draft: Draft, id: string, name: string): Draft {
  const old = nodeOf(draft, id)?.name
  if (old === undefined || name === old || name === NOWHERE || nameTaken(draft, id, name)) {
    return draft
  }
  const nodes = retarget(draft.config.nodes, old, name).map((node, i) =>
    draft.ids[i] === id ? { ...node, name } : node,
  )
  const { [old]: position, ...layout } = draft.layout
  return {
    ...draft,
    config: {
      ...draft.config,
      nodes,
      initial_node: draft.config.initial_node === old ? name : draft.config.initial_node,
    },
    layout: position ? { ...layout, [name]: position } : layout,
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

export type FieldChange = {
  name?: string
  description?: string
  type?: string
  required?: boolean
  options?: string[] // the only values allowed; empty for any
}

/**
 * Changes a field an edge collects. A new name keeps the field's place and its
 * "required"; it is refused if empty or already a field of the edge. Allowed
 * values make it an enum, which only text can be.
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

    const property: EdgeProperty = { ...current }
    if (change.description !== undefined) {
      if (change.description) property.description = change.description
      else delete property.description
    }
    if (change.type !== undefined) property.type = change.type
    if (change.options !== undefined) property.enum = change.options
    // Only text has a list of values. A property with no type is taken as text.
    if ((property.type ?? 'string') !== 'string' || property.enum?.length === 0) {
      delete property.enum
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
  const { [node.name]: _removed, ...layout } = draft.layout
  const rest: Draft = {
    config: {
      ...draft.config,
      nodes: retarget(draft.config.nodes.toSpliced(index, 1), node.name, NOWHERE),
    },
    ids: draft.ids.toSpliced(index, 1),
    layout,
  }
  if (draft.config.initial_node !== node.name) return rest
  const next = rest.ids[0]
  return next === undefined
    ? { ...rest, config: { ...rest.config, initial_node: NOWHERE } }
    : setStart(rest, next)
}

/** Puts a node's card at `position`. */
export function moveNode(draft: Draft, id: string, position: Point): Draft {
  const name = nodeOf(draft, id)?.name
  if (name === undefined) return draft
  const current = draft.layout[name]
  if (current?.x === position.x && current.y === position.y) return draft
  return { ...draft, layout: { ...draft.layout, [name]: position } }
}

/** Puts every card where `layout` says, by node name. */
export function setLayout(draft: Draft, layout: Record<string, Point>): Draft {
  return { ...draft, layout }
}
