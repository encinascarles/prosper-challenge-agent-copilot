// Names, as people read them and as the agent stores them.
//
// The agent JSON holds identifiers: node and field names in snake_case, and a
// function name per edge, which is the tool the model calls. The editor shows
// the first two as words and never shows the third, so it is generated here
// from the edge's target and nobody has to invent one.

/** A stored name as people read it: "collect_details" is shown as "Collect details". */
export function humanize(name: string): string {
  return name.replace(/_/g, ' ').replace(/^./, (first) => first.toUpperCase())
}

/** What someone typed, as the name to store: "Collect détails " becomes "collect_details". */
export function toName(text: string): string {
  return text
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
}

// What a provider accepts as a tool name; the backend checks the same pattern.
const MAX_FUNCTION = 64

/**
 * The function name of an edge that goes to the node `target`: `go_to_<target>`,
 * or `go_to_next` while the edge is not connected. `taken` are the names of the
 * node's other edges: a node's edges are the tools of one request, so two edges
 * to the same node get a number.
 */
export function functionName(target: string, taken: Iterable<string>): string {
  const used = new Set(taken)
  const slug = target.replace(/[^a-zA-Z0-9_-]+/g, '_') || 'next'
  const base = `go_to_${slug}`.slice(0, MAX_FUNCTION)
  for (let n = 1; ; n++) {
    const suffix = n === 1 ? '' : `_${n}`
    const candidate = base.slice(0, MAX_FUNCTION - suffix.length) + suffix
    if (!used.has(candidate)) return candidate
  }
}
