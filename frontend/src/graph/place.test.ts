import { describe, expect, it } from 'vitest'

import { freeSpot, type Rect } from './place'

const size = { width: 300, height: 120 }
const card = (x: number, y: number): Rect => ({ x, y, width: 300, height: 200 })
const clear = (spot: { x: number; y: number }, taken: Rect[]) =>
  taken.every(
    (other) =>
      spot.x + size.width <= other.x ||
      other.x + other.width <= spot.x ||
      spot.y + size.height <= other.y ||
      other.y + other.height <= spot.y,
  )

describe('freeSpot', () => {
  it('centers the card on the point when nothing is there', () => {
    expect(freeSpot({ x: 500, y: 400 }, size, [])).toEqual({ x: 350, y: 340 })
    expect(freeSpot({ x: 500, y: 400 }, size, [card(2000, 2000)])).toEqual({ x: 350, y: 340 })
  })

  it('moves off a card that is in the way, and stays close', () => {
    const taken = [card(300, 300)]
    const spot = freeSpot({ x: 450, y: 400 }, size, taken)
    expect(clear(spot, taken)).toBe(true)
    expect(Math.hypot(spot.x - 300, spot.y - 340)).toBeLessThan(400)
  })

  it('finds a gap between many cards', () => {
    const taken = [card(0, 0), card(340, 0), card(680, 0), card(0, 240), card(680, 240)]
    const spot = freeSpot({ x: 150, y: 100 }, size, taken)
    expect(clear(spot, taken)).toBe(true)
  })

  it('does not stack two cards added at the same point', () => {
    const first = freeSpot({ x: 0, y: 0 }, size, [])
    const second = freeSpot({ x: 0, y: 0 }, size, [{ ...first, ...size }])
    expect(clear(second, [{ ...first, ...size }])).toBe(true)
  })
})
