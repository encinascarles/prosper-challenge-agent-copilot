// A wire between two cards, drawn along the route the layout gave it.
//
// The route is only right for where the cards were when it was computed. Once
// a card is dragged the wire's ends no longer meet the route's, and it falls
// back to a plain curve from dot to dot until "Tidy up" lays the graph out
// again. Comparing the ends is the whole test: nothing has to remember which
// cards moved.
//
// A card that grows while it is edited pushes its dots down without moving
// sideways. The route still holds then: its first and last stretches are
// level, so they follow the dot up or down and the corner beside it stretches.

import { BaseEdge, getBezierPath, type Edge, type EdgeProps } from '@xyflow/react'

import type { Point } from './layout'

export type WireEdge = Edge<{ route?: Point[] }, 'wire'>

const CORNER = 8
// How far outside its card a dot ends, which is where React Flow starts a
// wire; the layout starts it at the card's border.
const REACH = 11

/** A path through `points` at right angles, with rounded corners. */
function roundedPath(points: Point[]): string {
  let path = `M${points[0].x},${points[0].y}`
  for (let i = 1; i < points.length - 1; i++) {
    const [before, corner, after] = [points[i - 1], points[i], points[i + 1]]
    const into = Math.hypot(corner.x - before.x, corner.y - before.y)
    const out = Math.hypot(after.x - corner.x, after.y - corner.y)
    if (into === 0 || out === 0) continue
    const radius = Math.min(CORNER, into / 2, out / 2)
    const start = {
      x: corner.x - ((corner.x - before.x) / into) * radius,
      y: corner.y - ((corner.y - before.y) / into) * radius,
    }
    const end = {
      x: corner.x + ((after.x - corner.x) / out) * radius,
      y: corner.y + ((after.y - corner.y) / out) * radius,
    }
    path += ` L${start.x},${start.y} Q${corner.x},${corner.y} ${end.x},${end.y}`
  }
  const last = points[points.length - 1]
  return `${path} L${last.x},${last.y}`
}

/** `route` with its ends on the dots, or nothing if the cards are no longer where it was made for. */
function fitted(route: Point[], from: Point, to: Point): Point[] | null {
  const first = route[0]
  const last = route[route.length - 1]
  const inPlace =
    Math.abs(from.x - first.x - REACH) <= 2 && Math.abs(last.x - to.x - REACH) <= 2
  if (!inPlace) return null
  // A straight wire has no corner to take up a dot that moved up or down.
  if (route.length < 4) return Math.abs(from.y - to.y) <= 0.5 ? [from, to] : null
  const before = route.slice(1, -1).map((point) => ({ ...point }))
  before[0].y = from.y
  before[before.length - 1].y = to.y
  return [from, ...before, to]
}

export function RoutedWire(props: EdgeProps<WireEdge>) {
  const { sourceX, sourceY, targetX, targetY, data } = props
  const points =
    data?.route && fitted(data.route, { x: sourceX, y: sourceY }, { x: targetX, y: targetY })
  if (points) return <BaseEdge id={props.id} path={roundedPath(points)} />
  const [curve] = getBezierPath(props)
  return <BaseEdge id={props.id} path={curve} />
}
