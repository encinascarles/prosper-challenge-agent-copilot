// The bar at the top of every screen: where you are (Prosper, then the agent)
// and, at the right, the open agent's actions.
//
// The agent's name is the one control for agents. It opens the list of them,
// with the open one checked and "New agent" at the end; picking a row opens
// that agent. Each row has a gear that opens that agent's settings. One
// control, because "which agent" and "this agent's settings" are both about
// the name you are looking at.

import { ChevronsUpDown, Plus, Settings } from 'lucide-react'
import { useRef, useState } from 'react'

import type { AgentSummary } from '@/agents/types'
import { Mark } from '@/components/Mark'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'

type Props = {
  agents: AgentSummary[]
  agentId: string | null
  onPick: (id: string) => void
  /** The gear of an agent's row: its settings, opening the agent first if needed. */
  onSettings: (id: string) => void
  onNew: () => void
  /** The open agent's name as it is being edited, when it is. */
  name?: string
  /** The open agent's actions, at the right. */
  children?: React.ReactNode
}

export function TopBar({ agents, agentId, onPick, onSettings, onNew, name, children }: Props) {
  const [listOpen, setListOpen] = useState(false)
  // What was asked for from the list that opens a dialog, until the list has
  // closed. The dialog opens only then: the closing list would otherwise take
  // the focus back from it.
  const after = useRef<(() => void) | null>(null)
  const title = (agent: AgentSummary) => (agent.id === agentId && name !== undefined ? name : agent.name)
  const open = agents.find((agent) => agent.id === agentId)

  return (
    <header className="flex h-12 shrink-0 items-center gap-1.5 border-b px-4">
      <Mark />
      <span className="ml-0.5 text-sm font-semibold tracking-[-0.01em]">Prosper</span>
      <span className="ml-1 text-sm text-muted-foreground">/</span>
      <DropdownMenu open={listOpen} onOpenChange={setListOpen}>
        <DropdownMenuTrigger
          aria-label="Agents"
          className="flex h-8 min-w-0 items-center gap-2 rounded-md px-2 text-sm font-medium outline-none hover:bg-muted focus-visible:bg-muted data-[state=open]:bg-muted"
        >
          <span className="truncate">{open ? title(open) || 'Untitled agent' : 'Choose an agent'}</span>
          <ChevronsUpDown className="size-3.5 shrink-0 text-muted-foreground" />
        </DropdownMenuTrigger>
        <DropdownMenuContent
          align="start"
          className="w-80"
          onCloseAutoFocus={(event) => {
            if (!after.current) return
            event.preventDefault()
            after.current()
            after.current = null
          }}
        >
          <DropdownMenuRadioGroup value={agentId ?? ''} onValueChange={onPick}>
            {agents.map((agent) => (
              <DropdownMenuRadioItem key={agent.id} value={agent.id} className="group/row pr-1">
                <span className="min-w-0 flex-1 truncate">{title(agent) || 'Untitled agent'}</span>
                <span className="text-xs text-muted-foreground tabular-nums">
                  {agent.nodes} {agent.nodes === 1 ? 'node' : 'nodes'}
                </span>
                <button
                  aria-label="Agent settings"
                  title="Agent settings"
                  // The row opens the agent; the gear is its own thing.
                  onClick={(event) => {
                    event.stopPropagation()
                    after.current = () => onSettings(agent.id)
                    setListOpen(false)
                  }}
                  onPointerUp={(event) => event.stopPropagation()}
                  // Only on the row being pointed at (or reached with the keyboard);
                  // where there is no pointer to hover with, always.
                  className="rounded p-1 text-muted-foreground opacity-0 outline-none group-hover/row:opacity-100 group-focus/row:opacity-100 hover:bg-background hover:text-foreground focus-visible:opacity-100 [@media(hover:none)]:opacity-100"
                >
                  <Settings className="size-3.5" />
                </button>
              </DropdownMenuRadioItem>
            ))}
          </DropdownMenuRadioGroup>
          {agents.length > 0 && <DropdownMenuSeparator />}
          <DropdownMenuItem
            onSelect={() => {
              after.current = onNew
            }}
          >
            <Plus /> New agent
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      {children}
    </header>
  )
}
