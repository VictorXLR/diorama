from starlette.testclient import TestClient

from diorama.app import app

client = TestClient(app)


def test_health_check_reports_visual_context_capabilities():
    response = client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "diorama-server"
    assert {"visual_context", "excalidraw_whiteboard", "websocket_streaming"} <= set(data["capabilities"])
    assert data["model_provider"] in {"openrouter", "unconfigured"}


def test_get_context_for_new_session_is_empty():
    response = client.get("/api/context", params={"session_id": "api-context-test"})

    assert response.status_code == 200
    data = response.json()
    assert data["context"] is None
    assert data["visualElements"] == []


def test_get_visual_context_presets():
    response = client.get("/api/presets")

    assert response.status_code == 200
    assert {preset["id"] for preset in response.json()} == {"architecture", "microservices"}
