// The menu of a card: what a node is in the call, and deleting it.
//
// "Start here" moves the one start of the agent; "Ends the call" is a switch
// any number of nodes can have on. What each drags along (edges disconnected or
// removed) is decided in draft/draft.ts, and all three can be undone.

import { Check, MoreHorizontal, PhoneOff, Play, Trash2 } from 'lucide-react'

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { deleteNode, setEnd, setStart } from '@/draft/draft'
import { useEditor } from '@/draft/editor'

type Props = { id: string; start: boolean; end: boolean }

export function NodeMenu({ id, start, end }: Props) {
  const { apply } = useEditor()
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        aria-label="Node options"
        className="nodrag -mr-1.5 shrink-0 rounded-md p-1 text-muted-foreground opacity-0 outline-none transition-opacity group-hover/card:opacity-100 hover:bg-muted [@media(hover:none)]:opacity-100 hover:text-foreground focus-visible:opacity-100 data-[state=open]:bg-muted data-[state=open]:opacity-100"
      >
        <MoreHorizontal className="size-4" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-48">
        <DropdownMenuItem disabled={start} onSelect={() => apply((draft) => setStart(draft, id))}>
          <Play /> Start here
          {start && <Check className="ml-auto" />}
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => apply((draft) => setEnd(draft, id, !end))}>
          <PhoneOff /> Ends the call
          {end && <Check className="ml-auto" />}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem variant="destructive" onSelect={() => apply((draft) => deleteNode(draft, id))}>
          <Trash2 /> Delete node
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
