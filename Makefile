# Prosper Challenge — run everything from the repo root.
# Dependencies are managed with uv (https://docs.astral.sh/uv/).

PROJECT := backend
RUFF_VERSION := 0.16.10

.PHONY: help install run lint clean

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

install: ## Create the venv and install dependencies (from uv.lock)
	uv sync --directory $(PROJECT)

run: ## Run the voice agent (then open http://localhost:7860/client)
	uv run --directory $(PROJECT) python bot.py

lint: ## Lint the backend with ruff
	uvx ruff@$(RUFF_VERSION) check $(PROJECT)

clean: ## Remove the venv and Python caches
	rm -rf $(PROJECT)/.venv
	find $(PROJECT) -type d -name __pycache__ -prune -exec rm -rf {} +
