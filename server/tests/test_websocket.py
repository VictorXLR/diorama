import copy
import json

import httpx
import pytest
from starlette.testclient import TestClient

from diorama.app import app
from diorama.agents.openrouter import OpenRouterContextModel
import diorama.server as server_module


@pytest.fixture(autouse=True)
def model_http(monkeypatch):
    """Exercise the real agent/model, and forbid unplanned model requests."""
    responses = []
    requests = []
    unexpected_requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        if not responses:
            unexpected_requests.append(request)
            raise AssertionError("Unexpected OpenRouter call")
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    model = OpenRouterContextModel(
        api_key="websocket-test-key",
        model="websocket-test-model",
        transport=httpx.MockTransport(respond),
    )
    monkeypatch.setattr(server_module.agent, "model", model)
    monkeypatch.setattr(server_module, "context_model", model)
    yield responses, requests
    assert not unexpected_requests, "Unexpected OpenRouter calls were made"
    assert not responses, "An expected OpenRouter call was not made"


@pytest.fixture
def native_scene():
    return [
        {
            "id": "sun", "type": "ellipse", "x": 12, "y": 34,
            "width": 80, "height": 80, "angle": 0.2,
            "backgroundColor": "#ffd43b", "seed": 123, "version": 7,
            "versionNonce": 456, "index": "a1", "isDeleted": False,
            "groupIds": ["illustration"], "frameId": "frame",
            "boundElements": [{"id": "ray", "type": "arrow"}],
            "customData": {"owner": "user", "nested": {"keep": True, "change": 1}},
        },
        {
            "id": "ray", "type": "arrow", "x": 92, "y": 74,
            "points": [[0, 0], [100, 20]],
            "startBinding": {"elementId": "sun", "focus": 0, "gap": 1},
            "endBinding": None, "endArrowhead": "arrow", "elbowed": False,
        },
        {
            "id": "photo", "type": "image", "x": 250, "y": 20,
            "width": 120, "height": 90, "fileId": "native-file",
            "status": "saved", "scale": [1, -1], "crop": None,
        },
        {
            "id": "frame", "type": "frame", "x": 0, "y": 0,
            "width": 500, "height": 300, "name": "User artwork",
        },
        {
            "id": "caption", "type": "text", "x": 20, "y": 150,
            "text": "Keep this café", "originalText": "Keep this café",
            "fontFamily": 5, "fontSize": 24, "lineHeight": 1.25,
            "containerId": None, "autoResize": True,
        },
        {
            "id": "sketch", "type": "freedraw", "x": 30, "y": 190,
            "points": [[0, 0], [10, 20]], "pressures": [0.3, 0.8],
            "simulatePressure": False, "lastCommittedPoint": [10, 20],
        },
    ]


def completion(upserts=(), deletes=()):
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
        "reply": "Updated the artwork.",
        "summary": "Applied the requested scene edits.",
        "suggestions": ["Add a cloud"],
        "canvas": {"upsertElements": list(upserts), "deleteElementIds": list(deletes)},
    })}}]})


def native_tool_completion(*calls):
    """Build an OpenAI-style native tool-calling response."""
    return httpx.Response(200, json={"choices": [{
        "finish_reason": "tool_calls",
        "message": {
            "content": None,
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(arguments)},
                }
                for call_id, name, arguments in calls
            ],
        },
    }]})


def legacy_context_completion():
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
        "reply": "Mapped the checkout flow.",
        "summary": "Rendered the checkout flow.",
        "suggestions": ["Add failure handling"],
        "context": {
            "id": "ctx-checkout", "title": "Checkout flow", "summary": "A customer completes a purchase.",
            "diagramType": "workflow", "groups": [{"id": "client", "title": "Customer"}],
            "nodes": [
                {"id": "cart", "label": "Cart", "category": "client", "groupId": "client", "description": "Items ready to buy"},
                {"id": "payment", "label": "Payment", "category": "service", "description": "Authorizes the charge"},
            ],
            "connections": [{"id": "cart-payment", "fromNode": "cart", "toNode": "payment", "label": "Submit"}],
            "insights": [], "tags": ["checkout"],
        },
    })}}]})


def receive_turn(ws):
    received = []
    # Bound unexpectedly verbose streams; receive_json still waits for each message.
    for _ in range(20):
        message = ws.receive_json()
        received.append(message)
        if message.get("type") == "agent_status" and message.get("status") == "idle":
            return received
    pytest.fail("Agent turn did not finish within 20 messages")


def context_update(messages):
    return next(message for message in messages if message["type"] == "context_update")


def model_prompt(request):
    return json.loads(request["messages"][1]["content"])


def test_websocket_handshake_starts_with_an_empty_session():
    client = TestClient(app)

    with client.websocket_connect("/ws/test-ws-1") as ws:
        ack = ws.receive_json()

    assert ack["type"] == "connection_ack"
    assert ack["sessionId"] == "test-ws-1"
    assert "initialContext" not in ack
    assert ack["initialMessages"] == []
    assert ack["visualElements"] == []


def test_websocket_ping_pong():
    client = TestClient(app)

    with client.websocket_connect("/ws/test-ws-2") as ws:
        ws.receive_json()
        ws.send_json({"type": "ping"})

        assert ws.receive_json() == {"type": "pong"}


def test_websocket_sync_scene_persists_browser_edits_without_an_agent_turn(native_scene):
    """Regression: the server only learned about canvas edits with the next chat message."""
    client = TestClient(app)
    with client.websocket_connect("/ws/browser-scene-sync") as ws:
        ws.receive_json()
        ws.send_json({"type": "sync_scene", "visualElements": native_scene, "files": {}})
        ws.send_json({"type": "request_current_state"})
        state = ws.receive_json()

    assert state["type"] == "context_update"
    assert state["visualElements"] == native_scene


def test_websocket_drops_stale_scene_sync_queued_during_an_agent_turn(model_http):
    """A delayed browser snapshot must not erase the agent's fresh whiteboard."""
    responses, _ = model_http
    responses.append(completion([
        {"id": "agent-route", "type": "rectangle", "x": 0, "y": 0, "width": 120, "height": 60},
    ]))

    with TestClient(app).websocket_connect("/ws/stale-scene-sync") as ws:
        ack = ws.receive_json()
        assert ack["sceneVersion"] == 0
        ws.send_json({
            "type": "user_message",
            "content": "Draw a route card.",
            "visualElements": [],
        })
        # The real browser can queue this while the server is awaiting the
        # model. It is read only after the final agent event otherwise.
        ws.send_json({
            "type": "sync_scene",
            "visualElements": [],
            "baseSceneVersion": ack["sceneVersion"],
        })
        received = receive_turn(ws)
        update = context_update(received)
        assert [element["id"] for element in update["visualElements"]] == ["agent-route"]
        assert update["sceneVersion"] > ack["sceneVersion"]

        ws.send_json({"type": "request_current_state"})
        state = ws.receive_json()

    assert [element["id"] for element in state["visualElements"]] == ["agent-route"]
    assert state["sceneVersion"] == update["sceneVersion"]


def test_websocket_renders_legacy_context_descriptions_as_excalidraw(model_http):
    """Regression: descriptive user queries stopped producing a visual context."""
    responses, _ = model_http
    responses.append(legacy_context_completion())

    with TestClient(app).websocket_connect("/ws/legacy-context") as ws:
        ws.receive_json()
        ws.send_json({"type": "user_message", "content": "Describe the checkout flow"})
        received = receive_turn(ws)

    update = context_update(received)
    assert update["context"]["id"] == "ctx-checkout"
    assert update["context"]["title"] == "Checkout flow"
    assert update["visualElements"]
    assert all(element["id"].startswith("ctx-checkout-preset-") for element in update["visualElements"])


def test_websocket_reprompts_prose_only_trip_reply_until_it_updates_canvas(model_http):
    """A useful itinerary must not be allowed to leave a route request's board stale."""
    responses, requests = model_http
    responses.extend([
        httpx.Response(200, json={"choices": [{"message": {"content": "Meet at Times Square, then visit MoMA."}}]}),
        completion([{"id": "trip-note", "type": "rectangle", "x": 0, "y": 0, "width": 100, "height": 50}]),
    ])

    with TestClient(app).websocket_connect("/ws/prose-trip-retry") as ws:
        ws.receive_json()
        ws.send_json({
            "type": "user_message",
            "content": "Plan a route from Flushing and Bushwick to Times Square and MoMA.",
        })
        received = receive_turn(ws)

    assert [element["id"] for element in context_update(received)["visualElements"]] == ["trip-note"]
    assert len(requests) == 2
    assert requests[1]["messages"][-1]["content"].startswith("Do not answer in prose only")


def test_websocket_rejects_json_final_without_a_visual_update(model_http):
    """JSON fallback finals obey the same visual requirement as native finish calls."""
    responses, requests = model_http
    responses.extend([
        httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
            "final": {"reply": "Here is your itinerary.", "summary": "Planned the trip."},
        })}}]}),
        completion([
            {"id": "json-trip-note", "type": "rectangle", "x": 0, "y": 0, "width": 100, "height": 50},
        ]),
    ])

    with TestClient(app).websocket_connect("/ws/json-final-retry") as ws:
        ws.receive_json()
        ws.send_json({
            "type": "user_message",
            "content": "Show a map-based Manhattan trip itinerary.",
        })
        received = receive_turn(ws)

    assert [element["id"] for element in context_update(received)["visualElements"]] == ["json-trip-note"]
    assert len(requests) == 2
    assert requests[1]["messages"][-1]["content"].startswith("Do not finish a visual request")


def test_websocket_rejects_native_finish_until_a_visual_request_changes_the_board(model_http):
    """A native `finish` call cannot bypass the visual-update requirement."""
    responses, requests = model_http
    responses.extend([
        native_tool_completion(("finish-early", "finish", {
            "reply": "Meet at Times Square, then visit MoMA.",
            "summary": "Planned the trip.",
        })),
        native_tool_completion(("draw-trip", "edit_elements", {
            "upsertElements": [
                {"id": "trip-note", "type": "rectangle", "x": 0, "y": 0, "width": 120, "height": 60},
            ],
        })),
        native_tool_completion(("finish-final", "finish", {
            "reply": "I added the route plan to the board.",
            "summary": "Drew the Manhattan trip plan.",
        })),
    ])

    with TestClient(app).websocket_connect("/ws/native-finish-retry") as ws:
        ws.receive_json()
        ws.send_json({
            "type": "user_message",
            "content": "Plan a route from Flushing and Bushwick to Times Square and MoMA.",
        })
        received = receive_turn(ws)

    assert [element["id"] for element in context_update(received)["visualElements"]] == ["trip-note"]
    assert len(requests) == 3
    retry_messages = requests[1]["messages"]
    assert retry_messages[-2] == {
        "role": "tool",
        "tool_call_id": "finish-early",
        "name": "finish",
        "content": json.dumps({
            "error": "finish was rejected because this visual request has not changed the Excalidraw board. "
            "Make a visible canvas update before calling finish.",
        }),
    }
    assert retry_messages[-1]["role"] == "user"
    assert retry_messages[-1]["content"].startswith("The previous finish was rejected")


def test_websocket_user_message_edits_full_native_scene(model_http, native_scene):
    responses, requests = model_http
    new_cloud = {
        "id": "cloud", "type": "ellipse", "x": 300, "y": 40,
        "width": 100, "height": 50, "backgroundColor": "#ffffff",
    }
    responses.append(completion([
        {"id": "sun", "x": 200, "groupIds": [], "boundElements": None,
         "customData": {"nested": {"change": 2}}},
        {"id": "photo", "x": 400},
        new_cloud,
    ], ["ray"]))
    expected = copy.deepcopy(native_scene)
    expected[0].update(x=200, groupIds=[], boundElements=None)
    expected[0]["customData"]["nested"]["change"] = 2
    expected[2]["x"] = 400
    expected = [element for element in expected if element["id"] != "ray"] + [new_cloud]
    content = "Move the sun and photo, delete its ray, and add a cloud."

    with TestClient(app).websocket_connect("/ws/test-ws-3") as ws:
        ws.receive_json()
        ws.send_json({"type": "user_message", "content": content, "visualElements": native_scene})
        received = receive_turn(ws)
        ws.send_json({"type": "request_current_state"})
        state = ws.receive_json()

    types = [message["type"] for message in received]
    assert types[0] == "agent_status"
    assert types[-3:] == ["context_update", "agent_message", "agent_status"]
    statuses = [message["status"] for message in received if message["type"] == "agent_status"]
    assert statuses[0] == "thinking"
    assert "generating_plan" in statuses
    assert statuses[-1] == "idle"
    update = context_update(received)
    assert "context" not in update
    assert update["visualElements"] == expected
    assert state["visualElements"] == expected
    reply = received[-2]
    assert reply["sender"] == "agent"
    assert reply["content"] == "Updated the artwork."
    assert reply["suggestions"] == ["Add a cloud"]
    assert reply["visualUpdate"] == {
        "summary": update["summary"], "elementsAdded": 1,
    }
    assert len(requests) == 1
    assert requests[0]["model"] == "websocket-test-model"
    # Native tool calling sends a toolbox; JSON-mode fallback sends response_format.
    assert "tools" in requests[0] or requests[0].get("response_format") == {"type": "json_object"}
    prompt = model_prompt(requests[0])
    assert prompt["userRequest"] == content
    assert prompt["visualElements"] == native_scene
    assert prompt["conversationHistory"] == [{"sender": "user", "content": content}]
    assert prompt["workspaceContext"] == {}


def test_websocket_select_preset_streams_microservices_context():
    client = TestClient(app)

    with client.websocket_connect("/ws/test-ws-4") as ws:
        ws.receive_json()
        ws.send_json({"type": "select_preset", "presetId": "microservices"})

        context_update = ws.receive_json()
        agent_message = ws.receive_json()

    assert context_update["type"] == "context_update"
    assert context_update["context"]["id"] == "ctx-microservices"
    assert context_update["context"]["diagramType"] == "system_topology"
    assert len(context_update["visualElements"]) > 0
    assert agent_message["type"] == "agent_message"
    assert "microservices" in agent_message["content"].lower()


def test_websocket_reset_and_state_requests_use_context_contract():
    client = TestClient(app)

    with client.websocket_connect("/ws/test-ws-5") as ws:
        ws.receive_json()
        ws.send_json({"type": "select_preset", "presetId": "microservices"})
        ws.receive_json()
        ws.receive_json()

        ws.send_json({"type": "request_current_state"})
        current_context = ws.receive_json()

        ws.send_json({"type": "reset_session"})
        reset_ack = ws.receive_json()

    assert current_context["type"] == "context_update"
    assert current_context["context"]["id"] == "ctx-microservices"
    assert reset_ack["type"] == "connection_ack"
    assert "initialContext" not in reset_ack
    assert reset_ack["visualElements"] == []


def test_websocket_request_current_state_on_empty_session_returns_no_context():
    client = TestClient(app)

    with client.websocket_connect("/ws/test-ws-7") as ws:
        ws.receive_json()
        ws.send_json({"type": "request_current_state"})
        current_state = ws.receive_json()

    assert current_state["type"] == "context_update"
    assert "context" not in current_state
    assert current_state["visualElements"] == []


def test_websocket_rejects_invalid_json():
    client = TestClient(app)

    with client.websocket_connect("/ws/test-ws-6") as ws:
        ws.receive_json()
        ws.send_text("THIS IS NOT JSON")

        error = ws.receive_json()

    assert error["type"] == "error"
    assert error["code"] == "INVALID_JSON"


def test_websocket_omitted_scene_uses_stored_scene_but_empty_list_clears(model_http, native_scene):
    responses, requests = model_http
    responses.extend([completion(), completion([{"id": "sun", "y": 99}]), completion()])
    expected = copy.deepcopy(native_scene)
    expected[0]["y"] = 99
    with TestClient(app).websocket_connect("/ws/scene-omission") as ws:
        ws.receive_json()
        ws.send_json({"type": "user_message", "content": "Keep this", "visualElements": native_scene})
        assert context_update(receive_turn(ws))["visualElements"] == native_scene
        ws.send_json({"type": "user_message", "content": "Move the sun"})
        edited = receive_turn(ws)
        assert context_update(edited)["visualElements"] == expected
        assert edited[-2]["visualUpdate"]["elementsAdded"] == 0
        ws.send_json({"type": "user_message", "content": "Keep it empty", "visualElements": []})
        cleared = receive_turn(ws)
        assert context_update(cleared)["visualElements"] == []
        assert cleared[-2]["visualUpdate"]["elementsAdded"] == 0
        ws.send_json({"type": "request_current_state"})
        assert ws.receive_json()["visualElements"] == []
    assert len(requests) == 3
    assert [model_prompt(request)["visualElements"] for request in requests] == [native_scene, native_scene, []]
    assert [item["sender"] for item in model_prompt(requests[1])["conversationHistory"]] == [
        "user", "agent", "user",
    ]


def test_websocket_reconnect_restores_scene_history_and_reset_clears_both(model_http, native_scene):
    responses, requests = model_http
    responses.append(completion())
    client = TestClient(app)
    with client.websocket_connect("/ws/reconnect-native") as ws:
        ws.receive_json()
        ws.send_json({"type": "user_message", "content": "Preserve this", "visualElements": native_scene})
        receive_turn(ws)
    with client.websocket_connect("/ws/reconnect-native") as ws:
        ack = ws.receive_json()
        assert ack["type"] == "connection_ack", ack
        assert ack["sessionId"] == "reconnect-native"
        assert "initialContext" not in ack
        assert ack["visualElements"] == native_scene
        assert [message["sender"] for message in ack["initialMessages"]] == ["user", "agent"]
        assert ack["initialMessages"][0]["content"] == "Preserve this"
        assert ack["initialMessages"][1]["content"] == "Updated the artwork."
        ws.send_json({"type": "request_current_state"})
        state = ws.receive_json()
        assert state["type"] == "context_update"
        assert "context" not in state
        assert state["visualElements"] == native_scene
        ws.send_json({"type": "reset_session"})
        reset = ws.receive_json()
        assert reset["type"] == "connection_ack"
        assert reset["sessionId"] == ack["sessionId"]
        assert reset["initialMessages"] == []
        assert reset["visualElements"] == []
        assert "initialContext" not in reset
        ws.send_json({"type": "request_current_state"})
        assert ws.receive_json()["visualElements"] == []
    with client.websocket_connect("/ws/reconnect-native") as ws:
        ack = ws.receive_json()
        assert ack["initialMessages"] == []
        assert ack["visualElements"] == []
        assert "initialContext" not in ack
    assert len(requests) == 1


def test_websocket_reset_native_scene_clears_history_and_next_model_prompt(model_http, native_scene):
    responses, requests = model_http
    responses.extend([completion(), completion()])
    with TestClient(app).websocket_connect("/ws/reset-native") as ws:
        ws.receive_json()
        ws.send_json({"type": "user_message", "content": "Keep", "visualElements": native_scene})
        receive_turn(ws)
        ws.send_json({"type": "reset_session"})
        ack = ws.receive_json()
        assert ack["type"] == "connection_ack"
        assert ack["sessionId"] == "reset-native"
        assert ack["visualElements"] == []
        assert ack["initialMessages"] == []
        assert "initialContext" not in ack
        ws.send_json({"type": "user_message", "content": "Start fresh"})
        assert context_update(receive_turn(ws))["visualElements"] == []
    assert len(requests) == 2
    prompt = model_prompt(requests[-1])
    assert prompt["visualElements"] == []
    assert prompt["conversationHistory"] == [{"sender": "user", "content": "Start fresh"}]


@pytest.mark.parametrize("preset_id,context_id,diagram_type", [
    ("architecture", "ctx-diorama-arch", "architecture"),
    ("microservices", "ctx-microservices", "system_topology"),
])
def test_websocket_presets_have_stable_ids_and_support_model_edits(
    model_http, preset_id, context_id, diagram_type,
):
    responses, requests = model_http
    with TestClient(app).websocket_connect(f"/ws/preset-edit-{preset_id}") as ws:
        ws.receive_json()
        scenes = []
        for _ in range(2):
            ws.send_json({"type": "select_preset", "presetId": preset_id})
            update = ws.receive_json()
            reply = ws.receive_json()
            assert update["type"] == "context_update"
            assert update["context"]["id"] == context_id
            assert update["context"]["diagramType"] == diagram_type
            assert reply["type"] == "agent_message"
            assert reply["visualUpdate"]["elementsAdded"] == len(update["visualElements"])
            scenes.append(update["visualElements"])
        assert scenes[0] == scenes[1]
        ids = [element["id"] for element in scenes[0]]
        assert ids and all(isinstance(id_, str) and id_.strip() for id_ in ids)
        assert len(ids) == len(set(ids))
        assert not requests
        responses.append(completion([{"id": ids[0], "x": 777}]))
        ws.send_json({"type": "user_message", "content": "Move the header"})
        received = receive_turn(ws)
        expected = copy.deepcopy(scenes[0])
        expected[0]["x"] = 777
        assert context_update(received)["visualElements"] == expected
        assert received[-2]["visualUpdate"]["elementsAdded"] == 0
    assert len(requests) == 1
    assert model_prompt(requests[0])["visualElements"] == scenes[0]


@pytest.mark.parametrize("payload,code", [
    ([], "INVALID_MESSAGE"),
    (None, "INVALID_MESSAGE"),
    ({"type": "unknown"}, "UNKNOWN_MESSAGE_TYPE"),
    ({"type": "select_preset", "presetId": "missing"}, "UNKNOWN_PRESET"),
    ({"type": "user_message"}, "INVALID_MESSAGE"),
    ({"type": "user_message", "content": 123}, "INVALID_MESSAGE"),
    ({"type": "user_message", "content": "  ", "visualElements": []}, "EMPTY_MESSAGE"),
    ({"type": "user_message", "content": "Edit", "visualElements": {}}, "INVALID_MESSAGE"),
    ({"type": "user_message", "content": "Edit", "visualElements": [{"id": "bad"}]}, "INVALID_MESSAGE"),
])
def test_websocket_invalid_messages_preserve_state_and_connection(model_http, native_scene, payload, code, request):
    responses, requests = model_http
    responses.append(completion())
    with TestClient(app).websocket_connect(f"/ws/{request.node.name}") as ws:
        ws.receive_json()
        ws.send_json({"type": "user_message", "content": "Keep", "visualElements": native_scene})
        receive_turn(ws)
        ws.send_json(payload)
        error = ws.receive_json()
        assert error["type"] == "error"
        assert error["code"] == code
        ws.send_json({"type": "request_current_state"})
        assert ws.receive_json()["visualElements"] == native_scene
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}
    assert len(requests) == 1


@pytest.mark.parametrize("invalid_scene", [
    [{"id": "duplicate", "type": "text", "x": 0, "y": 0, "text": "a"}] * 2,
    [{"id": "bad", "type": "rectangle", "x": "0", "y": 0, "width": 10, "height": 10}],
    [{"id": "bad", "type": "rectangle", "x": 0, "y": 0, "width": -1, "height": 10}],
    [{"id": "bad", "type": "arrow", "x": 0, "y": 0, "points": [[0, 0]]}],
    [{"id": "bad", "type": "text", "x": 0, "y": 0}],
    [{"id": "bad", "type": "text", "x": 0, "y": 0, "text": "a", "customData": {"bad": float("inf")}}],
])
def test_websocket_invalid_scene_is_rejected_before_model_call(model_http, native_scene, invalid_scene, request):
    responses, requests = model_http
    responses.append(completion())
    with TestClient(app).websocket_connect(f"/ws/{request.node.name}") as ws:
        ws.receive_json()
        ws.send_json({"type": "user_message", "content": "Keep", "visualElements": native_scene})
        receive_turn(ws)
        ws.send_text(json.dumps({"type": "user_message", "content": "Edit", "visualElements": invalid_scene}))
        error = ws.receive_json()
        assert error["type"] == "error"
        assert error["code"] == "INVALID_MESSAGE"
        ws.send_json({"type": "request_current_state"})
        assert ws.receive_json()["visualElements"] == native_scene
    assert len(requests) == 1


@pytest.mark.parametrize("failure", [
    httpx.Response(503, json={"error": "unavailable"}),
    httpx.ConnectError("offline"),
    httpx.Response(200, json={"choices": []}),
    httpx.Response(200, json={"choices": [{"message": {"content": '{"reply": "cut off'}}]}),
    completion([{"id": "sun", "x": 999}, {"id": "broken", "type": "ellipse", "x": 0, "y": 0}]),
    completion([{"id": "sun", "x": 999}, {"id": "photo", "type": "rectangle"}]),
    completion([{"id": "sun", "x": 999}], ["unknown"]),
    completion([{"id": "sun", "x": 999}], ["sun"]),
], ids=["http-error", "network-error", "missing-content", "invalid-json", "invalid-new-element",
        "type-change", "unknown-delete", "conflicting-ids"])
@pytest.mark.parametrize("supply_scene", [False, True], ids=["stored-scene", "supplied-scene"])
def test_websocket_model_failures_do_not_partially_mutate_scene(
    model_http, native_scene, failure, supply_scene, request,
):
    responses, requests = model_http
    responses.extend([completion(), failure])
    client = TestClient(app)
    with client.websocket_connect(f"/ws/{request.node.name}") as ws:
        ws.receive_json()
        ws.send_json({"type": "user_message", "content": "Keep", "visualElements": native_scene})
        receive_turn(ws)
        payload = {"type": "user_message", "content": "Move the sun"}
        if supply_scene:
            payload["visualElements"] = native_scene
        ws.send_json(payload)
        received = receive_turn(ws)
        types = [message["type"] for message in received]
        assert "context_update" not in types and "agent_message" not in types
        assert types[-2:] == ["error", "agent_status"]
        assert received[-2]["code"] == "AGENT_EXECUTION_ERROR"
        assert received[-2]["message"]
        assert received[-1]["status"] == "idle"
    # The error path ends the handler; inspect persisted state independently
    # of the reconnect contract so a handshake failure cannot mask atomicity.
    state = client.get("/api/context", params={"session_id": request.node.name})
    assert state.status_code == 200
    assert state.json()["visualElements"] == native_scene
    assert len(requests) == 2
    assert model_prompt(requests[-1])["visualElements"] == native_scene
