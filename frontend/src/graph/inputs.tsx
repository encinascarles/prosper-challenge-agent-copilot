// The inputs of a card: text that is edited where it is read.
//
// There is no edit mode. Every text on a card is an input styled as the text
// it replaces, with a faint background on hover to say it can be typed in.
// `nodrag` tells React Flow that a press here selects text and does not move
// the card.

import { useState } from 'react'

import { humanize, toName } from '@/draft/names'
import { cn } from '@/lib/utils'

const ghost =
  'nodrag -mx-1 rounded-md bg-transparent px-1 py-0.5 outline-none transition-colors placeholder:text-muted-foreground/60 hover:bg-muted/70 focus:bg-background focus:ring-1 focus:ring-foreground/20'

// Leaves the field, which is what "done" means when there is no save button.
function blurOn(event: React.KeyboardEvent<HTMLElement>, ...keys: string[]) {
  if (keys.includes(event.key)) event.currentTarget.blur()
}

type TextProps = {
  value: string
  onChange: (value: string) => void
  onBlur: () => void
  placeholder: string
  label: string
  className?: string
}

/**
 * Text of any length, as tall as what it holds. The hidden copy underneath
 * takes the height the text needs and the textarea fills it: a textarea does
 * not grow on its own, and one that scrolls would hide part of a prompt.
 */
export function GrowingText({ value, onChange, onBlur, placeholder, label, className }: TextProps) {
  const cell = 'col-start-1 row-start-1 whitespace-pre-wrap [overflow-wrap:anywhere]'
  return (
    <div className={cn('grid', className)}>
      <div aria-hidden className={cn(cell, 'invisible -mx-1 px-1 py-0.5')}>
        {value || placeholder}{' '}
      </div>
      <textarea
        aria-label={label}
        rows={1}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        onBlur={onBlur}
        onKeyDown={(event) => blurOn(event, 'Escape')}
        className={cn(ghost, cell, 'resize-none overflow-hidden')}
      />
    </div>
  )
}

type NameProps = {
  name: string // as stored, snake_case
  /** Why `name` cannot be used, or null if it can. */
  refuse: (name: string) => string | null
  onRename: (name: string) => void
  /** The field was left. `refused`: on a name that could not be stored. */
  onBlur: (refused: boolean) => void
  label: string
  className?: string
  selectOnFocus?: boolean // for a name just created, to type over it
}

/**
 * A name, shown as words and stored in snake_case. While it is typed the input
 * shows the text as typed, not the stored name read back: reading it back
 * would eat a trailing space and move the caret. A refused name is not stored:
 * the input keeps it with the reason underneath. Each letter is a rename, so
 * typing towards a refused name stores the letters before it; leaving the
 * field on a refused name tells the caller, which takes the whole run back.
 */
export function NameInput({
  name,
  refuse,
  onRename,
  onBlur,
  label,
  className,
  selectOnFocus,
}: NameProps) {
  // `stored` is the name the draft had after this text was typed. If the draft
  // has another (an undo), the text is stale and the stored name shows again.
  const [typed, setTyped] = useState<{ text: string; stored: string; problem: string | null }>()
  const current = typed?.stored === name ? typed : undefined

  const type = (text: string) => {
    const next = toName(text)
    const problem = next === name ? null : refuse(next)
    if (!problem && next !== name) onRename(next)
    setTyped({ text, stored: problem ? name : next, problem })
  }

  return (
    <div className="min-w-0 flex-1">
      <input
        aria-label={label}
        aria-invalid={current?.problem ? true : undefined}
        onFocus={selectOnFocus ? (event) => event.target.select() : undefined}
        value={current?.text ?? humanize(name)}
        onChange={(event) => type(event.target.value)}
        onBlur={() => {
          setTyped(undefined)
          onBlur(Boolean(current?.problem))
        }}
        onKeyDown={(event) => blurOn(event, 'Enter', 'Escape')}
        className={cn(ghost, 'w-full', className)}
      />
      {current?.problem && (
        <p role="alert" className="mt-0.5 text-[11.5px] font-normal tracking-normal text-bad">
          {current.problem}
        </p>
      )}
    </div>
  )
}
