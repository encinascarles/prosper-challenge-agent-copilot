// The sections of an agent, in the middle of the top bar: Build, where its
// flow is edited, and Pull requests, where proposed changes to it are read and
// decided on. The open ones are counted next to the name.

import { cn } from '@/lib/utils'

export type Section = 'build' | 'pulls'

const NAMES: [Section, string][] = [
  ['build', 'Build'],
  ['pulls', 'Pull requests'],
]

type Props = {
  section: Section
  /** Open pull requests. */
  open: number
  onSection: (section: Section) => void
}

export function Sections({ section, open, onSection }: Props) {
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
          {key === 'pulls' && open > 0 && <span className="text-[12px] font-normal text-muted-foreground tabular-nums">{open}</span>}
        </button>
      ))}
    </nav>
  )
}
