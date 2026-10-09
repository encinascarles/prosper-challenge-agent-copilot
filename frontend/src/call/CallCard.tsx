// The card of a test call, floating over the canvas at the bottom right: the
// call's status, the steps it has taken through the graph, and what was said.
//
// Over the canvas and not beside it: the graph is where the call is read, and
// a side panel would take a third of it. The canvas fits the graph into the
// space this card leaves when a call starts.

import { PhoneOff } from 'lucide-react'
import { useEffect, useRef } from 'react'

import { Button } from '@/components/ui/button'
import { humanize } from '@/draft/names'
import { cn } from '@/lib/utils'

import { clock, collectedAt, currentNode, elapsed, type Call } from './path'
import { useNow } from './useCall'

type Props = {
  call: Call
  onEnd: () => void
  onAgain: () => void
  onClose: () => void
  /** A step was clicked: bring that node's card into view. */
  onShow: (node: string) => void
}

export function CallCard({ call, onEnd, onAgain, onClose, onShow }: Props) {
  const over = call.status === 'ended' || call.status === 'failed'
  const now = useNow(call.status === 'live')
  const current = currentNode(call)
  // The transcript follows what was said last, as a chat does.
  const newest = useRef<HTMLDivElement>(null)
  const said = call.lines.at(-1)?.text.length ?? 0
  useEffect(() => {
    newest.current?.scrollIntoView({ block: 'end', behavior: 'smooth' })
  }, [call.lines.length, said])

  return (
    <section
      aria-label="Test call"
      className="absolute right-4 bottom-4 z-20 flex max-h-[calc(100%-2rem)] w-[360px] flex-col overflow-hidden rounded-2xl border bg-card shadow-[0_18px_50px_-18px_rgba(0,0,0,0.35)]"
    >
      <header className="flex items-center gap-2.5 border-b px-4 py-3">
        <span
          className={cn(
            'size-2 shrink-0 rounded-full',
            call.status === 'failed' ? 'bg-bad' : over ? 'bg-muted-foreground' : 'call-blink bg-brand',
          )}
        />
        <div className="min-w-0 flex-1">
          <div className="text-[13px] font-semibold">
            {call.status === 'failed' ? "Call didn't work" : over ? 'Call ended' : 'Test call'}
            {call.startedAt !== null && (
              <span className="font-normal text-muted-foreground tabular-nums">
                {' '}
                · {clock(elapsed(call, now))}
              </span>
            )}
          </div>
          <div className="truncate text-[11.5px] text-muted-foreground" aria-live="polite">
            {call.status === 'connecting' ? (
              'Connecting…'
            ) : current ? (
              <>
                Now in <span className="font-medium text-foreground">{humanize(current)}</span>
              </>
            ) : call.steps.length === 0 ? (
              'It never started'
            ) : (
              `${call.steps.length} ${call.steps.length === 1 ? 'step' : 'steps'}`
            )}
          </div>
        </div>
        {over ? (
          <>
            <Button size="sm" variant="outline" onClick={onAgain}>
              Again
            </Button>
            <Button size="sm" onClick={onClose}>
              Close
            </Button>
          </>
        ) : (
          <Button size="sm" onClick={onEnd}>
            <PhoneOff className="size-3.5" /> End
          </Button>
        )}
      </header>
      {call.problem && (
        <p role="alert" className="border-b border-bad/20 bg-bad/10 px-4 py-2.5 text-[12.5px] leading-snug text-bad">
          {call.problem}
        </p>
      )}
      {call.steps.length > 0 && (
        <ol className="max-h-[38%] shrink-0 space-y-0.5 overflow-auto border-b px-2 py-2">
          {call.steps.map((step, index) => {
            const here = index === call.steps.length - 1 && current !== null
            const collected = Object.entries(collectedAt(call, index))
            return (
              <li key={index}>
                <button
                  onClick={() => onShow(step.node)}
                  className="flex w-full items-start gap-2.5 rounded-lg px-2 py-1.5 text-left outline-none hover:bg-muted focus-visible:bg-muted"
                >
                  <span
                    className={cn(
                      'mt-px flex size-[18px] shrink-0 items-center justify-center rounded-full text-[10px] font-semibold',
                      here ? 'bg-brand text-white' : 'bg-foreground text-background',
                    )}
                  >
                    {index + 1}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex items-baseline gap-2 text-[12.5px] font-medium">
                      <span className="truncate">{humanize(step.node)}</span>
                      <span className="ml-auto text-[11px] font-normal text-muted-foreground tabular-nums">
                        {clock(step.at)}
                      </span>
                    </span>
                    {collected.length > 0 && (
                      <span className="mt-0.5 flex flex-wrap gap-1">
                        {collected.map(([name, value]) => (
                          <span key={name} className="max-w-full truncate rounded-full bg-muted px-1.5 py-px text-[10.5px]">
                            <span className="text-muted-foreground">{humanize(name)}</span>{' '}
                            <span className="font-medium">{value}</span>
                          </span>
                        ))}
                      </span>
                    )}
                  </span>
                </button>
              </li>
            )
          })}
        </ol>
      )}
      {(call.lines.length > 0 || !over) && (
        <div className="min-h-0 flex-1 space-y-2 overflow-auto px-4 py-3" aria-label="Transcript">
          {call.lines.length === 0 && (
            <div className="text-[12px] text-muted-foreground">
              {call.status === 'connecting' ? 'Connecting…' : 'Nothing said yet.'}
            </div>
          )}
          {call.lines.map((line, index) => (
            <div key={index} className={cn('flex', line.who === 'caller' && 'justify-end')}>
              <div
                className={cn(
                  'max-w-[85%] rounded-2xl px-3 py-1.5 text-[12.5px] leading-snug',
                  line.who === 'agent'
                    ? 'rounded-tl-md bg-muted'
                    : 'rounded-tr-md bg-foreground text-background',
                )}
              >
                {line.text}
              </div>
            </div>
          ))}
          <div ref={newest} />
        </div>
      )}
    </section>
  )
}
