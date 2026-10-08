// Saving, in the top bar: what state the draft is in and the one thing to do
// about it.
//
// The button changes with what stands in the way. Loose wires are checked
// here, before anything is sent: the backend would refuse an edge with no
// target anyway, and the canvas can show where they are. What the backend
// refuses for another reason is shown as its own sentence on the card it names.
// Warnings are counted next to it and never change what the button does.

import { TriangleAlert } from 'lucide-react'

import { Button } from '@/components/ui/button'

type Props = {
  dirty: boolean
  saving: boolean
  saved: boolean // a save went through since the agent was opened
  loose: number // edges that go nowhere
  warnings: number // places a call could get stuck: shown, not in the way
  /** Why the last save of this very draft was refused, if it was. */
  problem: { message: string; onCard: boolean } | null
  onSave: () => void
  onShowLoose: () => void
  onShowWarnings: () => void
  onShowProblem: () => void
}

const link = 'rounded px-1 text-[13px] font-medium text-bad outline-none hover:underline focus-visible:underline'

export function SaveControl(props: Props) {
  const { dirty, saving, saved, loose, warnings, problem } = props
  const { onSave, onShowLoose, onShowWarnings, onShowProblem } = props
  return (
    <div className="ml-auto flex items-center gap-3 text-[13px]">
      {problem ? (
        problem.onCard ? (
          <button onClick={onShowProblem} title={problem.message} className={link}>
            Not saved: 1 problem
          </button>
        ) : (
          <span role="alert" className="max-w-[40ch] truncate text-bad" title={problem.message}>
            Not saved: {problem.message}
          </span>
        )
      ) : (
        <span className="text-muted-foreground" aria-live="polite">
          {dirty ? 'Unsaved changes' : saved ? 'Saved' : ''}
        </span>
      )}
      {warnings > 0 && (
        // Not crimson: the agent is valid and saves. It is a call that would not get through.
        <button
          onClick={onShowWarnings}
          title="A call could get stuck. Saving is not affected."
          className="flex items-center gap-1 rounded px-1 font-medium text-warn outline-none hover:underline focus-visible:underline"
        >
          <TriangleAlert className="size-3.5" />
          {warnings} {warnings === 1 ? 'warning' : 'warnings'}
        </button>
      )}
      {loose > 0 ? (
        // Nothing to send yet: the button says what is missing and shows where.
        <Button
          size="sm"
          variant="outline"
          onClick={onShowLoose}
          title="Connect or remove them to save"
          className="border-bad/40 text-bad hover:bg-bad/5 hover:text-bad"
        >
          {loose} loose {loose === 1 ? 'wire' : 'wires'}
        </Button>
      ) : (
        <Button size="sm" disabled={!dirty || saving} onClick={onSave} title="Save (⌘S)">
          {saving ? 'Saving…' : 'Save'}
        </Button>
      )}
    </div>
  )
}
