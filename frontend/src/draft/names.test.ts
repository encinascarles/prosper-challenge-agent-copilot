import { describe, expect, it } from 'vitest'

import { functionName, humanize, toName } from './names'

const VALID = /^[a-zA-Z0-9_-]{1,64}$/

describe('humanize', () => {
  it('shows a stored name as words', () => {
    expect(humanize('collect_details')).toBe('Collect details')
    expect(humanize('full_name')).toBe('Full name')
  })
})

describe('toName', () => {
  it('stores what was typed in snake_case', () => {
    expect(toName('Collect details')).toBe('collect_details')
    expect(toName('  Offer   2 times! ')).toBe('offer_2_times')
    expect(toName('Petició')).toBe('peticio')
  })

  it('reads back as it was typed', () => {
    expect(humanize(toName('Collect details'))).toBe('Collect details')
  })

  it('is empty when nothing usable was typed', () => {
    expect(toName(' ?! ')).toBe('')
  })
})

describe('functionName', () => {
  it('is go_to_ and the target', () => {
    expect(functionName('collect_details', [])).toBe('go_to_collect_details')
  })

  it('is go_to_next for an edge that goes nowhere yet', () => {
    expect(functionName('', [])).toBe('go_to_next')
  })

  it('gets a number when the node already has that name', () => {
    expect(functionName('confirm', ['go_to_confirm'])).toBe('go_to_confirm_2')
    expect(functionName('confirm', ['go_to_confirm', 'go_to_confirm_2'])).toBe('go_to_confirm_3')
  })

  it('is always a valid tool name', () => {
    const long = 'a'.repeat(80)
    const first = functionName(long, [])
    const second = functionName(long, [first])
    expect(first).toMatch(VALID)
    expect(second).toMatch(VALID)
    expect(second).not.toBe(first)
    expect(functionName('weird name/ñ', [])).toMatch(VALID)
  })
})
