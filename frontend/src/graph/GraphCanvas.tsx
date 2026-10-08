// The canvas: an agent's graph drawn with React Flow, one card per node and
// one wire per connected edge.
//
// Cards are as tall as their text, so the layout needs their real size: the
// graph renders once out of sight, React Flow measures the cards and their
// dots, ELK places them and routes the wires, and only then is the canvas
// shown. "Tidy up" runs the same layout again. Dragging moves a card on screen
// only: nothing is saved yet.

import {
  Background,
  BackgroundVariant,
  Controls,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesInitialized,
  useNodesState,
  useReactFlow,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { LayoutGrid } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'

import type { AgentConfig } from '@/agents/types'
import { cn } from '@/lib/utils'

import { layoutGraph, type Box } from './layout'
import { newIds, toGraph } from './model'
import { NodeCard, type CardNode } from './NodeCard'
import { RoutedWire, type WireEdge } from './RoutedWire'

const nodeTypes = { card: NodeCard }
const edgeTypes = { wire: RoutedWire }
const TIDY_MS = 300

function Canvas({ config }: { config: AgentConfig }) {
  const flow = useReactFlow<CardNode, WireEdge>()
  const [ids] = useState(() => newIds(config))
  const graph = useMemo(() => toGraph(config, ids), [config, ids])
  const [nodes, setNodes, onNodesChange] = useNodesState<CardNode>(
    graph.cards.map((card) => ({
      id: card.id,
      type: 'card',
      position: { x: 0, y: 0 },
      data: card,
    })),
  )
  const [edges, setEdges] = useEdgesState<WireEdge>(
    graph.wires.map((wire) => ({
      id: wire.id,
      type: 'wire',
      source: wire.source,
      sourceHandle: wire.handle,
      target: wire.target,
      data: {},
    })),
  )
  const measured = useNodesInitialized()
  const [placed, setPlaced] = useState(false)
  const [animating, setAnimating] = useState(false)

  const tidy = useCallback(
    async (duration: number) => {
      // Each card as React Flow measured it, with the height of every dot.
      const boxes: Record<string, Box> = {}
      for (const card of graph.cards) {
        const internal = flow.getInternalNode(card.id)
        const handles = internal?.internals.handleBounds
        const middle = (handle: { y: number; height: number }) => handle.y + handle.height / 2
        boxes[card.id] = {
          width: internal?.measured.width ?? 0,
          height: internal?.measured.height ?? 0,
          inY: handles?.target?.[0] && middle(handles.target[0]),
          outY: Object.fromEntries(
            (handles?.source ?? []).map((handle) => [handle.id, middle(handle)]),
          ),
        }
      }
      const layout = await layoutGraph(graph, boxes)
      setAnimating(duration > 0)
      setNodes((current) =>
        current.map((node) => ({ ...node, position: layout.positions[node.id] ?? node.position })),
      )
      setEdges((current) =>
        current.map((edge) => ({ ...edge, data: { route: layout.routes[edge.id] } })),
      )
      // After React Flow has taken the new positions, so the view fits them.
      requestAnimationFrame(() => void flow.fitView({ padding: 0.15, maxZoom: 1, duration }))
      if (duration > 0) setTimeout(() => setAnimating(false), duration)
      setPlaced(true)
    },
    [graph, flow, setNodes, setEdges],
  )

  useEffect(() => {
    // The first layout waits for React Flow's measurements, and `tidy` only
    // sets state after ELK answers, never during the effect.
    // oxlint-disable-next-line react/set-state-in-effect
    if (measured && !placed) void tidy(0)
  }, [measured, placed, tidy])

  return (
    <div className={cn('relative size-full bg-muted/40', animating && 'graph-tidying')}>
      <ReactFlow
        className={cn('transition-opacity', placed ? 'opacity-100' : 'opacity-0')}
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodesChange={onNodesChange}
        // Read-only for now: cards move, nothing else changes.
        nodesConnectable={false}
        elementsSelectable={false}
        deleteKeyCode={null}
        minZoom={0.3}
        maxZoom={1.5}
      >
        <Background variant={BackgroundVariant.Dots} gap={20} size={1.2} color="var(--border-strong)" />
        <Controls showInteractive={false} position="bottom-left" />
      </ReactFlow>
      <div className="absolute top-4 left-1/2 z-10 -translate-x-1/2 rounded-xl border bg-card p-1 shadow-sm">
        <button
          onClick={() => void tidy(TIDY_MS)}
          className="flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-[13px] text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          <LayoutGrid className="size-3.5" /> Tidy up
        </button>
      </div>
    </div>
  )
}

/** The graph of `config`. Mount it with a `key` per agent: it lays the graph out once, when it opens. */
export function GraphCanvas({ config }: { config: AgentConfig }) {
  return (
    <ReactFlowProvider>
      <Canvas config={config} />
    </ReactFlowProvider>
  )
}
