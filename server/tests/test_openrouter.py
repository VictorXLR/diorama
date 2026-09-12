import json

import httpx
import pytest

from diorama.agents.base import AgentContext
from diorama.agents.openrouter import OpenRouterContextModel, OpenRouterError
from diorama.data.default_contexts import DEFAULT_ARCHITECTURE_CONTEXT


def model_payload() -> dict:
    return {
        "reply": "The request is represented as an API-to-worker processing path.",
        "summary": "Added an asynchronous processing worker and queue.",
        "suggestions": ["Add retry handling", "Map failure states"],
        "context": {
            "id": "ctx-analysis",
            "title": "Request Processing Path",
            "summary": "API work is queued for asynchronous processing.",
            "diagramType": "workflow",
            "groups": [
                {"id": "edge", "title": "Edge"},
                {"id": "async", "title": "Asynchronous Work"},
            ],
            "nodes": [
                {
                    "id": "api",
                    "label": "API Gateway",
                    "category": "gateway",
                    "groupId": "edge",
                },
                {
                    "id": "queue",
                    "label": "Work Queue",
                    "category": "queue",
                    "groupId": "async",
                },
                {
                    "id": "worker",
                    "label": "Processing Worker",
                    "category": "service",
                    "groupId": "async",
                },
            ],
            "connections": [
                {
                    "id": "api-queue",
                    "fromNode": "api",
                    "toNode": "queue",
                    "label": "Enqueue work",
                    "style": "solid",
                },
                {
                    "id": "queue-worker",
                    "fromNode": "queue",
                    "toNode": "worker",
                    "label": "Consume work",
                    "style": "dashed",
                },
                {
                    "id": "invalid-link",
                    "fromNode": "worker",
                    "toNode": "absent-node",
                    "label": "Discard",
                    "style": "solid",
                },
            ],
            "insights": [
                {
                    "title": "Asynchronous Boundary",
                    "content": "Queueing keeps request latency independent of background work.",
                    "kind": "decision",
                }
            ],
            "tags": ["workflow", "queue"],
        },
    }


def canvas_payload() -> dict:
    return {
        "reply": "Sketched the async processing path.",
        "summary": "Added a queue and worker.",
        "suggestions": ["Add retry handling"],
        "canvas": {
            "primitives": [
                {"kind": "card", "id": "api", "title": "API Gateway", "body": ["Enqueue work"], "x": 0, "y": 0},
                {"kind": "card", "id": "worker", "title": "Worker", "body": ["Drains queue"], "x": 400, "y": 0},
                {"kind": "route", "id": "api-worker", "from": "api", "to": "worker", "label": "jobs"},
            ]
        },
    }


@pytest.mark.asyncio
async def test_openrouter_model_posts_structured_request_and_validates_context():
    captured_request = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_request["headers"] = dict(request.headers)
        captured_request["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": json.dumps(canvas_payload())}}
                ]
            },
        )

    model = OpenRouterContextModel(
        api_key="test-key",
        model="acme/test-model",
        site_url="https://diorama.example",
        transport=httpx.MockTransport(handler),
    )
    context = AgentContext(
        sessionId="session-1",
        currentContext=DEFAULT_ARCHITECTURE_CONTEXT,
        conversationHistory=[{"sender": "user", "content": "Map the async processing path"}],
    )

    analysis = await model.analyze("Map the async processing path", context)

    assert analysis is not None
    assert analysis.model == "acme/test-model"
    assert analysis.canvas is not None
    assert [primitive.id for primitive in analysis.canvas.primitives] == ["api", "worker", "api-worker"]
    assert analysis.reply == "Sketched the async processing path."
    assert captured_request["headers"]["authorization"] == "Bearer test-key"
    assert captured_request["headers"]["http-referer"] == "https://diorama.example"
    assert captured_request["payload"]["model"] == "acme/test-model"
    assert captured_request["payload"]["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_openrouter_model_is_disabled_without_an_api_key():
    model = OpenRouterContextModel(api_key="")
    context = AgentContext(sessionId="session-1")

    assert await model.analyze("Map the system", context) is None


def test_openrouter_model_rejects_invalid_context_payload():
    model = OpenRouterContextModel(api_key="test-key")
    invalid = model_payload()
    invalid["context"]["diagramType"] = "not-a-diagram"

    with pytest.raises(OpenRouterError, match="does not match"):
        model._parse_completion(json.dumps(invalid), None)


def test_openrouter_model_reports_truncated_json_clearly():
    model = OpenRouterContextModel(api_key="test-key")
    truncated = json.dumps(model_payload())[:200]

    with pytest.raises(OpenRouterError, match="cut off"):
        model._parse_completion(truncated, None)


@pytest.mark.asyncio
async def test_openrouter_model_reports_length_finish_reason_and_sends_larger_budget():
    captured_request = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_request["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {"content": '{"reply": "Drawing a pizza", "canvas": {"upsertElements": [{"id": "crust", "ty'},
                    }
                ]
            },
        )

    model = OpenRouterContextModel(api_key="test-key", max_tokens=12000, transport=httpx.MockTransport(handler))

    with pytest.raises(OpenRouterError, match="too large"):
        await model.analyze("draw a pizza with every ingredient", AgentContext(sessionId="session-1"))

    assert captured_request["payload"]["max_tokens"] == 12000
