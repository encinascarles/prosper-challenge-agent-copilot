// The agent's own settings: what is true of the whole agent and not of one
// node. This is the form; AgentSettingsDialog shows it.
//
// They are edits of the draft like any on a card, so they undo, count as
// unsaved changes and go out with Save. Model and voice are plain on purpose:
// a short list of models worth using and the voice's id as text. A picker with
// previews is more than building an agent needs today.

import { setAgent, type AgentChange } from '@/draft/draft'
import { useEditor } from '@/draft/editor'
import { GrowingText } from '@/graph/inputs'

// What the backend runs an agent on when it names neither (agent_builder/schema.py).
const DEFAULT_MODEL = 'gpt-4o'
const DEFAULT_VOICE = '21m00Tcm4TlvDq8ikWAM'

// Cheap enough to iterate with and good enough to hold a call. The model an
// agent already has is always offered too, whatever it is.
const MODELS = ['gpt-4o', 'gpt-4o-mini', 'gpt-4.1', 'gpt-4.1-mini']

const label = 'text-[11px] font-medium text-muted-foreground'
const input =
  'w-full rounded-md border bg-background px-2 py-1 text-[13px] outline-none focus:border-foreground/40'

export function AgentSettings() {
  const { draft, apply, seal } = useEditor()
  const { name, persona, model, voice_id: voice } = draft.config
  const change = (edit: AgentChange, merge?: string) =>
    apply((current) => setAgent(current, edit), merge && `agent:${merge}`)
  const current = model ?? DEFAULT_MODEL

  return (
    <div className="space-y-3">
        <label className="block space-y-1">
          <span className={label}>Name</span>
          <input
            value={name}
            onChange={(event) => change({ name: event.target.value }, 'name')}
            onBlur={seal}
            className={input}
          />
        </label>
        <div className="space-y-1">
          <span className={label}>Persona (every step of the call starts from this)</span>
          <div className="max-h-[40vh] overflow-y-auto rounded-md border bg-background px-2 py-1 focus-within:border-foreground/40">
            <GrowingText
              label="Persona"
              value={persona ?? ''}
              placeholder="Who the agent is and how it speaks."
              onChange={(text) => change({ persona: text }, 'persona')}
              onBlur={seal}
              className="text-[13px] leading-[1.5]"
            />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <label className="block space-y-1">
            <span className={label}>Model</span>
            <select
              aria-label="Model"
              value={current}
              onChange={(event) => change({ model: event.target.value })}
              className={input}
            >
              {[...new Set([...MODELS, current])].map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>
          <label className="block space-y-1">
            <span className={label}>Voice (ElevenLabs voice id)</span>
            <input
              aria-label="Voice"
              value={voice ?? DEFAULT_VOICE}
              onChange={(event) => change({ voice_id: event.target.value.trim() }, 'voice')}
              onBlur={seal}
              spellCheck={false}
              className={input}
            />
          </label>
        </div>
    </div>
  )
}
