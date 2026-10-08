import { describe, expect, it } from 'vitest'

import { openDraft, renameNode, setEnd, setInstructions, type Draft } from './draft'
import { historyReducer, startHistory, type Action, type History } from './history'

const start = () =>
  startHistory(
    openDraft({
      name: 'Test',
      initial_node: 'greeting',
      nodes: [
        { name: 'greeting', edges: [{ function: 'next', description: '', target: 'goodbye' }] },
        { name: 'goodbye', end: true },
      ],
    }),
  )

const run = (history: History, ...actions: Action[]) => actions.reduce(historyReducer, history)
const apply = (edit: (draft: Draft) => Draft, merge?: string): Action => ({ type: 'apply', edit, merge })
const undo: Action = { type: 'undo' }
const redo: Action = { type: 'redo' }
const names = (history: History) => history.present.config.nodes.map((node) => node.name)

describe('historyReducer', () => {
  it('undoes and redoes an edit', () => {
    const history = start()
    const [greeting] = history.present.ids
    const renamed = run(history, apply((d) => renameNode(d, greeting, 'welcome')))
    expect(names(renamed)).toEqual(['welcome', 'goodbye'])
    expect(names(run(renamed, undo))).toEqual(['greeting', 'goodbye'])
    expect(names(run(renamed, undo, redo))).toEqual(['welcome', 'goodbye'])
  })

  it('brings back the edges that "Ends the call" removed', () => {
    const history = start()
    const [greeting] = history.present.ids
    const ended = run(history, apply((d) => setEnd(d, greeting, true)))
    expect(ended.present.config.nodes[0].edges).toEqual([])
    expect(run(ended, undo).present).toBe(history.present)
  })

  it('does nothing when there is nothing to undo or redo', () => {
    const history = start()
    expect(run(history, undo)).toBe(history)
    expect(run(history, redo)).toBe(history)
  })

  it('does not record an edit that changed nothing', () => {
    const history = start()
    expect(run(history, apply((d) => d))).toBe(history)
  })

  it('forgets what was undone once something new is done', () => {
    const history = start()
    const [greeting] = history.present.ids
    const branched = run(
      history,
      apply((d) => renameNode(d, greeting, 'welcome')),
      undo,
      apply((d) => renameNode(d, greeting, 'hello')),
    )
    expect(run(branched, redo)).toBe(branched)
    expect(names(branched)).toEqual(['hello', 'goodbye'])
  })

  it('undoes what was typed in a field in one step', () => {
    const history = start()
    const [greeting, goodbye] = history.present.ids
    const type = (id: string, text: string) => apply((d) => setInstructions(d, id, text), `text:${id}`)
    const typed = run(history, type(greeting, 'H'), type(greeting, 'He'), type(greeting, 'Hey'))
    expect(typed.past).toHaveLength(1)
    expect(run(typed, undo).present).toBe(history.present)

    // Another field, or the same one after leaving it, is a step of its own.
    const two = run(typed, type(goodbye, 'B'), { type: 'seal' }, type(goodbye, 'By'))
    expect(two.past).toHaveLength(3)
    expect(run(two, undo).present.config.nodes[1].task_messages![0].content).toBe('B')
  })

  it('places the cards without making it something to undo', () => {
    const history = start()
    const placed = run(history, { type: 'place', layout: { greeting: { x: 1, y: 2 } } })
    expect(placed.present.layout).toEqual({ greeting: { x: 1, y: 2 } })
    expect(placed.past).toEqual([])
  })
})
