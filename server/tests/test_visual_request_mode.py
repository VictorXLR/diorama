"""Regression coverage for keeping general visual requests out of code mode."""

from __future__ import annotations

import asyncio
import json

import httpx

from diorama.agents.base import AgentContext, ResponseEvent
from diorama.agents.openrouter import OpenRouterContextModel
from diorama.agents.tool_agent import FULL_SCENE_ELEMENT_LIMIT, ToolLoopAgent
from diorama.codebase.indexer import build_code_graph
from diorama.codebase.visualize import graph_to_primitives
from diorama.codebase.workspace import Workspace
from diorama.models.canvas import CanvasPatch, apply_canvas_patch


CODE_TOOL_NAMES = {
    "list_dir",
    "read_file",
    "search_code",
    "index_codebase",
    "visualize_codebase",
    "write_file",
    "edit_file",
    "run_command",
}


def _large_codebase_scene(tmp_path):
    """Build the same generated scene that a bound workspace opens with."""
    package = tmp_path / "trip_app"
    package.mkdir()
    (package / "__init__.py").write_text("")
    for index in range(18):
        next_index = (index + 1) % 18
        (package / f"module_{index}.py").write_text(
            f"from trip_app.module_{next_index} import value\n\nvalue = {index}\n"
        )

    workspace = Workspace(tmp_path)
    graph = build_code_graph(workspace)
    primitives = graph_to_primitives(graph, title="Codebase map · trip_app", max_nodes=60)
    scene = apply_canvas_patch([], CanvasPatch(primitives=primitives), theme="light")
    assert len(scene) > FULL_SCENE_ELEMENT_LIMIT
    return workspace, graph, scene


def test_bound_workspace_travel_request_uses_visual_tools_and_a_compact_non_code_prompt(tmp_path):
    """A trip should not inherit the repository agent's toolset or map-sized prompt."""
    workspace, graph, scene = _large_codebase_scene(tmp_path)
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "reply": "Added a route card.",
                                    "summary": "Drew the trip.",
                                    "canvas": {
                                        "upsertElements": [
                                            {
                                                "id": "trip-card",
                                                "type": "rectangle",
                                                "x": 0,
                                                "y": 0,
                                                "width": 120,
                                                "height": 60,
                                            }
                                        ],
                                        "deleteElementIds": [],
                                    },
                                }
                            )
                        }
                    }
                ]
            },
        )

    model = OpenRouterContextModel(
        api_key="test-key",
        model="test-model",
        native_tools=True,
        transport=httpx.MockTransport(respond),
    )
    agent = ToolLoopAgent(model=model)
    request_text = (
        "My friend and I have three hours to explore Manhattan. I am coming from Flushing and "
        "my friend is coming from Bushwick. Plan the best route to Times Square and MoMA and show it on a map."
    )
    context = AgentContext(
        sessionId="travel-with-bound-workspace",
        visualElements=scene,
        workspace=workspace,
        workspaceContext={
            "repository": workspace.root.name,
            "indexedFiles": len(graph.nodes),
            "note": "The board already shows the codebase map. Use index_codebase / read_file for details.",
        },
    )

    events = asyncio.run(_collect(agent, request_text, context))

    assert any(isinstance(event, ResponseEvent) for event in events)
    assert len(requests) == 1

    outbound = requests[0]
    tool_names = {tool["function"]["name"] for tool in outbound["tools"]}
    assert {"draw", "fetch_map", "route_info", "finish"} <= tool_names
    assert CODE_TOOL_NAMES.isdisjoint(tool_names)

    system_prompt = outbound["messages"][0]["content"]
    assert "## Working with the codebase" not in system_prompt
    assert "index_codebase" not in system_prompt

    user_prompt_text = outbound["messages"][1]["content"]
    user_prompt = json.loads(user_prompt_text)
    assert user_prompt["workspaceContext"] == {}
    assert "Codebase map" not in user_prompt_text
    # A generated repo map is about 40–50 KB today.  General visual requests
    # need room for route/tool results instead of resending that entire map.
    overview = user_prompt["sceneOverview"]
    assert len(overview["primitives"]) <= 36
    assert overview["truncated"]["primitives"] > 0
    assert len(user_prompt_text) < 12_000


async def _collect(agent, request_text, context):
    return [event async for event in agent.process_user_input(request_text, context)]
