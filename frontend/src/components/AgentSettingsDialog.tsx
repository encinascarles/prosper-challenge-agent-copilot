// The open agent's settings, in a dialog in the middle of the screen, and the
// way to delete the agent.
//
// In the middle because it is about the whole agent, not about a place on the
// canvas. Deleting is at the foot of it, behind a question: it is the one thing
// here that undo does not bring back, so it is not a button on every row of
// the picker.

import { Trash2 } from 'lucide-react'
import { useState } from 'react'

import { AgentSettings } from '@/components/AgentSettings'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useEditor } from '@/draft/editor'

type Props = {
  open: boolean
  onOpenChange: (open: boolean) => void
  onDelete: () => void
}

export function AgentSettingsDialog({ open, onOpenChange, onDelete }: Props) {
  const { draft } = useEditor()
  const [asking, setAsking] = useState(false)
  const name = draft.config.name || 'Untitled agent'
  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="gap-0 p-0 sm:max-w-[34rem]">
          <DialogHeader className="border-b px-5 py-3.5">
            <DialogTitle className="text-[15px]">Agent settings</DialogTitle>
            <DialogDescription className="sr-only">
              The name, persona, model and voice of {name}.
            </DialogDescription>
          </DialogHeader>
          <div className="p-5">
            <AgentSettings />
          </div>
          <div className="flex items-center border-t px-5 py-3.5">
            <button
              onClick={() => setAsking(true)}
              className="flex items-center gap-1.5 rounded px-1 text-[13px] font-medium text-bad outline-none hover:underline focus-visible:underline"
            >
              <Trash2 className="size-3.5" /> Delete agent
            </button>
            <Button size="sm" className="ml-auto" onClick={() => onOpenChange(false)}>
              Done
            </Button>
          </div>
        </DialogContent>
      </Dialog>
      <AlertDialog open={asking} onOpenChange={setAsking}>
        <AlertDialogContent size="sm">
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {name}?</AlertDialogTitle>
            <AlertDialogDescription>
              Its flow and settings are removed for good. This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={onDelete}>
              Delete agent
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
