# Prosper Challenge — run everything from the repo root.
# Dependencies are managed with uv (https://docs.astral.sh/uv/).

PROJECT := backend
FRONTEND := frontend
RUFF_VERSION := 0.16.10
# Ports, overridable so several worktrees can run at once (tools/wt/dev picks free ones).
# WEB_HOST is a manual override, e.g. WEB_HOST=0.0.0.0 to reach Vite from the LAN.
BACKEND_PORT ?= 7860
WEB_PORT ?= 5173
WEB_HOST ?=

.PHONY: help install run web dev lint test check clean

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

install: ## Install backend (uv.lock) and frontend (package-lock.json) dependencies
	uv sync --directory $(PROJECT)
	npm ci --prefix $(FRONTEND)

run: ## Run the voice agent (then open http://localhost:7860/client)
	uv run --directory $(PROJECT) python bot.py --port $(BACKEND_PORT)

web: ## Run the frontend dev server (http://localhost:5173)
	BACKEND_PORT=$(BACKEND_PORT) npm run dev --prefix $(FRONTEND) -- --port $(WEB_PORT) --strictPort $(if $(WEB_HOST),--host $(WEB_HOST))

dev: ## Run backend and frontend together; Ctrl+C stops both
	$(MAKE) -j2 run web

lint: ## Lint the backend with ruff
	uvx ruff@$(RUFF_VERSION) check $(PROJECT)

test: ## Run the backend tests (no network, no LLM calls)
	uv run --directory $(PROJECT) pytest

check: ## Run every check CI runs: ruff, backend tests, frontend lint, typecheck and build
	$(MAKE) lint
	$(MAKE) test
	npm run lint --prefix $(FRONTEND)
	npm run build --prefix $(FRONTEND)

clean: ## Remove the venv and Python caches
	rm -rf $(PROJECT)/.venv
	find $(PROJECT) -type d -name __pycache__ -prune -exec rm -rf {} +
