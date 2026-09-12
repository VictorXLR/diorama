# Diorama — developer Makefile
#
# Single entry point for the two halves of the project:
#   server/  Python FastAPI + WebSocket harness (its own .venv)
#   web/     React + Excalidraw frontend (Bun)
#
# Common flows:
#   make install                    set up everything (venv + node deps)
#   make server ~/Developer/proj    run the backend bound to a repo (serves built UI)
#   make dev-all                    run backend + Vite dev server together
#   make test                       run both test suites
#   make index ~/Developer/proj     summarize a repository's structure
#
# Any target that takes a repository accepts it positionally (as above) or via
# WORKSPACE=/path; the positional form wins.

SHELL := /bin/bash

# --- paths & tools -----------------------------------------------------------
SERVER_DIR := server
WEB_DIR    := web
VENV       := $(CURDIR)/$(SERVER_DIR)/.venv
PY         := $(VENV)/bin/python
PIP        := $(VENV)/bin/pip
DIORAMA    := $(VENV)/bin/diorama
BUN        ?= bun

# Repository the code tools bind to. Either:
#   make server ~/Developer/some-repo
#   make server WORKSPACE=/Users/me/Developer/some-repo
# The first word after the target is taken as the path (the shell has already
# expanded `~`); that extra goal is turned into a no-op at the bottom of this file.
WORKSPACE ?= .
ARGS      := $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))
REPO      := $(if $(ARGS),$(firstword $(ARGS)),$(WORKSPACE))
# Output path for `make analyze`.
OUTPUT    ?= codebase.excalidraw

.DEFAULT_GOAL := help
.PHONY: help install install-server install-web venv build test test-server \
        test-web lint lint-web server dev dev-web dev-all serve index analyze \
        clean distclean

# --- help --------------------------------------------------------------------
help: ## Show this help
	@echo "Diorama targets:"
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'
	@echo
	@echo "  Repo-bound targets take a path:  make server ~/Developer/some-repo"
	@echo "  (or WORKSPACE=/path; current default: $(WORKSPACE))"

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
server: ## Run the backend bound to a repo:  make server ~/Developer/some-repo
	$(DIORAMA) dev "$(REPO)"

dev: server ## Alias for `server`

dev-web: ## Run the Vite dev server (proxies API/WS to the backend)
	cd $(WEB_DIR) && $(BUN) run dev

dev-all: ## Run the backend and the Vite dev server together
	@trap 'kill 0' INT TERM EXIT; \
	$(DIORAMA) dev "$(REPO)" & \
	(cd $(WEB_DIR) && $(BUN) run dev) & \
	wait

serve: ## Run the backend with no repository bound
	$(DIORAMA) serve

# --- codebase harness --------------------------------------------------------
index: ## Print a structural summary of a repo:  make index ~/Developer/some-repo
	$(DIORAMA) index "$(REPO)"

analyze: ## Export a codebase map of a repo to $(OUTPUT)
	$(DIORAMA) analyze "$(REPO)" -o $(OUTPUT)

# --- clean -------------------------------------------------------------------
clean: ## Remove build output and test caches
	rm -rf $(WEB_DIR)/dist $(SERVER_DIR)/.pytest_cache .pytest_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +

distclean: clean ## Also remove the venv, node_modules, and egg-info
	rm -rf $(VENV) $(WEB_DIR)/node_modules
	find . -type d -name '*.egg-info' -prune -exec rm -rf {} +

# --- positional arguments ----------------------------------------------------
# A path given after a target (e.g. `make server ~/Developer/x`) also shows up
# as a goal; treat such extra goals as no-ops so make does not try to build them.
ifneq ($(ARGS),)
.PHONY: $(ARGS)
$(ARGS):
	@:
endif
