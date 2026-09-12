from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from diorama.models.canvas import CanvasFile, VisualElements
from diorama.models.chat import AgentStatus, ChatMessage, FileChange, VisualUpdate
from diorama.models.context import ContextVisualization

# -------------------------------------------------------------
# Client -> Server Messages
# -------------------------------------------------------------

class UserMessagePayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    type: Literal["user_message"] = "user_message"
    content: str
    visual_elements: Optional[VisualElements] = Field(default=None, alias="visualElements")
    files: Optional[Dict[str, CanvasFile]] = Field(default=None, description="Binary assets currently on the board.")
    selected_element_ids: List[str] = Field(default_factory=list, alias="selectedElementIds")
    theme: Literal["light", "dark"] = "light"
    viewport: Optional[Dict[str, float]] = None
    session_id: Optional[str] = Field(default=None, alias="sessionId")
    client_timestamp: Optional[str] = Field(default=None, alias="clientTimestamp")


class RevertTurnPayload(BaseModel):
    """Undo everything one agent turn did to the board."""

    model_config = ConfigDict(populate_by_name=True)
    type: Literal["revert_turn"] = "revert_turn"
    turn_id: str = Field(alias="turnId")


class SelectPresetPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    type: Literal["select_preset"] = "select_preset"
    preset_id: str = Field(alias="presetId")
    session_id: Optional[str] = Field(default=None, alias="sessionId")


class ResetSessionPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    type: Literal["reset_session"] = "reset_session"
    session_id: Optional[str] = Field(default=None, alias="sessionId")


class PingPayload(BaseModel):
    type: Literal["ping"] = "ping"


class RequestCurrentStatePayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    type: Literal["request_current_state"] = "request_current_state"
    session_id: Optional[str] = Field(default=None, alias="sessionId")


class ConnectionAckMessage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    type: Literal["connection_ack"] = "connection_ack"
    session_id: str = Field(alias="sessionId")
    server_version: str = Field(default="0.1.0", alias="serverVersion")
    message: str = "Connected to Diorama AI Harness"
    initial_context: Optional[ContextVisualization] = Field(default=None, alias="initialContext")
    initial_messages: Optional[List[ChatMessage]] = Field(default=None, alias="initialMessages")
    visual_elements: Optional[List[Dict[str, Any]]] = Field(default=None, alias="visualElements")
    files: Optional[Dict[str, CanvasFile]] = None
    capabilities: Optional[List[str]] = None


class AgentStatusMessage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    type: Literal["agent_status"] = "agent_status"
    status: AgentStatus
    stage_description: Optional[str] = Field(default=None, alias="stageDescription")


class AgentThoughtMessage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    type: Literal["agent_thought"] = "agent_thought"
    thought: str
    tool: Optional[str] = None
    arguments: Optional[Dict[str, Any]] = None


class ContextUpdateMessage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    type: Literal["context_update"] = "context_update"
    context: Optional[ContextVisualization] = None
    visual_elements: Optional[List[Dict[str, Any]]] = Field(default=None, alias="visualElements")
    files: Optional[Dict[str, CanvasFile]] = Field(default=None, description="New/changed assets only.")
    changed_element_ids: Optional[List[str]] = Field(default=None, alias="changedElementIds")
    turn_id: Optional[str] = Field(default=None, alias="turnId")
    partial: bool = Field(default=False, description="True while the agent is still working on this turn.")
    summary: Optional[str] = None


class AgentChatMessage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    type: Literal["agent_message"] = "agent_message"
    id: str
    sender: Literal["agent"] = "agent"
    content: str
    timestamp: str
    visual_update: Optional[VisualUpdate] = Field(default=None, alias="visualUpdate")
    suggestions: Optional[List[str]] = None
    questions: Optional[List[str]] = None
    turn_id: Optional[str] = Field(default=None, alias="turnId")
    changed_element_ids: Optional[List[str]] = Field(default=None, alias="changedElementIds")
    file_changes: Optional[List[FileChange]] = Field(default=None, alias="fileChanges")


class PongMessage(BaseModel):
    type: Literal["pong"] = "pong"


class ErrorMessage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    type: Literal["error"] = "error"
    message: str
    code: Optional[str] = None
    details: Optional[str] = None


ClientMessage = Union[
    UserMessagePayload,
    SelectPresetPayload,
    ResetSessionPayload,
    RevertTurnPayload,
    PingPayload,
    RequestCurrentStatePayload,
]

ServerMessage = Union[
    ConnectionAckMessage,
    AgentStatusMessage,
    AgentThoughtMessage,
    ContextUpdateMessage,
    AgentChatMessage,
    PongMessage,
    ErrorMessage,
]
