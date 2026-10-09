// The fields an edge collects, as chips, and the small editor a chip opens.
//
// A field is one property of the tool the model calls to take the edge: its
// name, what it is (the model reads the description), its type and whether it
// is required. A choice is the type whose value must be one of a list of
// options; the chip on the card shows them next to the name.

import { Plus, Trash2, X } from 'lucide-react'
import { useState } from 'react'

import type { Edge, EdgeProperty } from '@/agents/types'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import {
  addField,
  fieldKind,
  fieldTaken,
  removeField,
  updateField,
  type FieldChange,
} from '@/draft/draft'
import { useEditor } from '@/draft/editor'
import { humanize } from '@/draft/names'
import { cn } from '@/lib/utils'

import { NameInput } from './inputs'

// The kinds of field, as draft/draft.ts names them and as people read them.
const KINDS = [
  ['text', 'Text'],
  ['number', 'Number'],
  ['boolean', 'Yes / no'],
  ['choice', 'Choice'],
]

// How many options of a choice a chip shows before it says how many more.
const SHOWN = 3

const label = 'text-[11px] font-medium text-muted-foreground'
const input =
  'w-full rounded-md border bg-background px-2 py-1 text-[12px] outline-none focus:border-foreground/40'

/**
 * The options of a choice, as chips: type one and press Enter to add it, × to
 * remove it. A choice between fewer than two is not a choice, so it says so
 * until there are two.
 */
function Options({ options, onChange }: { options: string[]; onChange: (options: string[]) => void }) {
  const [typed, setTyped] = useState('')
  const add = () => {
    const option = typed.trim()
    if (option && !options.includes(option)) onChange([...options, option])
    setTyped('')
  }
  return (
    <div className="space-y-1">
      <span className={label}>Options</span>
      <div className="flex flex-wrap items-center gap-1 rounded-md border bg-background p-1 focus-within:border-foreground/40">
        {options.map((option) => (
          <span
            key={option}
            className="inline-flex max-w-full items-center gap-0.5 rounded-full border bg-card py-px pr-0.5 pl-2 text-[11.5px]"
          >
            <span className="truncate">{option}</span>
            <button
              aria-label={`Remove ${option}`}
              onClick={() => onChange(options.filter((other) => other !== option))}
              className="rounded-full p-0.5 text-muted-foreground hover:text-bad"
            >
              <X className="size-3" />
            </button>
          </span>
        ))}
        <input
          aria-label="Add an option"
          value={typed}
          onChange={(event) => setTyped(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault()
              add()
            } else if (event.key === 'Backspace' && typed === '' && options.length > 0) {
              onChange(options.slice(0, -1))
            }
          }}
          // What was typed and not entered is an option too, not lost.
          onBlur={add}
          placeholder={options.length > 0 ? 'Add another' : 'Type one and press Enter'}
          className="min-w-[96px] flex-1 bg-transparent px-1 py-0.5 text-[12px] outline-none"
        />
      </div>
      {options.length < 2 && (
        <p className="text-[10.5px] text-bad">A choice needs at least two options.</p>
      )}
    </div>
  )
}

type EditorProps = {
  edge: Edge
  name: string
  property: EdgeProperty
  change: (change: FieldChange, merge?: string) => void
  onBlur: (refused?: boolean) => void
  onRemove: () => void
  onDone: () => void
}

function FieldEditor({ edge, name, property, change, onBlur, onRemove, onDone }: EditorProps) {
  const kind = fieldKind(property)

  return (
    <div className="space-y-2.5 text-left">
      <label className="block space-y-1">
        <span className={label}>Name</span>
        <NameInput
          label="Field name"
          name={name}
          refuse={(next) =>
            next === ''
              ? 'A field needs a name.'
              : fieldTaken(edge, name, next)
                ? 'This edge already collects that.'
                : null
          }
          onRename={(next) => change({ name: next }, 'name')}
          onBlur={onBlur}
          selectOnFocus
          className={cn(input, 'mx-0 hover:bg-background focus:ring-0')}
        />
      </label>
      <label className="block space-y-1">
        <span className={label}>What it is (the model reads this)</span>
        <input
          value={property.description ?? ''}
          onChange={(event) => change({ description: event.target.value }, 'description')}
          onBlur={() => onBlur()}
          placeholder="Caller's full name."
          className={input}
        />
      </label>
      <div className="flex items-end gap-3">
        <label className="block flex-1 space-y-1">
          <span className={label}>Type</span>
          <select
            aria-label="Type"
            value={kind}
            onChange={(event) => change({ kind: event.target.value })}
            className={input}
          >
            {KINDS.map(([value, text]) => (
              <option key={value} value={value}>
                {text}
              </option>
            ))}
            {/* A type the editor does not offer stays as it was loaded. */}
            {!KINDS.some(([value]) => value === kind) && <option value={kind}>{kind}</option>}
          </select>
        </label>
        <label className="flex h-[28px] items-center gap-1.5 text-[12px]">
          <input
            type="checkbox"
            checked={edge.required?.includes(name) ?? false}
            onChange={(event) => change({ required: event.target.checked })}
          />
          Required
        </label>
      </div>
      {kind === 'choice' && (
        <Options options={property.enum ?? []} onChange={(options) => change({ options })} />
      )}
      <div className="flex items-center border-t pt-2">
        <button onClick={onRemove} className="flex items-center gap-1 text-[12px] text-bad">
          <Trash2 className="size-3" /> Remove
        </button>
        <button
          onClick={onDone}
          className="ml-auto rounded-md bg-foreground px-2.5 py-1 text-[12px] font-medium text-background"
        >
          Done
        </button>
      </div>
    </div>
  )
}

type ChipsProps = {
  id: string
  index: number
  edge: Edge
  /** A control of the edge itself, to end the row with at the right. */
  trailing?: React.ReactNode
}

/** The chips of the edge at `index` of node `id`, and a "+" chip to collect one more. */
export function FieldChips({ id, index, edge, trailing }: ChipsProps) {
  const { apply, seal, cancel } = useEditor()
  // Which chip's editor is open, by position: a field's name is being edited.
  const [open, setOpen] = useState<number | null>(null)
  const fields = Object.entries(edge.properties ?? {})

  return (
    // The chips wrap as a row; a chip never wraps inside.
    <div className="mt-1.5 flex flex-wrap items-center gap-1">
      {fields.map(([name, property], at) => {
        const key = (part: string) => `field:${id}:${index}:${at}:${part}`
        const options = property.enum ?? []
        return (
          <Popover key={at} open={open === at} onOpenChange={(next) => setOpen(next ? at : null)}>
            <PopoverTrigger
              title={property.description}
              className={cn(
                'nodrag inline-flex max-w-full items-center gap-1 rounded-full border bg-card px-2 py-0.5 text-left text-[11.5px] whitespace-nowrap outline-none hover:border-foreground/30 focus-visible:border-foreground/40',
                open === at && 'border-foreground/40',
              )}
            >
              <span className="shrink-0 font-medium">{humanize(name)}</span>
              {/* A glance at a choice, not its list: that is in the popover. */}
              {options.length > 0 && (
                <span className="truncate text-muted-foreground">
                  {options.slice(0, SHOWN).join(' · ')}
                </span>
              )}
              {options.length > SHOWN && (
                <span className="shrink-0 text-muted-foreground">+{options.length - SHOWN}</span>
              )}
              {!edge.required?.includes(name) && (
                <span className="shrink-0 text-muted-foreground">optional</span>
              )}
            </PopoverTrigger>
            <PopoverContent align="start" sideOffset={6} className="w-64 p-3">
              <FieldEditor
                edge={edge}
                name={name}
                property={property}
                change={(change, part) =>
                  apply(
                    (current) => updateField(current, id, index, name, change),
                    part && key(part),
                  )
                }
                onBlur={(refused) => (refused ? cancel(key('name')) : seal())}
                onRemove={() => {
                  setOpen(null)
                  apply((current) => removeField(current, id, index, name))
                }}
                onDone={() => setOpen(null)}
              />
            </PopoverContent>
          </Popover>
        )
      })}
      <button
        aria-label="Collect a field"
        title="Collect a field"
        onClick={() => {
          apply((current) => addField(current, id, index))
          setOpen(fields.length)
        }}
        className="nodrag inline-flex size-[23px] items-center justify-center rounded-full border border-dashed border-foreground/20 text-muted-foreground outline-none hover:border-foreground/40 hover:text-foreground focus-visible:border-foreground/40"
      >
        <Plus className="size-3" />
      </button>
      {/* An item of the row like the chips: with no room left on the line it
          takes the next one, and never sits over a chip. It leans into the
          card's padding, so it needs less of the line and that happens less. */}
      {trailing && <span className="-mr-2 ml-auto flex">{trailing}</span>}
    </div>
  )
}
