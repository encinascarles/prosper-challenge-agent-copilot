// A wire between two cards, drawn along the route the layout gave it.
//
// The route is only right for where the cards were when it was computed. Once
// a card is dragged the wire's ends no longer meet the route's, and it falls
// back to a plain curve from dot to dot until "Tidy up" lays the graph out
// again. Comparing the ends is the whole test: nothing has to remember which
// cards moved.

import { BaseEdge, getBezierPath, type Edge, type EdgeProps } from '@xyflow/react'

import type { Point } from './layout'

export type WireEdge = Edge<{ route?: Point[] }, 'wire'>

const CORNER = 8
// React Flow ends a wire at the outer side of the dot, which hangs off the
// card, and the layout at the card's border: about a dot apart.
const NEAR = 14

const near = (point: Point, x: number, y: number) =>
  Math.abs(point.x - x) <= NEAR && Math.abs(point.y - y) <= 1

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

export function RoutedWire(props: EdgeProps<WireEdge>) {
  const { sourceX, sourceY, targetX, targetY, data } = props
  const route = data?.route
  if (route && near(route[0], sourceX, sourceY) && near(route[route.length - 1], targetX, targetY)) {
    // The route's ends are moved onto the dots, so the wire touches them.
    const points = route.map((point) => ({ ...point }))
    points[0].x = sourceX
    points[points.length - 1].x = targetX
    return <BaseEdge id={props.id} path={roundedPath(points)} />
  }
  const [curve] = getBezierPath(props)
  return <BaseEdge id={props.id} path={curve} />
}
