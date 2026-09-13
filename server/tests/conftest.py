import os
import tempfile

# Hermetic knowledge base: set before diorama.server is imported anywhere in
# the suite, so no test ever touches the user's real ~/.diorama/knowledge.db.
os.environ["DIORAMA_KB"] = os.path.join(tempfile.mkdtemp(prefix="diorama-test-kb-"), "knowledge.db")

import httpx
import pytest

import diorama.server as server_module


@pytest.fixture(autouse=True)
def isolate_sessions_and_block_live_http(monkeypatch):
    """Never allow credentials or session state to leak into a test."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    # The singleton may already have captured credentials during collection.
    monkeypatch.setattr(server_module.context_model, "api_key", None)
    monkeypatch.setattr(server_module.agent.model, "api_key", None)
    server_module.sessions.clear()
    attempted = []

    def block_request(self, request):
        attempted.append(str(request.url))
        raise AssertionError("Real HTTP requests are forbidden; use httpx.MockTransport")

    async def block_async_request(self, request):
        block_request(self, request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", block_request)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", block_async_request)
    yield
    server_module.sessions.clear()
    assert not attempted, f"Tests attempted live HTTP requests: {attempted}"
