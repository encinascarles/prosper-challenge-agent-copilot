// The canvas: the draft's graph drawn with React Flow, one card per node and
// one wire per connected edge.
//
// React Flow only draws. What the graph is and where the cards are comes from
// the draft; what React Flow knows on its own is kept here and is not worth
// undoing: the size it measured for each card, a drag in progress, and the
// routes of the wires from the last layout.
//
// Cards are as tall as their text, so the layout needs their real size: the
// graph renders once out of sight, React Flow measures the cards and their
// dots, ELK places them and routes the wires, and only then is the canvas
// shown. After that the layout runs only on "Tidy up": editing makes a card
// grow where it is, and nothing else moves.

import {
  Background,
  BackgroundVariant,
  Controls,
  ReactFlow,
  ReactFlowProvider,
  useNodesInitialized,
  useReactFlow,
  type NodeChange,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { LayoutGrid } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { moveNode, setLayout, type Point } from '@/draft/draft'
import { useEditor } from '@/draft/editor'
import { cn } from '@/lib/utils'

import { layoutGraph, type Box } from './layout'
import { toGraph } from './model'
import { NodeCard, type CardNode } from './NodeCard'
import { RoutedWire, type WireEdge } from './RoutedWire'

const nodeTypes = { card: NodeCard }
const edgeTypes = { wire: RoutedWire }
const TIDY_MS = 300

const ORIGIN = { x: 0, y: 0 }

function Canvas() {
  const { draft, apply, place } = useEditor()
  const flow = useReactFlow<CardNode, WireEdge>()
  const graph = useMemo(() => toGraph(draft.config, draft.ids), [draft.config, draft.ids])
  const [sizes, setSizes] = useState<Record<string, { width: number; height: number }>>({})
  const [dragging, setDragging] = useState<Record<string, Point>>({})
  const [routes, setRoutes] = useState<Record<string, Point[]>>({})

  const nodes = useMemo<CardNode[]>(
    () =>
      graph.cards.map((card) => ({
        id: card.id,
        type: 'card',
        position: dragging[card.id] ?? draft.layout[card.node.name] ?? ORIGIN,
        measured: sizes[card.id],
        data: card,
      })),
    [graph, draft.layout, dragging, sizes],
  )
  const edges = useMemo<WireEdge[]>(
    () =>
      graph.wires.map((wire) => ({
        id: wire.id,
        type: 'wire',
        source: wire.source,
        sourceHandle: wire.handle,
        target: wire.target,
        data: { route: routes[wire.id] },
      })),
    [graph, routes],
  )

  const onNodesChange = useCallback((changes: NodeChange<CardNode>[]) => {
    for (const change of changes) {
      if (change.type === 'dimensions' && change.dimensions) {
        const { id, dimensions } = change
        setSizes((current) => ({ ...current, [id]: dimensions }))
      } else if (change.type === 'position' && change.position) {
        const { id, position } = change
        setDragging((current) => ({ ...current, [id]: position }))
      }
    }
  }, [])
  // A drag becomes one edit when the card is dropped, not one per pixel.
  const onNodeDragStop = useCallback(
    (_: unknown, __: CardNode, dropped: CardNode[]) => {
      apply((current) =>
        dropped.reduce((moved, node) => moveNode(moved, node.id, node.position), current),
      )
      setDragging({})
    },
    [apply],
  )

  // A layout asks for the view to be fitted to it, with this animation time.
  // The fitting waits for the render that carries the new positions: fitted
  // any sooner, on a busy machine, the view frames the cards where they were.
  const fitting = useRef<number | null>(null)
  useEffect(() => {
    const duration = fitting.current
    if (duration === null) return
    fitting.current = null
    void flow.fitView({ padding: 0.15, maxZoom: 1, duration })
  }, [draft.layout, flow])

  const measured = useNodesInitialized()
  const [placed, setPlaced] = useState(false)
  const [animating, setAnimating] = useState(false)

  const tidy = useCallback(
    async (duration: number, first = false) => {
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
      const byName = Object.fromEntries(
        graph.cards.flatMap((card) =>
          layout.positions[card.id] ? [[card.node.name, layout.positions[card.id]]] : [],
        ),
      )
      fitting.current = duration
      setAnimating(duration > 0)
      // The first layout is where the cards are; "Tidy up" is an edit to undo.
      if (first) place(byName)
      else apply((current) => setLayout(current, byName))
      setRoutes(layout.routes)
      if (duration > 0) setTimeout(() => setAnimating(false), duration)
      setPlaced(true)
    },
    [graph, flow, apply, place],
  )

  useEffect(() => {
    // The first layout waits for React Flow's measurements, and `tidy` only
    // sets state after ELK answers, never during the effect.
    // oxlint-disable-next-line react/set-state-in-effect
    if (measured && !placed) void tidy(0, true)
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
        onNodeDragStop={onNodeDragStop}
        nodesConnectable={false}
        elementsSelectable={false}
        // Nodes are deleted from their menu. A key would also fire while typing.
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

/** The graph of the draft being edited. It lays the graph out once, when it opens. */
export function GraphCanvas() {
  return (
    <ReactFlowProvider>
      <Canvas />
    </ReactFlowProvider>
  )
}
