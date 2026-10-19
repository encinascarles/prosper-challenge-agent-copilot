// Prosper AI at work, over the graph in Build: the card in the corner while it
// sets up the agent. Its steps as they land, with a spinner on the one under
// way; its questions, answered right here by picking an option; and the way
// to the whole conversation, where an answer can also be written. The graph
// behind it fills in as Prosper AI draws it, and is read-only until it is done.

import { ArrowRight } from 'lucide-react'
import { useState } from 'react'

import { answerQuestion } from '@/agents/api'
import type { Pull } from '@/agents/types'
import { Mark } from '@/components/Mark'
import { pullLabel } from '@/pulls/model'

import { eventsInWords, isProsper, openQuestions } from './model'
import { Question, Steps } from './parts'

type Props = {
  agentId: string
  pull: Pull
  /** What an answer changed: the pull request as it is now. */
  onChanged: (pull: Pull) => void
  onOpenPage: () => void
}

export function SetupCard({ agentId, pull, onChanged, onOpenPage }: Props) {
  const [picking, setPicking] = useState<number | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const work = pull.prosper
  const events = eventsInWords(pull.events, pull.config)
  const steps = events.filter((event) => event.type === 'step')
  const questions = openQuestions(events)
  const failed = work?.state === 'failed' ? events.findLast((e) => e.type === 'message' && isProsper(e)) : undefined

  const pick = async (question: string, option: number) => {
    setPicking(option)
    setProblem(null)
    try {
      onChanged(await answerQuestion(agentId, pull.number, question, option))
    } catch (failure) {
      setProblem((failure as Error).message)
    } finally {
      setPicking(null)
    }
  }

  return (
    <div className="absolute right-4 bottom-4 z-20 flex max-h-[calc(100%-2rem)] w-[360px] flex-col overflow-hidden rounded-2xl border bg-card shadow-[0_18px_50px_-18px_rgba(0,0,0,0.35)]">
      <div className="flex items-center gap-2 border-b px-4 py-2.5">
        <Mark className="h-[14px]" />
        <span className="text-[13.5px] font-semibold">Prosper AI</span>
        <span className="text-[12.5px] text-muted-foreground tabular-nums">· {pullLabel(pull.number)}</span>
        <button
          onClick={onOpenPage}
          className="ml-auto flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[12.5px] font-medium text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          Conversation <ArrowRight className="size-3.5" />
        </button>
      </div>
      <div className="min-h-0 flex-1 space-y-3 overflow-auto px-4 py-3">
        <Steps steps={steps} doing={work?.state === 'working' ? work.doing : null} />
        {questions.map((question) => (
          <div key={question.question} className="space-y-2 border-t pt-3">
            <div className="text-[12px] font-medium text-brand">Prosper AI needs your answer</div>
            <Question event={question} answer={null} busy={picking} onPick={(option) => void pick(question.question ?? '', option)} />
          </div>
        ))}
        {questions.length > 0 && (
          <p className="text-[12px] text-muted-foreground">
            Or answer in your own words in the{' '}
            <button onClick={onOpenPage} className="font-medium text-foreground hover:underline">
              conversation
            </button>
            .
          </p>
        )}
        {failed && <p className="border-t pt-3 text-[13px] leading-relaxed text-bad">{failed.text}</p>}
        {problem && <p className="text-[12.5px] text-bad">{problem}</p>}
      </div>
    </div>
  )
}
