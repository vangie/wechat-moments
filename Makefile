.DEFAULT_GOAL := help

.PHONY: help install check check-fix test test-e2e mcp mcp-remote deploy-remote status adb-screenshot cleanup post build

help: ## Show this help
	@grep -E '^[a-zA-Z0-9_%-]+:.*?## .*$$' $(MAKEFILE_LIST) | sed 's/^Makefile://' | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install dependencies (uv sync)
	uv sync

check: ## Run linter and format check
	uv run ruff check src/ tests/
	uv run ruff format --check src/ tests/

check-fix: ## Auto-fix lint and format issues
	uv run ruff check --fix src/ tests/
	uv run ruff format src/ tests/

test: ## Run unit tests
	uv run pytest tests/ -q --ignore=tests/e2e

test-e2e: ## Run end-to-end tests (requires connected device)
	uv run pytest tests/e2e -v

build: ## Build package (uv build)
	uv build

mcp: ## Start MCP inspector UI with hot reload
	npx @modelcontextprotocol/inspector uv run mcp-hmr wechat_moments.server:mcp

mcp-remote: ## Start MCP server for remote access (SSE on 0.0.0.0:8765)
	./scripts/mcp-remote.sh

deploy-remote: ## Deploy MCP config to remote mcporter [REMOTE=...] [ENDPOINT=...]
	./scripts/deploy-mcp-remote.sh "$(REMOTE)" "$(ENDPOINT)"

status: ## Check ADB connection and WeChat status
	uv run wx-pyq status

adb-screenshot: ## Take a screenshot and save to screenshots/
	./scripts/adb-screenshot.sh

cleanup: ## Remove expired staging and archive directories
	uv run wx-pyq cleanup

post: ## Post to WeChat Moments [TEXT=...] [IMAGE=...]
	uv run wx-pyq post $(if $(TEXT),"$(TEXT)",) $(if $(IMAGE),-i "$(IMAGE)",) --debug
