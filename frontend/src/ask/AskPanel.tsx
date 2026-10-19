// Ask Prosper AI: the panel at the right of every section, for questions about
// the open agent ("Can Anna book for a child?", "Why did Maria's call go to
// the nurse?"). "New chat", the past chats (collapsed to the one open once
// there are a few), the open chat, and the composer at the bottom.
//
// Prosper AI answers from the copy the top bar is on: live, or the pull
// request. What an answer names (an issue, a pull request, a call) is a chip
// that opens it; what it read to answer is a muted line each. It can also do
// what the person can (open an issue, run a test, merge), but only on a
// click: it proposes the act as a card with Do it and Cancel, and the card
// then says what happened, with a link. A change to the agent itself is a
// pull request, where it is tested before it can go live.

import {
  ArrowRight,
  ArrowUp,
  ChevronDown,
  ChevronUp,
  CircleAlert,
  CircleCheck,
  CircleDot,
  CircleSlash,
  FlaskConical,
  GitMerge,
  GitPullRequestArrow,
  GitPullRequestClosed,
  ListPlus,
  Loader2,
  MessageCircle,
  PenLine,
  Phone,
  PhoneCall,
  Plus,
  Search,
  Wrench,
  X,
  type LucideIcon,
} from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'

import { askProsper, decideAction, getChat, listCalls, listChats, listIssues, listPulls, openOffer } from '@/agents/api'
import type { Agent, Pull } from '@/agents/types'
import { Mark } from '@/components/Mark'
import { cn } from '@/lib/utils'
import { Turn } from '@/prosper/parts'
import { pullLabel, versionLabel } from '@/pulls/model'

import { actionOutcome, chatMeta, linkText, offerWhere, suggestions, withQuestion, type Known } from './model'
import type { Action, Chat, ChatMessage, ChatSummary, Link } from './types'

type Props = {
  agent: Agent
  /** The open pull request the top bar is on; null for live. */
  on: number | null
  /** The chat shown; null for a new one. */
  chatId: number | null
  onChat: (chat: number | null) => void
  onClose: () => void
  onLink: (link: Link) => void
  /** An offer opened this pull request. */
  onOpened: (pull: Pull) => void
  /** Prosper AI did something the person said to: what the sections show may have changed. */
  onActed: () => void
}

const NONE: Known = { issues: [], pulls: [], calls: [] }

export function AskPanel({ agent, on, chatId, onChat, onClose, onLink, onOpened, onActed }: Props) {
  const [chats, setChats] = useState<ChatSummary[]>([])
  const [chat, setChat] = useState<Chat | null>(null)
  const [known, setKnown] = useState<Known>(NONE)
  // The question being answered, shown in the chat until the answer comes.
  const [asking, setAsking] = useState<{ chat: number | null; text: string } | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const [listOpen, setListOpen] = useState(false)
  // The card being done (or cancelled), until the chat comes back.
  const [deciding, setDeciding] = useState<{ chat: number; index: number; run: boolean } | null>(null)

  const refresh = useCallback(() => {
    listChats(agent.id).then(setChats, () => {})
    // Only to name what answers link to: what fails to load is shown by number.
    Promise.all([listIssues(agent.id), listPulls(agent.id), listCalls(agent.id)]).then(
      ([issues, pulls, { calls }]) => setKnown({ issues, pulls, calls }),
      () => {},
    )
  }, [agent.id])
  useEffect(refresh, [refresh])

  // Another chat picked: what is shown is the chat loaded with its id (`shown`).
  useEffect(() => {
    if (chatId === null) return
    let current = true
    let timer: ReturnType<typeof setTimeout> | undefined
    const load = () =>
      getChat(agent.id, chatId).then(
        (loaded) => {
          if (!current) return
          setChat(loaded)
          // A question asked before the panel was last opened again (the
          // editor reloads it) is still being answered: read it again soon.
          if (loaded.messages.at(-1)?.by === 'you') timer = setTimeout(load, 2000)
        },
        (failure: Error) => current && setProblem(failure.message),
      )
    void load()
    return () => {
      current = false
      clearTimeout(timer)
    }
  }, [agent.id, chatId])

  const send = async (text: string) => {
    const into = chat?.id ?? null
    setAsking({ chat: into, text })
    setProblem(null)
    try {
      const answered = await askProsper(agent.id, text, into, on)
      setChat(answered)
      if (into === null) onChat(answered.id)
      refresh()
    } catch (failure) {
      setProblem((failure as Error).message)
    } finally {
      setAsking(null)
    }
  }

  const create = async (index: number) => {
    if (!chat) return
    setProblem(null)
    try {
      const opened = await openOffer(agent.id, chat.id, index)
      setChat(opened.chat)
      refresh()
      onOpened(opened.pull)
    } catch (failure) {
      setProblem((failure as Error).message)
    }
  }

  const decide = async (index: number, run: boolean) => {
    if (!chat) return
    setDeciding({ chat: chat.id, index, run })
    setProblem(null)
    try {
      setChat(await decideAction(agent.id, chat.id, index, run))
      refresh()
      if (run) onActed()
    } catch (failure) {
      setProblem((failure as Error).message)
    } finally {
      setDeciding(null)
    }
  }

  const shown = chat && chat.id === chatId ? chat : null
  const doing = deciding !== null && deciding.chat === shown?.id ? deciding : null
  const asked = asking !== null && asking.chat === (shown?.id ?? null) ? asking.text : null
  // Prosper AI answers a question, and goes on after a card it was told to do.
  const waiting = asked !== null || doing?.run === true
  const messages = asked !== null ? withQuestion(shown, asked) : (shown?.messages ?? [])

  return (
    <aside aria-label="Ask Prosper AI" className="flex w-[400px] shrink-0 flex-col border-l bg-card">
      <div className="flex h-11 shrink-0 items-center gap-2 border-b px-4">
        <Mark className="h-[14px]" />
        <span className="text-[13.5px] font-semibold">Ask Prosper AI</span>
        <button
          onClick={() => onChat(null)}
          disabled={chatId === null}
          className="ml-auto flex h-7 items-center gap-1 rounded-md border px-2 text-[12.5px] font-medium hover:bg-muted disabled:opacity-50"
        >
          <Plus className="size-3.5" /> New chat
        </button>
        <button aria-label="Close" onClick={onClose} className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground">
          <X className="size-4" />
        </button>
      </div>
      <ChatList chats={chats} chatId={chatId} open={listOpen || chatId === null} onToggle={() => setListOpen((now) => !now)} onPick={(id) => {
        onChat(id)
        setListOpen(false)
      }} />
      <div className="min-h-0 flex-1 overflow-auto">
        {messages.length === 0 ? (
          <Empty name={agent.name} live={agent.live_version > 0} onAsk={(text) => void send(text)} />
        ) : (
          <Thread
            messages={messages}
            waiting={waiting}
            known={known}
            live={agent.live_version}
            on={on}
            doing={doing?.index ?? null}
            onLink={onLink}
            onCreate={(index) => create(index)}
            onDecide={(index, run) => void decide(index, run)}
          />
        )}
      </div>
      <Composer name={agent.name} busy={asking !== null || deciding !== null} problem={problem} on={on} live={agent.live_version} onSend={send} />
    </aside>
  )
}

function ChatList({ chats, chatId, open, onToggle, onPick }: { chats: ChatSummary[]; chatId: number | null; open: boolean; onToggle: () => void; onPick: (id: number) => void }) {
  if (chats.length === 0) return null
  const picked = chats.find((chat) => chat.id === chatId)
  if (!open && picked) {
    return (
      <button onClick={onToggle} className="flex h-10 w-full shrink-0 items-center gap-2.5 border-b px-4 text-left hover:bg-muted/50">
        <MessageCircle className="size-4 shrink-0 text-muted-foreground" />
        <span className="min-w-0 flex-1 truncate text-[13px] font-medium">{picked.title}</span>
        <span className="flex shrink-0 items-center gap-0.5 border-l pl-2.5 text-[12px] text-muted-foreground">
          {chats.length} {chats.length === 1 ? 'chat' : 'chats'}
          <ChevronDown className="size-3.5" />
        </span>
      </button>
    )
  }
  return (
    <div className="max-h-[40%] shrink-0 overflow-auto border-b pb-1.5">
      <div className="mt-1 flex h-7 items-center px-4 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
        Chats <span className="ml-1.5 font-normal tabular-nums">{chats.length}</span>
        {picked && (
          <button onClick={onToggle} aria-label="Collapse the chats" className="ml-auto rounded p-0.5 hover:bg-muted hover:text-foreground">
            <ChevronUp className="size-3.5" />
          </button>
        )}
      </div>
      {chats.map((chat) => (
        <button
          key={chat.id}
          onClick={() => onPick(chat.id)}
          className={cn('flex w-full items-center gap-2.5 px-4 py-[7px] text-left hover:bg-muted/60', chat.id === chatId && 'bg-muted')}
        >
          <MessageCircle className="size-4 shrink-0 text-muted-foreground" />
          <span className="min-w-0 flex-1 truncate text-[13px]">{chat.title}</span>
          <span className="shrink-0 text-[12px] text-muted-foreground tabular-nums">{chatMeta(chat)}</span>
        </button>
      ))}
    </div>
  )
}

function Empty({ name, live, onAsk }: { name: string; live: boolean; onAsk: (text: string) => void }) {
  return (
    <div className="px-4 pt-8">
      <p className="text-center text-[12.5px] text-muted-foreground">
        Ask about {name || 'the agent'}, its tests and its calls,
        <br />
        or ask Prosper AI to do something: it asks before it acts.
      </p>
      <div className="mt-5 space-y-1.5">
        {suggestions(name, live).map((text) => (
          <button key={text} onClick={() => onAsk(text)} className="flex w-full items-center gap-2 rounded-lg border px-3 py-2 text-left text-[13px] hover:border-foreground/30">
            <span className="min-w-0 flex-1">{text}</span>
            <ArrowRight className="size-3.5 shrink-0 text-muted-foreground" />
          </button>
        ))}
      </div>
    </div>
  )
}

type ThreadProps = {
  /** The open pull request the panel is on; null for live. */
  on: number | null
  messages: ChatMessage[]
  waiting: boolean
  known: Known
  live: number
  /** The message whose card is being done or cancelled. */
  doing: number | null
  onLink: (link: Link) => void
  onCreate: (index: number) => Promise<void>
  onDecide: (index: number, run: boolean) => void
}

function Thread({ messages, waiting, known, live, on, doing, onLink, onCreate, onDecide }: ThreadProps) {
  const end = useRef<HTMLDivElement>(null)
  useEffect(() => {
    end.current?.scrollIntoView({ block: 'end' })
  }, [messages.length, waiting])
  return (
    <div className="space-y-4 px-4 pt-4">
      {messages.map((message, i) => (
        <Turn key={i} who={message.by} at={message.at} title={message.about ? `on ${message.about}` : undefined}>
          {message.reads.length > 0 && <Reads reads={message.reads} />}
          {message.text && <p className={cn('text-[13px] leading-relaxed whitespace-pre-wrap', message.failed && 'text-bad')}>{message.text}</p>}
          {message.links.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {message.links.map((link) => (
                <LinkChip key={`${link.kind}${link.number}`} link={link} known={known} onOpen={() => onLink(link)} />
              ))}
            </div>
          )}
          {message.action && (
            <ActionCard action={message.action} busy={doing === i} disabled={doing !== null} onDecide={(run) => onDecide(i, run)} onOpen={onLink} />
          )}
          {message.offer && <OfferCard offer={message.offer} live={live} on={on} onCreate={() => onCreate(i)} onOpen={(n) => onLink({ kind: 'pull', number: n })} />}
        </Turn>
      ))}
      {waiting && (
        <Turn who="Prosper AI">
          <span className="flex gap-1 pt-1" aria-label="Prosper AI is answering">
            {[0, 1, 2].map((i) => (
              <span key={i} className="size-1.5 animate-pulse rounded-full bg-muted-foreground" style={{ animationDelay: `${i * 0.2}s` }} />
            ))}
          </span>
        </Turn>
      )}
      <div ref={end} className="h-3" />
    </div>
  )
}

/** What Prosper AI read to answer, a muted line each: "Read Issue #5 and its 3 calls". */
function Reads({ reads }: { reads: string[] }) {
  return (
    <div className="space-y-0.5">
      {reads.map((line, i) => (
        <div key={i} className="flex items-center gap-1.5 text-[12px] text-muted-foreground">
          <Search className="size-3 shrink-0" />
          <span className="min-w-0 truncate">{line}</span>
        </div>
      ))}
    </div>
  )
}

const ACTION_ICONS: Record<string, LucideIcon> = {
  open_issue: CircleDot,
  tidy_issue: PenLine,
  fix_issue: Wrench,
  open_pull_request: GitPullRequestArrow,
  run_tests: FlaskConical,
  play_calls: PhoneCall,
  change_issues: CircleDot,
  change_pull: GitPullRequestClosed,
  merge_pull: GitMerge,
  add_rule: ListPlus,
  add_test: FlaskConical,
}

/**
 * Something Prosper AI proposes to do: what, and what follows from it, with
 * Do it and Cancel. Nothing happens before the click. Decided, it is one line:
 * what happened, with a link to it, or why it was not done.
 */
function ActionCard({ action, busy, disabled, onDecide, onOpen }: { action: Action; busy: boolean; disabled: boolean; onDecide: (run: boolean) => void; onOpen: (link: Link) => void }) {
  const outcome = actionOutcome(action)
  if (outcome !== null) {
    const link = action.state === 'done' ? action.result?.link : null
    const Icon = action.state === 'done' ? CircleCheck : action.state === 'failed' ? CircleAlert : CircleSlash
    const row = (
      <>
        <Icon className={cn('size-4 shrink-0', action.state === 'done' ? 'text-emerald-600' : action.state === 'failed' ? 'text-bad' : 'text-muted-foreground')} />
        <span className="min-w-0 flex-1">
          {action.state === 'done' ? (
            <>
              <span className="font-medium">{outcome}</span>
              {action.what && <span className="block truncate text-[12px] text-muted-foreground">{action.what}</span>}
            </>
          ) : (
            <>
              <span className={cn('font-medium', action.state !== 'failed' && 'text-muted-foreground line-through')}>{action.title}</span>
              <span className={cn('block text-[12px]', action.state === 'failed' ? 'text-bad' : 'text-muted-foreground')}>{outcome}</span>
            </>
          )}
        </span>
        {link && <ArrowRight className="size-3.5 shrink-0 text-muted-foreground" />}
      </>
    )
    const box = 'flex w-full items-center gap-2 rounded-lg border bg-card px-3 py-2 text-left text-[13px]'
    return link ? (
      <button onClick={() => onOpen(link)} className={cn(box, 'hover:border-foreground/30')}>
        {row}
      </button>
    ) : (
      <div className={box}>{row}</div>
    )
  }
  const Icon = ACTION_ICONS[action.tool] ?? CircleDot
  const running = busy || action.state === 'running'
  return (
    <div className="overflow-hidden rounded-xl border border-brand/40 bg-card">
      <div className="flex items-start gap-2.5 px-3.5 py-3">
        <Icon className="mt-px size-4 shrink-0 text-brand" />
        <div className="min-w-0 flex-1">
          <div className="text-[13.5px] font-semibold">{action.title}</div>
          {action.what && <div className="mt-0.5 text-[13px] leading-snug">{action.what}</div>}
          {action.meta.length > 0 && <div className="mt-1 text-[12px] leading-snug text-muted-foreground">{action.meta.join(' · ')}</div>}
        </div>
      </div>
      <div className="flex items-center justify-end gap-2 border-t bg-muted/30 px-3.5 py-2.5">
        <button
          disabled={disabled || running}
          onClick={() => onDecide(false)}
          className="flex h-8 items-center rounded-lg px-3 text-[13px] font-medium text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-50"
        >
          Cancel
        </button>
        <button
          disabled={disabled || running}
          onClick={() => onDecide(true)}
          className="flex h-8 items-center gap-1.5 rounded-lg bg-foreground px-3.5 text-[13px] font-medium text-background disabled:opacity-60"
        >
          {running && <Loader2 className="size-3.5 animate-spin" />} {running ? 'Doing it' : 'Do it'}
        </button>
      </div>
    </div>
  )
}

function LinkChip({ link, known, onOpen }: { link: Link; known: Known; onOpen: () => void }) {
  const { label, detail } = linkText(link, known)
  const Icon = link.kind === 'issue' ? CircleDot : link.kind === 'pull' ? GitPullRequestArrow : Phone
  return (
    <button onClick={onOpen} className="inline-flex max-w-full items-center gap-1.5 rounded-md border bg-card px-2 py-1 text-left text-[12px] hover:border-foreground/30">
      <Icon className={cn('size-3.5 shrink-0', link.kind === 'issue' ? 'text-bad' : 'text-muted-foreground')} />
      <span className="shrink-0 font-medium tabular-nums">{label}</span>
      {detail && <span className="min-w-0 truncate text-muted-foreground">{detail}</span>}
      <ArrowRight className="size-3 shrink-0 text-muted-foreground" />
    </button>
  )
}

/**
 * A change asked for: what it would be, and the button that opens its pull
 * request. It opens on live, always: a pull request the person is on has its
 * own conversation for changes, which the card points to.
 */
function OfferCard({ offer, live, on, onCreate, onOpen }: { offer: NonNullable<ChatMessage['offer']>; live: number; on: number | null; onCreate: () => Promise<void>; onOpen: (pull: number) => void }) {
  const [creating, setCreating] = useState(false)
  return (
    <div className="overflow-hidden rounded-xl border border-brand/40 bg-card">
      <div className="flex items-start gap-2.5 px-3.5 py-3">
        <GitPullRequestArrow className="mt-px size-4 shrink-0 text-brand" />
        <div className="min-w-0 flex-1">
          <div className="text-[13.5px] font-semibold">{offer.title}</div>
          <div className="mt-0.5 text-[12.5px] leading-snug">{offer.what}</div>
          <div className="mt-1 text-[12px] text-muted-foreground">
            {offerWhere(live)}
          </div>
          {offer.pull === null && on !== null && (
            <div className="mt-1 text-[12px] text-muted-foreground">
              To change {pullLabel(on)},{' '}
              <button onClick={() => onOpen(on)} className="font-medium text-foreground hover:underline">
                write in its conversation
              </button>
            </div>
          )}
        </div>
      </div>
      <div className="flex items-center justify-end border-t bg-muted/30 px-3.5 py-2.5">
        {offer.pull !== null ? (
          <button onClick={() => onOpen(offer.pull!)} className="flex h-8 items-center gap-1.5 rounded-lg border bg-card px-3 text-[13px] font-medium hover:border-foreground/30">
            <GitPullRequestArrow className="size-3.5 text-brand" /> Opened {pullLabel(offer.pull)} <ArrowRight className="size-3.5 text-muted-foreground" />
          </button>
        ) : (
          <button
            disabled={creating}
            onClick={() => {
              setCreating(true)
              void onCreate().finally(() => setCreating(false))
            }}
            className="flex h-8 items-center gap-1.5 rounded-lg bg-foreground px-3.5 text-[13px] font-medium text-background disabled:opacity-60"
          >
            {creating ? <Loader2 className="size-3.5 animate-spin" /> : <GitPullRequestArrow className="size-3.5" />} Create pull request
          </button>
        )}
      </div>
    </div>
  )
}

function Composer({ name, busy, problem, on, live, onSend }: { name: string; busy: boolean; problem: string | null; on: number | null; live: number; onSend: (text: string) => Promise<void> }) {
  const [text, setText] = useState('')
  const ready = text.trim() !== '' && !busy
  const send = () => {
    if (!ready) return
    void onSend(text.trim())
    setText('')
  }
  return (
    <div className="shrink-0 border-t p-3">
      <div className="rounded-xl border bg-background px-3 py-2 focus-within:border-foreground/30">
        <div className="flex items-end gap-2">
          <textarea
            autoFocus
            aria-label="Ask Prosper AI"
            value={text}
            onChange={(event) => setText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                send()
              }
            }}
            rows={2}
            placeholder={`Ask about ${name || 'the agent'}, or ask Prosper AI to do something…`}
            className="field-sizing-content max-h-32 min-h-[40px] min-w-0 flex-1 resize-none bg-transparent py-0.5 text-[13px] leading-relaxed outline-none placeholder:text-muted-foreground"
          />
          <button onClick={send} disabled={!ready} aria-label="Send" className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-foreground text-background disabled:opacity-25">
            <ArrowUp className="size-4" />
          </button>
        </div>
      </div>
      <p className={cn('mt-1.5 text-[11.5px]', problem ? 'text-bad' : 'text-muted-foreground')}>
        {problem ?? `Answers from ${on !== null ? pullLabel(on) : live ? versionLabel(live) : 'PR #1'} · nothing changes until you click Do it`}
      </p>
    </div>
  )
}
