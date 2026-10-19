// The Checks tab of a pull request: every test of its copy, with how its runs
// went on the latest run, those it added first. A row opens to the test's
// checks and runs. While the run goes, the rows fill in as calls finish. Each
// test runs again on its own from its row; the others keep their results.

import { ChevronDown, CircleCheck, CircleX, Loader2, RotateCw } from 'lucide-react'
import { useState } from 'react'

import type { Pull, SuiteRun } from '@/agents/types'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { ScoreText, TestIcon } from '@/suite/bits'
import { addedIn, beforeAfter, isFixTest, namesOf, orderTests, progress, resultsOf, score, summarize, verdict } from '@/suite/model'
import { TestResults } from '@/suite/TestResults'

import { pullLabel } from './model'

type Props = {
  pull: Pull
  run: SuiteRun | null | undefined
  onRerun: () => void
  onRunOne: (test: string) => void
}

export function PullChecks({ pull, run, onRerun, onRunOne }: Props) {
  const [open, setOpen] = useState<string | null>(null)
  const [selected, setSelected] = useState(0)
  if (run === undefined) return <p className="py-10 text-center text-[13px] text-muted-foreground">Loading…</p>
  const checks = summarize(run)
  const repeats = run?.repeats ?? 3
  const results = resultsOf(run)
  const canRun = pull.state === 'open'
  if (pull.tests.length === 0) {
    return (
      <p className="py-10 text-center text-[13px] text-muted-foreground">
        No tests yet. Add one in Build: every test runs 3 times on each change, and a merge waits for them to pass.
      </p>
    )
  }
  const head =
    checks === null
      ? 'Not run yet'
      : checks.state === 'running'
        ? `Running · ${progress(run!).done} of ${progress(run!).of} calls`
        : checks.state === 'stopped'
          ? "Didn't finish"
          : checks.failing
            ? `${checks.failing} of ${checks.total} failing`
            : checks.flaky
              ? `Checks pass · ${checks.flaky} flaky, not blocking`
              : 'All checks passed'
  return (
    <div className="overflow-hidden rounded-xl border bg-card">
      <div className="flex items-center gap-2 border-b bg-muted/30 px-4 py-2.5">
        {checks?.state === 'running' ? (
          <Loader2 className="size-4 animate-spin text-brand" />
        ) : checks?.state === 'passed' ? (
          <CircleCheck className="size-4 text-emerald-600" />
        ) : (
          <CircleX className={cn('size-4', checks ? 'text-bad' : 'text-muted-foreground')} />
        )}
        <span className="text-[13px] font-medium tabular-nums">{head}</span>
        <span className="text-[12.5px] text-muted-foreground tabular-nums">
          · {pull.tests.length} {pull.tests.length === 1 ? 'test' : 'tests'} · {repeats} runs each · simulated, in text
        </span>
        {canRun && (
          <Button
            size="sm"
            variant="outline"
            className="ml-auto h-7 bg-card text-[12.5px]"
            disabled={checks?.state === 'running'}
            onClick={onRerun}
          >
            <RotateCw className="size-3.5" /> Run again
          </Button>
        )}
      </div>
      {orderTests(pull.tests, pull.number).map((test) => {
        const result = results.get(test.id)
        const s = result && run ? score(result, repeats) : null
        const expanded = open === test.id
        const going = checks?.state === 'running'
        const mine = going && s !== null && verdict(s) === 'running'
        return (
          <div key={test.id} className="group/test relative border-b last:border-b-0">
            <button
              aria-expanded={expanded}
              onClick={() => {
                setOpen(expanded ? null : test.id)
                setSelected(0)
              }}
              className={cn(
                'flex w-full items-center gap-2.5 px-4 py-2 text-left hover:bg-muted/40',
                canRun && 'pr-[140px]',
                expanded && 'bg-muted/40',
              )}
            >
              <TestIcon score={s} />
              <span className="text-[13px] font-medium">{test.name}</span>
              <span className="min-w-0 flex-1 truncate text-[12.5px] text-muted-foreground">
                {isFixTest(test) ? (
                  <span className="font-medium text-brand tabular-nums">new · {beforeAfter(test, null)}</span>
                ) : addedIn(test, pull.number) ? (
                  <span className="font-medium text-brand">new · added in {pullLabel(pull.number)}</span>
                ) : test.source.pull ? (
                  `from ${pullLabel(test.source.pull)}`
                ) : (
                  `${test.checks.length} checks`
                )}
              </span>
              <ScoreText score={s} className="text-[12.5px]" />
              <ChevronDown className={cn('size-3.5 shrink-0 text-muted-foreground transition-transform', !expanded && '-rotate-90')} />
            </button>
            {canRun && (
              // Beside the row's button, not in it: a button cannot hold another.
              <button
                disabled={going}
                title={going ? 'Waits for the tests running now' : 'Runs it 3 times; the other tests keep their results'}
                onClick={() => onRunOne(test.id)}
                className={cn(
                  'absolute top-1.5 right-4 flex h-7 items-center gap-1 rounded-md border bg-card px-2 text-[12px] font-medium text-muted-foreground hover:text-foreground disabled:opacity-40',
                  !expanded && 'opacity-0 group-hover/test:opacity-100 focus-visible:opacity-100',
                  mine && 'opacity-100',
                )}
              >
                <RotateCw className={cn('size-3', mine && 'animate-spin')} />
                {mine ? 'Running…' : 'Run this test'}
              </button>
            )}
            {expanded && (
              <div className="border-t bg-muted/20 pl-[26px]">
                <TestResults test={test} names={namesOf(pull.config)} result={result} repeats={repeats} selected={selected} onSelect={setSelected} />
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
