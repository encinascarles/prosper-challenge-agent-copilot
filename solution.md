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
