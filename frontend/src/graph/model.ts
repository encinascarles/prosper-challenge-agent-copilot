// The agent as the canvas draws it: cards with an id of their own, and wires.
//
// The agent JSON names nodes and points edges at names. A name is text the user
// can edit, so the canvas cannot use it as an identity: a card would be a new
// card after every keystroke. The draft gives each node an id when the agent
// opens, and everything on screen (cards, dots, wires) refers to that id.
// Nothing here is saved: the agent JSON stays as schema.py defines it.

import type { AgentConfig, Edge, Node } from '@/agents/types'

export type Card = {
  id: string
  node: Node
  start: boolean // the agent's initial node
  edges: Edge[] // the edges the card shows, in order
  connected: boolean[] // per shown edge: its target is a node it can lead to
}

/** A connected edge: from the dot of one card's row to another card. */
export type Wire = {
  id: string
  source: string // card id
  index: number // which of the source node's edges it is
  handle: string // the dot it leaves from
  target: string // card id
}

export type Graph = { cards: Card[]; wires: Wire[] }

/** The id of the dot of a card's edge. By position: an edge has no identity of its own. */
export function handleId(index: number): string {
  return `edge-${index}`
}

/** Which edge a dot belongs to: the reverse of `handleId`. */
export function edgeIndex(handle: string): number {
  return Number(handle.slice('edge-'.length))
}

export function toGraph(config: AgentConfig, ids: string[]): Graph {
  // What an edge can connect to. Not the start node: a call begins there and
  // nothing leads into it, so an edge that names it counts as not connected.
  const idOf = new Map(
    config.nodes.flatMap((node, i) =>
      node.name === config.initial_node ? [] : [[node.name, ids[i]] as const],
    ),
  )
  const cards = config.nodes.map((node, i) => {
    // An end node shows no edges: the call stops there.
    const edges = node.end ? [] : (node.edges ?? [])
    return {
      id: ids[i],
      node,
      start: node.name === config.initial_node,
      edges,
      connected: edges.map((edge) => idOf.has(edge.target)),
    }
  })
  const wires = cards.flatMap((card) =>
    card.edges.flatMap((edge, index) => {
      const target = idOf.get(edge.target)
      const handle = handleId(index)
      return target
        ? [{ id: `${card.id}:${handle}`, source: card.id, index, handle, target }]
        : []
    }),
  )
  return { cards, wires }
}
