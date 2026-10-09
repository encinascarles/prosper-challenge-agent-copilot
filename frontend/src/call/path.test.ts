import { describe, expect, it } from 'vitest'

import {
  callReducer,
  clock,
  collectedAt,
  currentNode,
  edgeTaken,
  elapsed,
  isNodeMessage,
  newCall,
  nodeView,
  type Call,
  type CallEvent,
  type NodeMessage,
} from './path'

const T0 = 1_000_000
const at = (seconds: number) => T0 + seconds * 1000
const node = (
  name: string,
  from: string | null = null,
  edge: string | null = null,
  collected: Record<string, unknown> = {},
): NodeMessage => ({ type: 'node', node: name, from, edge, collected })
const run = (...events: CallEvent[]): Call => events.reduce(callReducer, newCall)

// A booking, as the bot reports it: greeting -> collect_details -> offer_times.
const booking: CallEvent[] = [
  { type: 'ready', now: at(0) },
  { type: 'node', message: node('greeting'), now: at(0) },
  { type: 'node', message: node('collect_details', 'greeting', 'choose_intent', { intent: 'book' }), now: at(9) },
  {
    type: 'node',
    message: node('offer_times', 'collect_details', 'record_details', { full_name: 'Anna Puig', reason: 'Knee' }),
    now: at(31),
  },
]

describe('the path of a call', () => {
  it('starts connecting, with no path', () => {
    expect(newCall).toMatchObject({ status: 'connecting', steps: [], lines: [] })
    expect(currentNode(newCall)).toBeNull()
  })

  it('is the nodes the bot reported, in order, with when and how the call got there', () => {
    expect(run(...booking).steps).toEqual([
      { node: 'greeting', at: 0, from: null, edge: null, collected: {} },
      { node: 'collect_details', at: 9, from: 'greeting', edge: 'choose_intent', collected: { intent: 'book' } },
      {
        node: 'offer_times',
        at: 31,
        from: 'collect_details',
        edge: 'record_details',
        collected: { full_name: 'Anna Puig', reason: 'Knee' },
      },
    ])
  })

  it('is live from the first node, even if it arrives before the bot says it is ready', () => {
    const call = run({ type: 'node', message: node('greeting'), now: at(0) })
    expect(call).toMatchObject({ status: 'live', startedAt: at(0) })
    // The late "ready" does not restart the clock.
    expect(callReducer(call, { type: 'ready', now: at(2) }).startedAt).toBe(at(0))
  })

  it('shows what was collected as text, whatever type the model passed', () => {
    const call = run(
      { type: 'node', message: node('a'), now: at(0) },
      { type: 'node', message: node('b', 'a', 'go', { age: 41, insured: true, name: 'Anna' }), now: at(1) },
    )
    expect(call.steps[1].collected).toEqual({ age: '41', insured: 'true', name: 'Anna' })
  })

  it('numbers each node by its step, marks the current one and the edges that fired', () => {
    const call = run(...booking)
    expect(nodeView(call, 'greeting')).toEqual({
      step: 1,
      current: false,
      fired: { choose_intent: { intent: 'book' } },
    })
    expect(nodeView(call, 'offer_times')).toEqual({ step: 3, current: true, fired: {} })
    expect(nodeView(call, 'confirm')).toEqual({ step: null, current: false, fired: {} })
    expect(currentNode(call)).toBe('offer_times')
  })

  it('tells the wire of the last move from the ones taken before', () => {
    const call = run(...booking)
    expect(edgeTaken(call, 'collect_details', 'record_details')).toBe('latest')
    expect(edgeTaken(call, 'greeting', 'choose_intent')).toBe('taken')
    expect(edgeTaken(call, 'offer_times', 'select_time')).toBeNull()
    // The same function name on another node is another edge.
    expect(edgeTaken(call, 'offer_times', 'choose_intent')).toBeNull()
  })

  it('lists with each step what the call collected there', () => {
    const call = run(...booking)
    expect(collectedAt(call, 0)).toEqual({ intent: 'book' })
    expect(collectedAt(call, 1)).toEqual({ full_name: 'Anna Puig', reason: 'Knee' })
    expect(collectedAt(call, 2)).toEqual({})
  })

  it('gives a node the call came back to the number of its last visit', () => {
    const call = run(
      { type: 'node', message: node('a'), now: at(0) },
      { type: 'node', message: node('b', 'a', 'go_to_b'), now: at(1) },
      { type: 'node', message: node('a', 'b', 'go_to_a'), now: at(2) },
    )
    expect(nodeView(call, 'a')).toMatchObject({ step: 3, current: true })
    expect(nodeView(call, 'b')).toMatchObject({ step: 2, current: false })
    expect(edgeTaken(call, 'a', 'go_to_b')).toBe('taken')
    expect(edgeTaken(call, 'b', 'go_to_a')).toBe('latest')
  })

  it('keeps the path when the call ends, with no current node', () => {
    const call = run(...booking, { type: 'ended', now: at(40) })
    expect(call).toMatchObject({ status: 'ended', endedAt: at(40) })
    expect(call.steps).toHaveLength(3)
    expect(currentNode(call)).toBeNull()
    expect(nodeView(call, 'offer_times')).toMatchObject({ step: 3, current: false })
  })

  it('ignores what arrives after the call is over', () => {
    const ended = run(...booking, { type: 'ended', now: at(40) })
    expect(callReducer(ended, { type: 'node', message: node('confirm'), now: at(41) })).toBe(ended)
    expect(callReducer(ended, { type: 'failed', problem: 'Late.', now: at(41) })).toBe(ended)
  })

  it('fails with the sentence it was given, keeping what there was', () => {
    const call = run({ type: 'failed', problem: "No agent with id 'x'.", now: at(0) })
    expect(call).toMatchObject({ status: 'failed', problem: "No agent with id 'x'.", steps: [] })
  })

  it('only reads node messages off the channel', () => {
    expect(isNodeMessage(node('greeting'))).toBe(true)
    expect(isNodeMessage({ type: 'other', node: 'greeting' })).toBe(false)
    expect(isNodeMessage({ type: 'node' })).toBe(false)
    expect(isNodeMessage(null)).toBe(false)
    expect(isNodeMessage('node')).toBe(false)
  })
})

describe('the transcript of a call', () => {
  const say = (text: string): CallEvent => ({ type: 'agent-text', text })
  const hear = (text: string): CallEvent => ({ type: 'caller-text', text })
  const turn: CallEvent = { type: 'agent-turn' }

  it('joins the pieces of what the agent says into one line', () => {
    expect(run(turn, say('Hello,'), say(' how can'), say(' I help?')).lines).toEqual([
      { who: 'agent', text: 'Hello, how can I help?' },
    ])
  })

  it('starts a new line for each turn of the agent', () => {
    expect(run(turn, say('Hello.'), turn, say('Your name?')).lines).toEqual([
      { who: 'agent', text: 'Hello.' },
      { who: 'agent', text: 'Your name?' },
    ])
  })

  it('alternates agent and caller', () => {
    expect(run(turn, say('Hello.'), hear('Book, please.'), turn, say('Sure.')).lines).toEqual([
      { who: 'agent', text: 'Hello.' },
      { who: 'caller', text: 'Book, please.' },
      { who: 'agent', text: 'Sure.' },
    ])
  })

  it('keeps a caller turn transcribed in several sentences as one line', () => {
    expect(run(hear('I would like to book.'), hear(' Please. ')).lines).toEqual([
      { who: 'caller', text: 'I would like to book. Please.' },
    ])
  })

  it('does not add a line for a turn with nothing said', () => {
    // The model called a function and said nothing.
    expect(run(turn, say('Hello.'), turn, turn, say(''), hear('  ')).lines).toEqual([
      { who: 'agent', text: 'Hello.' },
    ])
  })
})

describe('the call clock', () => {
  it('reads as minutes and seconds', () => {
    expect([0, 9, 42, 60, 605].map(clock)).toEqual(['0:00', '0:09', '0:42', '1:00', '10:05'])
  })

  it('counts from when the bot answered and stops when the call ends', () => {
    expect(elapsed(newCall, at(5))).toBe(0)
    const live = run({ type: 'ready', now: at(0) })
    expect(elapsed(live, at(42.9))).toBe(42)
    const ended = callReducer(live, { type: 'ended', now: at(50) })
    expect(elapsed(ended, at(300))).toBe(50)
  })
})
