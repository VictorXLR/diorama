from typing import List, Optional, Literal, Dict, Any
from pydantic import BaseModel, ConfigDict, Field

NodeCategory = Literal[
    "client",
    "service",
    "gateway",
    "database",
    "queue",
    "storage",
    "external",
    "workflow_step",
    "concept",
    "custom",
]

DiagramType = Literal[
    "architecture",
    "flowchart",
    "context_map",
    "system_topology",
    "workflow",
]


class ContextNode(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    label: str
    subtitle: Optional[str] = None
    category: NodeCategory = "service"
    description: Optional[str] = None
    group_id: Optional[str] = Field(default=None, alias="groupId")
    tags: List[str] = Field(default_factory=list)
    status: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ContextConnection(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    from_node: str = Field(alias="fromNode")
    to_node: str = Field(alias="toNode")
    label: Optional[str] = None
    style: Literal["solid", "dashed", "dotted"] = "solid"
    bidirectional: bool = False


class ContextGroup(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    title: str
    description: Optional[str] = None
    color: Optional[str] = None
    category: Optional[str] = None


class ContextInsight(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    title: str
    content: str
    kind: Literal["info", "metric", "decision", "warning", "tip"] = "info"


class ContextVisualization(BaseModel):
    """
    Top-level generalized visual context representation.
    Used to visualize architectures, system contexts, workflows,
    domain graphs, or any structured knowledge on the Excalidraw whiteboard.
    """
    model_config = ConfigDict(populate_by_name=True)

    id: str
    title: str
    summary: str
    diagram_type: DiagramType = Field(default="architecture", alias="diagramType")
    groups: List[ContextGroup] = Field(default_factory=list)
    nodes: List[ContextNode] = Field(default_factory=list)
    connections: List[ContextConnection] = Field(default_factory=list)
    insights: List[ContextInsight] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
