// Writing to Prosper AI, at the bottom of the conversation of any open pull
// request: the answer to its question in your own words, or a change to make
// ("make the greeting shorter", "if they don't know it, use their phone"). Prosper AI changes the pull request's
// copy, says what it changed, and the checks run again. While it works on
// something, it takes nothing new.

import { ArrowUp } from 'lucide-react'
import { useState } from 'react'

import type { Pull } from '@/agents/types'

import { openQuestions } from './model'
import { Avatar } from './parts'

export function Composer({ pull, onSend }: { pull: Pull; onSend: (text: string) => Promise<void> }) {
  const [text, setText] = useState('')
  const [sending, setSending] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const working = pull.prosper?.state === 'working'
  const asking = openQuestions(pull.events).length > 0
  const ready = text.trim() !== '' && !working && !sending

  const send = async () => {
    if (!ready) return
    setSending(true)
    setProblem(null)
    try {
      await onSend(text.trim())
      setText('')
    } catch (failure) {
      setProblem((failure as Error).message)
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="relative mt-6 flex gap-2.5">
      <Avatar who="you" />
      <div className="min-w-0 flex-1">
        <div className="rounded-xl border bg-background px-3 py-2 focus-within:border-foreground/30">
          <div className="flex items-end gap-2">
            <textarea
              aria-label="Write to Prosper AI"
              disabled={working}
              value={text}
              onChange={(event) => setText(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault()
                  void send()
                }
              }}
              rows={2}
              placeholder={
                working ? 'Prosper AI is working on it…' : asking ? 'Or write your answer…' : 'Ask Prosper AI for a change…'
              }
              className="field-sizing-content max-h-32 min-h-[40px] min-w-0 flex-1 resize-none bg-transparent py-0.5 text-[13px] leading-relaxed outline-none placeholder:text-muted-foreground"
            />
            <button
              onClick={() => void send()}
              disabled={!ready}
              aria-label="Send"
              className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-foreground text-background disabled:opacity-25"
            >
              <ArrowUp className="size-4" />
            </button>
          </div>
        </div>
        <p className={problem ? 'mt-1.5 text-[12px] text-bad' : 'mt-1.5 text-[11.5px] text-muted-foreground'}>
          {problem ?? 'Prosper AI changes this pull request and runs every test again.'}
        </p>
      </div>
    </div>
  )
}
