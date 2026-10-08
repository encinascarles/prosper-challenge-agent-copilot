import { describe, expect, it } from 'vitest'

import type { AgentConfig, Edge } from '@/agents/types'

import {
  addField,
  deleteNode,
  moveNode,
  nameTaken,
  openDraft,
  removeField,
  renameNode,
  setEdgeDescription,
  setEnd,
  setInstructions,
  setStart,
  updateField,
  type Draft,
} from './draft'

const edge = (name: string, target: string, extra: Partial<Edge> = {}): Edge => ({
  function: name,
  description: `Go to ${target}.`,
  target,
  ...extra,
})

const config: AgentConfig = {
  name: 'Test',
  initial_node: 'greeting',
  nodes: [
    {
      name: 'greeting',
      role_message: 'Be brief.',
      pre_actions: [{ type: 'tts_say', text: 'Hi' }],
      post_actions: [{ type: 'log' }],
      task_messages: [
        { role: 'developer', content: 'Greet.' },
        { role: 'developer', content: 'Never give medical advice.' },
      ],
      edges: [
        edge('choose_intent', 'details', {
          properties: {
            intent: { type: 'string', enum: ['book', 'cancel'], description: 'What they want.' },
            notes: { type: 'string' },
          },
          required: ['intent'],
        }),
        edge('to_details_again', 'details'),
        edge('bye', 'goodbye'),
      ],
    },
    { name: 'details', task_messages: [{ role: 'developer', content: 'Ask.' }], edges: [edge('done', 'goodbye')] },
    { name: 'goodbye', end: true },
  ],
}

// Every test starts from the same draft, with positions, and by id.
function open(): { draft: Draft; greeting: string; details: string; goodbye: string } {
  const opened = openDraft(config)
  const [greeting, details, goodbye] = opened.ids
  const layout = { greeting: { x: 0, y: 0 }, details: { x: 400, y: 0 }, goodbye: { x: 800, y: 0 } }
  return { draft: { ...opened, layout }, greeting, details, goodbye }
}

const node = (draft: Draft, name: string) => draft.config.nodes.find((n) => n.name === name)!
const VALID = /^[a-zA-Z0-9_-]{1,64}$/

describe('openDraft', () => {
  it('gives every node an id of its own', () => {
    const { draft } = open()
    expect(new Set(draft.ids).size).toBe(3)
    expect(openDraft(config).ids).not.toEqual(draft.ids)
  })
})

describe('renameNode', () => {
  it('renames the node and every edge that goes to it', () => {
    const { draft, details } = open()
    const next = renameNode(draft, details, 'collect_details')
    expect(next.config.nodes.map((n) => n.name)).toEqual(['greeting', 'collect_details', 'goodbye'])
    expect(node(next, 'greeting').edges!.map((e) => e.target)).toEqual([
      'collect_details',
      'collect_details',
      'goodbye',
    ])
  })

  it('regenerates the function names of those edges, unique and valid in the node', () => {
    const { draft, details } = open()
    const functions = node(renameNode(draft, details, 'collect_details'), 'greeting').edges!.map(
      (e) => e.function,
    )
    expect(functions).toEqual(['go_to_collect_details', 'go_to_collect_details_2', 'bye'])
    functions.forEach((name) => expect(name).toMatch(VALID))
  })

  it('moves its position to the new name', () => {
    const { draft, details } = open()
    const next = renameNode(draft, details, 'collect_details')
    expect(next.layout).toEqual({
      greeting: { x: 0, y: 0 },
      collect_details: { x: 400, y: 0 },
      goodbye: { x: 800, y: 0 },
    })
  })

  it('keeps the agent starting there when the start node is renamed', () => {
    const { draft, greeting } = open()
    expect(renameNode(draft, greeting, 'welcome').config.initial_node).toBe('welcome')
  })

  it('refuses a name another node has, and an empty one', () => {
    const { draft, details } = open()
    expect(nameTaken(draft, details, 'goodbye')).toBe(true)
    expect(nameTaken(draft, details, 'details')).toBe(false)
    expect(renameNode(draft, details, 'goodbye')).toBe(draft)
    expect(renameNode(draft, details, '')).toBe(draft)
  })

  it('keeps the same id', () => {
    const { draft, details } = open()
    expect(renameNode(draft, details, 'collect_details').ids).toEqual(draft.ids)
  })
})

describe('texts', () => {
  it('sets the instructions in the first task message and keeps the others', () => {
    const { draft, greeting } = open()
    expect(node(setInstructions(draft, greeting, 'Say hello.'), 'greeting').task_messages).toEqual([
      { role: 'developer', content: 'Say hello.' },
      { role: 'developer', content: 'Never give medical advice.' },
    ])
  })

  it('gives a node without task messages its first one', () => {
    const { draft, goodbye } = open()
    expect(node(setInstructions(draft, goodbye, 'Say bye.'), 'goodbye').task_messages).toEqual([
      { role: 'developer', content: 'Say bye.' },
    ])
  })

  it('sets the description of one edge', () => {
    const { draft, greeting } = open()
    const edges = node(setEdgeDescription(draft, greeting, 2, 'If they are done.'), 'greeting').edges!
    expect(edges.map((e) => e.description)).toEqual([
      'Go to details.',
      'Go to details.',
      'If they are done.',
    ])
  })

  it('returns the same draft when nothing changes', () => {
    const { draft, greeting } = open()
    expect(setInstructions(draft, greeting, 'Greet.')).toBe(draft)
    expect(setEdgeDescription(draft, greeting, 0, 'Go to details.')).toBe(draft)
  })
})

describe('fields', () => {
  const first = (draft: Draft) => node(draft, 'greeting').edges![0]

  it('adds a required text field with a name of its own', () => {
    const { draft, greeting } = open()
    const twice = addField(addField(draft, greeting, 0), greeting, 0)
    expect(Object.keys(first(twice).properties!)).toEqual([
      'intent',
      'notes',
      'new_field',
      'new_field_2',
    ])
    expect(first(twice).properties!.new_field).toEqual({ type: 'string' })
    expect(first(twice).required).toEqual(['intent', 'new_field', 'new_field_2'])
  })

  it('renames a field in place, with its "required"', () => {
    const { draft, greeting } = open()
    const next = first(updateField(draft, greeting, 0, 'intent', { name: 'reason' }))
    expect(Object.keys(next.properties!)).toEqual(['reason', 'notes'])
    expect(next.properties!.reason.enum).toEqual(['book', 'cancel'])
    expect(next.required).toEqual(['reason'])
  })

  it('refuses a field name the edge already has, and an empty one', () => {
    const { draft, greeting } = open()
    expect(updateField(draft, greeting, 0, 'intent', { name: 'notes' })).toBe(draft)
    expect(updateField(draft, greeting, 0, 'intent', { name: '' })).toBe(draft)
  })

  it('makes a field an enum when it gets allowed values, and plain again without', () => {
    const { draft, greeting } = open()
    const listed = updateField(draft, greeting, 0, 'notes', { options: ['a', 'b'] })
    expect(first(listed).properties!.notes).toEqual({ type: 'string', enum: ['a', 'b'] })
    const plain = updateField(listed, greeting, 0, 'notes', { options: [] })
    expect(first(plain).properties!.notes).toEqual({ type: 'string' })
  })

  it('drops the allowed values when the field stops being text', () => {
    const { draft, greeting } = open()
    const next = first(updateField(draft, greeting, 0, 'intent', { type: 'number' }))
    expect(next.properties!.intent).toEqual({ type: 'number', description: 'What they want.' })
  })

  it('keeps the allowed values of a field that was loaded without a type', () => {
    const { draft, greeting } = open()
    const untyped: Draft = {
      ...draft,
      config: {
        ...draft.config,
        nodes: draft.config.nodes.with(0, {
          ...draft.config.nodes[0],
          edges: [edge('pick', 'details', { properties: { slot: { enum: ['am', 'pm'] } } })],
        }),
      },
    }
    const next = first(updateField(untyped, greeting, 0, 'slot', { description: 'When.' }))
    expect(next.properties!.slot).toEqual({ enum: ['am', 'pm'], description: 'When.' })
  })

  it('sets the description and whether it is required', () => {
    const { draft, greeting } = open()
    const next = first(
      updateField(draft, greeting, 0, 'notes', { description: 'Anything else.', required: true }),
    )
    expect(next.properties!.notes.description).toBe('Anything else.')
    expect(next.required).toEqual(['intent', 'notes'])
    const optional = first(updateField(draft, greeting, 0, 'intent', { required: false }))
    expect(optional.required).toEqual([])
  })

  it('removes a field and its "required"', () => {
    const { draft, greeting } = open()
    const next = first(removeField(draft, greeting, 0, 'intent'))
    expect(Object.keys(next.properties!)).toEqual(['notes'])
    expect(next.required).toEqual([])
  })
})

describe('setStart', () => {
  it('moves the start and disconnects the edges that went to the new start', () => {
    const { draft, details } = open()
    const next = setStart(draft, details)
    expect(next.config.initial_node).toBe('details')
    const edges = node(next, 'greeting').edges!
    expect(edges.map((e) => e.target)).toEqual(['', '', 'goodbye'])
    expect(edges.map((e) => e.function)).toEqual(['go_to_next', 'go_to_next_2', 'bye'])
  })

  it('changes nothing for the node that already is the start', () => {
    const { draft, greeting } = open()
    expect(setStart(draft, greeting)).toBe(draft)
  })
})

describe('setEnd', () => {
  it('removes the edges of a node that now ends the call', () => {
    const { draft, details } = open()
    expect(node(setEnd(draft, details, true), 'details')).toMatchObject({ end: true, edges: [] })
  })

  it('lets any number of nodes end the call, and stop ending it', () => {
    const { draft, details, goodbye } = open()
    const both = setEnd(draft, details, true)
    expect(both.config.nodes.filter((n) => n.end).map((n) => n.name)).toEqual(['details', 'goodbye'])
    expect('end' in node(setEnd(both, goodbye, false), 'goodbye')).toBe(false)
  })
})

describe('deleteNode', () => {
  it('removes the node, its id and its position', () => {
    const { draft, details, greeting, goodbye } = open()
    const next = deleteNode(draft, details)
    expect(next.config.nodes.map((n) => n.name)).toEqual(['greeting', 'goodbye'])
    expect(next.ids).toEqual([greeting, goodbye])
    expect(Object.keys(next.layout)).toEqual(['greeting', 'goodbye'])
  })

  it('disconnects the edges that went to it, and keeps them', () => {
    const { draft, details } = open()
    const edges = node(deleteNode(draft, details), 'greeting').edges!
    expect(edges.map((e) => e.target)).toEqual(['', '', 'goodbye'])
    expect(edges[0].description).toBe('Go to details.')
    expect(new Set(edges.map((e) => e.function)).size).toBe(3)
  })

  it('starts at the first node left when the start node is deleted', () => {
    const { draft, greeting } = open()
    const next = deleteNode(draft, greeting)
    expect(next.config.initial_node).toBe('details')
  })

  it('leaves an agent with no nodes without a start', () => {
    const { draft, greeting, details, goodbye } = open()
    const empty = [greeting, details, goodbye].reduce(deleteNode, draft)
    expect(empty.config.nodes).toEqual([])
    expect(empty.config.initial_node).toBe('')
  })
})

describe('moveNode', () => {
  it('stores the position under the node name', () => {
    const { draft, details } = open()
    expect(moveNode(draft, details, { x: 5, y: 6 }).layout.details).toEqual({ x: 5, y: 6 })
    expect(moveNode(draft, details, { x: 400, y: 0 })).toBe(draft)
  })
})

describe('what the editor does not edit', () => {
  it('survives every edit of its node', () => {
    const { draft, greeting, details } = open()
    const edits: ((draft: Draft) => Draft)[] = [
      (d) => renameNode(d, greeting, 'welcome'),
      (d) => setInstructions(d, greeting, 'Say hello.'),
      (d) => setEdgeDescription(d, greeting, 0, 'If they say what they want.'),
      (d) => addField(d, greeting, 0),
      (d) => updateField(d, greeting, 0, 'intent', { name: 'reason' }),
      (d) => removeField(d, greeting, 0, 'notes'),
      (d) => setStart(d, details),
      (d) => setEnd(d, greeting, true),
      (d) => setEnd(d, greeting, false),
    ]
    const welcome = node(edits.reduce((d, edit) => edit(d), draft), 'welcome')
    expect(welcome.role_message).toBe('Be brief.')
    expect(welcome.pre_actions).toEqual([{ type: 'tts_say', text: 'Hi' }])
    expect(welcome.post_actions).toEqual([{ type: 'log' }])
    expect(welcome.task_messages![1]).toEqual({ role: 'developer', content: 'Never give medical advice.' })
  })

  it('is never changed in the agent that was loaded', () => {
    const before = JSON.stringify(config)
    const { draft, greeting, details } = open()
    deleteNode(setStart(renameNode(draft, details, 'x'), details), greeting)
    expect(JSON.stringify(config)).toBe(before)
  })
})
