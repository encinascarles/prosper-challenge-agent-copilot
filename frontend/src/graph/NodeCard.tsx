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
import { ArrowRight, PhoneOff, Play, Plus, RotateCcw, Trash2 } from 'lucide-react'
import { useState } from 'react'

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import {
  addEdge,
  edgeIsEmpty,
  nameTaken,
  removeEdge,
  renameNode,
  setEdgeDescription,
  setEnd,
  setInstructions,
} from '@/draft/draft'
import { useEditor } from '@/draft/editor'
import { cn } from '@/lib/utils'

import { FieldChips } from './FieldChips'
import { GrowingText, NameInput } from './inputs'
import { handleId, type Card } from './model'
import { NodeMenu } from './NodeMenu'

// What the canvas adds to a card for the moment: nothing of the agent.
export type CardView = {
  active: boolean // the card last touched: on top, its wires highlighted
  accepting: boolean // a wire being dragged is over it and it would take it
}
export type CardNode = FlowNode<Card & CardView, 'card'>

const dot = '!size-[11px] !rounded-full !border-2 !border-card'
// Where a call enters and leaves the graph: a solid band across the card, on
// top of the start node and under an end node, readable at any zoom.
const band = 'flex items-center gap-1.5 px-4 py-1.5 text-[12px] font-medium'
const choice =
  'nodrag flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-left text-[12px] hover:bg-muted'
// A control that only shows when its row or card is pointed at. Where there
// is no pointer to hover with, it is always there.
const hidden =
  'opacity-0 outline-none transition-opacity focus-visible:opacity-100 [@media(hover:none)]:opacity-100'

/**
 * A wire that is missing, drawn as what it is: a short dashed stub in crimson
 * that leaves the dot and ends in the air. Out of an edge with no target, or
 * into a node nothing leads to. It says so in words to a screen reader, and
 * the dot beside it says so on hover.
 */
function LooseWire({ side, className }: { side: 'in' | 'out'; className?: string }) {
  return (
    <span
      data-loose={side}
      className={cn(
        'pointer-events-none absolute flex -translate-y-1/2 items-center',
        // From the outer side of the dot, which hangs half off the card.
        side === 'out' ? 'left-full ml-[12px]' : 'right-full mr-[12px] flex-row-reverse',
        className,
      )}
    >
      <span className="w-[26px] border-t-2 border-dashed border-bad/70" />
      <span className="size-[10px] rounded-full border-2 border-bad/70" />
      <span className="sr-only">Not connected</span>
    </span>
  )
}

export function NodeCard({ data }: NodeProps<CardNode>) {
  const { id, node, start, edges, connected, reached, active, accepting } = data
  const { draft, apply, seal, cancel, refusal } = useEditor()
  // What the backend said when it refused to save, if it was about this node.
  const refused = refusal?.node === id ? refusal : null
  const [instructions, ...more] = node.task_messages ?? []
  // The edge being removed, while it waits for a yes: one with a condition or
  // fields in it asks first. Undo would bring it back, but only if noticed.
  const [removing, setRemoving] = useState<number | null>(null)
  const remove = (index: number) => apply((current) => removeEdge(current, id, index))
  const fields = removing === null ? 0 : Object.keys(edges[removing]?.properties ?? {}).length
  const losing = [
    removing !== null && edges[removing]?.description.trim() ? 'its condition' : null,
    fields > 0 ? (fields === 1 ? 'its field' : `its ${fields} fields`) : null,
  ].filter(Boolean)
  return (
    <div
      data-active={active || undefined}
      data-accepting={accepting || undefined}
      className={cn(
        'group/card relative w-[300px] rounded-2xl border bg-card text-left shadow-[0_1px_2px_rgba(0,0,0,0.04),0_10px_28px_-14px_rgba(0,0,0,0.14)]',
        start && 'border-brand/45',
        active && !start && 'border-foreground/30',
        active && 'shadow-[0_1px_2px_rgba(0,0,0,0.06),0_14px_32px_-12px_rgba(0,0,0,0.22)]',
        refused && 'ring-2 ring-bad',
        // A ring, not the border: it must read on the start card's orange too.
        accepting && 'ring-2 ring-foreground',
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
          title={reached ? undefined : 'Not connected: nothing leads to this node'}
          className={cn(dot, '!top-[26px] !left-[-6px]', reached ? '!bg-muted-foreground' : '!bg-bad')}
        />
      )}
      {/* Nothing leads here: a call can never get to this node. */}
      {!reached && <LooseWire side="in" className="top-[26px]" />}
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
      {/* In the backend's own words: it is the one that knows what it refused. */}
      {refused && (
        <p role="alert" className="border-t border-bad/20 bg-bad/10 px-4 py-2 text-[12px] leading-snug text-bad">
          {refused.message}
        </p>
      )}
      {node.end ? (
        <div className={cn(band, 'rounded-b-[15px] bg-foreground text-background')}>
          <PhoneOff className="size-3" /> The call ends here
          {/* The way back from "End the call here", where it was chosen. Always
              shown, faint: on the band there is nothing else to find it by. */}
          <button
            aria-label="Don't end the call here"
            title="Don't end the call here"
            onClick={() => apply((current) => setEnd(current, id, false))}
            className="nodrag -my-0.5 -mr-1.5 ml-auto rounded p-1 opacity-60 outline-none transition-opacity hover:bg-background/15 hover:opacity-100 focus-visible:bg-background/15 focus-visible:opacity-100"
          >
            <RotateCcw className="size-3" />
          </button>
        </div>
      ) : (
        <div className="rounded-b-2xl border-t bg-muted/35 pb-1.5">
          {edges.length > 0 && (
            <div className="px-4 pt-2.5 text-[10.5px] font-medium tracking-wide text-muted-foreground uppercase">
              Moves on when
            </div>
          )}
          {edges.map((edge, index) => (
            // One block per edge, with a line between them: an edge is a
            // condition, what it collects and where it goes, read together.
            <div
              key={index}
              className={cn(
                'group/edge relative px-4 py-2.5',
                index > 0 && 'border-t border-border/70',
                // The edge the refusal is about, when it names one.
                refused?.edge === index && 'shadow-[inset_3px_0_0_var(--bad)]',
              )}
            >
              <div className="flex items-start gap-1.5">
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
              </div>
              <FieldChips
                id={id}
                index={index}
                edge={edge}
                trailing={
                  // At the end of the chips row, shaped like the "+" that adds
                  // a field: the same place for every edge, and away from the
                  // dot, where a slip would be a wire dragged.
                  <button
                    aria-label="Remove this way to move on"
                    title="Remove this way to move on"
                    onClick={() => (edgeIsEmpty(edge) ? remove(index) : setRemoving(index))}
                    className={cn(
                      hidden,
                      'nodrag inline-flex size-[23px] items-center justify-center rounded-full border border-dashed border-foreground/20 text-muted-foreground group-hover/edge:opacity-100 hover:border-bad/50 hover:text-bad focus-visible:border-bad/50',
                    )}
                  >
                    <Trash2 className="size-3" />
                  </button>
                }
              />
              {!connected[index] && <LooseWire side="out" className="top-[25px]" />}
              <Handle
                id={handleId(index)}
                type="source"
                position={Position.Right}
                isConnectableEnd={false}
                title={connected[index] ? undefined : 'Not connected: drag it to a node'}
                className={cn(
                  dot,
                  // Level with the first line of the description.
                  '!top-[25px] !right-[-6px]',
                  connected[index] ? '!bg-foreground' : '!bg-bad',
                )}
              />
            </div>
          ))}
          {edges.length > 0 ? (
            <button
              onClick={() => apply((current) => addEdge(current, id))}
              className="nodrag flex w-full items-center gap-1 border-t border-border/70 px-4 pt-2 pb-1 text-[12px] text-muted-foreground/80 hover:text-foreground"
            >
              <Plus className="size-3" /> Another way to move on
            </button>
          ) : (
            // A node with no way out and no end is where a call would stay
            // for good. The card asks the question instead of leaving a gap:
            // the two answers are the two things a node can do next.
            <div className="px-2.5 pt-2.5 pb-1">
              <div className="px-1.5 pb-1 text-[10.5px] font-medium tracking-wide text-muted-foreground uppercase">
                What happens next?
              </div>
              <button onClick={() => apply((current) => addEdge(current, id))} className={choice}>
                <ArrowRight className="size-3.5 text-muted-foreground" /> Move on to another step
              </button>
              <button onClick={() => apply((current) => setEnd(current, id, true))} className={choice}>
                <PhoneOff className="size-3.5 text-muted-foreground" /> End the call here
              </button>
            </div>
          )}
        </div>
      )}
      <AlertDialog open={removing !== null} onOpenChange={(open) => !open && setRemoving(null)}>
        <AlertDialogContent size="sm">
          <AlertDialogHeader>
            <AlertDialogTitle>Remove this way to move on?</AlertDialogTitle>
            <AlertDialogDescription>
              {losing.join(' and ').replace(/^i/, 'I')} will be removed with it.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => removing !== null && remove(removing)}
            >
              Remove
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
