import copy
import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from diorama.agents.base import AgentContext, PatchEvent, ResponseEvent, StatusEvent, ThoughtEvent
from diorama.agents.context_agent import ContextAgent
from diorama.agents.openrouter import OpenRouterContextModel
from diorama.codebase.workspace import Workspace, WorkspaceError
from diorama.config import Settings, get_settings
from diorama.data.default_contexts import DEFAULT_ARCHITECTURE_CONTEXT, MICROSERVICES_CONTEXT
from diorama.persistence import SessionStore
from diorama.models.canvas import CanvasFile
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
    RevertTurnPayload,
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

if store.enabled:
    for _persisted in store.load_all().values():
        sessions[_persisted["session_id"]] = _persisted


def build_initial_session(session_id: str) -> Dict[str, Any]:
    """Create an empty session. The visual context is built entirely from the conversation."""
    return {
        "session_id": session_id,
        "context": None,
        "messages": [],
        "visual_elements": [],
        "files": {},
        "turns": [],
    }


def get_or_create_session(session_id: Optional[str] = None) -> Dict[str, Any]:
    session_key = session_id or f"sess-{uuid.uuid4().hex[:8]}"
    if session_key not in sessions:
        sessions[session_key] = build_initial_session(session_key)
    return sessions[session_key]


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


async def send_connection_ack(websocket: WebSocket, session_data: Dict[str, Any], message: str) -> None:
    ack = ConnectionAckMessage(
        sessionId=session_data["session_id"],
        serverVersion="0.1.0",
        message=message,
        initialContext=session_data["context"],
        initialMessages=session_data["messages"],
        visualElements=session_data["visual_elements"],
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
) -> None:
    update = ContextUpdateMessage(
        context=context,
        visualElements=visual_elements,
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
        "execEnabled": bool(workspace and workspace.allow_exec),
        "persistence": store.enabled,
        "capabilities": CAPABILITIES,
    }


@app.get("/api/context")
async def get_context(session_id: Optional[str] = None) -> Dict[str, Any]:
    session_data = get_or_create_session(session_id)
    context: Optional[ContextVisualization] = session_data["context"]
    return {
        "context": context.model_dump(by_alias=True) if context is not None else None,
        "visualElements": session_data["visual_elements"],
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
                restored = restore_files(session_data, index)
                summary = "Reverted the board to before that change."
                if restored:
                    summary += f" Restored {len(restored)} file{'s' if len(restored) != 1 else ''} in the workspace."
                persist_session(session_data)
                await send_context_update(
                    websocket, session_data["context"], session_data["visual_elements"], summary,
                    files=session_data["files"], turn_id=revert.turn_id,
                )
                await send_agent_message(
                    websocket, session_data, content=summary, summary=summary,
                    element_count=0, suggestions=[],
                )
                continue

            if msg_type == "reset_session":
                session_data = build_initial_session(session_id)
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
                await send_context_update(websocket, context, visual_elements, summary)
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
                session_data["visual_elements"] = payload.visual_elements
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
                        session_data["visual_elements"] = event.visual_elements
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
                        )
                    elif isinstance(event, ResponseEvent):
                        session_data["context"] = event.context
                        session_data["visual_elements"] = event.visual_elements
                        session_data.setdefault("files", {}).update(event.files)
                        if event.file_changes:
                            record_turn_file_edits(session_data, turn_id, event.file_changes)
                        persist_session(session_data)
                        await send_context_update(
                            websocket,
                            event.context,
                            event.visual_elements,
                            event.visual_summary,
                            files=event.files,
                            changed_element_ids=event.changed_element_ids,
                            turn_id=turn_id,
                        )
                        await send_agent_message(
                            websocket,
                            session_data,
                            content=event.reply_text,
                            summary=event.visual_summary,
                            element_count=event.elements_added,
                            suggestions=event.suggestions,
                            questions=event.questions,
                            turn_id=turn_id if event.changed_element_ids or event.file_changes else None,
                            changed_element_ids=event.changed_element_ids or None,
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "diorama.server:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
    )
