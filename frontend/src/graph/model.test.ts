import { describe, expect, it } from 'vitest'

import type { AgentConfig } from '@/agents/types'

import { edgeIndex, handleId, toGraph } from './model'

const edge = (target: string) => ({ function: `go_to_${target}`, description: '', target })

const config: AgentConfig = {
  name: 'Test',
  initial_node: 'greeting',
  nodes: [
    { name: 'greeting', edges: [edge('details'), edge('nowhere')] },
    { name: 'details', edges: [edge('goodbye'), edge('greeting')] },
    { name: 'goodbye', end: true, edges: [edge('details')] },
  ],
}
const ids = ['a', 'b', 'c']

describe('toGraph', () => {
  const graph = toGraph(config, ids)

  it('draws one card per node, under its own id', () => {
    expect(graph.cards.map((card) => [card.id, card.node.name])).toEqual([
      ['a', 'greeting'],
      ['b', 'details'],
      ['c', 'goodbye'],
    ])
    expect(graph.cards.map((card) => card.start)).toEqual([true, false, false])
  })

  it('wires an edge to the card of the node it names', () => {
    expect(graph.wires).toContainEqual({
      id: `a:${handleId(0)}`,
      source: 'a',
      index: 0,
      handle: handleId(0),
      target: 'b',
    })
  })

  it('leaves an edge to a name that is not a node unconnected', () => {
    expect(graph.cards[0].connected).toEqual([true, false])
  })

  it('lets nothing lead into the start node', () => {
    expect(graph.cards[1].connected).toEqual([true, false])
    expect(graph.wires.some((wire) => wire.target === 'a')).toBe(false)
  })

  it('knows which nodes a call can get to', () => {
    expect(graph.cards.map((card) => card.reached)).toEqual([true, true, true])
    // Nothing leads to "details" once the only edge to it is gone.
    const cut = toGraph(
      { ...config, nodes: [{ name: 'greeting', edges: [edge('goodbye')] }, ...config.nodes.slice(1)] },
      ids,
    )
    expect(cut.cards.map((card) => card.reached)).toEqual([true, false, true])
  })

  it('shows no edges on an end node', () => {
    expect(graph.cards[2].edges).toEqual([])
    expect(graph.wires.some((wire) => wire.source === 'c')).toBe(false)
  })
})

describe('edgeIndex', () => {
  it('reads back the edge a dot belongs to', () => {
    expect(edgeIndex(handleId(7))).toBe(7)
  })
})
