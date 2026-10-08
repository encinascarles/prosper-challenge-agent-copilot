// The fields an edge collects, as chips, and the small editor a chip opens.
//
// A field is one property of the tool the model calls to take the edge: its
// name, what it is (the model reads the description), its type, whether it is
// required, and optionally the only values allowed. On the card it is a chip
// with its name and, for a list of values, the values.

import { Trash2 } from 'lucide-react'
import { useState } from 'react'

import type { Edge, EdgeProperty } from '@/agents/types'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { addField, fieldTaken, removeField, updateField, type FieldChange } from '@/draft/draft'
import { useEditor } from '@/draft/editor'
import { humanize } from '@/draft/names'
import { cn } from '@/lib/utils'

import { NameInput } from './inputs'

const TYPES = [
  ['string', 'Text'],
  ['number', 'Number'],
  ['boolean', 'Yes / no'],
]

const label = 'text-[11px] font-medium text-muted-foreground'
const input =
  'w-full rounded-md border bg-background px-2 py-1 text-[12px] outline-none focus:border-foreground/40'

const toOptions = (text: string) =>
  text
    .split(',')
    .map((option) => option.trim())
    .filter(Boolean)

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
  // A property with no type takes any value; as a field to collect it is text.
  const type = property.type ?? 'string'
  const options = property.enum ?? []
  // The list as typed, kept while it still says what the draft holds, so a
  // comma or a space being typed is not tidied away under the caret.
  const [typed, setTyped] = useState(options.join(', '))
  const listed = toOptions(typed).join('\n') === options.join('\n') ? typed : options.join(', ')

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
            value={type}
            onChange={(event) => change({ type: event.target.value })}
            className={input}
          >
            {TYPES.map(([value, text]) => (
              <option key={value} value={value}>
                {text}
              </option>
            ))}
            {/* A type the editor does not offer stays as it was loaded. */}
            {!TYPES.some(([value]) => value === type) && <option value={type}>{type}</option>}
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
      {type === 'string' && (
        <label className="block space-y-1">
          <span className={label}>Only these values</span>
          <input
            value={listed}
            onChange={(event) => {
              setTyped(event.target.value)
              change({ options: toOptions(event.target.value) }, 'options')
            }}
            onBlur={() => onBlur()}
            placeholder="book, reschedule, cancel"
            className={input}
          />
          <span className="block text-[10.5px] text-muted-foreground">
            Separated by commas. Empty means any text.
          </span>
        </label>
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

/** The chips of the edge at `index` of node `id`, with "+ Collect" to add one. */
export function FieldChips({ id, index, edge }: { id: string; index: number; edge: Edge }) {
  const { apply, seal, cancel } = useEditor()
  // Which chip's editor is open, by position: a field's name is being edited.
  const [open, setOpen] = useState<number | null>(null)
  const fields = Object.entries(edge.properties ?? {})

  return (
    <div className="mt-1 flex flex-wrap items-center gap-1">
      {fields.map(([name, property], at) => {
        const key = (part: string) => `field:${id}:${index}:${at}:${part}`
        return (
          <Popover key={at} open={open === at} onOpenChange={(next) => setOpen(next ? at : null)}>
            <PopoverTrigger
              title={property.description}
              className={cn(
                'nodrag inline-flex max-w-full items-center gap-1 rounded-full border bg-card px-2 py-0.5 text-left text-[11.5px] outline-none hover:border-foreground/30 focus-visible:border-foreground/40',
                open === at && 'border-foreground/40',
              )}
            >
              <span className="font-medium">{humanize(name)}</span>
              {property.enum && property.enum.length > 0 && (
                <span className="text-muted-foreground">{property.enum.join(' · ')}</span>
              )}
              {!edge.required?.includes(name) && (
                <span className="text-muted-foreground">optional</span>
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
        onClick={() => {
          apply((current) => addField(current, id, index))
          setOpen(fields.length)
        }}
        className="nodrag rounded-full px-1.5 py-0.5 text-[11.5px] text-muted-foreground/70 hover:bg-muted hover:text-foreground"
      >
        + Collect
      </button>
    </div>
  )
}
