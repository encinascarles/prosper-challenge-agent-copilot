// "Test call", in the top bar next to Save: a real voice call to the agent.
//
// A call runs the agent as it was saved, so it waits for the save; and it is
// not placed on a flow the checks say a call cannot get through. Either way
// the button stays where it is, disabled, and says why when pointed at.

import { Phone } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { callBlocker, type Warning } from '@/draft/checks'

type Props = {
  dirty: boolean
  warnings: Warning[]
  /** A call is on screen, running or ended. */
  open: boolean
  onStart: () => void
}

export function TestCallButton({ dirty, warnings, open, onStart }: Props) {
  const blocker = open ? null : callBlocker(dirty, warnings)
  return (
    // The reason is on a wrapper: a disabled button takes no pointer, so no tooltip.
    <span title={blocker ?? undefined} className="ml-2 flex">
      <Button size="sm" disabled={open || blocker !== null} onClick={onStart} aria-description={blocker ?? undefined}>
        <Phone className="size-3.5" /> Test call
      </Button>
    </span>
  )
}
