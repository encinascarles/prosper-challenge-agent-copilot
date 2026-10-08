// The bar at the top of every screen: where you are (Prosper, then the agent,
// which is also how you switch to another one). The right side is for the open
// agent's actions: saving now, the test call later.

import { ChevronsUpDown } from 'lucide-react'

import type { AgentSummary } from '@/agents/types'
import { Mark } from '@/components/Mark'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'

type Props = {
  agents: AgentSummary[]
  agentId: string | null
  onPick: (id: string) => void
  /** The open agent's actions, at the right. */
  children?: React.ReactNode
}

export function TopBar({ agents, agentId, onPick, children }: Props) {
  const agent = agents.find((candidate) => candidate.id === agentId)
  return (
    <header className="flex h-12 shrink-0 items-center gap-1.5 border-b px-4">
      <Mark />
      <span className="ml-0.5 text-sm font-semibold tracking-[-0.01em]">Prosper</span>
      {agents.length > 0 && (
        <>
          <span className="ml-1 text-sm text-muted-foreground">/</span>
          <DropdownMenu>
            <DropdownMenuTrigger
              aria-label="Switch agent"
              className="flex h-8 min-w-0 items-center gap-2 rounded-md px-2 text-sm font-medium outline-none hover:bg-muted focus-visible:bg-muted data-[state=open]:bg-muted"
            >
              <span className="truncate">{agent?.name ?? 'Choose an agent'}</span>
              <ChevronsUpDown className="size-3.5 shrink-0 text-muted-foreground" />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="w-72">
              <DropdownMenuRadioGroup value={agentId ?? ''} onValueChange={onPick}>
                {agents.map((candidate) => (
                  <DropdownMenuRadioItem key={candidate.id} value={candidate.id}>
                    <span className="min-w-0 flex-1 truncate">{candidate.name}</span>
                    <span className="text-xs text-muted-foreground tabular-nums">
                      {candidate.nodes} {candidate.nodes === 1 ? 'node' : 'nodes'}
                    </span>
                  </DropdownMenuRadioItem>
                ))}
              </DropdownMenuRadioGroup>
            </DropdownMenuContent>
          </DropdownMenu>
        </>
      )}
      {children}
    </header>
  )
}
