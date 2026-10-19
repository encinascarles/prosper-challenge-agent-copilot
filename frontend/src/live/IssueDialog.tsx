// Reporting an issue by hand: what the clinic complained about, or what the
// person noticed, as an issue like the ones Prosper AI finds in calls. A title
// and what happened are enough; the step, the severity and the calls that show
// it are optional ("Not sure" is an answer). The same form edits a reported
// issue later: its calls can be added to, never taken away.

import { Check, ChevronDown, X } from 'lucide-react'
import { useEffect, useState } from 'react'

import { getVersion, listCalls } from '@/agents/api'
import type { Agent } from '@/agents/types'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuRadioGroup, DropdownMenuRadioItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { humanize } from '@/draft/names'
import { cn } from '@/lib/utils'

import { callMeta, SEVERITIES } from './model'
import type { CallSummary, Issue, IssueReport, Reporter, Severity } from './types'

const CALLS_SHOWN = 8 // the latest: older ones are a Calls page away

type Props = {
  agent: Agent
  /** The issue being edited; none for a new one. */
  issue?: Issue
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Saves it. A failure is shown here and the dialog stays. */
  onSave: (report: IssueReport) => Promise<void>
}

export function IssueDialog({ open, onOpenChange, ...props }: Props) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="gap-0 p-0 sm:max-w-[600px]" showCloseButton={false}>
        <IssueForm {...props} onCancel={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  )
}

// Its own component, so it starts from the issue each time the dialog opens.
function IssueForm({ agent, issue, onSave, onCancel }: Omit<Props, 'open' | 'onOpenChange'> & { onCancel: () => void }) {
  const [reported, setReported] = useState<Reporter>(issue?.reported ?? 'you')
  const [title, setTitle] = useState(issue?.title ?? '')
  const [description, setDescription] = useState(issue?.description ?? '')
  const [step, setStep] = useState(issue?.step ?? '')
  const [severity, setSeverity] = useState<Severity | null>(issue?.severity ?? null)
  const [picked, setPicked] = useState<number[]>([])
  const [steps, setSteps] = useState<string[]>([])
  const [calls, setCalls] = useState<CallSummary[] | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const linked = new Set(issue?.findings.map((found) => found.call))
  const ready = title.trim() !== '' && description.trim() !== '' && !saving

  useEffect(() => {
    // The steps a call can go wrong in are the live version's.
    getVersion(agent.id, agent.live_version).then(
      (version) => setSteps(version.config.nodes.map((node) => node.name)),
      () => setSteps([]),
    )
    listCalls(agent.id).then(
      (page) => setCalls(page.calls.slice(0, CALLS_SHOWN)),
      () => setCalls([]),
    )
  }, [agent.id, agent.live_version])

  const save = async () => {
    if (!ready) return
    setSaving(true)
    setError(null)
    try {
      await onSave({ title: title.trim(), description: description.trim(), step, severity, reported, calls: picked })
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure))
      setSaving(false)
    }
  }

  const label = 'text-[13px] font-medium'
  const field = 'h-9 w-full rounded-lg border bg-background px-3 text-[14px] outline-none focus:border-foreground/40'
  const menu =
    'flex h-9 w-full items-center gap-1 rounded-lg border bg-background px-3 text-left text-[13.5px] outline-none focus-visible:border-foreground/40 data-[state=open]:border-foreground/40'

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        void save()
      }}
    >
      <div className="flex items-center px-6 pt-5 pb-4">
        <DialogTitle className="text-[16px] font-semibold">{issue ? 'Edit issue' : 'New issue'}</DialogTitle>
        <DialogDescription className="sr-only">Report something that goes wrong in the agent's calls.</DialogDescription>
        <button type="button" aria-label="Close" onClick={onCancel} className="ml-auto rounded-md p-1 text-muted-foreground hover:bg-muted">
          <X className="size-4" />
        </button>
      </div>
      <div className="space-y-4 px-6 pb-5">
        {!issue && (
          <div role="radiogroup" aria-label="Who flagged it" className="flex w-fit rounded-lg border bg-muted/40 p-0.5 text-[13px]">
            {(
              [
                ['you', 'You noticed it'],
                ['clinic', 'The clinic flagged it'],
              ] as [Reporter, string][]
            ).map(([value, text]) => (
              <button
                key={value}
                type="button"
                role="radio"
                aria-checked={reported === value}
                onClick={() => setReported(value)}
                className={cn(
                  'h-7 rounded-md px-3',
                  reported === value ? 'bg-background font-medium shadow-xs ring-1 ring-border' : 'text-muted-foreground hover:text-foreground',
                )}
              >
                {text}
              </button>
            ))}
          </div>
        )}
        <label className="block space-y-1.5">
          <span className={label}>Title</span>
          <input
            autoFocus
            value={title}
            maxLength={120}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="e.g. Books appointments on Sundays"
            className={field}
          />
        </label>
        <label className="block space-y-1.5">
          <span className={label}>What happened</span>
          <textarea
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder={reported === 'clinic' ? 'Paste what the clinic wrote, as it is.' : 'What the agent did, and what it should have done.'}
            rows={5}
            className="block w-full resize-none rounded-lg border bg-background px-3 py-2.5 text-[13px] leading-relaxed outline-none focus:border-foreground/40"
          />
        </label>
        <div className="flex gap-3">
          <div className="flex-1 space-y-1.5">
            <div className={label}>Step</div>
            <DropdownMenu>
              <DropdownMenuTrigger aria-label="Step" className={menu}>
                <span className={cn('flex-1 truncate', !step && 'text-muted-foreground')}>{step ? humanize(step) : 'Not sure'}</span>
                <ChevronDown className="size-3.5 text-muted-foreground" />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-[var(--radix-dropdown-menu-trigger-width)]">
                <DropdownMenuRadioGroup value={step} onValueChange={setStep}>
                  <DropdownMenuRadioItem value="" className="text-[13px]">
                    Not sure
                  </DropdownMenuRadioItem>
                  {steps.map((name) => (
                    <DropdownMenuRadioItem key={name} value={name} className="text-[13px]">
                      {humanize(name)}
                    </DropdownMenuRadioItem>
                  ))}
                </DropdownMenuRadioGroup>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
          <div className="flex-1 space-y-1.5">
            <div className={label}>Severity</div>
            <DropdownMenu>
              <DropdownMenuTrigger aria-label="Severity" className={menu}>
                <span className={cn('flex-1', !severity && 'text-muted-foreground')}>{severity ? SEVERITIES[severity] : 'Not sure'}</span>
                <ChevronDown className="size-3.5 text-muted-foreground" />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-[var(--radix-dropdown-menu-trigger-width)]">
                <DropdownMenuRadioGroup value={severity ?? ''} onValueChange={(value) => setSeverity((value || null) as Severity | null)}>
                  <DropdownMenuRadioItem value="" className="text-[13px]">
                    Not sure
                  </DropdownMenuRadioItem>
                  {(Object.keys(SEVERITIES) as Severity[]).map((key) => (
                    <DropdownMenuRadioItem key={key} value={key} className="text-[13px]">
                      {SEVERITIES[key]}
                    </DropdownMenuRadioItem>
                  ))}
                </DropdownMenuRadioGroup>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
        <div className="space-y-1.5">
          <div className={label}>
            Calls that show it <span className="font-normal text-muted-foreground">· optional</span>
          </div>
          <div className="max-h-[188px] divide-y overflow-auto rounded-lg border">
            {calls === null ? (
              <p className="px-3 py-2.5 text-[12.5px] text-muted-foreground">Loading…</p>
            ) : calls.length === 0 ? (
              <p className="px-3 py-2.5 text-[12.5px] text-muted-foreground">No calls yet.</p>
            ) : (
              calls.map((call) => {
                const on = linked.has(call.id) || picked.includes(call.id)
                return (
                  <button
                    key={call.id}
                    type="button"
                    role="checkbox"
                    aria-checked={on}
                    disabled={linked.has(call.id)}
                    onClick={() => setPicked((now) => (now.includes(call.id) ? now.filter((id) => id !== call.id) : [...now, call.id]))}
                    className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-[13px] outline-none hover:bg-muted/40 focus-visible:bg-muted/40 disabled:opacity-60"
                  >
                    <span
                      className={cn(
                        'flex size-4 shrink-0 items-center justify-center rounded border',
                        on && 'border-foreground bg-foreground text-background',
                      )}
                    >
                      {on && <Check className="size-3" />}
                    </span>
                    <span className="font-medium">{call.caller}</span>
                    <span className="truncate text-[12.5px] text-muted-foreground tabular-nums">{callMeta(call)}</span>
                  </button>
                )
              })
            )}
          </div>
        </div>
        {error && (
          <p role="alert" className="text-[13px] text-bad">
            {error}
          </p>
        )}
      </div>
      <div className="flex items-center gap-3 border-t bg-muted/30 px-6 py-3.5">
        <p className="min-w-0 flex-1 text-[12.5px] leading-snug text-muted-foreground">
          {issue ? '' : 'Prosper AI can tidy it and fix it once it is open.'}
        </p>
        <Button type="button" variant="outline" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" disabled={!ready}>
          {saving ? 'Saving…' : issue ? 'Save' : 'Open issue'}
        </Button>
      </div>
    </form>
  )
}
