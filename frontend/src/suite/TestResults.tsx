// What one test is and how it went: who calls, each check with how many runs
// passed it, and the runs themselves (how each ended, the steps it went
// through, what was said). Shared by the test card over the graph and the
// Checks tab of a pull request.
//
// A check is marked by how it is decided: "on the path" ones exactly from the
// steps the call went through, "judged" ones by a model reading the
// transcript, whose one-line reason is shown when it fails.

import { Route, Scale } from 'lucide-react'

import type { CheckResult, Test, TestRun } from '@/agents/types'
import { humanize } from '@/draft/names'
import { cn } from '@/lib/utils'

import { ScoreText, TestIcon } from './bits'
import { checkKind, endedText, tokensOf, type Names } from './model'

export const label = 'text-[11px] font-medium tracking-wide text-muted-foreground uppercase'

/** How a check line is decided, in a muted word: on the call's path, or judged on what was said. */
export function CheckKind({ kind }: { kind: CheckResult['kind'] }) {
  const judged = kind === 'judged'
  return (
    <span
      className="flex shrink-0 items-center gap-1 text-[11px] whitespace-nowrap text-muted-foreground"
      title={judged ? 'Judged by a model on what was said' : 'Decided from the steps the call went through'}
    >
      {judged ? <Scale className="size-3" /> : <Route className="size-3" />}
      {judged ? 'judged' : 'on the path'}
    </span>
  )
}

type Props = {
  test: Test
  /** The copy's steps and fields: what tells a path check from a judged one before it runs. */
  names: Names
  result: TestRun | undefined
  repeats: number
  /** The run shown, by index. */
  selected: number
  onSelect: (index: number) => void
  /** A step of the run was clicked: show that node. */
  onShowNode?: (node: string) => void
}

export function TestResults({ test, names, result, repeats, selected, onSelect, onShowNode }: Props) {
  const runs = result?.runs ?? []
  const run = runs[selected] ?? null
  return (
    <>
      <div className="border-b px-4 py-3">
        <div className={cn(label, 'mb-1')}>The caller</div>
        <p className="text-[13px] leading-snug">{test.caller}</p>
      </div>
      <div className="border-b px-4 py-3">
        <div className={cn(label, 'mb-1.5')}>Checks</div>
        {test.checks.map((text, i) => {
          const done = runs.map((r) => r.checks[i]).filter(Boolean)
          const passed = done.filter((check) => check.pass).length
          const failed = done.find((check) => !check.pass)
          const kind = done[0]?.kind ?? checkKind(text, names)
          return (
            <div key={i} className="mb-1.5 flex items-start gap-2 text-[13px]">
              <TestIcon
                className="mt-px"
                score={result ? { passed, done: done.length, of: repeats } : null}
              />
              <div className="min-w-0 flex-1 leading-snug">
                {text}
                {failed?.detail && (
                  <div className="line-clamp-2 text-[12px] text-bad" title={failed.detail}>
                    {failed.detail}
                  </div>
                )}
              </div>
              {done.length > 0 && passed < done.length && (
                <ScoreText className="text-[11.5px]" score={{ passed, done: done.length, of: done.length }} />
              )}
              <CheckKind kind={kind} />
            </div>
          )
        })}
      </div>
      <div className="px-4 py-3">
        <div className="mb-2 flex items-center gap-1.5">
          <span className={label}>Runs</span>
          <div role="tablist" className="ml-auto flex gap-1">
            {Array.from({ length: repeats }, (_, i) => {
              const r = runs[i]
              return (
                <button
                  key={i}
                  role="tab"
                  aria-selected={selected === i}
                  disabled={!r}
                  onClick={() => onSelect(i)}
                  className={cn(
                    'flex h-6 items-center gap-1 rounded-md px-2 text-[12px] tabular-nums outline-none focus-visible:ring-2 focus-visible:ring-ring/50 disabled:opacity-50',
                    selected === i ? 'bg-foreground text-background' : 'bg-muted hover:bg-muted/70',
                  )}
                >
                  {r ? (
                    <span className={cn('size-1.5 rounded-full', r.passed ? 'bg-emerald-500' : 'bg-bad')} />
                  ) : null}
                  Run {i + 1}
                </button>
              )
            })}
          </div>
        </div>
        {run === null ? (
          <p className="text-[12.5px] text-muted-foreground">{result ? 'Running…' : 'Not run yet.'}</p>
        ) : (
          <>
            <p className="text-[12px] text-muted-foreground tabular-nums">
              {endedText(run.ended)} · {run.seconds.toFixed(1)} s · {tokensOf(run).toLocaleString('en-US')} tokens
            </p>
            {run.path.length > 0 && (
              <ol className="mt-2 flex flex-wrap items-center gap-1 text-[12px]">
                {run.path.map((step, i) => (
                  <li key={i} className="flex items-center gap-1">
                    {i > 0 && <span className="text-muted-foreground">→</span>}
                    <button
                      disabled={!onShowNode}
                      onClick={() => onShowNode?.(step.node)}
                      className="rounded-full border bg-card px-2 py-px enabled:hover:border-foreground/30"
                    >
                      {humanize(step.node)}
                    </button>
                  </li>
                ))}
              </ol>
            )}
            <div className="mt-3 space-y-2" aria-label="Transcript">
              {run.transcript.map((line, i) => (
                <div key={i} className={cn('flex', line.role === 'caller' && 'justify-end')}>
                  <div
                    className={cn(
                      'max-w-[85%] rounded-2xl px-3 py-1.5 text-[12.5px] leading-snug',
                      line.role === 'agent' ? 'rounded-tl-md bg-muted' : 'rounded-tr-md bg-foreground text-background',
                    )}
                  >
                    {line.text}
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </>
  )
}
