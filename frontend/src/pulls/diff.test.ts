import { describe, expect, it } from 'vitest'

import type { AgentConfig, AgentCopy } from '@/agents/types'
import {
  addField,
  addNode,
  deleteNode,
  openDraft,
  renameNode,
  setAgent,
  setEdgeDescription,
  setInstructions,
  updateField,
  type Draft,
} from '@/draft/draft'

import { diffAgents, editedWhat, matchSteps, NOTHING, rebase, summarize, updateSummary, wordDiff } from './diff'

// A small clinic agent: greeting → collect_details → confirm (ends the call).
const CLINIC: AgentConfig = {
  name: 'Anna',
  persona: 'You are a warm scheduling assistant.',
  initial_node: 'greeting',
  nodes: [
    {
      name: 'greeting',
      task_messages: [{ role: 'developer', content: 'Greet the caller and ask what they need.' }],
      edges: [{ function: 'go_to_collect_details', description: 'Once they say what they need.', target: 'collect_details' }],
    },
    {
      name: 'collect_details',
      task_messages: [{ role: 'developer', content: 'Ask for the full name and the reason for the visit.' }],
      edges: [
        {
          function: 'go_to_confirm',
          description: 'Once both are known.',
          target: 'confirm',
          properties: { full_name: { type: 'string' } },
          required: ['full_name'],
        },
      ],
    },
    {
      name: 'confirm',
      task_messages: [{ role: 'developer', content: 'Read the booking back and say goodbye.' }],
      end: true,
    },
  ],
}

const LAYOUT = { greeting: { x: 0, y: 0 }, collect_details: { x: 300, y: 0 }, confirm: { x: 600, y: 0 } }

// Edits made the way the editor makes them, on a draft of `config`.
function edit(config: AgentConfig, ...edits: ((draft: Draft, id: (name: string) => string) => Draft)[]): AgentConfig {
  let draft = openDraft(config, LAYOUT)
  for (const change of edits) {
    const current = draft
    draft = change(current, (name) => current.ids[current.config.nodes.findIndex((node) => node.name === name)])
  }
  return draft.config
}
// A copy with its cards where they were: a renamed step keeps its place.
const copy = (config: AgentConfig): AgentCopy => ({
  config,
  layout: Object.fromEntries(
    config.nodes.flatMap((n, i) => {
      const at = LAYOUT[n.name as keyof typeof LAYOUT] ?? LAYOUT[CLINIC.nodes[i]?.name as keyof typeof LAYOUT]
      return at ? [[n.name, at]] : []
    }),
  ),
})
const node = (config: AgentConfig, name: string) => config.nodes.find((n) => n.name === name)
const instructions = (config: AgentConfig, name: string) => node(config, name)?.task_messages?.[0].content

// What the backend checks before it takes an agent: every target and the start exist.
function expectValid(config: AgentConfig) {
  const names = new Set(config.nodes.map((n) => n.name))
  expect(names.size).toBe(config.nodes.length)
  expect(names.has(config.initial_node)).toBe(true)
  for (const n of config.nodes) {
    const functions = (n.edges ?? []).map((edge) => edge.function)
    expect(new Set(functions).size).toBe(functions.length)
    for (const edge of n.edges ?? []) expect(names.has(edge.target)).toBe(true)
  }
}

describe('wordDiff', () => {
  it('keeps what stayed and marks the words that changed', () => {
    expect(wordDiff('Read the booking back.', 'Read the date back.')).toEqual([
      { op: 'same', text: 'Read the ' },
      { op: 'remove', text: 'booking' },
      { op: 'add', text: 'date' },
      { op: 'same', text: ' back.' },
    ])
  })
})

describe('diffAgents', () => {
  it('sees nothing between a copy and itself', () => {
    expect(diffAgents(CLINIC, structuredClone(CLINIC))).toEqual([])
  })

  it('shows an instructions edit as one step, word by word', () => {
    const next = edit(CLINIC, (d, id) => setInstructions(d, id('confirm'), 'Read the date back and say goodbye.'))
    const changes = diffAgents(CLINIC, next)
    expect(changes).toHaveLength(1)
    expect(changes[0]).toMatchObject({ label: 'Confirm', kind: 'edited' })
    expect(changes[0].lines).toEqual([
      {
        op: 'words',
        label: 'Instructions',
        parts: [
          { op: 'same', text: 'Read the ' },
          { op: 'remove', text: 'booking' },
          { op: 'add', text: 'date' },
          { op: 'same', text: ' back and say goodbye.' },
        ],
      },
    ])
    expect(editedWhat(changes)).toBe('Confirm')
  })

  it('lists an added step and a field an edge now collects', () => {
    const next = edit(
      CLINIC,
      (d, id) => addNode(d, 'new', { x: 0, y: 300 }, { id: id('confirm'), index: 0 }),
      (d, id) => addField(d, id('collect_details'), 0),
      (d, id) => updateField(d, id('collect_details'), 0, 'new_field', { name: 'date_of_birth', required: false }),
    )
    const changes = diffAgents(CLINIC, next)
    expect(changes.map((c) => [c.label, c.kind])).toEqual([
      ['Collect details', 'edited'],
      ['Step 4', 'added'],
    ])
    expect(changes[0].lines).toEqual([{ op: 'add', label: 'Collects', text: 'Date of birth' }])
    expect(summarize(changes)).toBe('Edited Collect details · added Step 4')
  })

  it('follows a renamed step instead of listing it removed and added', () => {
    const next = edit(CLINIC, (d, id) => renameNode(d, id('confirm'), 'wrap_up'))
    expect(matchSteps(CLINIC, next)).toEqual([0, 1, 2])
    const changes = diffAgents(CLINIC, next)
    // The edge into it follows the name: it did not move.
    expect(changes).toEqual([
      { key: 'wrap_up:edited', label: 'Wrap up', kind: 'edited', lines: [{ op: 'note', label: 'Renamed', text: 'from Confirm' }] },
    ])
  })

  it('lists a removed step, and the way that led to it', () => {
    const next = edit(
      CLINIC,
      (d, id) => deleteNode(d, id('confirm')),
      (d, id) => addNode(d, 'bye', { x: 0, y: 0 }, { id: id('collect_details'), index: 0 }),
    )
    const changes = diffAgents(CLINIC, next)
    expect(changes.map((c) => [c.label, c.kind])).toEqual([
      ['Collect details', 'edited'],
      ['Step 3', 'added'],
      ['Confirm', 'removed'],
    ])
    expect(changes[0].lines).toEqual([{ op: 'note', label: 'Moves on', text: 'to Step 3 instead of Confirm' }])
  })

  it("says what changed in a field and in the agent's settings", () => {
    const next = edit(
      CLINIC,
      (d, id) => updateField(d, id('collect_details'), 0, 'full_name', { kind: 'choice', options: ['a', 'b'], required: false }),
      (d, id) => setEdgeDescription(d, id('greeting'), 0, 'Once they say what they want.'),
      (d) => setAgent(d, { name: 'Anna 2' }),
    )
    const changes = diffAgents(CLINIC, next)
    expect(changes[0]).toEqual({
      key: 'agent',
      label: 'Agent settings',
      kind: 'agent',
      lines: [
        { op: 'remove', label: 'Name', text: 'Anna' },
        { op: 'add', label: 'Name', text: 'Anna 2' },
      ],
    })
    expect(changes[1].lines[0]).toMatchObject({ op: 'words', label: 'When' })
    expect(changes[2].lines).toEqual([{ op: 'note', label: 'Collects', text: 'Full name: now optional, now a choice' }])
  })

  it('shows everything as added for a pull request based on nothing', () => {
    const changes = diffAgents(NOTHING, CLINIC)
    expect(changes.map((c) => c.kind)).toEqual(['added', 'added', 'added'])
    expect(changes[0].lines[0]).toEqual({ op: 'add', label: 'Start', text: 'The call starts here' })
  })
})

describe('rebase', () => {
  it("keeps the pull request's edit and what went live since, in different steps", () => {
    const ours = edit(CLINIC, (d, id) => setInstructions(d, id('confirm'), 'Keep it short.'))
    const theirs = edit(CLINIC, (d, id) => addField(d, id('collect_details'), 0))
    const rebased = rebase(copy(CLINIC), copy(ours), copy(theirs))
    expect(instructions(rebased.config, 'confirm')).toBe('Keep it short.')
    expect(Object.keys(node(rebased.config, 'collect_details')?.edges?.[0].properties ?? {})).toEqual(['full_name', 'new_field'])
    expect(rebased.kept).toEqual([])
    expect(updateSummary(rebased, 2)).toBeNull()
    expectValid(rebased.config)
  })

  it("keeps the pull request's text where both changed the same text, and says so", () => {
    const ours = edit(CLINIC, (d, id) => setInstructions(d, id('confirm'), 'Ours.'))
    const theirs = edit(CLINIC, (d, id) => setInstructions(d, id('confirm'), 'Theirs.'))
    const rebased = rebase(copy(CLINIC), copy(ours), copy(theirs))
    expect(instructions(rebased.config, 'confirm')).toBe('Ours.')
    expect(rebased.kept).toEqual(['Confirm'])
    expect(updateSummary(rebased, 2)).toBe('kept your text in Confirm')
  })

  it('merges both edits of one step: our text, their field', () => {
    const ours = edit(CLINIC, (d, id) => setInstructions(d, id('collect_details'), 'Ask the name first.'))
    const theirs = edit(
      CLINIC,
      (d, id) => addField(d, id('collect_details'), 0),
      (d, id) => updateField(d, id('collect_details'), 0, 'new_field', { name: 'date_of_birth' }),
    )
    const step = node(rebase(copy(CLINIC), copy(ours), copy(theirs)).config, 'collect_details')!
    expect(step.task_messages?.[0].content).toBe('Ask the name first.')
    expect(step.edges?.[0].required).toEqual(['full_name', 'date_of_birth'])
  })

  it('keeps a step the pull request edited and the newer version removed', () => {
    const ours = edit(CLINIC, (d, id) => setInstructions(d, id('confirm'), 'Read it back slowly.'))
    const theirs = edit(
      CLINIC,
      (d, id) => deleteNode(d, id('confirm')),
      (d, id) => addNode(d, 'bye', { x: 0, y: 0 }, { id: id('collect_details'), index: 0 }),
    )
    const rebased = rebase(copy(CLINIC), copy(ours), copy(theirs))
    expect(instructions(rebased.config, 'confirm')).toBe('Read it back slowly.')
    expect(rebased.restored).toEqual(['Confirm'])
    expect(updateSummary(rebased, 2)).toBe('kept Confirm, which v2 removed')
    // Theirs moved the edge on to the new step: that stays.
    expect(node(rebased.config, 'collect_details')?.edges?.[0].target).toBe('step_3')
    expectValid(rebased.config)
  })

  it('removes a step the pull request removed, even if the newer version changed it', () => {
    const ours = edit(
      CLINIC,
      (d, id) => deleteNode(d, id('confirm')),
      (d, id) => addNode(d, 'bye', { x: 0, y: 0 }, { id: id('collect_details'), index: 0 }),
    )
    const theirs = edit(CLINIC, (d, id) => setInstructions(d, id('confirm'), 'Theirs.'))
    const rebased = rebase(copy(CLINIC), copy(ours), copy(theirs))
    expect(node(rebased.config, 'confirm')).toBeUndefined()
    expect(rebased.dropped).toEqual(['Confirm'])
    expectValid(rebased.config)
  })

  it('follows a step the pull request renamed, with what the newer version changed in it', () => {
    const ours = edit(CLINIC, (d, id) => renameNode(d, id('confirm'), 'wrap_up'))
    const theirs = edit(CLINIC, (d, id) => setInstructions(d, id('confirm'), 'Read the booking back and say goodbye warmly.'))
    const rebased = rebase(copy(CLINIC), copy(ours), copy(theirs))
    expect(rebased.config.nodes.map((n) => n.name)).toEqual(['greeting', 'collect_details', 'wrap_up'])
    expect(instructions(rebased.config, 'wrap_up')).toBe('Read the booking back and say goodbye warmly.')
    const edge = node(rebased.config, 'collect_details')?.edges?.[0]
    expect([edge?.target, edge?.function]).toEqual(['wrap_up', 'go_to_wrap_up'])
    expect(rebased.layout.wrap_up).toEqual(LAYOUT.confirm)
    expectValid(rebased.config)
  })

  it('follows a step the newer version renamed', () => {
    const ours = edit(CLINIC, (d, id) => setInstructions(d, id('confirm'), 'Ours.'))
    const theirs = edit(CLINIC, (d, id) => renameNode(d, id('confirm'), 'wrap_up'))
    const rebased = rebase(copy(CLINIC), copy(ours), copy(theirs))
    expect(rebased.config.nodes.map((n) => n.name)).toEqual(['greeting', 'collect_details', 'wrap_up'])
    expect(instructions(rebased.config, 'wrap_up')).toBe('Ours.')
    expect(rebased.kept).toEqual([])
    expectValid(rebased.config)
  })

  it("keeps the pull request's agent settings and steps both added", () => {
    const ours = edit(
      CLINIC,
      (d) => setAgent(d, { name: 'Ours' }),
      (d, id) => addNode(d, 'a', { x: 0, y: 0 }, { id: id('confirm'), index: 0 }),
    )
    const theirs = edit(
      CLINIC,
      (d) => setAgent(d, { name: 'Theirs', persona: 'New persona.' }),
      (d) => addNode(d, 'b', { x: 0, y: 0 }),
    )
    const rebased = rebase(copy(CLINIC), copy(ours), copy(theirs))
    expect([rebased.config.name, rebased.config.persona]).toEqual(['Ours', 'New persona.'])
    expect(rebased.kept).toEqual(["the agent's settings"])
    // Both added a step_4: theirs keeps the name, ours gets another.
    expect(rebased.config.nodes.map((n) => n.name)).toEqual(['greeting', 'collect_details', 'confirm', 'step_4', 'step_4_2'])
  })
})
