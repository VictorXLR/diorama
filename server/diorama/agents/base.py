from typing import Any, AsyncIterator, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from diorama.models.canvas import CanvasFile, VisualElements
from diorama.models.chat import AgentStatus
from diorama.models.context import ContextVisualization


class AgentContext(BaseModel):
    """
    Context passed to an agent containing current domain state,
    conversation history, and session metadata.
    Designed to generalize beyond trips to code workspaces, systems, and architectures.
    """
    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

    session_id: str = Field(alias="sessionId")
    current_context: Optional[ContextVisualization] = Field(default=None, alias="currentContext")
    visual_elements: VisualElements = Field(default_factory=list, alias="visualElements")
    conversation_history: List[Dict[str, Any]] = Field(default_factory=list, alias="conversationHistory")
    workspace_context: Optional[Dict[str, Any]] = Field(default_factory=dict, alias="workspaceContext")
    workspace: Optional[Any] = Field(default=None, exclude=True, description="Confined repository view for code tools.")
    theme: Literal["light", "dark"] = "light"
    selected_element_ids: List[str] = Field(default_factory=list, alias="selectedElementIds")
    files: Dict[str, CanvasFile] = Field(default_factory=dict, description="Binary assets already on the board.")
    viewport: Optional[Dict[str, float]] = Field(
        default=None, description="Visible scene rect {x, y, width, height} so new content lands on screen."
    )


class StatusEvent(BaseModel):
    kind: str = "status"
    status: AgentStatus
    stage_description: Optional[str] = None


class ThoughtEvent(BaseModel):
    kind: str = "thought"
    thought: str
    tool: Optional[str] = None
    arguments: Optional[Dict[str, Any]] = None


class PatchEvent(BaseModel):
    """An intermediate canvas update streamed while the agent is still working."""

    kind: str = "patch"
    visual_elements: List[Dict[str, Any]] = Field(default_factory=list)
    files: Dict[str, CanvasFile] = Field(default_factory=dict)
    changed_element_ids: List[str] = Field(default_factory=list)
    summary: str = ""


class ResponseEvent(BaseModel):
    kind: str = "response"
    reply_text: str
    context: Optional[ContextVisualization] = None
    visual_elements: List[Dict[str, Any]] = Field(default_factory=list)
    files: Dict[str, CanvasFile] = Field(default_factory=dict)
    changed_element_ids: List[str] = Field(default_factory=list)
    visual_summary: str = ""
    elements_added: int = 0
    suggestions: List[str] = Field(default_factory=list)
    questions: List[str] = Field(default_factory=list, description="Clarifying questions shown as quick replies.")
    file_changes: List[Dict[str, Any]] = Field(
        default_factory=list, description="Workspace files created/edited this turn, with unified diffs."
    )


AgentLifecycleEvent = Union[StatusEvent, ThoughtEvent, PatchEvent, ResponseEvent]


class BaseAgent:
    """Base contract for agents that synthesize shared visual context."""

    def __init__(self, agent_id: str, name: str, description: str):
        self.agent_id = agent_id
        self.name = name
        self.description = description

    async def process_user_input(
        self,
        input_text: str,
        context: AgentContext,
    ) -> AsyncIterator[AgentLifecycleEvent]:
        """
        Processes a user message and yields lifecycle events:
        1. status changes ('thinking', 'analyzing_context', 'generating_visual', 'syncing_whiteboard')
        2. intermediate thoughts/reasoning traces
        3. final response event with chat text and visual context artifacts
        """
        raise NotImplementedError
