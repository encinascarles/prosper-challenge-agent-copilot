// The rail at the left of the graph: the agent's rules and its tests.
//
// Rules are short instructions added to the agent's prompt, on every step or
// on one; they are listed by where they apply. Tests are simulated calls with
// checks; each shows its score on the copy the editor is on (3/3, 2/3…), and
// opens its card over the graph. Both are added here, to the pull request the
// editor is on, or (on live) to the one the first addition opens, like an
// edit. Those added in this pull request say so and can be taken out again.
// A rule Prosper AI wrote says where it came from: the line of the guidelines
// it quotes, word for word, or the answer or request it was made from.

import { BookOpen, Globe, Plus, RotateCw, Trash2 } from 'lucide-react'
import { useState } from 'react'

import type { Rule, Suite, SuiteRun, Test } from '@/agents/types'
import { humanize } from '@/draft/names'
import { cn } from '@/lib/utils'
import { sourceText } from '@/prosper/model'
import { pullLabel } from '@/pulls/model'

import { ScoreText, TestIcon } from './bits'
import { addedIn, orderTests, progress, resultsOf, rulesByStep, score, summarize } from './model'

const heading =
  'flex items-center gap-1.5 px-4 pt-4 pb-1.5 text-[11px] font-medium tracking-wide text-muted-foreground uppercase'
const addButton =
  'flex h-6 items-center gap-1 rounded-md px-1.5 text-[11.5px] font-medium tracking-normal normal-case text-muted-foreground hover:bg-muted hover:text-foreground disabled:pointer-events-none disabled:opacity-40'
const field =
  'w-full rounded-md border bg-background px-2 py-1.5 text-[12.5px] leading-snug outline-none focus:border-foreground/40'

/** A rule written by hand: where it applies, and what it says. Enter adds it. */
function RuleForm({ steps, into, onAdd, onDone }: {
  steps: string[]
  into: string
  onAdd: (step: string | null, text: string) => Promise<void>
  onDone: () => void
}) {
  const [step, setStep] = useState('')
  const [text, setText] = useState('')
  const [adding, setAdding] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const add = async () => {
    if (!text.trim() || adding) return
    setAdding(true)
    setProblem(null)
    try {
      await onAdd(step || null, text.trim())
      onDone()
    } catch (error) {
      setProblem((error as Error).message)
      setAdding(false)
    }
  }
  return (
    <div className="mx-2 mb-2 space-y-1.5 rounded-lg border bg-card p-2">
      <select aria-label="Applies to" value={step} onChange={(e) => setStep(e.target.value)} className={field}>
        <option value="">Every step</option>
        {steps.map((name) => (
          <option key={name} value={name}>
            {humanize(name)}
          </option>
        ))}
      </select>
      <textarea
        aria-label="Rule"
        autoFocus
        rows={2}
        value={text}
        placeholder="What the agent must always do here…"
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            void add()
          }
          if (e.key === 'Escape') onDone()
        }}
        className={cn(field, 'field-sizing-content resize-none')}
      />
      {problem && <p className="text-[12px] text-bad">{problem}</p>}
      <div className="flex items-center gap-1.5">
        <span className="min-w-0 flex-1 truncate text-[11px] text-muted-foreground">Goes into {into}</span>
        <button onClick={onDone} className="h-7 rounded-md px-2 text-[12px] text-muted-foreground hover:bg-muted">
          Cancel
        </button>
        <button
          disabled={!text.trim() || adding}
          onClick={() => void add()}
          className="h-7 rounded-md bg-foreground px-2.5 text-[12px] font-medium text-background disabled:opacity-35"
        >
          {adding ? 'Adding…' : 'Add rule'}
        </button>
      </div>
    </div>
  )
}

/** The line a rule came from, under it: a quote of the guidelines, or your answer. */
function Quote({ rule }: { rule: Rule }) {
  const { source } = rule
  if (!source.quote || source.kind === 'manual') return null
  if (source.kind === 'guidelines') {
    return (
      <p
        title={`From ${sourceText(source)}`}
        className="mt-1 rounded-sm border-l-2 border-foreground/20 bg-background/70 px-2 py-1 text-[11.5px] leading-snug text-foreground/75"
      >
        <BookOpen className="mr-1 inline size-3 align-[-2px] text-muted-foreground" />“{source.quote}”
        <span className="text-muted-foreground"> · {sourceText(source)}</span>
      </p>
    )
  }
  return (
    <p className="mt-1 text-[11.5px] leading-snug text-muted-foreground">
      {sourceText(source)}: <span className="text-foreground/75">“{source.quote}”</span>
    </p>
  )
}

/** Where a rule or test came from, when it says something: added here, or by an earlier pull request. */
function origin(item: Rule | Test, on: number | null): React.ReactNode {
  if (addedIn(item, on)) return <span className="font-medium text-brand">Added in {pullLabel(on ?? 0)}</span>
  return item.source.pull ? `From ${pullLabel(item.source.pull)}` : null
}

type Props = {
  suite: Suite
  steps: string[] // the agent's node names, in order
  /** The pull request the editor is on, or null for live. */
  on: number | null
  /** The latest run of this copy's tests; null if none ran, undefined while it loads. */
  run: SuiteRun | null | undefined
  /** Where an addition goes: "PR #2", or "a new pull request" on live. */
  into: string
  /** Why nothing can be added now, or null. */
  blocked: string | null
  openTest: string | null
  onOpenTest: (id: string | null) => void
  onNewTest: () => void
  onAddRule: (step: string | null, text: string) => Promise<void>
  onRemoveRule: (rule: Rule) => void
  onRerun: () => void
}

export function SuiteRail(props: Props) {
  const { suite, steps, on, run, into, blocked, openTest, onOpenTest, onNewTest, onAddRule, onRemoveRule, onRerun } = props
  const [writing, setWriting] = useState(false)
  const checks = summarize(run ?? null)
  const results = resultsOf(run)
  const repeats = run?.repeats ?? 3
  const groups = rulesByStep(suite.rules, steps)
  const running = checks?.state === 'running'
  const done = run && running ? progress(run) : null
  return (
    <aside aria-label="Rules and tests" className="flex w-[300px] shrink-0 flex-col overflow-hidden border-r bg-card">
      <div className="min-h-0 flex-1 overflow-auto pb-4">
        <div className={heading}>
          Rules <span className="font-normal tracking-normal normal-case">· added to the prompt</span>
          <button
            disabled={blocked !== null}
            title={blocked ?? `Goes into ${into}`}
            onClick={() => setWriting(true)}
            className={cn(addButton, 'ml-auto')}
          >
            <Plus className="size-3" /> Add
          </button>
        </div>
        {writing && blocked === null && (
          <RuleForm steps={steps} into={into} onAdd={onAddRule} onDone={() => setWriting(false)} />
        )}
        {groups.length === 0 && !writing && <p className="px-4 text-[12.5px] text-muted-foreground">No rules yet.</p>}
        {groups.map(({ step, rules }) => (
          <div key={step ?? ''} className="mx-2 px-2 py-1.5">
            <div className="flex items-center gap-1.5 px-0.5 pb-1 text-[12px] font-medium">
              {step === null ? (
                <>
                  <Globe className="size-3 text-muted-foreground" /> Every step
                </>
              ) : (
                humanize(step)
              )}
            </div>
            {rules.map((rule) => {
              const mine = addedIn(rule, on)
              const from = origin(rule, on)
              return (
                <div
                  key={rule.id}
                  className={cn(
                    'group/rule relative mb-1 rounded-md border px-2.5 py-1.5',
                    mine ? 'border-brand/40 bg-brand-tint' : 'border-transparent bg-muted/50',
                  )}
                >
                  <div className={cn('text-[12.5px] leading-snug', mine && 'pr-5')}>{rule.text}</div>
                  <Quote rule={rule} />
                  {from && <div className="mt-0.5 truncate text-[11px] text-muted-foreground">{from}</div>}
                  {mine && blocked === null && (
                    <button
                      aria-label="Take this rule out"
                      title="Take it out of this pull request"
                      onClick={() => onRemoveRule(rule)}
                      className="absolute top-1.5 right-1.5 rounded p-0.5 text-muted-foreground opacity-0 group-hover/rule:opacity-100 hover:bg-background hover:text-bad focus-visible:opacity-100"
                    >
                      <Trash2 className="size-3.5" />
                    </button>
                  )}
                </div>
              )
            })}
          </div>
        ))}

        <div className={cn(heading, 'mt-3 border-t')}>
          Tests
          <span className="ml-auto font-normal tracking-normal normal-case tabular-nums">
            {done ? `Running ${done.done}/${done.of}` : checks && checks.total > 0 ? `${checks.passed}/${checks.total} pass${checks.flaky ? ` · ${checks.flaky} flaky` : ''}` : ''}
          </span>
          {suite.tests.length > 0 && (
            <button
              disabled={running || blocked !== null}
              title={running ? 'Running' : `Runs every test 3 times on ${on === null ? 'live' : pullLabel(on)}`}
              onClick={onRerun}
              className={addButton}
            >
              <RotateCw className={cn('size-3', running && 'animate-spin')} /> Run all
            </button>
          )}
          <button disabled={blocked !== null} title={blocked ?? `Goes into ${into}`} onClick={onNewTest} className={addButton}>
            <Plus className="size-3" /> Add
          </button>
        </div>
        {suite.tests.length === 0 && <p className="px-4 text-[12.5px] text-muted-foreground">No tests yet.</p>}
        {orderTests(suite.tests, on).map((test) => {
          const result = results.get(test.id)
          const s = result && run ? score(result, repeats) : null
          const from = origin(test, on)
          return (
            <button
              key={test.id}
              onClick={() => onOpenTest(openTest === test.id ? null : test.id)}
              className={cn(
                'flex w-full items-start gap-2 px-4 py-1.5 text-left outline-none hover:bg-muted/50 focus-visible:bg-muted/50',
                openTest === test.id && 'bg-muted',
              )}
            >
              <TestIcon score={s} className="mt-px" />
              <span className="min-w-0 flex-1">
                <span className="block text-[13px] leading-snug">{test.name}</span>
                <span className="block truncate text-[11.5px] text-muted-foreground">
                  {from ?? `${test.checks.length} ${test.checks.length === 1 ? 'check' : 'checks'}`}
                </span>
              </span>
              <ScoreText score={s} className="text-[11.5px]" />
            </button>
          )
        })}
      </div>
    </aside>
  )
}
