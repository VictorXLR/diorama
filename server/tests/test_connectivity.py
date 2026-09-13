"""Tests for the API connectivity map: connectors, tables, endpoints, UI wiring."""

from __future__ import annotations

import json

import pytest

from diorama.codebase.connectivity import (
    build_connectivity_map,
    connectivity_to_primitives,
    _matches_endpoint,
    _split_select_columns,
)
from diorama.codebase.workspace import Workspace
from diorama.tools import ToolContext
from diorama.tools.code import (
    MapConnectivityArgs,
    VisualizeConnectivityArgs,
    _map_connectivity,
    _visualize_connectivity,
)
from diorama.visual.primitives import CardPrimitive, RoutePrimitive


def make_supabase_repo(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "dependencies": {
                    "@supabase/supabase-js": "^2.45.0",
                    "next": "14.2.0",
                    "zustand": "^4.5.0",
                }
            }
        )
    )
    (tmp_path / ".env.example").write_text(
        "NEXT_PUBLIC_SUPABASE_URL=https://demo.supabase.co\nNEXT_PUBLIC_SUPABASE_ANON_KEY=abc\n"
    )

    lib = tmp_path / "src" / "lib"
    lib.mkdir(parents=True)
    (lib / "supabase.ts").write_text(
        """import { createClient } from '@supabase/supabase-js'
export const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
)
"""
    )

    api_users = tmp_path / "src" / "app" / "api" / "users"
    api_users.mkdir(parents=True)
    (api_users / "route.ts").write_text(
        """import { supabase } from '@/lib/supabase'
import { NextResponse } from 'next/server'

export async function GET() {
  const { data } = await supabase.from('users').select('id, email, created_at')
  return NextResponse.json(data)
}

export async function POST(request: Request) {
  const body = await request.json()
  const { error } = await supabase.from('users').insert({ email: body.email, name: body.name })
  if (error) return NextResponse.json({ error }, { status: 500 })
  return NextResponse.json({ ok: true })
}
"""
    )

    api_order = tmp_path / "src" / "app" / "api" / "orders" / "[id]"
    api_order.mkdir(parents=True)
    (api_order / "route.ts").write_text(
        """import { supabase } from '@/lib/supabase'

export async function GET() {
  const { data } = await supabase.from('orders').select('id, total, status').eq('status', 'paid')
  return Response.json(data)
}
"""
    )

    components = tmp_path / "src" / "components"
    components.mkdir()
    (components / "UsersList.tsx").write_text(
        """'use client'
import { useEffect, useState } from 'react'
import { supabase } from '@/lib/supabase'

export function UsersList() {
  const [users, setUsers] = useState([])
  useEffect(() => {
    fetch('/api/users', { method: 'POST', body: '{}' })
    supabase.from('users').select('id, email').eq('id', 1)
  }, [])
  return <div>{users.length}</div>
}
"""
    )

    store = tmp_path / "src" / "store"
    store.mkdir()
    (store / "useCart.ts").write_text(
        """import { create } from 'zustand'
export const useCart = create(() => ({ items: [] }))
"""
    )
    return tmp_path


def make_context(workspace: Workspace) -> ToolContext:
    return ToolContext(session_id="s1", scene=[], files={}, workspace=workspace)


# --------------------------------------------------------------------------- #
# Unit helpers
# --------------------------------------------------------------------------- #


def test_split_select_columns_handles_embedded_relations():
    assert _split_select_columns("id, email, author(name, bio), created_at") == [
        "id", "email", "author", "created_at",
    ]


def test_matches_endpoint_honours_dynamic_segments():
    from diorama.codebase.connectivity import Endpoint

    dynamic = Endpoint(method="GET", path="/api/orders/[id]", handler="x", line=1, framework="nextjs")
    assert _matches_endpoint("/api/orders/42", dynamic)
    assert not _matches_endpoint("/api/orders", dynamic)
    assert _matches_endpoint("/api/orders/42/items", dynamic)  # longer call paths still hit the route


# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #


def test_connectivity_detects_supabase_connector_and_tables(tmp_path):
    workspace = Workspace(make_supabase_repo(tmp_path))
    connectivity = build_connectivity_map(workspace)

    names = [connector.name for connector in connectivity.connectors]
    assert "Supabase" in names
    supabase = next(connector for connector in connectivity.connectors if connector.name == "Supabase")
    assert "@supabase/supabase-js" in supabase.packages
    assert "NEXT_PUBLIC_SUPABASE_URL" in supabase.env_vars

    tables = {table.name: table for table in connectivity.tables}
    assert set(tables) == {"users", "orders"}
    users = tables["users"]
    assert {"select", "insert"} <= users.operations
    assert {"id", "email", "name"} <= users.columns
    assert any("route.ts" in path for path in users.files)
    assert any("UsersList.tsx" in path for path in users.files)


def test_connectivity_detects_nextjs_endpoints(tmp_path):
    workspace = Workspace(make_supabase_repo(tmp_path))
    connectivity = build_connectivity_map(workspace)

    endpoint_ids = {endpoint.id for endpoint in connectivity.endpoints}
    assert "GET /api/users" in endpoint_ids
    assert "POST /api/users" in endpoint_ids
    assert "GET /api/orders/[id]" in endpoint_ids
    assert all(endpoint.framework == "nextjs" for endpoint in connectivity.endpoints)


def test_connectivity_links_ui_calls_to_endpoints(tmp_path):
    workspace = Workspace(make_supabase_repo(tmp_path))
    connectivity = build_connectivity_map(workspace)

    calls = [call for call in connectivity.client_calls if call.url == "/api/users"]
    assert calls and calls[0].method == "POST"
    assert calls[0].endpoint == "POST /api/users"
    assert any("UsersList.tsx" in call.file for call in calls)

    edges = {(edge.source, edge.target, edge.kind) for edge in connectivity.edges}
    assert any(
        source.startswith("ui:src/components/UsersList.tsx") and target == "endpoint:POST /api/users" and kind == "http"
        for source, target, kind in edges
    )
    assert any(target == "table:users" and kind == "data" for _, target, kind in edges)
    assert any(target == "connector:Supabase" for _, target, _ in edges)


def test_connectivity_detects_state_management(tmp_path):
    workspace = Workspace(make_supabase_repo(tmp_path))
    connectivity = build_connectivity_map(workspace)

    frameworks = {usage.framework: usage for usage in connectivity.state}
    assert "Zustand" in frameworks
    assert any("useCart.ts" in path for path in frameworks["Zustand"].files)
    assert "React local hooks" in frameworks


def test_connectivity_summary_is_json_serialisable(tmp_path):
    workspace = Workspace(make_supabase_repo(tmp_path))
    summary = build_connectivity_map(workspace).to_summary()
    json.dumps(summary)  # must not raise
    assert summary["clientCallsMatched"] >= 1


# --------------------------------------------------------------------------- #
# Layout
# --------------------------------------------------------------------------- #


def test_connectivity_layout_draws_frames_cards_and_routes(tmp_path):
    workspace = Workspace(make_supabase_repo(tmp_path))
    connectivity = build_connectivity_map(workspace)
    primitives = connectivity_to_primitives(connectivity)

    kinds = [primitive.kind for primitive in primitives]
    assert kinds.count("frame") == 3
    cards = [p for p in primitives if isinstance(p, CardPrimitive)]
    titles = [card.title for card in cards]
    assert "Supabase" in titles
    assert "table · users" in titles
    assert "GET /api/users" in titles
    assert "State management" in titles

    routes = [p for p in primitives if isinstance(p, RoutePrimitive)]
    assert routes, "expected UI -> endpoint -> table -> connector arrows"
    route_targets = {route.to for route in routes}
    assert any("conn-connector-Supabase" in target for target in route_targets)


def test_connectivity_layout_on_empty_repo(tmp_path):
    (tmp_path / "README.md").write_text("nothing\n")
    workspace = Workspace(tmp_path)
    primitives = connectivity_to_primitives(build_connectivity_map(workspace))
    kinds = [primitive.kind for primitive in primitives]
    assert "heading" in kinds
    assert "note" in kinds


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_map_connectivity_tool(tmp_path):
    workspace = Workspace(make_supabase_repo(tmp_path))
    result = await _map_connectivity(MapConnectivityArgs(), make_context(workspace))
    assert "Supabase" in [connector["name"] for connector in result.content["connectors"]]
    assert "users" in [table["name"] for table in result.content["tables"]]


@pytest.mark.asyncio
async def test_visualize_connectivity_tool_returns_patch(tmp_path):
    workspace = Workspace(make_supabase_repo(tmp_path))
    result = await _visualize_connectivity(VisualizeConnectivityArgs(), make_context(workspace))
    assert result.patch is not None
    assert any(p.kind == "route" for p in result.patch.primitives)
    assert "users" in result.content["tables"]
