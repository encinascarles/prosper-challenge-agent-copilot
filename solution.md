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

### The API lives on Pipecat's FastAPI app

**Context.** The Pipecat runner already starts a FastAPI server for the call
signalling, and exposes its `app` for extra routes.

**Options.**
- *A second service for the builder API.* Rejected: two processes and two ports
  to run, and CORS between them.
- *Mount an `APIRouter` on the runner's app.* Chosen.

**Trade-offs.** One backend, one port and one origin for the browser: calls and
agents go through the same `/api`. `bot.py` only does the wiring; the routes are
in `api/` and persistence in `store/`. Cost: the API starts with the runner, so
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
