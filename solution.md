# Solution

> Work in progress. This document grows with each PR: every key decision is
> recorded here in the same PR that implements it.

## The problem, as I read it

Prosper's deployment team spends its time on two manual loops:

1. **Initial implementation.** A clinic hands over natural-language guidelines
   (how to greet, what to collect, when to escalate, which visits need what) and
   someone translates them into a working agent graph.
2. **Production iteration.** Clients flag issues, or issues hide in call data.
   Someone has to find them, work out which part of the agent caused them, change
   it, and make sure the fix does not break something else. Finding the issues is
   itself a large part of the cost.

The builder UI (Phase 1) is the surface; the Copilot (Phase 2) is the point. The
measure of success is how much of those two loops it takes off the team's hands.

## Scope

_What is built, what is mocked, and what is deliberately left out, with the
reason for each. Filled in as the build progresses._

## Architecture

_Overview diagram and the main components. Filled in as the build progresses._

## Key decisions

### Frontend: Vite + React + TypeScript SPA

**Context.** The backend already exists in Python: Pipecat's FastAPI server runs
the voice pipeline, and the Copilot has to live next to `AgentBuilder` to work on
the real agent format. The UI needs a graph editor and an in-page WebRTC call.

**Options.**
- *Full-stack JS framework (Next.js, Remix).* Rejected: it brings a second server
  runtime, and logic would split between TypeScript and Python for no gain.
- *Python UI (Streamlit, Gradio).* Rejected: no native graph editor (React Flow
  would have to be wrapped anyway), a rerun-per-interaction model that fights a
  stateful canvas plus a live call, and weak WebRTC integration.
- *Client-only React SPA built with Vite.* Chosen.

**Trade-offs.** Minimal tooling and one backend. The dev server proxies `/api` to
FastAPI, so the browser sees one origin. Direct access to React Flow and Pipecat's
React client. Cost: two dev servers locally, hidden behind `make dev`.

**Styling: Tailwind + shadcn/ui.** The brief values judgement over polish, so the
UI should look decent at near-zero design cost. shadcn copies accessible
components into the repo (owned code, no runtime component library).

### Storage: SQLite, with the agent JSON in one column

**Context.** Agents have to survive a restart and be listed, opened and saved by
the editor. Phase 2 adds calls, issues and tests that point at agents.

**Options.**
- *JSON files, one per agent.* Rejected: enough for today, but calls and issues
  need queries across records ("the calls of this agent with an open issue"), and
  that would mean moving everything later.
- *A hosted database (Postgres).* Rejected: a server to install and configure
  before the reviewer can run anything, for a single-process app.
- *SQLite through the stdlib `sqlite3` module.* Chosen.

**Trade-offs.** Zero setup and no new dependency: the file is created and seeded
with the example agent on first start. No ORM and no migrations tool, which is
fine for one table and will need revisiting if the schema grows. The agent is
stored whole in one TEXT column, as `AgentConfig` reads it: nothing queries inside
the graph, so tables for nodes and edges would only be a mapping to keep in sync.
Deleting an agent removes its row for good: there are no versions yet to bring
it back from, so the editor asks first. Only a database that is being created is
seeded. One whose last agent was deleted stays empty, or the example would come
back on its own at the next start.

### Node positions live next to the agent, not in it

**Context.** The editor has to reopen a graph the way it was left, so where each
node sits must be saved. The agent JSON is what Pipecat runs and what the Copilot
reads and rewrites.

**Options.**
- *A `position` on each node of the agent JSON.* Rejected: a canvas coordinate is
  not part of an agent. It would reach the schema, the builder and every prompt
  that carries the agent, and moving a node would count as changing the agent.
- *The browser's local storage.* Rejected: the arrangement would be lost on
  another device, and it is part of how the team reads a flow.
- *A `layout` column next to `config`: `{ "<node name>": { "x", "y" } }`.* Chosen.

**Trade-offs.** Creating and saving an agent take the same body,
`{ config, layout? }`, and both are written in one statement, so they cannot be
saved apart. The store drops positions of
names that are not nodes of the agent on every save, with or without a layout in
the request, so the layout never refers to a node that is gone. A client that
leaves the layout out (the Copilot applying a fix) keeps the stored one; a node
without a position is fine, the editor places it. Cost: the layout is keyed by
node name, so a rename has to carry the position over, which is the editor's job
since it knows the old name. Existing databases get the column added at startup
(a check on `PRAGMA table_info`), the one migration so far and still short of
needing a tool.

### The API lives on Pipecat's FastAPI app

**Context.** The Pipecat runner already starts a FastAPI server for the call
signalling, and exposes its `app` for extra routes.

**Options.**
- *A second service for the builder API.* Rejected: two processes and two ports
  to run, and CORS between them.
- *Mount an `APIRouter` on the runner's app.* Chosen.

**Trade-offs.** One backend, one port and one origin for the browser: calls and
agents go through the same `/api`. `bot.py` only does the wiring; the routes are
in `api/` and persistence in `store/`. The bot runs in the same process, so it
reads the agent a call was started for (and will save its calls) straight through `store`,
with no HTTP between services. Cost: the API starts with the runner, so
it is tied to how Pipecat builds its app. The tests avoid that by mounting the
same router on a bare FastAPI app.

### Validation errors say where the problem is

**Context.** An agent is saved only if `AgentBuilder` accepts it, the same code
that compiles the graph for a call. Its message is what the API returns, so it
has to be usable: the editor points at the broken node with it, and the Copilot
will read it to repair its own output.

**Options.**
- *Catch `KeyError` / `TypeError` in the API.* Rejected: `KeyError: 'name'` cannot
  say whether the agent, a node or an edge is missing its name.
- *Move the schema to Pydantic.* Rejected: its errors locate by index
  (`nodes.1.edges.0.target`), and it means rewriting the dataclass schema that
  came with the challenge for a gain the builder's graph checks would not share.
- *Check each field in `schema.py` as `from_dict` reads it.* Chosen.

**Trade-offs.** Messages use names, not indexes ("Missing required field 'target'
in edge 'choose_intent' of node 'greeting'."), and everything that loads an agent
gets the same ones. The schema stays one set of dataclasses. Cost: a small
hand-written checker instead of a library, and the request body is an untyped
object in the OpenAPI docs (the example agent is shown instead). The tests pin
each sentence, because they are a contract.

### No agent versioning yet

**Context.** Saving replaces the stored agent. The Copilot will need versions:
a fix is applied as a new version, and a call has to know which one it ran on.

**Choice.** Left out of this API on purpose. Nothing in Phase 1 reads an old
version, and the right shape (what a version records, how calls and fixes refer
to it) depends on the Copilot's loop. It arrives with it.

**Trade-offs.** No undo history for manual edits until then.

### A test call runs the saved agent, and says where it is

**Context.** The editor holds a draft with unsaved changes, and a call has to run
some version of the agent. The bot runs in the backend; the draft only exists in
a browser tab.

**Options.**
- *Send the draft with the call.* Rejected: what was tested would be something
  that was never saved, and the next person to open the agent would not see what
  the call ran on. It also puts a whole agent in the body of a start request.
- *Start the call with the id of a saved agent.* Chosen.

**Trade-offs.** What you test is what goes live: the call reads the agent from
the store when it starts, so a passing test call is about the agent everyone
else sees. Cost: an edit has to be saved before it can be heard, so the editor
blocks the call while there are unsaved changes instead of quietly running the
older agent. A start that names no agent runs the sample flow, which keeps
Pipecat's prebuilt client at `/client` working as a way to check the voice
pipeline alone.

A wrong id fails at `POST /start`, with the same sentence the agents API gives.
The runner owns that route and, for WebRTC, only stores the body: the bot starts
later, on the browser's offer, when an error can no longer be an HTTP answer. So
the check sits in front of the route, as a middleware, and the bot runs it again
for an offer that skipped `/start`.

The call's path reaches the browser as messages on the RTVI channel the client
already has: `{ type: "node", node, from, edge, collected }`, once at the start
and on every node change. Flows has no transition event, but it runs a node's
pre-actions every time the node is entered, so each compiled node opens with a
`node_entered` action carrying those fields and the bot registers the handler
that sends it. That type is reserved: an agent that uses it in its own actions is
refused, with the reason, or its action would be reported as a node change. The builder states the fact and stays free of transports; a text simulation
can register another handler and record the same path. The alternative, reading
Pipecat's own function-call messages in the browser, would have left the UI to
work out the target from a function name and to guess the first node.

### The test call is read on the graph

**Context.** A test call answers "does the agent go where I meant it to?". The
transcript alone does not: the same sentence can come from two nodes, and what
the model passed to an edge is not said aloud.

**Options.**
- *Embed Pipecat's prebuilt client.* Rejected: it shows the conversation and
  nothing of the graph, and it cannot be told which agent to run.
- *A side panel with the call.* Rejected: it takes a third of the canvas from
  the thing the call is read on.
- *Draw the path on the cards, with a small call card floating over the canvas.*
  Chosen.

**Trade-offs.** The cards the call went through carry their step number, the
one it is in pulses, the ones not reached fade; the wires taken turn orange and
the edge that fired is tinted, with the values it collected on its field chips.
The call card holds what the graph cannot: the clock, the steps in order and the
transcript. The view is fitted once, into the space the card leaves, and does
not follow the call: the whole path stays in sight, and a step in the card
frames its node on demand.

The path is one pure reducer over the bot's `node` messages (`call/path.ts`),
so it is tested without a call and nothing in the browser infers a transition.
The transcript is in the same state: the caller's lines are the final
transcriptions, the agent's are the model's text as it is written, one line per
answer. That text is on screen a moment before it is heard and stays whole if
the caller cuts in; for reading a test that is the better side to err on.

The button is disabled, with the reason as its tooltip, while there are unsaved
changes or a warning: the call runs the saved agent, and a flow the checks say
a call cannot get through is not worth a call. While the call card is on
screen, running or ended, the editor is read-only: the path is drawn over this
very graph by node and edge name, and an edit would leave it pointing at what
changed. Closing the card gives the editor back.

Pipecat's JS client and its small WebRTC transport carry the call, the same
protocol as the prebuilt client; not the React bindings, since a handful of
callbacks into one reducer is all the editor needs. It is loaded when the first
call is placed, like ELK: it is 400 kB that most visits never use. A blocked
microphone, a start the backend refuses and a connection that fails each end as
a sentence in the call card, with Again next to it.

### The graph editor: React Flow, laid out and routed by ELK

**Context.** The deployment team has to read an agent's flow at a glance and
later edit it in place. A node can have several edges, and each one matters: it
is a tool the model calls, with its own condition and fields.

**Options.**
- *Canvas by hand (SVG).* Rejected: pan, zoom, drag and wires are most of an
  editor and none of the product.
- *React Flow with dagre for layout.* Rejected: dagre places boxes, not the
  points wires leave from, so the edges of one card cross on the way out.
- *React Flow, with ELK's layered layout and one port per edge.* Chosen.

**Trade-offs.** Each edge is a row of its card with its own dot, and ELK gets
that dot's real position as a fixed port, so wires leave in the order the rows
are read. That needs the cards' real sizes: the graph renders once out of sight,
is measured, then laid out and shown. ELK is 1.4 MB, loaded on first use.

The wires are drawn along ELK's own routes (right angles, rounded), not as
curves from dot to dot: a curve runs under whatever card is in between, and a
flow with a "go back" edge always has one. A route is only right for where the
cards were, so a wire whose ends no longer meet its route (its card was dragged)
falls back to a curve until "Tidy up". Columns are centered on one line rather
than placed to keep wires straight: with one dot per row, straight wires put
each card lower than the one before and a plain chain walks off the screen.

The card shows names as words ("Collect details" for `collect_details`) and
never an edge's function name: that is plumbing for the model, the condition is
what a person reads. The start node has no way in: a call begins there, so an
edge that names it is shown as not connected. Cards have an id of their own on
the canvas, because a name is text that will be edited and cannot also be the
card's identity; the agent JSON is untouched by it. The TypeScript types mirror
`schema.py` by hand, with the same field names: the API takes the agent as an
untyped object, so there is nothing to generate them from, and a schema change
has to be made in both places.

What is missing is drawn, not written: an edge with no target and a node nothing
leads to both end in a short dashed crimson stub, a wire that goes nowhere, so
the gap shows where it is. An edge that goes nowhere also stops a save, in
the editor, before anything is sent: the button then counts the loose wires and
frames them. A node nothing leads to is drawn the same way but saves: the
schema accepts it, and it is how a flow looks halfway through being built. A list of allowed values is a field type of its own,
Choice, though the agent JSON keeps it as a string with an `enum`: a type plus a
separate "only these values" asked for two decisions to say one thing. A node
with no way out and no end is where a call would stay for good, so its card asks
"What happens next?" and offers the two answers, move on to another step or end
the call here. The band that marks an end carries its own way back, next to
where it was chosen.

### Editing happens on a draft, changed by pure functions

**Context.** The editor changes an agent in many small steps (a word in a prompt,
a node made the start), several of which drag other things along, and all of it
has to be undoable. The backend only accepts an agent that is valid as a whole.

**Options.**
- *Let React Flow hold the graph and patch the agent from its events.* Rejected:
  two copies of the truth, and the rules (what a rename updates) end up spread
  over event handlers nobody can test.
- *A state library (Zustand, Redux).* Rejected for now: one agent open at a time
  and one screen reading it do not need one.
- *A draft in a reducer, edited by pure functions; React Flow only draws it.*
  Chosen.

**Trade-offs.** The draft is the agent JSON, an id per node and the card
positions by that id (they are stored by node name; keeping them by id is what
lets a rename carry the position). Each edit is a function from a draft to the next
(`draft/draft.ts`), so every rule is in one place with a test: renaming a node
updates the edges into it, its position and the agent's start; making a node the
start disconnects the edges into it; a deleted node leaves the edges into it
waiting for a target rather than deleting someone's condition. Fields the editor
does not show (`role_message`, pre and post actions, later task messages) pass
through untouched, so opening and saving never loses what the Copilot wrote.

Function names are generated, never typed or shown: `go_to_<target>`, numbered
when a node has two edges to the same place, regenerated when the target changes
or is renamed. They are the tool names the model sees, so they stay meaningful
without asking a deployment person to invent an identifier.

Changing the structure never runs the layout. A node added by hand goes where
it was dropped, or to the free spot nearest the middle of the view, and every
other card stays where someone put it; a new or retargeted wire is a plain curve
until "Tidy up", because ELK routes wires only as part of a full layout. The
start node takes no wire, in the draft and on the canvas, and a wire dropped
anywhere on a card connects to it.

Which card is on top is not part of the agent, so it is not in the draft: the
card last touched comes up and stays there, and its wires are highlighted, over
the other wires and under the cards like all of them. It is how the canvas is
being looked at, and undo and save never see it.

Saving sends the whole agent and its layout in one request, and the backend
stores both or neither. "Unsaved changes" is the draft not being the very one
that was loaded or last saved, so a save moves a marker and leaves undo alone,
and undoing back to the saved draft is clean again. When the backend refuses, its
422 carries the node's name and the edge's function as fields next to the
sentence: the editor marks that card and shows the sentence on it, without
reading names back out of text that may be reworded. The sentence is the
backend's own, so it is the one place a function name can reach the screen.

Saving is never blocked by unfinished work, only by what the backend refuses.
A node with no way out, a node no call can reach and a flow with no reachable
end are all valid agents, and they are what building one looks like, so they are
warnings: a quiet line on the card and a count next to Save. Running is what
they block. The checks are one pure function with the sentences in it
(`draft/checks.ts`), so the editor and whatever starts a call say the same thing
about the same draft. A loop is not a warning: some path has to end the call,
not every path.

Undo keeps whole drafts instead of inverse operations: an edit shares what it
does not touch with the draft before, so a snapshot is cheap and undo cannot
disagree with the edit. Typing in one field is one step. Cost: nothing is saved
until the save lands, and the browser's own undo inside a text field is replaced
by the editor's.

## How this was built

- Built with AI coding agents (Claude). `AGENTS.md` gives every coding agent the same context:
  goal, invariants, conventions and git workflow.
- Every change lands through a PR with CI (ruff) and an automated Claude review
  whose instructions are versioned in `.github/workflows/claude-review.yml`.
- PRs merge with merge commits, so the history shows how the work progressed.

## Demo

_The end-to-end walkthrough used in the review._

## Limitations and next steps

_Filled in at the end._
