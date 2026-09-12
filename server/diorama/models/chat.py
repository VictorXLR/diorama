from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

AgentStatus = Literal[
    "idle",
    "thinking",
    "analyzing_context",
    "generating_plan",
    "calling_tool",
    "generating_visual",
    "syncing_whiteboard",
    "working",
]


class VisualUpdate(BaseModel):
    """Metadata linking an agent response to its whiteboard update."""

    model_config = ConfigDict(populate_by_name=True)

    summary: str
    elements_added: int = Field(default=0, alias="elementsAdded")


class ChatMessage(BaseModel):
    """A durable conversation message shared by the chat panel and agent."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    sender: Literal["user", "agent", "system"]
    content: str
    timestamp: str
    visual_update: Optional[VisualUpdate] = Field(default=None, alias="visualUpdate")
    suggestions: Optional[List[str]] = None
    questions: Optional[List[str]] = None
    turn_id: Optional[str] = Field(default=None, alias="turnId")
    changed_element_ids: Optional[List[str]] = Field(default=None, alias="changedElementIds")
