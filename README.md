# Diorama

A harness for **visualizing and modifying codebases** on an interactive whiteboard, driven by an LLM agent.

Diorama binds to a repository on your disk, indexes it into a graph of files, symbols, and dependencies, renders
that graph on an Excalidraw canvas, and gives an agent tools to read, search, edit, and run code inside it. The
canvas is not a picture of the codebase — it is a working surface you can talk to, rearrange, and revert.

Its near-term goal is self-hosting: Diorama should be able to open its own repository, understand it, change it,
and verify the change by running its own build and tests.

---

## Why

Reading an unfamiliar codebase is mostly guesswork: you grep, you jump, you build a mental model that lives
nowhere and is thrown away. Diagrams help, but they go stale the moment they are drawn, and they are never
connected to the code they claim to describe.

Diorama's bet is that the diagram should be *derived* from the code, and that the same surface that shows you
the structure should also be the one you edit through. That gives:

- **Structure you can trust** — the map comes from the AST, not from a model's guess.
- **A view that stays current** — re-index after a change and the map reflects it.
- **One place for seeing and changing** — no context switch between editor, terminal, and diagram.

---

## Goals

### Achieved

- **Bind to any repository.** Point Diorama at a path and every code operation is confined to that root.
  Path traversal, absolute paths, and symlink escapes are rejected at a single boundary
  (`server/diorama/codebase/workspace.py`).
- **Index into a graph.** Walks the tree respecting `.gitignore`, parses Python with `ast` and TS/JS/Go/Rust/
  Java/Ruby and others with tree-sitter (`server/diorama/codebase/parsers.py`), with a regex fallback so
  indexing never hard-fails. Resolves import edges, including framework path aliases like `@/` and `~/`.
- **Render the graph.** Deterministic layout produces frames for directories, cards for files, and arrows for
  imports (`server/diorama/codebase/visualize.py`) — coordinates computed from measured content, not guessed.
- **Agent with code tools.** `list_dir`, `read_file`, `search_code`, `index_codebase`, `visualize_codebase`,
  `write_file`, `edit_file`, `run_command` (`server/diorama/tools/code.py`).
- **Closed-loop verification.** `run_command` captures stdout, stderr, and exit codes, so the agent can run
  `pytest` or `bun run build`, read the failure, and fix it.
- **Safety and rollback.** Writes go through a single workspace guard; every turn records prior file contents so
  `revert_turn` restores files, not just the board. Edits surface to the UI as unified diffs.
- **Whiteboard agent.** Composition primitives (`draw`, `edit_elements`, `delete_elements`, `inspect_scene`,
  `ask_user`, `finish`) streamed incrementally as patches, plus asset tools (maps, geocoding, images, routing).
- **Persistence and config.** Optional SQLite write-through for sessions; all settings env-driven
  (`server/diorama/config.py`).
- **Servable.** The backend serves the built SPA, and the bundle is same-origin so no host is hardcoded.
- **CLI.** `diorama index|analyze|dev|serve` (`server/diorama/cli.py`), plus a root `Makefile`.

### Not yet achieved

- **Self-modification end to end.** The pieces exist (code tools, exec, rollback) but have not been exercised
  as a full loop: open Diorama's own repo, propose a change, verify it, and land it.
- **Rolled-up architecture view.** `server/diorama/codebase/architecture.py` infers subsystem *roles* (UI,
  database, business logic, tests) and renders a component diagram. It works — dogfooding finds 9 components
  and 12 edges — but is not wired into the tool registry, so the agent cannot call it yet.
- **Token streaming.** Model calls are a single blocking POST; long turns block the socket. Only tool patches
  stream today.
- **Human approval before writes.** Edits are applied immediately and made revertible. There is no
  confirm-before-apply checkpoint.
- **Semantic code search.** `search_code` is regex over text, not embedding or symbol-aware search.
- **Diff review and terminal UI in the web client.** Changes render as diffs in the chat panel, but there is no
  code editor, side-by-side diff viewer, or streaming console.
- **Multi-worker deployment.** SQLite persistence is single-node; there is no Redis pub/sub for WebSockets
  across workers, no auth, and no rate limiting.

---

## Architecture

```
cli/                                 (reserved for a standalone CLI package)
server/
  diorama/
    agents/        Tool-loop agent (ReAct), prompts, provider-agnostic model client
    codebase/      Workspace guard, indexer, tree-sitter parsers, graph-to-canvas layout
    tools/         Tool registry: canvas, assets, code
    visual/        Theme and composition primitives
    models/        Pydantic protocol, canvas patch, chat models
    server.py      FastAPI app, WebSocket sessions, turn reversion, SPA mount
web/
  src/             React + Excalidraw client; chat panel, whiteboard, store
```

**Request flow.** The browser opens a WebSocket. Each turn, the agent runs a loop: the model either emits native
function calls or a JSON tool block, the harness executes the tool, and results stream back as patches. Canvas
mutations are primitives, not raw Excalidraw elements, so the server can lay them out and keep frames consistent.
File mutations are recorded on the turn for rollback.

**The workspace boundary.** Everything that touches disk goes through `Workspace.resolve()`. This is the single
choke point for confinement, and it is what makes it safe to let a model write files.

**Frames.** Excalidraw clips content outside its frame, so `finalize_scene` grows primitive frames to enclose
their children (never shrinks, never touches user-drawn frames). Layout measures content before placing it.

---

## Running it

Requirements: Python 3.10+, [bun](https://bun.sh).

```bash
make install                 # venv + editable server install + web deps
make build                   # build the frontend into web/dist

make dev ../new-friend-store # serve UI + API bound to a repo, then open http://127.0.0.1:8000/
```

`make dev .` binds to Diorama itself. For a frontend hot-reload loop, use `make dev-all` (backend plus Vite on
:5173, which proxies `/api`, `/health`, `/ws`).

Headless, no server:

```bash
make index    WORKSPACE=../new-friend-store   # summarize the graph
make analyze  WORKSPACE=../new-friend-store OUTPUT=map.excalidraw
```

Run `make help` for the full target list.

### Configuration

Set one of these before the agent can chat:

| Variable | Purpose |
| :-- | :-- |
| `OPENROUTER_API_KEY` | OpenRouter auth |
| `DIORAMA_LLM_BASE_URL` | Any OpenAI-compatible endpoint (e.g. a local server) |
| `DIORAMA_LLM_MODEL` | Model override |

Other settings (`server/diorama/config.py`): `DIORAMA_WORKSPACE`, `DIORAMA_WEB_DIST`, `DIORAMA_ALLOW_EXEC`,
`DIORAMA_EXEC_TIMEOUT`, `DIORAMA_CORS_ORIGINS`, `DIORAMA_DATABASE_PATH`, `DIORAMA_HOST`, `DIORAMA_PORT`,
`DIORAMA_RELOAD`.

---

## Development

```bash
make test           # server + web suites
make test-server
make test-web
make lint
```

Server: **102 passing**. Web: **9 passing**.

---

## Where it is going

The order matters: each step is only useful once the previous one is trustworthy.

1. **Wire the architecture view** into the tool registry so the agent can zoom out to subsystems, not just files.
2. **Close the self-modification loop** — have Diorama open its own repo, make a real change, and land it
   verified by its own tests. That is the proving ground for everything else.
3. **Add an approval checkpoint** before writes, with side-by-side diff review in the UI.
4. **Stream tokens** so long turns stay responsive.
5. **Symbol-aware and semantic search**, so the agent can ask "what calls this?" rather than grepping.
6. **Multi-worker deployment** — Redis-backed WebSocket fanout, auth, and rate limiting.
