// Where to put a card that is added by hand, without running the layout.
//
// Adding a node must not move the cards already there: someone arranged them.
// So the new card takes the free spot closest to where it is wanted, found by
// trying positions in growing rings around that point.

import type { Point } from '@/draft/draft'

export type Rect = Point & { width: number; height: number }

const STEP = 40 // how far apart the positions tried are
const GAP = 24 // room left around every card
const RINGS = 60 // 2400px each way: beyond that, anywhere is as good

function overlaps(a: Rect, b: Rect): boolean {
  return (
    a.x < b.x + b.width + GAP &&
    b.x < a.x + a.width + GAP &&
    a.y < b.y + b.height + GAP &&
    b.y < a.y + a.height + GAP
  )
}

/**
 * The top-left corner for a card of `size` centered as close to `center` as
 * the `taken` cards allow.
 */
export function freeSpot(center: Point, size: { width: number; height: number }, taken: Rect[]): Point {
  const wanted = { x: center.x - size.width / 2, y: center.y - size.height / 2 }
  const free = (spot: Point) => !taken.some((card) => overlaps({ ...spot, ...size }, card))
  for (let ring = 0; ring <= RINGS; ring++) {
    // The positions on the edge of a square of side 2 * ring, nearest first.
    const spots: Point[] = []
    for (let dx = -ring; dx <= ring; dx++) {
      for (let dy = -ring; dy <= ring; dy++) {
        if (Math.max(Math.abs(dx), Math.abs(dy)) === ring) {
          spots.push({ x: wanted.x + dx * STEP, y: wanted.y + dy * STEP })
        }
      }
    }
    const distance = (spot: Point) => Math.hypot(spot.x - wanted.x, spot.y - wanted.y)
    const found = spots.sort((a, b) => distance(a) - distance(b)).find(free)
    if (found) return found
  }
  return wanted
}
