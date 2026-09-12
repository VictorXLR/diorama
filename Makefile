# Diorama — developer Makefile
#
# Single entry point for the two halves of the project:
#   server/  Python FastAPI + WebSocket harness (its own .venv)
#   web/     React + Excalidraw frontend (Bun)
#
# Common flows:
#   make install        set up everything (venv + node deps)
#   make dev            run the backend bound to WORKSPACE (serves built UI)
#   make dev-all        run backend + Vite dev server together
#   make test           run both test suites
#   make index          summarize a repository's structure

SHELL := /bin/bash

# --- paths & tools -----------------------------------------------------------
SERVER_DIR := server
WEB_DIR    := web
VENV       := $(CURDIR)/$(SERVER_DIR)/.venv
PY         := $(VENV)/bin/python
PIP        := $(VENV)/bin/pip
DIORAMA    := $(VENV)/bin/diorama
BUN        ?= bun

# Repository the code tools bind to. Override, e.g.:
#   make dev WORKSPACE=/Users/me/Developer/some-repo
WORKSPACE ?= .
# Output path for `make analyze`.
OUTPUT    ?= codebase.excalidraw

.DEFAULT_GOAL := help
.PHONY: help install install-server install-web venv build test test-server \
        test-web lint lint-web dev dev-web dev-all serve index analyze \
        clean distclean

# --- help --------------------------------------------------------------------
help: ## Show this help
	@echo "Diorama targets:"
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'
	@echo
	@echo "  WORKSPACE=$(WORKSPACE)   (override with: make dev WORKSPACE=/path/to/repo)"

# --- install -----------------------------------------------------------------
install: install-server install-web ## Install all dependencies (Python venv + web)

install-server: $(PY) ## Install the server package (editable) into server/.venv
	$(PIP) install -e $(SERVER_DIR)

venv: $(PY) ## Create the server virtualenv
$(PY):
	python3 -m venv $(VENV)

install-web: $(WEB_DIR)/node_modules ## Install web dependencies with Bun
$(WEB_DIR)/node_modules: $(WEB_DIR)/package.json $(WEB_DIR)/bun.lock
	cd $(WEB_DIR) && $(BUN) install

# --- build -------------------------------------------------------------------
build: ## Build the web frontend into web/dist (served by the backend)
	cd $(WEB_DIR) && $(BUN) run build

# --- test --------------------------------------------------------------------
test: test-server test-web ## Run both test suites

test-server: ## Run the server (pytest) suite
	cd $(SERVER_DIR) && $(PY) -m pytest -q

test-web: ## Run the web (bun test) suite
	cd $(WEB_DIR) && $(BUN) test

# --- lint --------------------------------------------------------------------
lint: lint-web ## Lint the project (Python has no linter configured)

lint-web: ## Run ESLint over the web sources
	cd $(WEB_DIR) && $(BUN) run lint

# --- run ---------------------------------------------------------------------
dev: ## Run the backend bound to WORKSPACE (serves the built UI)
	$(DIORAMA) dev $(WORKSPACE)

dev-web: ## Run the Vite dev server (proxies API/WS to the backend)
	cd $(WEB_DIR) && $(BUN) run dev

dev-all: ## Run the backend and the Vite dev server together
	@trap 'kill 0' INT TERM EXIT; \
	$(DIORAMA) dev $(WORKSPACE) & \
	(cd $(WEB_DIR) && $(BUN) run dev) & \
	wait

serve: ## Run the backend with no repository bound
	$(DIORAMA) serve

# --- codebase harness --------------------------------------------------------
index: ## Print a structural summary of WORKSPACE
	$(DIORAMA) index $(WORKSPACE)

analyze: ## Export a codebase map of WORKSPACE to $(OUTPUT)
	$(DIORAMA) analyze $(WORKSPACE) -o $(OUTPUT)

# --- clean -------------------------------------------------------------------
clean: ## Remove build output and test caches
	rm -rf $(WEB_DIR)/dist $(SERVER_DIR)/.pytest_cache .pytest_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +

distclean: clean ## Also remove the venv, node_modules, and egg-info
	rm -rf $(VENV) $(WEB_DIR)/node_modules
	find . -type d -name '*.egg-info' -prune -exec rm -rf {} +
