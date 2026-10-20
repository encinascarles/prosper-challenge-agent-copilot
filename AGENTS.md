# AGENTS.md

Context for any coding agent (Claude Code, Codex, Cursor...) working in this repo.
`CLAUDE.md` only imports this file, so there is one source of truth.

## What we are building

Prosper's deployment team turns a clinic's natural-language guidelines into voice
agents, then keeps fixing them as issues show up in real calls. Both steps are
manual today, and even spotting the issues in call data is slow.

This repo is a take-home challenge with two parts:

1. **Agent builder (Phase 1).** A minimal UI to create and edit an agent's node
   graph and place a test call against it.
2. **Agent Copilot (Phase 2), the core of the work.** An AI assistant inside that
   UI that builds agents from guidelines and iterates on them from production
   feedback, the way coding agents iterate on software.

What matters, in order: a Copilot that removes real manual work from the deployment
team, sound judgement on what to build / mock / skip, and a live end-to-end demo.
UI polish and feature breadth matter little. Prefer the simplest thing that works.

Brief: https://shrouded-oriole-c5b.notion.site/Product-Engineer-Challenge-388939c8708780e39ea0f37d6823dc3a
Design decisions and their rationale live in `solution.md`.

## Repo map

| Path | Responsibility |
| --- | --- |
| `backend/bot.py` | Voice pipeline (WebRTC + ElevenLabs STT/TTS + OpenAI LLM). Generic: loads an agent JSON and runs it. No graph logic here. |
| `backend/agent_builder/schema.py` | The agent contract: `AgentConfig` / `Node` / `Edge`. What the UI edits and the Copilot reads and writes. |
| `backend/agent_builder/builder.py` | `AgentBuilder`: validates an agent and compiles it into a Pipecat Flows graph. |
| `frontend/` | Agent Builder UI (sections Build · Calls · Issues · Pull requests; `src/live/` is Calls and Issues; `src/ask/` the Ask Prosper AI panel): Vite + React + TypeScript, Tailwind, shadcn/ui. `src/components/ui/` is shadcn-generated, add components with `npx shadcn@latest add <name>` rather than hand-editing. |
| `backend/store/` | SQLite persistence, one module per thing stored: agents, versions, pull requests, runs, Prosper AI's work, calls and issues, the voice test calls placed from Build, and chats with Prosper AI. |
| `backend/api/` | The HTTP API on the Pipecat runner's FastAPI app; `live.py` serves calls, test calls and issues; `calls.py` says which agent a voice call runs and records it as a test call; `ask.py` serves chats with Prosper AI, and `tools.py` is what Prosper AI can read and do in them, each act a call to the route the UI uses. |
| `backend/simulate/` | Tests as text calls on the same Pipecat pipeline as voice calls: simulated caller, checks, the suite (3 runs per test). Unit tests use a scripted LLM, never OpenAI. |
| `backend/copilot/` | Prosper AI: builds a new agent from a clinic's guidelines inside its PR #1 (`setup.py`, a background job) and takes requests in that PR. One structured OpenAI request per artifact (`llm.py`), checked in code and retried with the error (`artifacts.py`); prompts in `prompts/*.md`; text from PDF/Word files (`files.py`). Also plays simulated calls on the live version and reviews each one into issues (`calls.py`, with its schemas and checks in `audit.py`). Answers and acts in chats about an agent (`ask.py`): reads with tools at once, and proposes every act as a card that runs only when the person clicks Do it; a change to the agent is a pull request it then makes like a fix. Tidies an issue a person reported: plain title, step, severity and the calls that show it (`tidy.py`). Tests script the model, never OpenAI. |
| `backend/example_flow.json` | Sample agent (clinic scheduler), only to illustrate the format. |
| `backend/example_tests.json` | The tests the sample agent is seeded with. |
| `solution.md` | Overview and key architectural decisions (part of the deliverable). |
| `tools/wt/`, `t3.json` | Worktree tooling: prepare a fresh worktree, run it on free ports, list them. See Worktrees below. |

## Commands

Run from the repo root.

```bash
make install   # backend (uv sync) + frontend (npm ci)
make dev       # backend + frontend, open http://localhost:5173
make run       # backend only; Pipecat's prebuilt client at http://localhost:7860/client
make lint      # ruff check on the backend (same command CI runs)
make test      # backend (pytest) and frontend (Vitest) tests: no network, no LLM calls
make check     # everything CI runs: ruff, tests, oxlint, typecheck, build
```

Frontend checks, from `frontend/`: `npm run lint` (oxlint), `npm test` (Vitest) and `npm run build`
(typecheck + build). CI runs all three.

API keys go in `backend/.env` (copy `backend/.env.example`). Never commit it.

## Invariants

- **The agent is data.** An agent is a JSON document validated by `AgentConfig`.
  The UI and the Copilot only ever produce or modify that JSON; nothing about a
  specific agent is hard-coded in Python.
- **Stay close to Pipecat Flows' vocabulary.** Node fields mirror Flows'
  `NodeConfig`. If the schema changes, update `schema.py`, `builder.py` and
  `example_flow.json` together, and record why in `solution.md`.
- **`bot.py` stays generic.** Graph logic belongs in `agent_builder/`.

## Conventions

- Python 3.11, dependencies through `uv` only (never `pip install`). Lint with ruff.
- Frontend: TypeScript, function components, Tailwind classes over custom CSS.
  Backend calls go to relative `/api/...` URLs (proxied in dev), never a hard-coded host.
- Comments explain *why*, not *what*. Each module opens with a short header
  saying what it is and why it exists, like the existing files.
- Everything in the repo is written in English.
- Never commit secrets, `.env` files or real patient data. Mock call data is fine
  and must be clearly marked as mock.

## Worktrees

Every agent thread works in its own git worktree, never in the main checkout
(that one is the user's).

- **T3 Code**: `t3.json` starts each thread in a new worktree and runs
  `tools/wt/prepare` on it, which copies `backend/.env` and installs both
  dependency sets in a few seconds.
- **Anything else**: `git worktree add <path> -b <branch> origin/main`, then
  `sh tools/wt/prepare` inside it.
- `sh tools/wt/dev` runs this worktree's backend and frontend on the first free
  ports and prints the link. Several worktrees can run at once. With Tailscale
  up the link is HTTPS on the tailnet, so test calls get the microphone from
  another device; Pipecat's prebuilt test client is at `<link>/client`.
- Run `make check` before pushing.
- T3 Code names branches `t3code/<slug>`. Before the first push, rename the
  branch to the PR's descriptive name: `git branch -m <name>`.

## Git workflow

- One branch and one PR per coherent change; descriptive branch names
  (`frontend-scaffold`, not `wip`).
- Several small commits per PR, each one building and doing one thing.
  Generated boilerplate goes in its own commit, untouched.
- Commit message: imperative headline; body with bullets on what and why;
  a `Verified: ...` line saying how it was checked; `Co-Authored-By` trailer
  when an agent wrote it.
- PR description follows `.github/pull_request_template.md`. Be explicit about
  what was **not** verified.
- PRs merge with a merge commit, never squash. Never rewrite pushed history.

## Working rules for agents

- Read the relevant files before changing them; keep diffs minimal and on topic.
- Verify before claiming: run it, lint it, exercise the path you touched. Report
  what you could not verify instead of implying it works.
- A design decision that a reviewer could ask "why?" about gets a short entry in
  `solution.md` in the same PR.
- If a task needs a new dependency, say why and prefer what is already in use.
