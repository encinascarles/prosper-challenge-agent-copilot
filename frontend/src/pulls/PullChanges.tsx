// The Changes tab of a pull request: what it changes compared with the version
// it is based on, one card per step, readable by someone who never saw the
// agent JSON. Additions in the orange of a proposed change, removals struck
// through, instructions compared word by word. Then the rules and tests it
// adds or takes out, which travel with the copy like the steps do.

import type { Rule, Test } from '@/agents/types'
import { humanize } from '@/draft/names'
import { cn } from '@/lib/utils'
import type { DiffLine, StepChange } from '@/pulls/diff'
import type { suiteChanges } from '@/suite/model'

const TAGS: Record<StepChange['kind'], string> = {
  added: 'new step',
  removed: 'removed',
  edited: 'edited',
  agent: 'name, persona, model, voice',
}

function Line({ line }: { line: DiffLine }) {
  const box = 'rounded-md px-2 py-1.5 text-[13px] leading-snug'
  if (line.op === 'words') {
    return (
      <div className={cn(box, 'border bg-card')}>
        <span className="mr-1.5 font-semibold text-foreground/80">{line.label}</span>
        {line.parts.map((part, i) =>
          part.op === 'same' ? (
            <span key={i}>{part.text}</span>
          ) : part.op === 'add' ? (
            <ins key={i} className="rounded-sm bg-brand-tint px-0.5 text-foreground no-underline ring-1 ring-brand/25">
              {part.text}
            </ins>
          ) : (
            <del key={i} className="mr-0.5 text-muted-foreground decoration-muted-foreground/60">
              {part.text}
            </del>
          ),
        )}
      </div>
    )
  }
  if (line.op === 'add') {
    return (
      <div className={cn(box, 'bg-brand-tint')}>
        <span className="mr-1.5 font-semibold text-brand">+ {line.label}</span>
        {line.text}
      </div>
    )
  }
  if (line.op === 'remove') {
    return (
      <div className={cn(box, 'bg-muted/60 text-muted-foreground')}>
        <span className="mr-1.5 font-semibold">− {line.label}</span>
        <span className="line-through decoration-muted-foreground/50">{line.text}</span>
      </div>
    )
  }
  return (
    <div className={cn(box, 'text-muted-foreground')}>
      <span className="mr-1.5 font-semibold text-foreground/80">{line.label}</span>
      {line.text}
    </div>
  )
}

function ChangeCard({ change }: { change: StepChange }) {
  const removed = change.kind === 'removed'
  return (
    <div className={cn('rounded-lg border bg-card px-4 py-3', removed ? 'border-dashed' : change.kind === 'added' && 'border-brand/50')}>
      <div className="flex items-baseline gap-2 text-[13.5px] font-semibold">
        <span className={cn(removed && 'text-muted-foreground line-through decoration-muted-foreground/50')}>{change.label}</span>
        <span className="text-[11.5px] font-normal text-muted-foreground">{TAGS[change.kind]}</span>
      </div>
      {change.lines.length > 0 && (
        <div className="mt-2 space-y-1">
          {change.lines.map((line, i) => (
            <Line key={i} line={line} />
          ))}
        </div>
      )}
    </div>
  )
}

type SuiteChanges = ReturnType<typeof suiteChanges>

function SuiteCard({ title, added, removed, line }: {
  title: string
  added: (Rule | Test)[]
  removed: (Rule | Test)[]
  line: (item: Rule | Test) => React.ReactNode
}) {
  if (added.length + removed.length === 0) return null
  const box = 'rounded-md px-2 py-1.5 text-[13px] leading-snug'
  return (
    <div className="rounded-lg border bg-card px-4 py-3">
      <div className="text-[13.5px] font-semibold">{title}</div>
      <div className="mt-2 space-y-1">
        {added.map((item) => (
          <div key={item.id} className={cn(box, 'bg-brand-tint')}>
            <span className="mr-1.5 font-semibold text-brand">+</span>
            {line(item)}
          </div>
        ))}
        {removed.map((item) => (
          <div key={item.id} className={cn(box, 'bg-muted/60 text-muted-foreground line-through decoration-muted-foreground/50')}>
            <span className="mr-1.5 font-semibold">−</span>
            {line(item)}
          </div>
        ))}
      </div>
    </div>
  )
}

const ruleLine = (item: Rule | Test) => {
  const rule = item as Rule
  return (
    <>
      <span className="mr-1.5 font-semibold text-foreground/80">{rule.step === null ? 'Every step' : humanize(rule.step)}</span>
      {rule.text}
    </>
  )
}

const testLine = (item: Rule | Test) => {
  const test = item as Test
  return (
    <>
      <span className="mr-1.5 font-semibold text-foreground/80">{test.name}</span>
      <span className="text-muted-foreground">{test.checks.join(' · ')}</span>
    </>
  )
}

type Props = {
  changes: StepChange[]
  suite: SuiteChanges
  /** What it is compared with: "v1", or null for a pull request based on nothing yet. */
  base: string | null
  open: boolean
}

export function PullChanges({ changes, suite, base, open }: Props) {
  const rules = suite.rulesAdded.length + suite.rulesRemoved.length
  const tests = suite.testsAdded.length + suite.testsRemoved.length
  if (changes.length === 0 && rules + tests === 0) {
    return (
      <p className="py-10 text-center text-[13px] text-muted-foreground">
        {open
          ? 'No changes yet. Open it in Build, edit the flow or add a rule or a test: the changes land here, and live stays as it is.'
          : 'It had no changes.'}
      </p>
    )
  }
  const steps = changes.filter((change) => change.kind !== 'agent').length
  const parts = [
    steps ? `${steps} ${steps === 1 ? 'step' : 'steps'}` : '',
    changes.some((change) => change.kind === 'agent') ? "the agent's settings" : '',
    rules ? `${rules} ${rules === 1 ? 'rule' : 'rules'}` : '',
    tests ? `${tests} ${tests === 1 ? 'test' : 'tests'}` : '',
  ].filter(Boolean)
  return (
    <div className="space-y-3">
      <p className="text-[12.5px] text-muted-foreground tabular-nums">
        {parts.join(' · ')} · {base ? `compared with ${base}` : 'everything is new: the agent is not live yet'}
      </p>
      {changes.map((change) => (
        <ChangeCard key={change.key} change={change} />
      ))}
      <SuiteCard title="Rules" added={suite.rulesAdded} removed={suite.rulesRemoved} line={ruleLine} />
      <SuiteCard title="Tests" added={suite.testsAdded} removed={suite.testsRemoved} line={testLine} />
    </div>
  )
}
