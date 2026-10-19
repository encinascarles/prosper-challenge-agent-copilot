// A test opened over the graph, at the right of the canvas where a test call's
// card goes: what it checks and how its runs went. The run picked is drawn on
// the graph the way a test call is, so where it went is read on the flow
// itself. It runs again on its own from here, 3 times, leaving the other
// tests' results as they are. And the card a new test is written in: a name,
// who calls, and the checks, one per line.

import { Plus, RotateCw, Trash2, X } from 'lucide-react'
import { useState } from 'react'

import type { Test, TestRun } from '@/agents/types'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

import { TestIcon } from './bits'
import { checkKind, score, verdict, type Names } from './model'
import { CheckKind, label, TestResults } from './TestResults'

const card =
  'absolute top-4 right-4 bottom-4 z-20 flex w-[380px] flex-col overflow-hidden rounded-2xl border bg-card shadow-[0_18px_50px_-18px_rgba(0,0,0,0.35)]'
const field =
  'w-full rounded-md border bg-background px-2 py-1.5 text-[12.5px] leading-snug outline-none focus:border-foreground/40'

function Header({ icon, title, sub, onClose }: { icon: React.ReactNode; title: string; sub: string; onClose: () => void }) {
  return (
    <div className="flex items-start gap-2.5 border-b px-4 py-3">
      {icon}
      <div className="min-w-0 flex-1">
        <div className="text-[14px] font-semibold">{title}</div>
        <div className="text-[12px] text-muted-foreground">{sub}</div>
      </div>
      <button onClick={onClose} aria-label="Close" className="rounded p-1 text-muted-foreground hover:bg-muted">
        <X className="size-4" />
      </button>
    </div>
  )
}

type Props = {
  test: Test
  names: Names
  result: TestRun | undefined
  repeats: number
  /** Where it ran: "PR #2" or "v3". */
  on: string
  /** It was added in the pull request the editor is on, so it can be taken out there. */
  removable: boolean
  /** The copy's tests are running, this one or others: nothing else runs until they end. */
  running: boolean
  selected: number
  onSelect: (index: number) => void
  onShowNode: (node: string) => void
  onRun: () => void
  onRemove: () => void
  onClose: () => void
}

export function TestCard(props: Props) {
  const { test, names, result, repeats, on, removable, running, selected, onSelect, onShowNode, onRun, onRemove, onClose } = props
  const s = result ? score(result, repeats) : null
  const shown = s ? verdict(s) : null
  const sub =
    s === null
      ? `Not run on ${on} yet`
      : shown === 'running'
        ? `Running on ${on} · ${s.done} of ${s.of} runs`
        : `${shown === 'fail' ? 'Fails' : shown === 'flaky' ? 'Flaky' : 'Passes'} · ${s.passed}/${s.of} runs on ${on}`
  return (
    <section aria-label="Test" className={card}>
      <Header icon={<TestIcon score={s} className="mt-px" />} title={test.name} sub={`${sub} · simulated, in text`} onClose={onClose} />
      <div className="min-h-0 flex-1 overflow-auto">
        <TestResults
          test={test}
          names={names}
          result={result}
          repeats={repeats}
          selected={selected}
          onSelect={onSelect}
          onShowNode={onShowNode}
        />
      </div>
      <div className="flex items-center gap-2 border-t bg-muted/30 px-4 py-2.5">
        <span title={running ? 'Waits for the tests running now' : `Runs it 3 times on ${on}; the other tests keep their results`}>
          <Button size="sm" variant="outline" disabled={running} onClick={onRun}>
            <RotateCw className={cn('size-3.5', running && shown === 'running' && 'animate-spin')} />
            {running && shown === 'running' ? 'Running…' : 'Run this test'}
          </Button>
        </span>
        {removable && (
          <Button size="sm" variant="outline" className="ml-auto text-bad" onClick={onRemove}>
            <Trash2 className="size-3.5" /> Take this test out
          </Button>
        )}
      </div>
    </section>
  )
}

type NewProps = {
  names: Names
  /** Where it goes: "PR #2", or "a new pull request" on live. */
  into: string
  onAdd: (test: { name: string; caller: string; checks: string[] }) => Promise<void>
  onClose: () => void
}

/** A test written by hand: who calls, and what must happen. It runs like the others, 3 times. */
export function NewTestCard({ names, into, onAdd, onClose }: NewProps) {
  const [name, setName] = useState('')
  const [caller, setCaller] = useState('')
  const [checks, setChecks] = useState('')
  const [adding, setAdding] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const lines = checks
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
  const ready = name.trim() !== '' && caller.trim() !== '' && lines.length > 0 && !adding
  const add = async () => {
    if (!ready) return
    setAdding(true)
    setProblem(null)
    try {
      await onAdd({ name: name.trim(), caller: caller.trim(), checks: lines })
    } catch (error) {
      setProblem((error as Error).message)
      setAdding(false)
    }
  }
  return (
    <section aria-label="New test" className={card}>
      <Header
        icon={<Plus className="mt-px size-4 shrink-0 text-muted-foreground" />}
        title="New test"
        sub={`A simulated call, run 3 times on every change · goes into ${into}`}
        onClose={onClose}
      />
      <div className="min-h-0 flex-1 space-y-3 overflow-auto px-4 py-3">
        <label className="block space-y-1">
          <span className={label}>Name</span>
          <input autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="Asks for a home visit" className={field} />
        </label>
        <label className="block space-y-1">
          <span className={label}>The caller</span>
          <textarea
            rows={3}
            value={caller}
            onChange={(e) => setCaller(e.target.value)}
            placeholder="Who calls, what they want, and how they behave."
            className={cn(field, 'field-sizing-content min-h-16 resize-none')}
          />
        </label>
        <label className="block space-y-1">
          <span className={label}>Checks · one per line</span>
          <textarea
            rows={3}
            value={checks}
            onChange={(e) => setChecks(e.target.value)}
            placeholder={'Says the clinic does no home visits\nEnds the call'}
            className={cn(field, 'field-sizing-content min-h-16 resize-none')}
          />
          <span className="block text-[11.5px] leading-snug text-muted-foreground">
            “Reaches …” a step, “Ends the call” and “… is recorded” for a field an edge collects are checked on the
            steps the call goes through; anything else is judged on what was said.
          </span>
        </label>
        {lines.length > 0 && (
          <ul aria-label="How each check is decided" className="space-y-1">
            {lines.map((line, i) => (
              <li key={i} className="flex items-start gap-2 text-[12.5px] leading-snug">
                <span className="min-w-0 flex-1">{line}</span>
                <CheckKind kind={checkKind(line, names)} />
              </li>
            ))}
          </ul>
        )}
        {problem && (
          <p role="alert" className="text-[12.5px] text-bad">
            {problem}
          </p>
        )}
      </div>
      <div className="flex items-center justify-end gap-2 border-t bg-muted/30 px-4 py-2.5">
        <Button size="sm" variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button size="sm" disabled={!ready} onClick={() => void add()}>
          {adding ? 'Adding…' : 'Add test'}
        </Button>
      </div>
    </section>
  )
}
