// The card of one node on the canvas, and where the node is edited.
//
// Everything a node says is on its card, so the graph reads without opening
// anything: the name, the instructions, and under "Moves on when" one row per
// edge. A row carries its own source dot, which is where its wire leaves from;
// the wire shows the target, so the row does not repeat it. The start node and
// the end nodes carry a band saying what they are.
//
// Editing is in place: each text is an input styled as the text it replaces,
// and every change is an edit of the draft, so it can be undone.
//
// The card speaks the deployment team's language, not the schema's: names are
// shown as words ("Collect details" for collect_details) and an edge's function
// name is not shown at all. It is plumbing for the model; the condition is what
// a person reads.

import { Handle, Position, type Node as FlowNode, type NodeProps } from '@xyflow/react'
import { PhoneOff, Play, Plus, X } from 'lucide-react'

import {
  addEdge,
  nameTaken,
  removeEdge,
  renameNode,
  setEdgeDescription,
  setInstructions,
} from '@/draft/draft'
import { useEditor } from '@/draft/editor'
import { cn } from '@/lib/utils'

import { FieldChips } from './FieldChips'
import { GrowingText, NameInput } from './inputs'
import { handleId, type Card } from './model'
import { NodeMenu } from './NodeMenu'

export type CardNode = FlowNode<Card, 'card'>

const dot = '!size-[11px] !rounded-full !border-2 !border-card'
// Where a call enters and leaves the graph: a solid band across the card, on
// top of the start node and under an end node, readable at any zoom.
const band = 'flex items-center gap-1.5 px-4 py-1.5 text-[12px] font-medium'
// A control that only shows when its row or card is pointed at. Where there
// is no pointer to hover with, it is always there.
const hidden =
  'opacity-0 outline-none transition-opacity focus-visible:opacity-100 [@media(hover:none)]:opacity-100'

export function NodeCard({ data }: NodeProps<CardNode>) {
  const { id, node, start, edges, connected } = data
  const { draft, apply, seal, cancel } = useEditor()
  const [instructions, ...more] = node.task_messages ?? []
  return (
    <div
      className={cn(
        'group/card w-[300px] rounded-2xl border bg-card text-left shadow-[0_1px_2px_rgba(0,0,0,0.04),0_10px_28px_-14px_rgba(0,0,0,0.14)]',
        start && 'border-brand/45',
      )}
    >
      {start && (
        <div className={cn(band, 'rounded-t-[15px] bg-brand text-white')}>
          <Play className="size-3 fill-current" /> The call starts here
        </div>
      )}
      {/* No way in to the start node: the call begins there. */}
      {!start && (
        <Handle
          type="target"
          position={Position.Left}
          // Wires end here; they start at an edge's own dot.
          isConnectableStart={false}
          className={cn(dot, '!top-[26px] !left-[-6px] !bg-muted-foreground')}
        />
      )}
      <div className="flex items-start gap-1 px-4 pt-3.5">
        <NameInput
          label="Node name"
          name={node.name}
          refuse={(name) =>
            name === ''
              ? 'A node needs a name.'
              : nameTaken(draft, id, name)
                ? 'Another node already has this name.'
                : null
          }
          onRename={(name) => apply((current) => renameNode(current, id, name), `name:${id}`)}
          onBlur={(refused) => (refused ? cancel(`name:${id}`) : seal())}
          className="text-[14px] font-semibold tracking-[-0.01em]"
        />
        <NodeMenu id={id} start={start} end={Boolean(node.end)} />
      </div>
      <div className="px-4 pt-1 pb-3.5">
        <GrowingText
          label="Instructions"
          value={instructions?.content ?? ''}
          placeholder="What the agent says and does here…"
          onChange={(content) =>
            apply((current) => setInstructions(current, id, content), `instructions:${id}`)
          }
          onBlur={seal}
          className="text-[13px] leading-[1.5] text-foreground/70 focus-within:text-foreground"
        />
        {more.length > 0 && (
          // They reach the model too, so the card says they are there.
          <p className="mt-1 text-[11.5px] text-muted-foreground">
            + {more.length} more {more.length === 1 ? 'message' : 'messages'} to the model, not
            shown here
          </p>
        )}
      </div>
      {node.end ? (
        <div className={cn(band, 'rounded-b-[15px] bg-foreground text-background')}>
          <PhoneOff className="size-3" /> The call ends here
        </div>
      ) : (
        <div className="rounded-b-2xl border-t bg-muted/35 pb-1.5">
          {edges.length > 0 && (
            <div className="px-4 pt-2.5 pb-0.5 text-[10.5px] font-medium tracking-wide text-muted-foreground uppercase">
              Moves on when
            </div>
          )}
          {edges.map((edge, index) => (
            <div key={index} className="group/edge relative px-4 py-1.5">
              <div className="flex items-start gap-1">
                <GrowingText
                  label="Moves on when"
                  value={edge.description}
                  placeholder="When should the agent move on?"
                  onChange={(description) =>
                    apply(
                      (current) => setEdgeDescription(current, id, index, description),
                      `description:${id}:${index}`,
                    )
                  }
                  onBlur={seal}
                  className="min-w-0 flex-1 text-[12.5px] leading-snug"
                />
                <button
                  aria-label="Remove this way to move on"
                  title="Remove"
                  onClick={() => apply((current) => removeEdge(current, id, index))}
                  className={cn(hidden, 'nodrag -mr-1.5 rounded p-0.5 text-muted-foreground group-hover/edge:opacity-100 hover:text-bad')}
                >
                  <X className="size-3.5" />
                </button>
              </div>
              <FieldChips id={id} index={index} edge={edge} />
              {!connected[index] && (
                <div className="mt-1 text-[11.5px] font-medium text-bad">Not connected</div>
              )}
              <Handle
                id={handleId(index)}
                type="source"
                position={Position.Right}
                isConnectableEnd={false}
                className={cn(
                  dot,
                  '!top-[17px] !right-[-6px]',
                  connected[index] ? '!bg-foreground' : '!bg-bad',
                )}
              />
            </div>
          ))}
          <button
            onClick={() => apply((current) => addEdge(current, id))}
            className="nodrag mx-3 mt-0.5 flex items-center gap-1 rounded-md px-1 py-1 text-[12px] text-muted-foreground/80 hover:text-foreground"
          >
            <Plus className="size-3" />
            {edges.length > 0 ? 'Another way to move on' : 'Add a way to move on'}
          </button>
        </div>
      )}
    </div>
  )
}
