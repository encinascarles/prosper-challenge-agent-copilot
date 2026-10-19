// The pieces Prosper AI's conversation is made of, shared by a pull request's
// page and the card over the graph in Build: a turn (who, when, what), the
// progress of its steps with a spinner on the one under way, a question with
// its options as buttons, the files it read and the notes it was given.
// Orange is what Prosper AI did; everything else stays neutral.

import { Check, CircleCheck, FileText, Loader2 } from 'lucide-react'
import { useState } from 'react'

import type { FileRead, PullEvent } from '@/agents/types'
import { Mark } from '@/components/Mark'
import { cn } from '@/lib/utils'
import { when } from '@/pulls/model'

import { fileMeta, lineCount, PROSPER, statusText } from './model'

export function Avatar({ who }: { who: string }) {
  if (who === PROSPER) {
    return (
      <span className="relative z-10 flex size-[22px] shrink-0 items-center justify-center rounded-full border border-brand/40 bg-card">
        <Mark className="h-[11px]" />
      </span>
    )
  }
  return (
    <span className="relative z-10 flex size-[22px] shrink-0 items-center justify-center rounded-full bg-foreground text-[10px] font-semibold text-background">
      Y
    </span>
  )
}

/** One turn of the conversation: who, when, and what they said or did. */
export function Turn({ who, at, title, children }: { who: string; at?: string; title?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="relative flex gap-2.5">
      <Avatar who={who} />
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-1.5 text-[12.5px]">
          <span className="font-semibold">{who === 'you' ? 'You' : who}</span>
          {title && <span className="text-muted-foreground">{title}</span>}
          {at && (
            <span className="ml-auto text-[11.5px] text-muted-foreground tabular-nums" title={new Date(at).toLocaleString('en-US')}>
              {when(at)}
            </span>
          )}
        </div>
        <div className="mt-1 space-y-2">{children}</div>
      </div>
    </div>
  )
}

/** Prosper AI's steps so far, and the one under way (`doing`) with a spinner. */
export function Steps({ steps, doing }: { steps: PullEvent[]; doing: string | null }) {
  return (
    <div className="space-y-1.5">
      {steps.map((step, i) => (
        <div key={i} className="flex items-center gap-2 text-[13px]">
          <CircleCheck className="size-4 shrink-0 text-emerald-600" />
          {step.text}
        </div>
      ))}
      {doing && (
        <div className="flex items-center gap-2 text-[13px] text-brand">
          <Loader2 className="size-4 shrink-0 animate-spin" />
          {doing}…
        </div>
      )}
    </div>
  )
}

/** A question of Prosper AI's: its options as buttons, or the answer it got. */
export function Question({
  event,
  answer,
  busy,
  onPick,
}: {
  event: PullEvent
  answer: PullEvent | null
  /** The option being sent, while it is. */
  busy: number | null
  /** Pick an option; none while it cannot be answered (the pull request is closed). */
  onPick?: (option: number) => void
}) {
  return (
    <>
      <p className="text-[13px] leading-relaxed">{event.text}</p>
      {answer ? (
        <div className="inline-flex max-w-full items-center gap-1.5 rounded-md bg-muted px-2 py-1 text-[12.5px]">
          <Check className="size-3.5 shrink-0" /> <span className="min-w-0">{answer.text}</span>
        </div>
      ) : onPick ? (
        <div className="space-y-1.5">
          {(event.options ?? []).map((option, i) => (
            <button
              key={option}
              disabled={busy !== null}
              onClick={() => onPick(i)}
              className="flex min-h-9 w-full items-center gap-2 rounded-lg border bg-card px-3 py-1.5 text-left text-[13px] hover:border-foreground/40 disabled:opacity-60"
            >
              <span className="min-w-0 flex-1">{option}</span>
              {busy === i ? (
                <Loader2 className="size-3.5 shrink-0 animate-spin text-muted-foreground" />
              ) : (
                <span className="text-[12px] text-muted-foreground tabular-nums">{i + 1}</span>
              )}
            </button>
          ))}
        </div>
      ) : null}
    </>
  )
}

export function FileChips({ files }: { files: FileRead[] }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {files.map((file) => (
        <span key={file.name} className="inline-flex max-w-full items-center gap-1.5 rounded-md border bg-card px-2 py-1 text-[12px]">
          <span className="rounded border px-1 text-[9.5px] font-semibold tracking-wide text-muted-foreground">{file.kind}</span>
          <span className="truncate">{file.name}</span>
          {fileMeta(file) && <span className="shrink-0 text-muted-foreground">{fileMeta(file)}</span>}
        </span>
      ))}
    </div>
  )
}

/** The notes that were pasted, folded to one line until opened. */
export function Notes({ text }: { text: string }) {
  const [open, setOpen] = useState(false)
  return (
    <button onClick={() => setOpen((now) => !now)} className="block w-full rounded-lg border bg-card px-2.5 py-1.5 text-left">
      <span className="flex items-center gap-1.5 text-[12px] font-medium">
        <FileText className="size-3.5 text-muted-foreground" /> Your notes
        <span className="font-normal text-muted-foreground">· {lineCount(text)}</span>
        <span className="ml-auto font-normal text-muted-foreground">{open ? 'Hide' : 'Show'}</span>
      </span>
      {open && <span className="mt-1.5 block text-[12px] leading-relaxed whitespace-pre-wrap text-muted-foreground">{text}</span>}
    </button>
  )
}

/** "Prosper AI is building" or "Waiting for your answer", as the top bar shows it. */
export function Status({ status, onClick, className }: { status: 'building' | 'waiting'; onClick?: () => void; className?: string }) {
  return (
    <button
      onClick={onClick}
      title="Open the conversation"
      className={cn('flex h-8 shrink-0 items-center gap-1.5 rounded-md px-2 text-[12.5px] font-medium text-brand hover:bg-muted', className)}
    >
      {status === 'building' ? <Loader2 className="size-3.5 animate-spin" /> : <Mark className="h-[12px]" />}
      {statusText(status)}
    </button>
  )
}
