// Automatic layout of the agent graph, with ELK.
//
// Layered, left to right: a call flows from the start node to the end nodes,
// and that is how the graph reads. Each edge is a port at its real height on
// the right side of its card (the card measures it), and ELK keeps ports where
// they are, so the wires leaving a card's rows do not cross on the way out.
//
// ELK also routes the wires, at right angles and around the cards, and those
// routes are returned with the positions: a curve drawn straight from dot to
// dot would run under whatever card sits in between.
//
// ELK is loaded on first use: it is most of the bundle and the page can show
// its shell before it arrives.

import type { ElkNode } from 'elkjs/lib/elk-api'

import type { Graph } from './model'

export type Point = { x: number; y: number }

/** A card as rendered: its size and where its dots are, from its top-left corner. */
export type Box = {
  width: number
  height: number
  inY?: number // the dot wires arrive at, on the left side; the start card has none
  outY: Record<string, number> // the dot of each shown edge, on the right side, by handle id
}

export type Layout = {
  positions: Record<string, Point> // top-left corner of each card, by card id
  routes: Record<string, Point[]> // the path of each wire, dot to dot, by wire id
}

const OPTIONS = {
  'elk.algorithm': 'layered',
  'elk.direction': 'RIGHT',
  'elk.edgeRouting': 'ORTHOGONAL',
  'elk.spacing.nodeNode': '32',
  'elk.spacing.edgeNode': '20',
  'elk.spacing.edgeEdge': '14',
  'elk.layered.spacing.nodeNodeBetweenLayers': '90',
  'elk.layered.spacing.edgeNodeBetweenLayers': '28',
  'elk.layered.spacing.edgeEdgeBetweenLayers': '14',
  'elk.layered.crossingMinimization.greedySwitch.type': 'TWO_SIDED',
  // Among equally good layouts, keep nodes in the order the agent lists them.
  'elk.layered.considerModelOrder.strategy': 'PREFER_EDGES',
  // Center every column on the same line. The placers that straighten edges
  // put each card level with the row it is reached from, lower than the card
  // before it, so a plain chain walks down the screen like a staircase.
  'elk.layered.nodePlacement.strategy': 'SIMPLE',
}

async function loadElk() {
  const { default: ELK } = await import('elkjs/lib/elk.bundled.js')
  return new ELK()
}
let elk: ReturnType<typeof loadElk> | undefined

/** Where to draw each card and wire of `graph`, given each card's `boxes` by card id. */
export async function layoutGraph(graph: Graph, boxes: Record<string, Box>): Promise<Layout> {
  // Card ids and port ids share one namespace in ELK; a card id has no space.
  const inPort = (card: string) => `${card} in`
  const port = { width: 0, height: 0 }
  const root: ElkNode = {
    id: 'root',
    layoutOptions: OPTIONS,
    children: graph.cards.map((card) => {
      const box = boxes[card.id]
      return {
        id: card.id,
        width: box.width,
        height: box.height,
        layoutOptions: { 'elk.portConstraints': 'FIXED_POS' },
        ports: [
          ...(box.inY === undefined ? [] : [{ ...port, id: inPort(card.id), x: 0, y: box.inY }]),
          ...Object.entries(box.outY).map(([handle, y]) => ({
            ...port,
            id: `${card.id}:${handle}`,
            x: box.width,
            y,
          })),
        ],
      }
    }),
    // A wire's id is also the id of the port it leaves from.
    edges: graph.wires.map((wire) => ({
      id: wire.id,
      sources: [wire.id],
      targets: [inPort(wire.target)],
    })),
  }
  elk ??= loadElk()
  const placed = await (await elk).layout(root)
  const positions: Layout['positions'] = {}
  for (const child of placed.children ?? []) positions[child.id] = { x: child.x ?? 0, y: child.y ?? 0 }
  const routes: Layout['routes'] = {}
  for (const edge of placed.edges ?? []) {
    const section = edge.sections?.[0]
    if (section) {
      routes[edge.id] = [section.startPoint, ...(section.bendPoints ?? []), section.endPoint]
    }
  }
  return { positions, routes }
}
