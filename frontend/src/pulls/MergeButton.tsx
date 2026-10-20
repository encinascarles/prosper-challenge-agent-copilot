// The Merge button, on a pull request's page and in Build's bar. A fix that
// may not fix its issue (its own test passes 2 of 3, or it was never
// reproduced) still merges: the first click shows why it may not, and "Merge
// anyway" merges. Every other pull request merges on the first click.

import { GitMerge, TriangleAlert } from 'lucide-react'
import { useState } from 'react'

import type { PullSummary } from '@/agents/types'
import { Button } from '@/components/ui/button'
import { Popover, PopoverAnchor, PopoverContent } from '@/components/ui/popover'

import { mergeStep } from './model'

type Props = {
  pull: Pick<PullSummary, 'warnings'>
  label: string // "Merge as v3"
  /** Why it cannot merge now, or null: shown as its tooltip. */
  blocker: string | null
  busy: boolean
  merging: boolean
  className?: string
  onMerge: (anyway: boolean) => void
}

export function MergeButton({ pull, label, blocker, busy, merging, className, onMerge }: Props) {
  const [warnings, setWarnings] = useState<string[] | null>(null)
  const click = () => {
    const step = mergeStep(pull, false)
    if ('confirm' in step) setWarnings(step.confirm)
    else onMerge(step.anyway)
  }
  const warned = pull.warnings.length > 0
  return (
    <Popover open={warnings !== null} onOpenChange={(open) => !open && setWarnings(null)}>
      <PopoverAnchor asChild>
        <span title={blocker ?? (warned ? pull.warnings.join(' ') : undefined)} className="flex">
          <Button size="sm" className={className} disabled={blocker !== null || busy || merging} onClick={click}>
            {warned ? <TriangleAlert className="size-3.5 text-warn" /> : <GitMerge className="size-3.5" />}
            {merging ? 'Merging…' : label}
          </Button>
        </span>
      </PopoverAnchor>
      <PopoverContent align="end" className="w-80 p-3.5">
        <div className="space-y-1.5 text-[13px] leading-snug">
          {(warnings ?? []).map((warning) => (
            <p key={warning} className="flex items-start gap-2">
              <TriangleAlert className="mt-0.5 size-3.5 shrink-0 text-warn" />
              <span>{warning}</span>
            </p>
          ))}
        </div>
        <div className="mt-3 flex justify-end gap-2">
          <Button size="sm" variant="ghost" className="h-7 text-[12.5px]" onClick={() => setWarnings(null)}>
            Cancel
          </Button>
          <Button
            size="sm"
            className="h-7 text-[12.5px]"
            onClick={() => {
              setWarnings(null)
              onMerge(true)
            }}
          >
            <GitMerge className="size-3.5" /> Merge anyway
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  )
}
