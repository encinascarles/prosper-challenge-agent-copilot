# Prosper Challenge — Agent Copilot

Voice AI for healthcare scheduling. An agent is a **graph of nodes** (Pipecat Flows), defined declaratively as JSON and compiled into a runnable voice pipeline.

- **Phase 1** — a UI to edit the node graph and place a test call.
- **Phase 2** — an AI Copilot that generates and iterates on agents from natural language.

```
browser mic  ->  ElevenLabs STT  ->  OpenAI LLM  ->  ElevenLabs TTS  ->  browser
```

The Agent Builder UI lives in `frontend/` (Vite + React + TypeScript). Pipecat's dev runner also ships a **prebuilt browser client** at `/client`, handy for a quick call without the UI.

## Quickstart

Requires **Python 3.11+**, [**uv**](https://docs.astral.sh/uv/getting-started/installation/) (uv will fetch a matching Python for you if needed) and **Node 22+**. Run from the repo root:

```bash
make install   # uv sync (backend/.venv from uv.lock) + npm ci (frontend)
make dev       # backend + frontend together, open http://localhost:5173
make run       # backend only: uv run python bot.py
```

With `make run` alone, open the URL it prints (default `http://localhost:7860/client`), click **Connect**, allow mic access, and talk to the agent. `Ctrl+C` to stop. (`make help` lists all targets.)

Prefer raw `uv`? The same commands without `make`:

```bash
uv sync --directory backend            # install dependencies
uv run --directory backend python bot.py   # run the agent
```\
\
Remember to update the `.env` file accordingly.

## Layout

| Path | Responsibility |
| --- | --- |
| `backend/bot.py` | The voice pipeline (WebRTC + ElevenLabs STT/TTS + OpenAI LLM). Loads an agent JSON via `AgentBuilder` and runs it. No graph logic lives here. |
| `backend/agent_builder/` | All agent-building code. `schema.py` = the declarative `AgentConfig` / `Node` / `Edge` contract; `builder.py` = `AgentBuilder`, which loads + validates the JSON and compiles it into a Pipecat Flows graph. |
| `frontend/` | The Agent Builder UI: Vite + React + TypeScript, Tailwind and shadcn/ui. The dev server proxies `/api` to the backend. |
| `backend/example_flow.json` | The example agent **as data** — a clinic scheduler. The artifact the Phase 2 Copilot generates/edits. |

To run a different agent, point `AGENT_FLOW` in `bot.py` at another JSON file.