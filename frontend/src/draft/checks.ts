// Will a call get through this agent? The checks that an agent the backend
// accepts can still fail.
//
// These are warnings, not errors. The agent is valid and can be saved, but a
// call could stay in a node for good, or part of the flow can never happen.
// They are what a flow looks like halfway through being built, so they never
// stop a save; they are a reason not to place a call.
//
// One pure function, with the sentences in it, so the canvas, the save bar and
// whatever starts a call all say the same thing about the same draft.
//
// What counts as "leads to" is what the canvas draws: an end node's edges do
// not exist, and nothing leads into the start node. A loop is fine. A call may
// go round as long as the caller keeps it there; not every path has to end,
// only some path has to.

import type { Draft } from './draft'
import { humanize } from './names'

export type Warning = {
  node: string // the id of the node the warning is about
  kind: 'dead-end' | 'unreachable' | 'no-end'
  message: string // a whole sentence, with the node's name as people read it
}

/** The warnings about `draft`, in the order of its nodes. None for an agent with no start. */
export function checkFlow(draft: Draft): Warning[] {
  const { nodes, initial_node: startName } = draft.config
  const start = nodes.findIndex((node) => node.name === startName)
  if (start < 0) return []

  const index = new Map(nodes.map((node, i) => [node.name, i]))
  // Where each node leads: the nodes its edges name, as the canvas wires them.
  const next = nodes.map((node) =>
    node.end
      ? []
      : (node.edges ?? []).flatMap((edge) => {
          const target = index.get(edge.target)
          return target === undefined || target === start ? [] : [target]
        }),
  )
  const reached = new Set([start])
  for (const queue = [start]; queue.length > 0; ) {
    for (const target of next[queue.pop()!]) {
      if (!reached.has(target)) {
        reached.add(target)
        queue.push(target)
      }
    }
  }

  const warnings: Warning[] = []
  const warn = (i: number, kind: Warning['kind'], message: string) =>
    warnings.push({ node: draft.ids[i], kind, message })
  const ends = [...reached].some((i) => nodes[i].end)
  nodes.forEach((node, i) => {
    const name = humanize(node.name)
    if (!reached.has(i)) {
      // Whatever else is wrong with it does not matter until a call can get there.
      warn(i, 'unreachable', `A call can never get to ${name}.`)
      return
    }
    // An edge that goes nowhere is an error of its own; with one, the node is
    // not finished rather than a dead end.
    if (!node.end && (node.edges ?? []).length === 0) {
      warn(i, 'dead-end', `The call would get stuck at ${name}.`)
    }
    if (i === start && !ends) {
      warn(i, 'no-end', `No path from ${name} ends the call.`)
    }
  })
  return warnings
}

/**
 * Why a test call cannot be placed on a draft now, or null if it can. A call
 * runs the saved agent, so unsaved changes come first: saving is what to do
 * next, whatever else is wrong. Then the first place a call would not get through.
 */
export function callBlocker(dirty: boolean, warnings: Warning[]): string | null {
  if (dirty) return 'Save first'
  return warnings[0]?.message ?? null
}
