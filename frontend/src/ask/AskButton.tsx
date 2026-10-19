// "Ask Prosper AI", in the top bar next to Test call: opens and closes the
// panel of questions (⌘J, or Ctrl+J, from anywhere).

import { Mark } from '@/components/Mark'
import { cn } from '@/lib/utils'

export function AskButton({ open, onToggle }: { open: boolean; onToggle: () => void }) {
  return (
    <button
      onClick={onToggle}
      aria-pressed={open}
      className={cn(
        'ml-2 flex h-8 shrink-0 items-center gap-2 rounded-md px-2.5 text-[13px] font-medium hover:bg-muted',
        open && 'bg-muted',
      )}
    >
      <Mark className="h-[14px]" /> Ask Prosper AI
      <kbd className="rounded border px-1 font-sans text-[10.5px] text-muted-foreground">⌘J</kbd>
    </button>
  )
}
