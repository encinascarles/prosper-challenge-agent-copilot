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
  type Connection,
  type EdgeChange,
  type FinalConnectionState,
  type NodeChange,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { LayoutGrid, Plus } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { addNode, connect, moveNode, newNodeId, setLayout, type Point } from '@/draft/draft'
import { useEditor } from '@/draft/editor'
import { cn } from '@/lib/utils'

import { layoutGraph, type Box } from './layout'
import { edgeIndex, toGraph } from './model'
import { NodeCard, type CardNode } from './NodeCard'
import { freeSpot } from './place'
import { RoutedWire, type WireEdge } from './RoutedWire'

const nodeTypes = { card: NodeCard }
const edgeTypes = { wire: RoutedWire }
const TIDY_MS = 300
const tool =
  'flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-[13px] text-muted-foreground hover:bg-muted hover:text-foreground'

const ORIGIN = { x: 0, y: 0 }
const DELETE_KEYS = ['Backspace', 'Delete']
// A new card before it is measured: its width, and the height of an empty one.
const NEW_CARD = { width: 300, height: 130 }
// Where a card's input dot is, from its top-left corner.
const INPUT_DOT = { x: -6, y: 26 }

function Canvas() {
  const { draft, apply, place } = useEditor()
  const flow = useReactFlow<CardNode, WireEdge>()
  const graph = useMemo(() => toGraph(draft.config, draft.ids), [draft.config, draft.ids])
  const [sizes, setSizes] = useState<Record<string, { width: number; height: number }>>({})
  const [dragging, setDragging] = useState<Record<string, Point>>({})
  // The route of each wire from the last layout, and the card it led to then:
  // a wire that now goes elsewhere has no use for it.
  const [routes, setRoutes] = useState<Record<string, { target: string; points: Point[] }>>({})
  const [selected, setSelected] = useState<Record<string, boolean>>({})
  const wrapper = useRef<HTMLDivElement>(null)
  // The node just added, until its name has the focus.
  const fresh = useRef<string | null>(null)

  const nodes = useMemo<CardNode[]>(
    () =>
      graph.cards.map((card) => ({
        id: card.id,
        type: 'card',
        position: dragging[card.id] ?? draft.layout[card.node.name] ?? ORIGIN,
        measured: sizes[card.id],
        data: card,
        // Only wires are selected, to disconnect them. A node is deleted from its menu.
        selectable: false,
        deletable: false,
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
        selected: selected[wire.id] ?? false,
        data: { route: routes[wire.id]?.target === wire.target ? routes[wire.id].points : undefined },
      })),
    [graph, routes, selected],
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
  // Adds a node at `position` and hands the keyboard to its name. Nothing
  // else moves: the layout only runs on "Tidy up".
  const add = useCallback(
    (position: Point, from?: { id: string; index: number }) => {
      const id = newNodeId()
      apply((current) => addNode(current, id, position, from))
      fresh.current = id
    },
    [apply],
  )
  const addAtCenter = () => {
    const view = wrapper.current?.getBoundingClientRect()
    if (!view) return
    const center = flow.screenToFlowPosition({
      x: view.left + view.width / 2,
      y: view.top + view.height / 2,
    })
    const taken = nodes.map((node) => ({ ...node.position, ...(sizes[node.id] ?? NEW_CARD) }))
    add(freeSpot(center, NEW_CARD, taken))
  }
  // React Flow keeps a card hidden until it has measured it, and a hidden
  // input cannot take the focus: so this waits for the new card's size.
  useEffect(() => {
    const id = fresh.current
    if (id === null || !(id in sizes)) return
    fresh.current = null
    const name = wrapper.current?.querySelector<HTMLInputElement>(
      `.react-flow__node[data-id="${id}"] input[aria-label="Node name"]`,
    )
    name?.focus()
    name?.select()
  }, [sizes])

  const onEdgesChange = useCallback((changes: EdgeChange<WireEdge>[]) => {
    for (const change of changes) {
      if (change.type === 'select') {
        const { id, selected: on } = change
        setSelected((current) => ({ ...current, [id]: on }))
      }
    }
  }, [])
  // Backspace or Delete on a selected wire: the edge stays, with no target.
  const onEdgesDelete = useCallback(
    (deleted: WireEdge[]) => {
      apply((current) =>
        deleted.reduce(
          (next, wire) =>
            wire.sourceHandle ? connect(next, wire.source, edgeIndex(wire.sourceHandle), null) : next,
          current,
        ),
      )
      setSelected({})
    },
    [apply],
  )
  // A wire dropped on a card's input dot.
  const onConnect = useCallback(
    ({ source, sourceHandle, target }: Connection) => {
      if (sourceHandle) apply((current) => connect(current, source, edgeIndex(sourceHandle), target))
    },
    [apply],
  )
  // A wire dropped anywhere else. On a card it connects to that card: the
  // whole card is the target, not only its dot.
  const onConnectEnd = useCallback(
    (event: MouseEvent | TouchEvent, connection: FinalConnectionState) => {
      const from = connection.fromHandle
      if (connection.isValid || !connection.fromNode || from?.type !== 'source' || !from.id) return
      const { clientX, clientY } = 'changedTouches' in event ? event.changedTouches[0] : event
      const under = document.elementFromPoint(clientX, clientY)
      const card = under?.closest<HTMLElement>('.react-flow__node')?.dataset.id
      const source = connection.fromNode.id
      const index = edgeIndex(from.id)
      if (card) {
        apply((current) => connect(current, source, index, card))
      } else if (under?.closest('.react-flow__pane')) {
        // On empty canvas: a new node there, its input dot under the pointer.
        const drop = flow.screenToFlowPosition({ x: clientX, y: clientY })
        add({ x: drop.x - INPUT_DOT.x, y: drop.y - INPUT_DOT.y }, { id: source, index })
      }
    },
    [apply, add, flow],
  )
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
      setRoutes(
        Object.fromEntries(
          graph.wires.flatMap((wire) =>
            layout.routes[wire.id]
              ? [[wire.id, { target: wire.target, points: layout.routes[wire.id] }]]
              : [],
          ),
        ),
      )
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
    <div ref={wrapper} className={cn('relative size-full bg-muted/40', animating && 'graph-tidying')}>
      <ReactFlow
        className={cn('transition-opacity', placed ? 'opacity-100' : 'opacity-0')}
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodesChange={onNodesChange}
        onNodeDragStop={onNodeDragStop}
        onEdgesChange={onEdgesChange}
        onEdgesDelete={onEdgesDelete}
        onConnect={onConnect}
        onConnectEnd={onConnectEnd}
        connectionLineStyle={{ stroke: 'var(--foreground)', strokeWidth: 1.5 }}
        // For a selected wire. React Flow ignores these keys while typing in an input.
        deleteKeyCode={DELETE_KEYS}
        minZoom={0.3}
        maxZoom={1.5}
      >
        <Background variant={BackgroundVariant.Dots} gap={20} size={1.2} color="var(--border-strong)" />
        <Controls showInteractive={false} position="bottom-left" />
      </ReactFlow>
      <div className="absolute top-4 left-1/2 z-10 flex -translate-x-1/2 items-center gap-0.5 rounded-xl border bg-card p-1 shadow-sm">
        <button onClick={addAtCenter} className={tool}>
          <Plus className="size-3.5" /> Add node
        </button>
        <span className="mx-1 h-5 w-px bg-border" />
        <button onClick={() => void tidy(TIDY_MS)} className={tool}>
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
