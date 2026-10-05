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
| `backend/example_flow.json` | Sample agent (clinic scheduler), only to illustrate the format. |
| `solution.md` | Overview and key architectural decisions (part of the deliverable). |

## Commands

Run from the repo root.

```bash
make install   # uv sync: create backend/.venv from uv.lock
make run       # start the voice agent, then open http://localhost:7860/client
make lint      # ruff check on the backend (same command CI runs)
```

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
- Comments explain *why*, not *what*. Each module opens with a short header
  saying what it is and why it exists, like the existing files.
- Everything in the repo is written in English.
- Never commit secrets, `.env` files or real patient data. Mock call data is fine
  and must be clearly marked as mock.

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
