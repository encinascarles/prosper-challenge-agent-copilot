import { describe, expect, it } from 'vitest'

import { checkFlow } from '@/draft/checks'
import { openDraft } from '@/draft/draft'
import { functionName } from '@/draft/names'
import { looseEdges, toGraph } from '@/graph/model'

import { NEW_AGENT } from './template'

describe('NEW_AGENT', () => {
  const draft = openDraft(NEW_AGENT)

  it('is a start node and an end node, connected', () => {
    expect(NEW_AGENT.nodes.map((node) => node.name)).toEqual(['greeting', 'goodbye'])
    expect(NEW_AGENT.initial_node).toBe('greeting')
    expect(NEW_AGENT.nodes[1].end).toBe(true)
    expect(looseEdges(toGraph(draft.config, draft.ids))).toEqual([])
  })

  it('is a flow a call gets through: nothing to warn about', () => {
    expect(checkFlow(draft)).toEqual([])
  })

  it('names its edge the way the editor would', () => {
    expect(NEW_AGENT.nodes[0].edges![0].function).toBe(functionName('goodbye', []))
  })
})
