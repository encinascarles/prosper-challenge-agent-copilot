// The sections of an agent, in the middle of the top bar: Build, where its
// flow is edited; Calls, what its live version answered; Issues, what Prosper
// AI found going wrong in them; and Pull requests, where proposed changes to
// it are read and decided on. Open issues and open pull requests are counted
// next to their names.

import { cn } from '@/lib/utils'

export type Section = 'build' | 'calls' | 'issues' | 'pulls'

const NAMES: [Section, string][] = [
  ['build', 'Build'],
  ['calls', 'Calls'],
  ['issues', 'Issues'],
  ['pulls', 'Pull requests'],
]

type Props = {
  section: Section
  /** Open pull requests. */
  open: number
  /** Open issues. */
  issues: number
  onSection: (section: Section) => void
}

export function Sections({ section, open, issues, onSection }: Props) {
  const counts: Partial<Record<Section, number>> = { issues, pulls: open }
  return (
    <nav aria-label="Sections" className="absolute left-1/2 flex -translate-x-1/2 rounded-lg bg-muted p-0.5 text-[13px]">
      {NAMES.map(([key, name]) => (
        <button
          key={key}
          aria-current={section === key ? 'page' : undefined}
          onClick={() => onSection(key)}
          className={cn(
            'flex h-7 items-center gap-1.5 rounded-md px-3.5 whitespace-nowrap outline-none focus-visible:ring-2 focus-visible:ring-ring/50',
            section === key ? 'bg-background font-medium shadow-sm' : 'text-muted-foreground hover:text-foreground',
          )}
        >
          {name}
          {(counts[key] ?? 0) > 0 && <span className="text-[12px] font-normal text-muted-foreground tabular-nums">{counts[key]}</span>}
        </button>
      ))}
    </nav>
  )
}
