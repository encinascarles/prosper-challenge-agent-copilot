// A new agent, before it exists: from scratch, or built by Prosper AI from the
// clinic's guidelines.
//
// An agent is found by its name in the picker and in the tab, so it gets one
// from the start. From scratch, it starts as the template's greeting and
// goodbye. With Prosper AI, the guidelines are pasted, attached as files
// (PDF, Word, text; dropped or picked) or both, and Prosper AI builds the
// first version in PR #1, in sight. The files are read by the backend: one it
// cannot read (a scan) is refused here, with the reason, and the dialog stays.

import { FileText, Plus, SquareDashed, X } from 'lucide-react'
import { useRef, useState } from 'react'

import { Mark } from '@/components/Mark'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import { cn } from '@/lib/utils'

export type NewAgent =
  | { mode: 'scratch'; name: string }
  | { mode: 'prosper'; name: string; guidelines: string; files: File[] }

type Props = {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Creates the agent. A failure is shown here and the dialog stays. */
  onCreate: (agent: NewAgent) => Promise<void>
}

const ACCEPT = '.pdf,.docx,.txt,.md'

export function NewAgentDialog({ open, onOpenChange, onCreate }: Props) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="gap-0 p-0 sm:max-w-[600px]" showCloseButton={false}>
        <NewAgentForm onCancel={() => onOpenChange(false)} onCreate={onCreate} />
      </DialogContent>
    </Dialog>
  )
}

/** What a file's row says next to its name: its kind and its size. */
function kindOf(file: File): string {
  return file.name.includes('.') ? (file.name.split('.').pop() ?? '').toUpperCase() : 'FILE'
}
function sizeOf(file: File): string {
  return file.size < 1024 * 1024 ? `${Math.max(1, Math.round(file.size / 1024))} KB` : `${(file.size / 1024 / 1024).toFixed(1)} MB`
}

// Its own component, so it starts empty each time the dialog opens: the dialog
// only mounts what is inside it while it is open.
function NewAgentForm({ onCancel, onCreate }: { onCancel: () => void; onCreate: Props['onCreate'] }) {
  const [mode, setMode] = useState<'scratch' | 'prosper'>('prosper')
  const [name, setName] = useState('')
  const [guidelines, setGuidelines] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [dragging, setDragging] = useState(false)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const picker = useRef<HTMLInputElement>(null)
  const given = guidelines.trim() !== '' || files.length > 0
  const ready = name.trim() !== '' && !creating && (mode === 'scratch' || given)

  // The same file twice is one file: the newer copy replaces the older.
  const attach = (list: FileList | null) => {
    if (!list?.length) return
    const added = [...list]
    setFiles((now) => [...now.filter((file) => !added.some((a) => a.name === file.name)), ...added])
  }

  const create = async () => {
    if (!ready) return
    setCreating(true)
    setError(null)
    try {
      await onCreate(mode === 'scratch' ? { mode, name: name.trim() } : { mode, name: name.trim(), guidelines, files })
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure))
    } finally {
      setCreating(false)
    }
  }

  const option = (value: typeof mode, icon: React.ReactNode, title: string, text: string) => (
    <button
      type="button"
      aria-pressed={mode === value}
      onClick={() => setMode(value)}
      className={cn(
        'flex-1 rounded-xl border px-4 py-3 text-left transition-colors',
        mode === value ? 'border-foreground ring-1 ring-foreground' : 'hover:border-foreground/30',
      )}
    >
      <span className="flex items-center gap-2 text-[14px] font-semibold">
        {icon}
        {title}
      </span>
      <span className="mt-1 block text-[12.5px] leading-snug text-muted-foreground">{text}</span>
    </button>
  )

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        void create()
      }}
    >
      <div className="flex items-center px-6 pt-5 pb-4">
        <DialogTitle className="text-[16px] font-semibold">New agent</DialogTitle>
        <DialogDescription className="sr-only">Start from scratch, or have Prosper AI build it from your guidelines.</DialogDescription>
        <button type="button" aria-label="Close" onClick={onCancel} className="ml-auto rounded-md p-1 text-muted-foreground hover:bg-muted">
          <X className="size-4" />
        </button>
      </div>
      <div className="space-y-5 px-6 pb-5">
        <div className="flex gap-3">
          {option('scratch', <SquareDashed className="size-4 text-muted-foreground" />, 'Start from scratch', 'A greeting and a goodbye. You draw the steps.')}
          {option('prosper', <Mark className="h-[14px]" />, 'Build it with Prosper AI', 'Give it your guidelines. It drafts the steps, rules and tests.')}
        </div>
        <label className="block space-y-1.5">
          <span className="text-[13px] font-medium">Name</span>
          <input
            autoFocus
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="e.g. Anna"
            className="h-9 w-full rounded-lg border bg-background px-3 text-[14px] outline-none focus:border-foreground/40"
          />
        </label>
        {mode === 'prosper' && (
          <div className="space-y-1.5">
            <div className="text-[13px] font-medium">
              Guidelines <span className="font-normal text-muted-foreground">· paste them, attach files, or both</span>
            </div>
            <div
              onDragOver={(event) => {
                event.preventDefault()
                setDragging(true)
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(event) => {
                event.preventDefault()
                setDragging(false)
                attach(event.dataTransfer.files)
              }}
              className={cn(
                'overflow-hidden rounded-lg border focus-within:border-foreground/40',
                dragging && 'border-foreground/50 bg-muted/40',
              )}
            >
              <textarea
                aria-label="Guidelines"
                value={guidelines}
                onChange={(event) => setGuidelines(event.target.value)}
                placeholder="Paste them as they are: an email, a document, notes from a call…"
                rows={6}
                className="block w-full resize-none bg-transparent px-3 py-2.5 text-[13px] leading-relaxed outline-none"
              />
              {files.map((file) => (
                <div key={file.name} className="flex h-9 items-center gap-2.5 border-t px-3 text-[13px]">
                  <FileText className="size-3.5 shrink-0 text-muted-foreground" />
                  <span className="truncate font-medium">{file.name}</span>
                  <span className="shrink-0 text-muted-foreground">
                    {kindOf(file)} · {sizeOf(file)}
                  </span>
                  <button
                    type="button"
                    aria-label={`Remove ${file.name}`}
                    onClick={() => setFiles((now) => now.filter((f) => f !== file))}
                    className="ml-auto rounded p-0.5 text-muted-foreground hover:text-foreground"
                  >
                    <X className="size-3.5" />
                  </button>
                </div>
              ))}
              <div className="flex h-9 items-center gap-2 border-t bg-muted/30 px-3 text-[12.5px]">
                <button type="button" onClick={() => picker.current?.click()} className="flex items-center gap-1 font-medium hover:underline">
                  <Plus className="size-3.5" /> Attach files
                </button>
                <span className="text-muted-foreground">or drop them here · PDF, Word, text</span>
                <input
                  ref={picker}
                  aria-label="Attach files"
                  type="file"
                  multiple
                  accept={ACCEPT}
                  className="hidden"
                  onChange={(event) => {
                    attach(event.target.files)
                    event.target.value = ''
                  }}
                />
              </div>
            </div>
          </div>
        )}
        {error && (
          <p role="alert" className="text-[13px] text-bad">
            {error}
          </p>
        )}
      </div>
      <div className="flex items-center gap-3 border-t bg-muted/30 px-6 py-3.5">
        <p className="min-w-0 flex-1 text-[12.5px] leading-snug text-muted-foreground">
          {mode === 'prosper'
            ? 'You watch Prosper AI build it in PR #1. Nothing goes live until you merge.'
            : 'It opens in Build with a greeting and a goodbye.'}
        </p>
        <Button type="button" variant="outline" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" disabled={!ready}>
          {mode === 'prosper' && <Mark className="h-[13px] [&_polygon:first-child]:fill-background" />}
          {creating ? (mode === 'prosper' ? 'Reading…' : 'Creating…') : mode === 'prosper' ? 'Build with Prosper AI' : 'Create agent'}
        </Button>
      </div>
    </form>
  )
}
