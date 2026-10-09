// Naming a new agent, before it exists.
//
// An agent is found by its name in the picker and in the tab, so it gets one
// from the start instead of a row of "New agent"s to tell apart later. The
// flow it starts with is the template's; only the name is asked.

import { useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

type Props = {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Creates the agent. A failure is shown here and the dialog stays. */
  onCreate: (name: string) => Promise<void>
}

export function NewAgentDialog({ open, onOpenChange, onCreate }: Props) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-sm">
        <NameForm onCancel={() => onOpenChange(false)} onCreate={onCreate} />
      </DialogContent>
    </Dialog>
  )
}

// Its own component, so it starts empty each time the dialog opens: the dialog
// only mounts what is inside it while it is open.
function NameForm({ onCancel, onCreate }: { onCancel: () => void; onCreate: Props['onCreate'] }) {
  const [name, setName] = useState('')
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const ready = name.trim() !== '' && !creating

  const create = async () => {
    if (!ready) return
    setCreating(true)
    setError(null)
    try {
      await onCreate(name.trim())
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure))
    } finally {
      setCreating(false)
    }
  }

  return (
    <form
      className="grid gap-4"
      onSubmit={(event) => {
        event.preventDefault()
        void create()
      }}
    >
      <DialogHeader>
        <DialogTitle>New agent</DialogTitle>
        <DialogDescription>
          It starts with a greeting and a goodbye. You can rename it later.
        </DialogDescription>
      </DialogHeader>
      <label className="block space-y-1">
        <span className="text-[11px] font-medium text-muted-foreground">Name</span>
        <input
          autoFocus
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="e.g. Riverside front desk"
          className="w-full rounded-md border bg-background px-2.5 py-1.5 text-sm outline-none focus:border-foreground/40"
        />
      </label>
      {error && (
        <p role="alert" className="text-[13px] text-bad">
          {error}
        </p>
      )}
      <DialogFooter>
        <Button type="button" size="sm" variant="outline" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" size="sm" disabled={!ready}>
          {creating ? 'Creating…' : 'Create'}
        </Button>
      </DialogFooter>
    </form>
  )
}
