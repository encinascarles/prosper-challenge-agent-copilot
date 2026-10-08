// The card of one node on the canvas.
//
// Everything a node says is on its card, so the graph reads without opening
// anything: the name, the instructions, and under "Moves on when" one row per
// edge. A row carries its own source dot, which is where its wire leaves from;
// the wire shows the target, so the row does not repeat it. The start node and
// the end nodes carry a band saying what they are.
//
// The card speaks the deployment team's language, not the schema's: names are
// shown as words ("Collect details" for collect_details) and an edge's function
// name is not shown at all. It is plumbing for the model; the condition is what
// a person reads.

import { Handle, Position, type Node as FlowNode, type NodeProps } from '@xyflow/react'
import { PhoneOff, Play } from 'lucide-react'

import type { Edge } from '@/agents/types'
import { humanize } from '@/draft/names'
import { cn } from '@/lib/utils'

import { handleId, type Card } from './model'

export type CardNode = FlowNode<Card, 'card'>

const dot = '!size-[11px] !rounded-full !border-2 !border-card'
// Where a call enters and leaves the graph: a solid band across the card, on
// top of the start node and under an end node, readable at any zoom.
const band = 'flex items-center gap-1.5 px-4 py-1.5 text-[12px] font-medium'

/** The fields an edge collects, as chips. An enum shows its options inline. */
function Fields({ edge }: { edge: Edge }) {
  const fields = Object.entries(edge.properties ?? {})
  if (fields.length === 0) return null
  return (
    <div className="mt-1 flex flex-wrap items-center gap-1">
      {fields.map(([name, property]) => (
        <span
          key={name}
          title={property.description}
          className="inline-flex items-center gap-1 rounded-full border bg-card px-2 py-0.5 text-[11.5px]"
        >
          <span className="font-medium">{humanize(name)}</span>
          {property.enum && property.enum.length > 0 && (
            <span className="text-muted-foreground">{property.enum.join(' · ')}</span>
          )}
          {!edge.required?.includes(name) && (
            <span className="text-muted-foreground">optional</span>
          )}
        </span>
      ))}
    </div>
  )
}

export function NodeCard({ data }: NodeProps<CardNode>) {
  const { node, start, edges, connected } = data
  const instructions = (node.task_messages ?? []).map((message) => message.content)
  return (
    <div
      className={cn(
        'w-[300px] rounded-2xl border bg-card text-left shadow-[0_1px_2px_rgba(0,0,0,0.04),0_10px_28px_-14px_rgba(0,0,0,0.14)]',
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
          isConnectable={false}
          className={cn(dot, '!top-[26px] !left-[-6px] !bg-muted-foreground')}
        />
      )}
      <div className="truncate px-4 pt-3.5 text-[14px] font-semibold tracking-[-0.01em]">
        {humanize(node.name)}
      </div>
      <div className="space-y-1.5 px-4 pt-1 pb-3.5 text-[13px] leading-[1.5] text-foreground/70">
        {instructions.length === 0 && <p className="italic">No instructions</p>}
        {instructions.map((content, index) => (
          <p key={index} className="whitespace-pre-wrap">
            {content}
          </p>
        ))}
      </div>
      {node.end ? (
        <div className={cn(band, 'rounded-b-[15px] bg-foreground text-background')}>
          <PhoneOff className="size-3" /> The call ends here
        </div>
      ) : (
        edges.length > 0 && (
          <div className="rounded-b-2xl border-t bg-muted/35 pb-1.5">
            <div className="px-4 pt-2.5 pb-0.5 text-[10.5px] font-medium tracking-wide text-muted-foreground uppercase">
              Moves on when
            </div>
            {edges.map((edge, index) => (
              <div key={index} className="relative px-4 py-1.5">
                <p className="text-[12.5px] leading-snug">{edge.description}</p>
                <Fields edge={edge} />
                {!connected[index] && (
                  <div className="mt-1 text-[11.5px] font-medium text-bad">Not connected</div>
                )}
                <Handle
                  id={handleId(index)}
                  type="source"
                  position={Position.Right}
                  isConnectable={false}
                  className={cn(
                    dot,
                    '!top-[17px] !right-[-6px]',
                    connected[index] ? '!bg-foreground' : '!bg-bad',
                  )}
                />
              </div>
            ))}
          </div>
        )
      )}
    </div>
  )
}
