import copy
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from diorama.agents.base import AgentContext, PatchEvent, ResponseEvent, StatusEvent, ThoughtEvent
from diorama.agents.context_agent import ContextAgent
from diorama.agents.openrouter import OpenRouterContextModel
from diorama.codebase.indexer import build_code_graph
from diorama.codebase.visualize import graph_to_primitives
from diorama.codebase.workspace import Workspace, WorkspaceError
from diorama.config import Settings, get_settings
from diorama.data.default_contexts import DEFAULT_ARCHITECTURE_CONTEXT, MICROSERVICES_CONTEXT
from diorama.persistence import SessionStore
from diorama.models.canvas import CanvasFile, CanvasPatch, apply_canvas_patch
from diorama.models.chat import ChatMessage, FileChange, VisualUpdate
from diorama.models.context import ContextVisualization
from diorama.models.protocol import (
    AgentChatMessage,
    AgentStatusMessage,
    AgentThoughtMessage,
    ConnectionAckMessage,
    ContextUpdateMessage,
    ErrorMessage,
    PongMessage,
    RefreshCodebaseMapPayload,
    RevertTurnPayload,
    SceneSyncPayload,
    UserMessagePayload,
)
from diorama.visual.generator import generate_context_whiteboard_skeletons

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("diorama.server")

settings: Settings = get_settings()

app = FastAPI(
    title="Diorama AI Harness Server",
    description="Backend server for real-time visual context conversations",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=settings.allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

sessions: Dict[str, Dict[str, Any]] = {}
store = SessionStore(settings.database_path)
context_model = OpenRouterContextModel()
agent = ContextAgent(model=context_model)
MAX_TURN_SNAPSHOTS = 20
CAPABILITIES = [
    "visual_context",
    "excalidraw_whiteboard",
    "websocket_streaming",
    "primitives",
    "files",
    "streamed_patches",
    "revert_turn",
    "selection_context",
    "codebase",
    "code_tools",
]


def build_workspace(settings: Settings) -> Optional[Workspace]:
    """Open the configured repository for the code tools, or None if unbound."""
    if settings.workspace_root is None:
        return None
    try:
        return Workspace(
            settings.workspace_root,
            max_read_bytes=settings.max_read_bytes,
            max_output_bytes=settings.max_output_bytes,
            exec_timeout=settings.exec_timeout,
            allow_exec=settings.allow_exec,
        )
    except WorkspaceError as exc:
        logger.warning("Code tools disabled: %s", exc)
        return None


workspace: Optional[Workspace] = build_workspace(settings)

CODEBASE_MAP_MAX_NODES = 60
CODEBASE_SUGGESTIONS = [
    "Explain how this codebase is organized",
    "Which files does the entry point depend on?",
    "Find the biggest files and suggest how to split them",
]


def build_codebase_seed(workspace: Optional[Workspace]) -> Optional[Dict[str, Any]]:
    """Index the bound repository and pre-render its map so a fresh board is never empty.

    Returns ``None`` when no workspace is bound or indexing fails; the server then
    behaves like a plain whiteboard.  The result is reused for every new session
    and handed to the agent as ``workspaceContext`` so it knows what repo it is in.
    """
    if workspace is None:
        return None
    try:
        graph = build_code_graph(workspace)
        primitives = graph_to_primitives(
            graph,
            title=f"Codebase map · {workspace.root.name}",
            max_nodes=CODEBASE_MAP_MAX_NODES,
        )
        elements = apply_canvas_patch([], CanvasPatch(primitives=primitives), theme="light")
    except Exception:  # noqa: BLE001 - a broken repo must not take the server down
        logger.exception("Could not build the codebase map for %s", workspace.root)
        return None
    drawn = min(len(graph.nodes), CODEBASE_MAP_MAX_NODES)
    languages = ", ".join(f"{name} ({count})" for name, count in list(graph.languages.items())[:4])
    logger.info(
        "Indexed %s: %d files, %d import edges, %d canvas elements",
        workspace.root, len(graph.nodes), len(graph.edges), len(elements),
    )
    return {
        "root": str(workspace.root),
        "name": workspace.root.name,
        "totalFiles": graph.total_files,
        "indexedFiles": len(graph.nodes),
        "drawnFiles": drawn,
        "edges": len(graph.edges),
        "languages": graph.languages,
        "languagesLabel": languages,
        "truncated": graph.truncated or drawn < len(graph.nodes),
        "visual_elements": elements,
    }


codebase_seed: Optional[Dict[str, Any]] = build_codebase_seed(workspace)


def refresh_codebase_seed() -> Optional[Dict[str, Any]]:
    """Re-index the workspace and retain the latest successful map metadata."""
    global codebase_seed
    fresh = build_codebase_seed(workspace)
    if fresh is not None:
        codebase_seed = fresh
    return fresh

if store.enabled:
    for _persisted in store.load_all().values():
        sessions[_persisted["session_id"]] = _persisted


def build_initial_session(session_id: str, *, seed: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Create a session.

    With no repository bound the board starts empty and is built entirely from
    the conversation.  When ``diorama dev PATH`` bound a workspace, the session
    opens on the pre-rendered codebase map with a welcome message describing it.
    """
    session: Dict[str, Any] = {
        "session_id": session_id,
        "context": None,
        "messages": [],
        "visual_elements": [],
        "files": {},
        "turns": [],
        # Physical Excalidraw ids owned by the generated repository map.  Keeping
        # these separately lets a refresh replace the map without touching a
        # user's own drawing.
        "codebase_map_element_ids": [],
        # Bumped for authoritative scene transitions (a submitted turn and
        # server-rendered updates). Browser-only syncs use it as a base token
        # but do not advance it, so several local edits can be coalesced.
        "scene_version": 0,
    }
    seed = codebase_seed if seed is None else seed
    if seed is not None:
        session["visual_elements"] = copy.deepcopy(seed["visual_elements"])
        session["codebase_map_element_ids"] = [element["id"] for element in session["visual_elements"]]
        session["messages"].append(build_codebase_welcome(seed))
    return session


def build_codebase_welcome(seed: Dict[str, Any]) -> ChatMessage:
    scope = f"{seed['drawnFiles']} of {seed['indexedFiles']} files" if seed["truncated"] else f"all {seed['indexedFiles']} files"
    content = (
        f"Connected to {seed['name']} ({seed['root']}). "
        f"I indexed {seed['indexedFiles']} source files ({seed['languagesLabel'] or 'no recognised languages'}) "
        f"with {seed['edges']} import edges and drew {scope} on the board. "
        "Each card is a file grouped by directory; arrows show imports. "
        "Ask me to explain, navigate, or change the code and I will keep the board in sync."
    )
    return ChatMessage(
        id="codebase-welcome",
        sender="agent",
        content=content,
        timestamp=time.strftime("%I:%M %p"),
        visualUpdate=VisualUpdate(summary="Rendered the codebase map.", elementsAdded=len(seed["visual_elements"])),
        suggestions=list(CODEBASE_SUGGESTIONS),
    )


def get_or_create_session(session_id: Optional[str] = None) -> Dict[str, Any]:
    session_key = session_id or f"sess-{uuid.uuid4().hex[:8]}"
    if session_key not in sessions:
        # Rebuild for each new board: code changes made while the server is
        # running must be visible without requiring a process restart.
        sessions[session_key] = build_initial_session(session_key, seed=refresh_codebase_seed())
    session = sessions[session_key]
    # Sessions persisted by earlier versions did not carry a revision.
    session.setdefault("scene_version", 0)
    return session


def scene_version(session_data: Dict[str, Any]) -> int:
    """Return a non-negative scene revision for a session, tolerating old data."""
    value = session_data.get("scene_version", 0)
    return value if isinstance(value, int) and value >= 0 else 0


def advance_scene_version(session_data: Dict[str, Any]) -> int:
    """Mark an authoritative change that invalidates delayed browser snapshots."""
    next_version = scene_version(session_data) + 1
    session_data["scene_version"] = next_version
    return next_version


def commit_scene(session_data: Dict[str, Any], visual_elements: List[Dict[str, Any]]) -> int:
    """Store a complete authoritative scene and advance its revision."""
    session_data["visual_elements"] = visual_elements
    retain_present_codebase_map_ids(session_data)
    return advance_scene_version(session_data)


def replace_codebase_map(session_data: Dict[str, Any], seed: Dict[str, Any]) -> None:
    """Replace only the generated map, preserving user-created canvas elements."""
    prior_ids = set(session_data.get("codebase_map_element_ids") or [])
    user_elements = [element for element in session_data["visual_elements"] if element["id"] not in prior_ids]
    codebase_elements = copy.deepcopy(seed["visual_elements"])
    session_data["visual_elements"] = [*user_elements, *codebase_elements]
    session_data["codebase_map_element_ids"] = [element["id"] for element in codebase_elements]
    advance_scene_version(session_data)


def retain_present_codebase_map_ids(session_data: Dict[str, Any]) -> None:
    """Drop ownership for map elements the user or agent has removed."""
    present = {element["id"] for element in session_data["visual_elements"]}
    session_data["codebase_map_element_ids"] = [
        element_id for element_id in session_data.get("codebase_map_element_ids", []) if element_id in present
    ]


def persist_session(session_data: Dict[str, Any]) -> None:
    """Write a session through to storage (no-op when persistence is disabled)."""
    if store.enabled:
        store.save(session_data)


def remember_turn(session_data: Dict[str, Any], turn_id: str) -> None:
    """Snapshot the board and files so one agent turn can be reverted later."""
    turns = session_data.setdefault("turns", [])
    turns.append(
        {
            "turn_id": turn_id,
            "visual_elements": copy.deepcopy(session_data["visual_elements"]),
            "files": dict(session_data.get("files", {})),
            "file_edits": {},
            "codebase_map_element_ids": list(session_data.get("codebase_map_element_ids", [])),
        }
    )
    del turns[:-MAX_TURN_SNAPSHOTS]


def record_turn_file_edits(session_data: Dict[str, Any], turn_id: str, changes: List[Dict[str, Any]]) -> None:
    """Remember the earliest pre-edit content of every file touched this turn."""
    turn = next((t for t in session_data.get("turns", []) if t["turn_id"] == turn_id), None)
    if turn is None:
        return
    edits: Dict[str, str] = turn.setdefault("file_edits", {})
    for change in changes:
        path = change.get("path")
        if not path or path in edits:
            continue
        before = change.get("before")
        edits[path] = before if isinstance(before, str) else ""


def restore_files(session_data: Dict[str, Any], from_index: int) -> List[str]:
    """Revert workspace files touched by turns at/after ``from_index``.

    Restores each path to the content it had before the earliest discarded turn.
    Returns the list of paths restored.
    """
    if workspace is None:
        return []
    turns = session_data.get("turns", [])
    first_before: Dict[str, str] = {}
    for turn in turns[from_index:]:
        for path, before in (turn.get("file_edits") or {}).items():
            if path not in first_before:
                first_before[path] = before
    restored: List[str] = []
    for path, before in first_before.items():
        try:
            workspace.write_file(path, before)
            restored.append(path)
        except WorkspaceError as exc:
            logger.warning("Could not restore %s: %s", path, exc)
    return restored


def workspace_context_for_agent() -> Dict[str, Any]:
    """Compact repo facts for the model prompt (never the element list)."""
    if codebase_seed is None:
        return {}
    return {
        "repository": codebase_seed["name"],
        "root": codebase_seed["root"],
        "indexedFiles": codebase_seed["indexedFiles"],
        "importEdges": codebase_seed["edges"],
        "languages": codebase_seed["languages"],
        "note": "The board already shows the codebase map (one card per file, arrows for imports). "
        "Use index_codebase / read_file for details instead of redrawing it.",
    }


async def send_connection_ack(websocket: WebSocket, session_data: Dict[str, Any], message: str) -> None:
    ack = ConnectionAckMessage(
        sessionId=session_data["session_id"],
        serverVersion="0.1.0",
        message=message,
        initialContext=session_data["context"],
        initialMessages=session_data["messages"],
        visualElements=session_data["visual_elements"],
        sceneVersion=scene_version(session_data),
        files=session_data.get("files") or None,
        capabilities=CAPABILITIES,
    )
    await websocket.send_text(ack.model_dump_json(by_alias=True, exclude_none=True))


async def send_context_update(
    websocket: WebSocket,
    context: Optional[ContextVisualization],
    visual_elements: list[dict[str, Any]],
    summary: str,
    *,
    files: Optional[Dict[str, CanvasFile]] = None,
    changed_element_ids: Optional[list[str]] = None,
    turn_id: Optional[str] = None,
    partial: bool = False,
    scene_version: int = 0,
) -> None:
    update = ContextUpdateMessage(
        context=context,
        visualElements=visual_elements,
        sceneVersion=scene_version,
        files=files or None,
        changedElementIds=changed_element_ids,
        turnId=turn_id,
        partial=partial,
        summary=summary,
    )
    await websocket.send_text(update.model_dump_json(by_alias=True, exclude_none=True))


def summarize_file_changes(changes: Optional[list[Dict[str, Any]]]) -> list[FileChange]:
    """Turn raw tool change records into compact, client-safe file changes."""
    summary: list[FileChange] = []
    for change in changes or []:
        path = change.get("path")
        if not path:
            continue
        diff = change.get("diff") or ""
        before = change.get("before")
        additions = 0
        deletions = 0
        for line in diff.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                additions += 1
            elif line.startswith("-") and not line.startswith("---"):
                deletions += 1
        summary.append(
            FileChange(
                path=path,
                change="created" if before in (None, "") else "modified",
                diff=diff,
                additions=additions,
                deletions=deletions,
            )
        )
    return summary


async def send_agent_message(
    websocket: WebSocket,
    session_data: Dict[str, Any],
    *,
    content: str,
    summary: str,
    element_count: int,
    suggestions: list[str],
    questions: Optional[list[str]] = None,
    turn_id: Optional[str] = None,
    changed_element_ids: Optional[list[str]] = None,
    file_changes: Optional[list[Dict[str, Any]]] = None,
) -> None:
    message = AgentChatMessage(
        id=f"agent-{int(time.time() * 1000)}",
        content=content,
        timestamp=time.strftime("%I:%M %p"),
        visualUpdate=VisualUpdate(summary=summary, elementsAdded=element_count),
        suggestions=suggestions,
        questions=questions or None,
        turnId=turn_id,
        changedElementIds=changed_element_ids,
        fileChanges=summarize_file_changes(file_changes) or None,
    )
    # Persist as a plain ChatMessage so reconnects replay a homogeneous history.
    session_data["messages"].append(ChatMessage.model_validate(message.model_dump(by_alias=True, exclude={"type"})))
    await websocket.send_text(message.model_dump_json(by_alias=True, exclude_none=True))


async def send_status(websocket: WebSocket, status: str, description: str) -> None:
    await websocket.send_text(
        AgentStatusMessage(status=status, stageDescription=description).model_dump_json(  # type: ignore[arg-type]
            by_alias=True, exclude_none=True
        )
    )


@app.get("/health")
async def health_check() -> Dict[str, Any]:
    return {
        "status": "ok",
        "service": "diorama-server",
        "version": "0.1.0",
        "active_sessions": len(sessions),
        "model_provider": context_model.provider_name if context_model.is_configured else "unconfigured",
        "model": context_model.model if context_model.is_configured else None,
        "tools": [tool.name for tool in agent.registry],
        "codeTools": [tool.name for tool in agent.code_registry],
        "workspace": str(workspace.root) if workspace is not None else None,
        "codebase": {k: v for k, v in codebase_seed.items() if k != "visual_elements"} if codebase_seed else None,
        "execEnabled": bool(workspace and workspace.allow_exec),
        "persistence": store.enabled,
        "frontendServed": settings.frontend_enabled,
        "capabilities": CAPABILITIES,
    }


@app.get("/api/context")
async def get_context(session_id: Optional[str] = None) -> Dict[str, Any]:
    session_data = get_or_create_session(session_id)
    context: Optional[ContextVisualization] = session_data["context"]
    return {
        "context": context.model_dump(by_alias=True) if context is not None else None,
        "visualElements": session_data["visual_elements"],
        "sceneVersion": scene_version(session_data),
        "files": {k: v.model_dump(by_alias=True) for k, v in (session_data.get("files") or {}).items()},
    }


@app.get("/api/presets")
async def get_presets() -> list[Dict[str, str]]:
    return [
        {
            "id": "architecture",
            "name": "Diorama Architecture",
            "summary": "Frontend, real-time gateway, context agent, and canvas renderer",
        },
        {
            "id": "microservices",
            "name": "Cloud Microservices",
            "summary": "Distributed services with an event-stream backbone",
        },
    ]


@app.websocket("/ws")
@app.websocket("/ws/{requested_session_id}")
@app.websocket("/api/ws")
async def websocket_endpoint(websocket: WebSocket, requested_session_id: Optional[str] = None) -> None:
    await websocket.accept()
    session_data = get_or_create_session(requested_session_id)
    session_id = session_data["session_id"]
    logger.info("WebSocket client connected: session %s", session_id)

    try:
        await send_connection_ack(websocket, session_data, "Connected to Diorama visual context server")

        while True:
            try:
                data = json.loads(await websocket.receive_text())
            except json.JSONDecodeError:
                await websocket.send_text(
                    ErrorMessage(code="INVALID_JSON", message="Malformed JSON message received.").model_dump_json(
                        by_alias=True,
                        exclude_none=True,
                    )
                )
                continue

            if not isinstance(data, dict):
                await websocket.send_text(
                    ErrorMessage(code="INVALID_MESSAGE", message="WebSocket messages must be JSON objects.").model_dump_json(
                        by_alias=True,
                        exclude_none=True,
                    )
                )
                continue

            msg_type = data.get("type")
            if msg_type == "ping":
                await websocket.send_text(PongMessage().model_dump_json(by_alias=True))
                continue

            if msg_type == "request_current_state":
                has_context = bool(session_data["visual_elements"])
                await send_context_update(
                    websocket,
                    session_data["context"],
                    session_data["visual_elements"],
                    "Current synchronized visual context." if has_context else "No visual context yet.",
                    files=session_data.get("files"),
                    scene_version=scene_version(session_data),
                )
                continue

            if msg_type == "sync_scene":
                try:
                    scene_sync = SceneSyncPayload.model_validate(data)
                except ValidationError as exc:
                    await websocket.send_text(
                        ErrorMessage(code="INVALID_MESSAGE", message="Invalid whiteboard scene.", details=str(exc))
                        .model_dump_json(by_alias=True, exclude_none=True)
                    )
                    continue
                # A direct canvas edit should survive reconnects even when the
                # user has not yet sent a chat message.  ``files`` is a full
                # snapshot when supplied, so removals are persisted too.
                if (
                    scene_sync.base_scene_version is not None
                    and scene_sync.base_scene_version != scene_version(session_data)
                ):
                    # The WebSocket handler processes an agent turn before it
                    # can read later client messages.  A debounced sync from
                    # before that turn would otherwise replace the fresh agent
                    # board after the final context_update was sent.
                    logger.info(
                        "Ignored stale scene sync for %s (client=%s, server=%s)",
                        session_id,
                        scene_sync.base_scene_version,
                        scene_version(session_data),
                    )
                    continue
                session_data["visual_elements"] = scene_sync.visual_elements
                retain_present_codebase_map_ids(session_data)
                if scene_sync.files is not None:
                    session_data["files"] = scene_sync.files
                persist_session(session_data)
                continue

            if msg_type == "refresh_codebase_map":
                try:
                    RefreshCodebaseMapPayload.model_validate(data)
                except ValidationError as exc:
                    await websocket.send_text(
                        ErrorMessage(code="INVALID_MESSAGE", message="Invalid codebase-map refresh request.", details=str(exc))
                        .model_dump_json(by_alias=True, exclude_none=True)
                    )
                    continue
                seed = refresh_codebase_seed()
                if seed is None:
                    await websocket.send_text(
                        ErrorMessage(
                            code="CODEBASE_UNAVAILABLE",
                            message="No readable workspace is bound, so there is no codebase map to refresh.",
                        ).model_dump_json(by_alias=True, exclude_none=True)
                    )
                    continue
                replace_codebase_map(session_data, seed)
                summary = f"Refreshed the codebase map from {seed['indexedFiles']} source files."
                persist_session(session_data)
                await send_context_update(
                    websocket,
                    session_data["context"],
                    session_data["visual_elements"],
                    summary,
                    changed_element_ids=list(session_data["codebase_map_element_ids"]),
                    scene_version=scene_version(session_data),
                )
                await send_agent_message(
                    websocket,
                    session_data,
                    content=summary,
                    summary=summary,
                    element_count=len(session_data["codebase_map_element_ids"]),
                    suggestions=list(CODEBASE_SUGGESTIONS),
                    changed_element_ids=list(session_data["codebase_map_element_ids"]),
                )
                continue

            if msg_type == "revert_turn":
                try:
                    revert = RevertTurnPayload.model_validate(data)
                except ValidationError as exc:
                    await websocket.send_text(
                        ErrorMessage(code="INVALID_MESSAGE", message="revert_turn requires a turnId.", details=str(exc))
                        .model_dump_json(by_alias=True, exclude_none=True)
                    )
                    continue
                turns = session_data.get("turns", [])
                index = next((i for i, turn in enumerate(turns) if turn["turn_id"] == revert.turn_id), None)
                if index is None:
                    await websocket.send_text(
                        ErrorMessage(code="UNKNOWN_TURN", message="That change can no longer be reverted.").model_dump_json(
                            by_alias=True, exclude_none=True
                        )
                    )
                    continue
                snapshot = turns[index]
                # Reverting a turn also discards everything drawn or edited after it.
                del turns[index:]
                session_data["visual_elements"] = copy.deepcopy(snapshot["visual_elements"])
                session_data["files"] = dict(snapshot["files"])
                session_data["codebase_map_element_ids"] = list(snapshot.get("codebase_map_element_ids", []))
                retain_present_codebase_map_ids(session_data)
                advance_scene_version(session_data)
                restored = restore_files(session_data, index)
                summary = "Reverted the board to before that change."
                if restored:
                    summary += f" Restored {len(restored)} file{'s' if len(restored) != 1 else ''} in the workspace."
                persist_session(session_data)
                await send_context_update(
                    websocket, session_data["context"], session_data["visual_elements"], summary,
                    files=session_data["files"], turn_id=revert.turn_id,
                    scene_version=scene_version(session_data),
                )
                await send_agent_message(
                    websocket, session_data, content=summary, summary=summary,
                    element_count=0, suggestions=[],
                )
                continue

            if msg_type == "reset_session":
                session_data = build_initial_session(session_id, seed=refresh_codebase_seed())
                sessions[session_id] = session_data
                persist_session(session_data)
                await send_connection_ack(websocket, session_data, "Session reset. Describe something to start a new visual context.")
                continue

            if msg_type == "select_preset":
                preset_id = str(data.get("presetId") or "").lower()
                if preset_id == "microservices":
                    context = copy.deepcopy(MICROSERVICES_CONTEXT)
                    reply = "Loaded the cloud microservices topology into the shared visual context."
                    summary = "Rendered the cloud microservices and event-stream topology."
                elif preset_id == "architecture":
                    context = copy.deepcopy(DEFAULT_ARCHITECTURE_CONTEXT)
                    reply = "Loaded the default Diorama architecture into the shared visual context."
                    summary = "Rendered the default Diorama system architecture."
                else:
                    await websocket.send_text(
                        ErrorMessage(
                            code="UNKNOWN_PRESET",
                            message="Choose either the 'architecture' or 'microservices' preset.",
                        ).model_dump_json(by_alias=True, exclude_none=True)
                    )
                    continue

                visual_elements = generate_context_whiteboard_skeletons(context)
                session_data["context"] = context
                session_data["visual_elements"] = visual_elements
                session_data["codebase_map_element_ids"] = []
                advance_scene_version(session_data)
                await send_context_update(
                    websocket, context, visual_elements, summary, scene_version=scene_version(session_data)
                )
                await send_agent_message(
                    websocket,
                    session_data,
                    content=reply,
                    summary=summary,
                    element_count=len(visual_elements),
                    suggestions=[
                        "Show the WebSocket message lifecycle",
                        "Add a codebase indexing worker",
                        "Add persistence for long-running context",
                    ],
                )
                continue

            if msg_type != "user_message":
                await websocket.send_text(
                    ErrorMessage(
                        code="UNKNOWN_MESSAGE_TYPE",
                        message=f"Unrecognized message type '{msg_type}'.",
                    ).model_dump_json(by_alias=True, exclude_none=True)
                )
                continue

            try:
                payload = UserMessagePayload.model_validate(data)
            except ValidationError as exc:
                await websocket.send_text(
                    ErrorMessage(code="INVALID_MESSAGE", message="Invalid user message or scene.", details=str(exc))
                    .model_dump_json(by_alias=True, exclude_none=True)
                )
                continue

            user_text = payload.content.strip()
            if not user_text:
                await websocket.send_text(
                    ErrorMessage(code="EMPTY_MESSAGE", message="A user_message requires non-empty content.").model_dump_json(
                        by_alias=True,
                        exclude_none=True,
                    )
                )
                continue

            if payload.visual_elements is not None:
                commit_scene(session_data, payload.visual_elements)
            if payload.files:
                session_data.setdefault("files", {}).update(payload.files)

            user_message = ChatMessage(
                id=f"user-{int(time.time() * 1000)}",
                sender="user",
                content=user_text,
                timestamp=time.strftime("%I:%M %p"),
            )
            session_data["messages"].append(user_message)
            turn_id = f"turn-{uuid.uuid4().hex[:8]}"
            remember_turn(session_data, turn_id)
            agent_context = AgentContext(
                sessionId=session_id,
                currentContext=session_data["context"],
                visualElements=session_data["visual_elements"],
                conversationHistory=[message.model_dump(by_alias=True) for message in session_data["messages"]],
                theme=payload.theme,
                selectedElementIds=payload.selected_element_ids,
                files=session_data.get("files", {}),
                viewport=payload.viewport,
                workspace=workspace,
                workspaceContext=workspace_context_for_agent(),
            )

            try:
                async for event in agent.process_user_input(user_text, agent_context):
                    if isinstance(event, StatusEvent):
                        await websocket.send_text(
                            AgentStatusMessage(
                                status=event.status,
                                stageDescription=event.stage_description,
                            ).model_dump_json(by_alias=True, exclude_none=True)
                        )
                    elif isinstance(event, ThoughtEvent):
                        await websocket.send_text(
                            AgentThoughtMessage(
                                thought=event.thought, tool=event.tool, arguments=event.arguments
                            ).model_dump_json(by_alias=True, exclude_none=True)
                        )
                    elif isinstance(event, PatchEvent):
                        # Stream intermediate progress; the session is committed so a later failure keeps this work.
                        commit_scene(session_data, event.visual_elements)
                        session_data.setdefault("files", {}).update(event.files)
                        await send_context_update(
                            websocket,
                            session_data["context"],
                            event.visual_elements,
                            event.summary,
                            files=event.files,
                            changed_element_ids=event.changed_element_ids,
                            turn_id=turn_id,
                            partial=True,
                            scene_version=scene_version(session_data),
                        )
                    elif isinstance(event, ResponseEvent):
                        session_data["context"] = event.context
                        commit_scene(session_data, event.visual_elements)
                        session_data.setdefault("files", {}).update(event.files)
                        if event.file_changes:
                            record_turn_file_edits(session_data, turn_id, event.file_changes)
                        visual_elements = event.visual_elements
                        changed_ids = list(event.changed_element_ids)
                        visual_summary = event.visual_summary
                        # Code edits made through the website used to leave the
                        # opening repository map stale until a server restart.
                        # Refresh only a map this session owns, so unrelated
                        # user diagrams remain untouched.
                        if event.file_changes and session_data.get("codebase_map_element_ids"):
                            seed = refresh_codebase_seed()
                            if seed is not None:
                                replace_codebase_map(session_data, seed)
                                visual_elements = session_data["visual_elements"]
                                changed_ids = list(dict.fromkeys([*changed_ids, *session_data["codebase_map_element_ids"]]))
                                map_summary = f"Refreshed the codebase map from {seed['indexedFiles']} source files."
                                visual_summary = "; ".join(part for part in (visual_summary, map_summary) if part)
                        persist_session(session_data)
                        await send_context_update(
                            websocket,
                            event.context,
                            visual_elements,
                            visual_summary,
                            files=event.files,
                            changed_element_ids=changed_ids,
                            turn_id=turn_id,
                            scene_version=scene_version(session_data),
                        )
                        await send_agent_message(
                            websocket,
                            session_data,
                            content=event.reply_text,
                            summary=visual_summary,
                            element_count=event.elements_added,
                            suggestions=event.suggestions,
                            questions=event.questions,
                            turn_id=turn_id if changed_ids or event.file_changes else None,
                            changed_element_ids=changed_ids or None,
                            file_changes=event.file_changes or None,
                        )
                        await send_status(websocket, "idle", "Ready")
            except WebSocketDisconnect:
                raise
            except Exception as exc:  # noqa: BLE001 - report to the user, keep the socket alive
                logger.exception("Agent turn failed for session %s", session_id)
                await websocket.send_text(
                    ErrorMessage(code="AGENT_EXECUTION_ERROR", message=str(exc)).model_dump_json(
                        by_alias=True, exclude_none=True
                    )
                )
                await send_status(websocket, "idle", "Ready")

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected: session %s", session_id)
    except Exception as exc:
        logger.exception("WebSocket error for session %s", session_id)
        try:
            await websocket.send_text(
                ErrorMessage(code="SERVER_ERROR", message=str(exc)).model_dump_json(by_alias=True, exclude_none=True)
            )
            await send_status(websocket, "idle", "Ready")
        except (WebSocketDisconnect, RuntimeError, OSError):
            # Client already went away; nothing left to report to.
            logger.info("Client disconnected before error could be delivered: session %s", session_id)


def mount_frontend(application: FastAPI, directory: Optional[Path]) -> bool:
    """Serve the built SPA at "/" when a build is present.

    Mounted last so every API and WebSocket route wins; the mount only handles
    the leftover paths (``/``, ``/assets/...``).  Returns whether it mounted.
    """
    if directory is None or not (directory / "index.html").is_file():
        return False
    application.mount("/", StaticFiles(directory=str(directory), html=True), name="web")
    logger.info("Serving built frontend from %s", directory)
    return True


FRONTEND_SERVED = mount_frontend(app, settings.web_dist)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "diorama.server:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
    )
