import { describe, expect, it } from 'vitest'

import type { AgentConfig, Node } from '@/agents/types'

import { checkFlow } from './checks'
import { addNode, connect, openDraft, setEnd, setStart } from './draft'

const to = (...targets: string[]) =>
  targets.map((target) => ({ function: `go_to_${target}`, description: '', target }))

const agent = (...nodes: Node[]): AgentConfig => ({ name: 'Test', initial_node: nodes[0].name, nodes })
const check = (config: AgentConfig) => {
  const draft = openDraft(config)
  return checkFlow(draft).map((warning) => ({
    ...warning,
    node: config.nodes[draft.ids.indexOf(warning.node)].name,
  }))
}
const messages = (config: AgentConfig) => check(config).map((warning) => warning.message)

describe('checkFlow', () => {
  it('has nothing to say about a flow that goes from the start to an end', () => {
    expect(
      check(
        agent(
          { name: 'greeting', edges: to('offer_times') },
          { name: 'offer_times', edges: to('confirm') },
          { name: 'confirm', end: true },
        ),
      ),
    ).toEqual([])
  })

  it('warns where a call would get stuck: a node with no way out that does not end it', () => {
    expect(
      check(
        agent(
          { name: 'greeting', edges: to('offer_times', 'confirm') },
          { name: 'offer_times' },
          { name: 'confirm', end: true },
        ),
      ),
    ).toEqual([
      { node: 'offer_times', kind: 'dead-end', message: 'The call would get stuck at Offer times.' },
    ])
  })

  it('warns about a node a call can never get to, also one only reached from another such node', () => {
    expect(
      messages(
        agent(
          { name: 'greeting', edges: to('confirm') },
          { name: 'confirm', end: true },
          { name: 'call_back', edges: to('take_number') },
          { name: 'take_number', edges: to('confirm') },
        ),
      ),
    ).toEqual(['A call can never get to Call back.', 'A call can never get to Take number.'])
  })

  it('says only that about it: whether it is a dead end does not matter yet', () => {
    expect(
      check(agent({ name: 'greeting', edges: to('bye') }, { name: 'bye', end: true }, { name: 'lost' })),
    ).toEqual([{ node: 'lost', kind: 'unreachable', message: 'A call can never get to Lost.' }])
  })

  it('warns on the start node when no path from it ends the call', () => {
    expect(
      check(
        agent(
          { name: 'greeting', edges: to('offer_times') },
          { name: 'offer_times', edges: to('greeting', 'ask_again') },
          { name: 'ask_again', edges: to('offer_times') },
          // An end nobody reaches does not count.
          { name: 'bye', end: true },
        ),
      ),
    ).toEqual([
      { node: 'greeting', kind: 'no-end', message: 'No path from Greeting ends the call.' },
      { node: 'bye', kind: 'unreachable', message: 'A call can never get to Bye.' },
    ])
  })

  it('is fine with a loop, as long as some path ends', () => {
    expect(
      check(
        agent(
          { name: 'greeting', edges: to('offer_times') },
          { name: 'offer_times', edges: to('ask_again', 'confirm') },
          { name: 'ask_again', edges: to('offer_times') },
          { name: 'confirm', end: true },
        ),
      ),
    ).toEqual([])
  })

  it('can say both about one node: it is where the call starts, and where it gets stuck', () => {
    expect(messages(agent({ name: 'greeting' }))).toEqual([
      'The call would get stuck at Greeting.',
      'No path from Greeting ends the call.',
    ])
  })

  it('follows the wires the canvas draws, not every name in the JSON', () => {
    const config = agent(
      // An edge into the start node, and one to a name that is no node, lead nowhere.
      { name: 'greeting', edges: to('middle') },
      { name: 'middle', edges: to('greeting', 'nowhere') },
      // An end node's edges are not there.
      { name: 'bye', end: true, edges: to('hidden') },
      { name: 'hidden', end: true },
    )
    expect(messages(config)).toEqual([
      'No path from Greeting ends the call.',
      'A call can never get to Bye.',
      'A call can never get to Hidden.',
    ])
  })

  it('leaves a node whose only edges go nowhere to the errors: it is unfinished, not a dead end', () => {
    expect(
      messages(agent({ name: 'greeting', edges: to('', 'bye') }, { name: 'bye', end: true })),
    ).toEqual([])
  })

  it('clears as the flow is finished, edit by edit', () => {
    let draft = openDraft(agent({ name: 'greeting', edges: to('offer_times') }, { name: 'offer_times' }))
    const [greeting, offer] = draft.ids
    const said = () => checkFlow(draft).map((warning) => warning.message)
    expect(said()).toEqual([
      'No path from Greeting ends the call.',
      'The call would get stuck at Offer times.',
    ])
    draft = setEnd(draft, offer, true)
    expect(said()).toEqual([])
    draft = addNode(setEnd(draft, offer, false), 'new', { x: 0, y: 0 })
    expect(said()).toContain('A call can never get to Step 3.')
    draft = connect(
      { ...draft, config: { ...draft.config, nodes: draft.config.nodes.with(1, { ...draft.config.nodes[1], edges: to('') }) } },
      offer,
      0,
      'new',
    )
    draft = setEnd(draft, 'new', true)
    expect(said()).toEqual([])
    // Moving the start makes the old one unreachable.
    expect(checkFlow(setStart(draft, offer)).map((warning) => warning.node)).toEqual([greeting])
  })

  it('has nothing to check in an agent with no start', () => {
    expect(checkFlow(openDraft({ name: 'Empty', initial_node: '', nodes: [] }))).toEqual([])
  })
})
