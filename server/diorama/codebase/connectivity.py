"""API connectivity map: connectors, endpoints, data tables, and the UI wiring.

The file map answers "what files exist?".  The architecture view answers "what
roles do they play?".  This module answers the question an engineer actually
asks about a running system: **what talks to what?**

* Which **external services** the app is wired to (Supabase, Firebase, Stripe,
  OpenAI, ...) and through which SDK / env vars.
* For BaaS connectors such as Supabase: which **tables** are touched, from
  which files, with which operations, and which columns those touches imply —
  so you can "zoom into" the database without leaving the board.
* Which **HTTP endpoints** exist (Next.js route handlers, Express, FastAPI,
  Flask) and which UI files call them — the request path from click to query.
* How the front end **holds state** (Zustand, Redux, React Query, context,
  local hooks) so data-flow claims can be checked against reality.

Extraction is regex over the same indexed sources (fast, dependency-free, and
never worse than a grep); the output is a :class:`ConnectivityMap` that can be
summarised for the model or laid out into canvas primitives for the user.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from diorama.codebase.architecture import classify
from diorama.codebase.indexer import CodeGraph, CodeNode
from diorama.codebase.workspace import Workspace
from diorama.visual.primitives import (
    CardPrimitive,
    FramePrimitive,
    HeadingPrimitive,
    LegendItem,
    LegendPrimitive,
    NotePrimitive,
    Primitive,
    RoutePrimitive,
)

# --------------------------------------------------------------------------- #
# Connectors
# --------------------------------------------------------------------------- #

# Import specifier (prefix) -> (connector name, kind, note)
CONNECTOR_PACKAGES: Dict[str, Tuple[str, str, str]] = {
    "@supabase/supabase-js": ("Supabase", "baas", "Postgres + auth + storage SDK"),
    "@supabase/ssr": ("Supabase", "baas", "server-side Supabase client"),
    "@supabase/auth-helpers-nextjs": ("Supabase", "baas", "Next.js auth helpers"),
    "firebase": ("Firebase", "baas", "client SDK"),
    "firebase-admin": ("Firebase", "baas", "admin SDK"),
    "stripe": ("Stripe", "payments", "server SDK"),
    "@stripe/stripe-js": ("Stripe", "payments", "client SDK"),
    "@paypal/react-paypal-js": ("PayPal", "payments", "client SDK"),
    "openai": ("OpenAI", "llm", "API client"),
    "@anthropic-ai/sdk": ("Anthropic", "llm", "API client"),
    "anthropic": ("Anthropic", "llm", "API client"),
    "@google/generative-ai": ("Google AI", "llm", "Gemini client"),
    "contentful": ("Contentful", "cms", "headless CMS"),
    "@sanity/client": ("Sanity", "cms", "headless CMS"),
    "algoliasearch": ("Algolia", "search", "search client"),
    "@aws-sdk/client-s3": ("AWS S3", "storage", "object storage"),
    "@aws-sdk/client-sns": ("AWS SNS", "messaging", "notifications"),
    "@sendgrid/mail": ("SendGrid", "email", "transactional email"),
    "nodemailer": ("SMTP", "email", "direct mailer"),
    "@resend/react-email": ("Resend", "email", "transactional email"),
    "@sentry/nextjs": ("Sentry", "observability", "error reporting"),
    "@sentry/node": ("Sentry", "observability", "error reporting"),
    "sentry_sdk": ("Sentry", "observability", "error reporting"),
}

# env var prefix -> (connector name, kind)
CONNECTOR_ENV_VARS: Dict[str, Tuple[str, str]] = {
    "SUPABASE_URL": ("Supabase", "baas"),
    "NEXT_PUBLIC_SUPABASE_URL": ("Supabase", "baas"),
    "STRIPE_SECRET_KEY": ("Stripe", "payments"),
    "NEXT_PUBLIC_STRIPE": ("Stripe", "payments"),
    "OPENAI_API_KEY": ("OpenAI", "llm"),
    "ANTHROPIC_API_KEY": ("Anthropic", "llm"),
    "FIREBASE": ("Firebase", "baas"),
    "CONTENTFUL": ("Contentful", "cms"),
    "SANITY": ("Sanity", "cms"),
    "ALGOLIA": ("Algolia", "search"),
    "SENDGRID": ("SendGrid", "email"),
    "RESEND": ("Resend", "email"),
    "SENTRY_DSN": ("Sentry", "observability"),
}

CONNECTOR_ACCENTS: Dict[str, str] = {
    "baas": "emerald",
    "database": "emerald",
    "payments": "coral",
    "llm": "violet",
    "cms": "amber",
    "search": "amber",
    "storage": "sky",
    "messaging": "amber",
    "email": "coral",
    "observability": "slate",
    "http_api": "sky",
}

# State management: import -> framework label
STATE_PACKAGES: Dict[str, str] = {
    "zustand": "Zustand",
    "@reduxjs/toolkit": "Redux Toolkit",
    "redux": "Redux",
    "react-redux": "React Redux",
    "jotai": "Jotai",
    "valtio": "Valtio",
    "mobx": "MobX",
    "recoil": "Recoil",
    "@tanstack/react-query": "React Query (server-state cache)",
    "swr": "SWR (server-state cache)",
    "xstate": "XState",
    "immer": "Immer",
}

HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")

# Supabase query-builder operations worth recording.
TABLE_OPS = {"select", "insert", "update", "upsert", "delete"}
# Column-filtering calls whose first string argument is a column name.
COLUMN_FILTER_CALLS = (
    "eq", "neq", "gt", "gte", "lt", "lte", "like", "ilike", "is", "in", "contains",
    "order", "range", "match", "textSearch", "containedBy",
)
AUTH_CALLS = (
    "signInWithPassword", "signInWithOAuth", "signUp", "signOut", "getUser", "getSession",
    "onAuthStateChange", "resetPasswordForEmail", "updateUser", "getClaims",
)

_FROM_CALL_RE = re.compile(r"""\.from\(\s*["']([\w-]+)["']\s*\)""")
_RPC_RE = re.compile(r"""\.rpc\(\s*["']([\w-]+)["']""")
_STORAGE_BUCKET_RE = re.compile(r"""\.storage\(\s*\)\s*\.from\(\s*["']([\w-]+)["']""")
_OP_RE = re.compile(r"""\.\b(select|insert|update|upsert|delete)\b""")
_SELECT_COLUMNS_RE = re.compile(r"""\.select\(\s*["']([^"']+)["']""")
_FILTER_COLUMN_RE = re.compile(
    r"""\.\b(?:%s)\(\s*["']([\w]+)["']""" % "|".join(COLUMN_FILTER_CALLS)
)
_OBJECT_KEYS_RE = re.compile(r"""[{,]\s*([A-Za-z_$][\w$]*)\s*:""")
_METHOD_EXPORT_RE = re.compile(
    r"""export\s+(?:async\s+)?function\s+(%s)\b""" % "|".join(HTTP_METHODS)
)
_EXPRESS_ROUTE_RE = re.compile(
    r"""\b(?:app|router|server|api)\s*\.\s*(get|post|put|patch|delete|head|options)\s*\(\s*["']([^"']+)["']"""
)
_PYTHON_ROUTE_RE = re.compile(
    r"""@\w+\s*\.\s*(get|post|put|patch|delete|route)\s*\(\s*["']([^"']+)["']""",
    re.IGNORECASE,
)
_FETCH_URL_RE = re.compile(r"""\bfetch\s*\(\s*["'`]([^"'`]+)["'`]""")
_AXIOS_RE = re.compile(r"""\baxios\s*\.\s*(get|post|put|patch|delete)\s*\(\s*["']([^"']+)["']""")
_USESTATE_RE = re.compile(r"""\buse(?:State|Reducer)\s*\(""")
_CREATE_CONTEXT_RE = re.compile(r"""\bcreateContext\s*\(""")

SOURCE_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".py", ".vue", ".svelte"}


# --------------------------------------------------------------------------- #
# Model
# --------------------------------------------------------------------------- #


@dataclass
class Connector:
    name: str
    kind: str  # baas | payments | llm | cms | search | storage | email | observability | http_api
    files: List[str] = field(default_factory=list)
    packages: Set[str] = field(default_factory=set)
    env_vars: Set[str] = field(default_factory=set)
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "files": self.files[:8],
            "packages": sorted(self.packages),
            "envVars": sorted(self.env_vars),
            "note": self.note,
        }


@dataclass
class TableUsage:
    name: str
    operations: Set[str] = field(default_factory=set)
    columns: Set[str] = field(default_factory=set)
    files: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "operations": sorted(self.operations),
            "columns": sorted(self.columns)[:12],
            "files": self.files[:6],
        }


@dataclass
class Endpoint:
    method: str
    path: str
    handler: str
    line: int
    framework: str  # nextjs | express | fastapi | flask | unknown

    @property
    def id(self) -> str:
        return f"{self.method} {self.path}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "method": self.method,
            "path": self.path,
            "handler": self.handler,
            "line": self.line,
            "framework": self.framework,
        }


@dataclass
class ClientCall:
    file: str
    method: str
    url: str
    endpoint: Optional[str] = None  # matched endpoint id, if any

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {"file": self.file, "method": self.method, "url": self.url}
        if self.endpoint:
            data["endpoint"] = self.endpoint
        return data


@dataclass
class StateUsage:
    framework: str
    files: List[str] = field(default_factory=list)
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"framework": self.framework, "files": self.files[:8], "detail": self.detail}


@dataclass
class ConnectivityEdge:
    source: str  # e.g. "ui:src/components/Users.tsx" or "endpoint:GET /api/users"
    target: str
    kind: str  # http | data | rpc | storage | auth
    label: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"source": self.source, "target": self.target, "kind": self.kind, "label": self.label}


@dataclass
class ConnectivityMap:
    root: str
    name: str
    connectors: List[Connector] = field(default_factory=list)
    tables: List[TableUsage] = field(default_factory=list)
    rpcs: List[str] = field(default_factory=list)
    buckets: List[str] = field(default_factory=list)
    auth_files: List[str] = field(default_factory=list)
    endpoints: List[Endpoint] = field(default_factory=list)
    client_calls: List[ClientCall] = field(default_factory=list)
    state: List[StateUsage] = field(default_factory=list)
    edges: List[ConnectivityEdge] = field(default_factory=list)

    # ------------------------------------------------------------- summaries

    def to_summary(self) -> Dict[str, Any]:
        matched = sum(1 for call in self.client_calls if call.endpoint)
        return {
            "root": self.root,
            "name": self.name,
            "connectors": [connector.to_dict() for connector in self.connectors],
            "tables": [table.to_dict() for table in self.tables],
            "rpcFunctions": self.rpcs,
            "storageBuckets": self.buckets,
            "authFiles": self.auth_files[:8],
            "endpoints": [endpoint.to_dict() for endpoint in self.endpoints],
            "clientCalls": [call.to_dict() for call in self.client_calls],
            "clientCallsMatched": matched,
            "state": [usage.to_dict() for usage in self.state],
            "edges": [edge.to_dict() for edge in self.edges],
        }


# --------------------------------------------------------------------------- #
# Extraction helpers
# --------------------------------------------------------------------------- #


def _split_select_columns(spec: str) -> List[str]:
    """Top-level column names from a Supabase ``.select("a, b(c), d")`` spec."""
    columns: List[str] = []
    depth = 0
    current = ""
    for char in spec:
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(depth - 1, 0)
        elif char == "," and depth == 0:
            columns.append(current.strip().split(" ")[0].split("(")[0])
            current = ""
            continue
        current += char
    tail = current.strip()
    if tail:
        columns.append(tail.split(" ")[0].split("(")[0])
    return [column for column in columns if column and column.isidentifier()]


def _object_literal_keys(source: str, call: str) -> List[str]:
    """Top-level keys of the first object literal argument of ``.call({...})``."""
    index = source.find(call)
    while index != -1:
        brace = source.find("{", index)
        if brace == -1:
            return []
        depth = 0
        for position in range(brace, len(source)):
            if source[position] == "{":
                depth += 1
            elif source[position] == "}":
                depth -= 1
                if depth == 0:
                    return _OBJECT_KEYS_RE.findall(source[brace:position])
        index = source.find(call, index + 1)
    return []


def _detect_connectors(sources: Dict[str, str], env_vars: Dict[str, str]) -> Dict[str, Connector]:
    connectors: Dict[str, Connector] = {}
    for path, source in sources.items():
        for raw in _iter_imports(source):
            for package, (name, kind, note) in CONNECTOR_PACKAGES.items():
                if raw == package or raw.startswith(package + "/"):
                    connector = connectors.setdefault(name, Connector(name=name, kind=kind, note=note))
                    connector.packages.add(package)
                    if path not in connector.files:
                        connector.files.append(path)
    for var, value in env_vars.items():
        for prefix, (name, kind) in CONNECTOR_ENV_VARS.items():
            if var.upper().startswith(prefix):
                connector = connectors.setdefault(name, Connector(name=name, kind=kind))
                connector.env_vars.add(var)
                if value and "localhost" not in value and "127.0.0.1" not in value:
                    connector.note = connector.note or f"configured via {var}"
    return connectors


_IMPORT_LINE_RE = re.compile(
    r"""(?:^|\n)\s*(?:import|export)[^\n]*?from\s+["']([^"']+)["']|(?:^|\n)\s*import\s+["']([^"']+)["']|require\(\s*["']([^"']+)["']|(?:^|\n)\s*from\s+([\w.]+)\s+import"""
)


def _iter_imports(source: str) -> Iterable[str]:
    for match in _IMPORT_LINE_RE.finditer(source):
        for group in match.groups():
            if group:
                yield group


def _detect_env_vars(workspace: Workspace) -> Dict[str, str]:
    env_vars: Dict[str, str] = {}
    for path in workspace.iter_files():
        if path.name not in {".env", ".env.local", ".env.example", ".env.development", ".env.production"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            env_vars[key.strip()] = value.strip().strip("\"'")
    return env_vars


def _nextjs_route_path(rel: str) -> Optional[str]:
    """``src/app/api/users/[id]/route.ts`` -> ``/api/users/[id]``."""
    parts = rel.split("/")
    if "app" not in parts:
        return None
    app_index = len(parts) - 1 - parts[::-1].index("app")
    segments = parts[app_index + 1 : -1]
    if not segments:
        return None
    segments = [segment for segment in segments if segment not in {"(auth)", "(shop)", "(app)"}]
    return "/" + "/".join(segments)


def _normalise_path(path: str) -> str:
    path = path.split("?")[0].split("#")[0]
    if len(path) > 1:
        path = path.rstrip("/")
    return path


def _matches_endpoint(call_path: str, endpoint: Endpoint) -> bool:
    """True when a client path hits this route, honouring dynamic segments."""
    call_segments = [segment for segment in _normalise_path(call_path).split("/") if segment]
    route_segments = [segment for segment in endpoint.path.split("/") if segment]
    if len(call_segments) < len(route_segments):
        return False
    for call_segment, route_segment in zip(call_segments, route_segments):
        if route_segment.startswith("[") or route_segment.startswith(":") or route_segment.startswith("<"):
            continue
        if call_segment != route_segment:
            return False
    return True


# --------------------------------------------------------------------------- #
# Build
# --------------------------------------------------------------------------- #


def build_connectivity_map(workspace: Workspace, graph: Optional[CodeGraph] = None) -> ConnectivityMap:
    """Scan the repository for connectors, endpoints, tables, and UI wiring."""
    if graph is None:
        from diorama.codebase.indexer import build_code_graph

        graph = build_code_graph(workspace)

    sources: Dict[str, str] = {}
    roles: Dict[str, str] = {}
    for node in graph.nodes:
        if node.language in {"config", "tests"} or node.is_test:
            continue
        path = workspace.root / node.path
        if path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        try:
            sources[node.path] = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        roles[node.path] = classify(node)[0]

    env_vars = _detect_env_vars(workspace)
    connectivity = ConnectivityMap(root=str(workspace.root), name=workspace.root.name)

    # --- connectors -------------------------------------------------------
    connectivity.connectors = sorted(
        _detect_connectors(sources, env_vars).values(), key=lambda connector: connector.name.lower()
    )

    # --- Supabase (and generic BaaS) table usage ---------------------------
    tables: Dict[str, TableUsage] = {}
    rpcs: List[str] = []
    buckets: List[str] = []
    auth_files: List[str] = []
    table_files: Dict[str, List[str]] = {}
    for path, source in sources.items():
        uses_supabase = bool(_FROM_CALL_RE.search(source) or _RPC_RE.search(source) or _STORAGE_BUCKET_RE.search(source))
        for match in _FROM_CALL_RE.finditer(source):
            table = tables.setdefault(match.group(1), TableUsage(name=match.group(1)))
            table_files.setdefault(match.group(1), [])
            if path not in table_files[match.group(1)]:
                table_files[match.group(1)].append(path)
            window = source[match.end() : match.end() + 800]
            for op_match in _OP_RE.finditer(window):
                table.operations.add(op_match.group(1))
                if op_match.group(1) in {"insert", "update", "upsert"}:
                    table.columns.update(_object_literal_keys(window, f".{op_match.group(1)}("))
            for column_match in _SELECT_COLUMNS_RE.finditer(window[:400]):
                table.columns.update(_split_select_columns(column_match.group(1)))
            table.columns.update(_FILTER_COLUMN_RE.findall(window))
        for match in _RPC_RE.finditer(source):
            if match.group(1) not in rpcs:
                rpcs.append(match.group(1))
        for match in _STORAGE_BUCKET_RE.finditer(source):
            if match.group(1) not in buckets:
                buckets.append(match.group(1))
        if uses_supabase and any(re.search(rf"\b{call}\b", source) for call in AUTH_CALLS):
            if path not in auth_files:
                auth_files.append(path)
    for table in tables.values():
        table.files = table_files.get(table.name, [])
    connectivity.tables = sorted(tables.values(), key=lambda table: (-len(table.files), table.name))
    connectivity.rpcs = rpcs
    connectivity.buckets = buckets
    connectivity.auth_files = auth_files

    # --- endpoints ---------------------------------------------------------
    endpoints: List[Endpoint] = []
    seen_endpoints: Set[Tuple[str, str, str]] = set()
    for path, source in sources.items():
        if path.endswith((".ts", ".tsx", ".js", ".jsx")) and path.endswith(("route.ts", "route.tsx", "route.js", "route.jsx")):
            route_path = _nextjs_route_path(path)
            if route_path:
                for match in _METHOD_EXPORT_RE.finditer(source):
                    key = (match.group(1), route_path, path)
                    if key not in seen_endpoints:
                        seen_endpoints.add(key)
                        endpoints.append(
                            Endpoint(
                                method=match.group(1),
                                path=route_path,
                                handler=path,
                                line=source.count("\n", 0, match.start()) + 1,
                                framework="nextjs",
                            )
                        )
        for match in _EXPRESS_ROUTE_RE.finditer(source):
            key = (match.group(1).upper(), match.group(2), path)
            if key not in seen_endpoints:
                seen_endpoints.add(key)
                endpoints.append(
                    Endpoint(
                        method=match.group(1).upper(),
                        path=match.group(2),
                        handler=path,
                        line=source.count("\n", 0, match.start()) + 1,
                        framework="express",
                    )
                )
        for match in _PYTHON_ROUTE_RE.finditer(source):
            method = match.group(1).upper()
            if method == "ROUTE":  # Flask @app.route defaults to GET
                method = "GET"
            key = (method, match.group(2), path)
            if key not in seen_endpoints:
                seen_endpoints.add(key)
                endpoints.append(
                    Endpoint(
                        method=method,
                        path=match.group(2),
                        handler=path,
                        line=source.count("\n", 0, match.start()) + 1,
                        framework="fastapi" if "fastapi" in source.lower() else "flask",
                    )
                )
    endpoints.sort(key=lambda endpoint: (endpoint.path, endpoint.method))
    connectivity.endpoints = endpoints

    # --- client calls ------------------------------------------------------
    client_calls: List[ClientCall] = []
    for path, source in sources.items():
        for match in _FETCH_URL_RE.finditer(source):
            url = _strip_template_prefix(match.group(1))
            if not url:
                continue
            # fetch(url, { method: "POST" }) — peek at the options for the verb.
            method = "GET"
            options = source[match.end() : match.end() + 120]
            method_match = re.search(r"""method\s*:\s*["'](GET|POST|PUT|PATCH|DELETE)["']""", options, re.IGNORECASE)
            if method_match:
                method = method_match.group(1).upper()
            client_calls.append(ClientCall(file=path, method=method, url=url))
        for match in _AXIOS_RE.finditer(source):
            url = _strip_template_prefix(match.group(2))
            if url:
                client_calls.append(ClientCall(file=path, method=match.group(1).upper(), url=url))
    for call in client_calls:
        if call.url.startswith("http"):
            continue  # external API, not one of our routes
        candidates = [endpoint for endpoint in endpoints if _matches_endpoint(call.url, endpoint)]
        # Prefer the route with the same verb; fall back to any route on that path.
        for endpoint in candidates:
            if endpoint.method == call.method:
                call.endpoint = endpoint.id
                break
        else:
            if candidates:
                call.endpoint = candidates[0].id
    connectivity.client_calls = client_calls

    # --- state management --------------------------------------------------
    state: Dict[str, StateUsage] = {}
    hook_counts: Dict[str, int] = {}
    context_files: List[str] = []
    for path, source in sources.items():
        for raw in _iter_imports(source):
            framework = STATE_PACKAGES.get(raw) or STATE_PACKAGES.get(raw.split("/")[0])
            if framework:
                usage = state.setdefault(framework, StateUsage(framework=framework))
                if path not in usage.files:
                    usage.files.append(path)
        if roles.get(path) == "ui":
            hooks = len(_USESTATE_RE.findall(source))
            if hooks:
                hook_counts[path] = hooks
            if _CREATE_CONTEXT_RE.search(source) and path not in context_files:
                context_files.append(path)
    if hook_counts:
        total = sum(hook_counts.values())
        state.setdefault(
            "React local hooks",
            StateUsage(
                framework="React local hooks",
                files=sorted(hook_counts, key=lambda path: -hook_counts[path])[:8],
                detail=f"{total} useState/useReducer call{'s' if total != 1 else ''} across {len(hook_counts)} file{'s' if len(hook_counts) != 1 else ''}",
            ),
        )
    if context_files:
        state.setdefault("React Context", StateUsage(framework="React Context", files=context_files[:8]))
    connectivity.state = sorted(state.values(), key=lambda usage: usage.framework)

    # --- edges -------------------------------------------------------------
    edges: List[ConnectivityEdge] = []
    seen_edges: Set[Tuple[str, str, str]] = set()

    def add_edge(source_ref: str, target_ref: str, kind: str, label: Optional[str] = None) -> None:
        key = (source_ref, target_ref, kind)
        if source_ref != target_ref and key not in seen_edges:
            seen_edges.add(key)
            edges.append(ConnectivityEdge(source=source_ref, target=target_ref, kind=kind, label=label))

    for call in client_calls:
        if call.endpoint:
            add_edge(f"ui:{call.file}", f"endpoint:{call.endpoint}", "http", call.method)
        elif call.url.startswith("http"):
            host = re.sub(r"^https?://", "", call.url).split("/")[0]
            add_edge(f"ui:{call.file}", f"connector:{host}", "http", call.method)

    table_by_file: Dict[str, List[str]] = {}
    for table in tables.values():
        for path in table.files:
            table_by_file.setdefault(path, []).append(table.name)
    for path, table_names in table_by_file.items():
        for table_name in table_names:
            if roles.get(path) in {"ui", "business"}:
                add_edge(f"ui:{path}", f"table:{table_name}", "data")
            for endpoint in endpoints:
                if endpoint.handler == path:
                    add_edge(f"endpoint:{endpoint.id}", f"table:{table_name}", "data")
    for table in tables.values():
        add_edge(f"table:{table.name}", "connector:Supabase", "data")
    for rpc in rpcs:
        add_edge(f"rpc:{rpc}", "connector:Supabase", "rpc")
    for bucket in buckets:
        add_edge(f"bucket:{bucket}", "connector:Supabase", "storage")
    connectivity.edges = edges
    return connectivity


def _strip_template_prefix(url: str) -> str:
    """``${base}/api/users`` -> ``/api/users``; keep absolute and root-relative URLs."""
    if url.startswith("http"):
        return url
    if "${" in url:
        _, _, rest = url.rpartition("}")
        url = rest
    return url if url.startswith("/") else ""


# --------------------------------------------------------------------------- #
# Layout
# --------------------------------------------------------------------------- #

COL_WIDTH = 320
COL_GAP = 120
ROW_GAP = 36
FRAME_PAD = 48
FRAME_TITLE = 64
MAX_TABLES = 14
MAX_ENDPOINTS = 18
MAX_UI_SURFACES = 14
MAX_STATE_ROWS = 6


def _sanitize(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in value)


def _estimate_card_height(body_lines: int) -> float:
    return 64 + 22 * max(body_lines, 1) + 24


def _table_body(table: TableUsage) -> List[str]:
    lines = []
    if table.operations:
        lines.append("ops: " + ", ".join(sorted(table.operations)))
    if table.columns:
        shown = sorted(table.columns)[:6]
        lines.append("columns: " + ", ".join(shown) + ("…" if len(table.columns) > 6 else ""))
    for path in table.files[:3]:
        lines.append(path)
    if len(table.files) > 3:
        lines.append(f"… +{len(table.files) - 3} more")
    return lines or ["used via Supabase client"]


def _endpoint_body(endpoint: Endpoint, tables_by_handler: Dict[str, List[str]]) -> List[str]:
    lines = [f"{endpoint.framework} · {endpoint.handler}:{endpoint.line}"]
    touched = tables_by_handler.get(endpoint.handler, [])
    if touched:
        lines.append("writes/reads: " + ", ".join(sorted(set(touched))[:4]))
    return lines


def _ui_body(path: str, endpoint_ids: List[str], table_names: List[str]) -> List[str]:
    lines = []
    if endpoint_ids:
        lines.append("calls: " + ", ".join(endpoint_ids[:3]) + ("…" if len(endpoint_ids) > 3 else ""))
    if table_names:
        lines.append("tables: " + ", ".join(table_names[:4]) + ("…" if len(table_names) > 4 else ""))
    return lines or ["(no direct data access found)"]


def connectivity_to_primitives(
    connectivity: ConnectivityMap,
    *,
    title: Optional[str] = None,
) -> List[Primitive]:
    """Lay the connectivity map out as three columns: data, API, UI.

    Left: connectors and their tables (zoom into Supabase here).  Middle: HTTP
    endpoints.  Right: UI surfaces and state management.  Arrows carry the
    request path: UI -> endpoint -> table -> connector.
    """
    title = title or f"{connectivity.name} · API connectivity"
    primitives: List[Primitive] = []

    endpoint_count = len(connectivity.endpoints)
    table_count = len(connectivity.tables)
    matched = sum(1 for call in connectivity.client_calls if call.endpoint)
    heading = HeadingPrimitive(
        kind="heading",
        id="conn-heading",
        text=title,
        subtitle=(
            f"{len(connectivity.connectors)} connector{'s' if len(connectivity.connectors) != 1 else ''} · "
            f"{table_count} table{'s' if table_count != 1 else ''} · "
            f"{endpoint_count} endpoint{'s' if endpoint_count != 1 else ''} · "
            f"{matched}/{len(connectivity.client_calls)} client calls matched to routes"
        ),
        x=0,
        y=0,
        size="xl",
    )
    primitives.append(heading)

    tables_by_handler: Dict[str, List[str]] = {}
    for table in connectivity.tables:
        for path in table.files:
            tables_by_handler.setdefault(path, []).append(table.name)

    # Column 1: connectors + tables.
    connector_cards: List[Tuple[str, float]] = []
    table_cards: List[Tuple[str, float]] = []
    connector_frame_id = "conn-frame-data"
    connector_frame_y = 140.0
    cursor_y = connector_frame_y + FRAME_TITLE
    connector_ids: Dict[str, str] = {}
    for connector in connectivity.connectors:
        body = [connector.note or connector.kind]
        if connector.packages:
            body.append("via " + ", ".join(sorted(connector.packages)[:3]))
        if connector.env_vars:
            body.append("env: " + ", ".join(sorted(connector.env_vars)[:3]))
        for path in connector.files[:2]:
            body.append(path)
        card_id = _sanitize(f"conn-connector-{connector.name}")
        connector_ids[connector.name] = card_id
        body = [line for line in body if line]
        connector_cards.append((card_id, _estimate_card_height(len(body))))
        primitives.append(
            CardPrimitive(
                kind="card",
                id=card_id,
                frame=connector_frame_id,
                title=connector.name,
                body=body,
                x=FRAME_PAD,
                y=cursor_y,
                width=COL_WIDTH,
                accent=CONNECTOR_ACCENTS.get(connector.kind, "indigo"),
            )
        )
        cursor_y += _estimate_card_height(len(body)) + ROW_GAP
    for table in connectivity.tables[:MAX_TABLES]:
        body = _table_body(table)
        card_id = _sanitize(f"conn-table-{table.name}")
        table_cards.append((card_id, _estimate_card_height(len(body))))
        primitives.append(
            CardPrimitive(
                kind="card",
                id=card_id,
                frame=connector_frame_id,
                title=f"table · {table.name}",
                body=body,
                x=FRAME_PAD,
                y=cursor_y,
                width=COL_WIDTH,
                accent="emerald",
            )
        )
        cursor_y += _estimate_card_height(len(body)) + ROW_GAP
    for rpc in connectivity.rpcs[:4]:
        body = ["Postgres function invoked via .rpc()"]
        card_id = _sanitize(f"conn-rpc-{rpc}")
        table_cards.append((card_id, _estimate_card_height(1)))
        primitives.append(
            CardPrimitive(
                kind="card", id=card_id, frame=connector_frame_id,
                title=f"rpc · {rpc}", body=body, x=FRAME_PAD, y=cursor_y,
                width=COL_WIDTH, accent="emerald",
            )
        )
        cursor_y += _estimate_card_height(1) + ROW_GAP
    for bucket in connectivity.buckets[:4]:
        body = ["storage bucket via .storage().from()"]
        card_id = _sanitize(f"conn-bucket-{bucket}")
        table_cards.append((card_id, _estimate_card_height(1)))
        primitives.append(
            CardPrimitive(
                kind="card", id=card_id, frame=connector_frame_id,
                title=f"bucket · {bucket}", body=body, x=FRAME_PAD, y=cursor_y,
                width=COL_WIDTH, accent="sky",
            )
        )
        cursor_y += _estimate_card_height(1) + ROW_GAP
    data_height = cursor_y - connector_frame_y - FRAME_TITLE - ROW_GAP + FRAME_PAD
    if not connector_cards and not table_cards:
        primitives.append(
            NotePrimitive(
                kind="note",
                id="conn-data-empty",
                text="No external connectors or database tables detected.",
                x=FRAME_PAD,
                y=cursor_y,
            )
        )
        data_height = 200
    primitives.append(
        FramePrimitive(
            kind="frame",
            id=connector_frame_id,
            title="Connectors & data",
            x=0,
            y=connector_frame_y,
            width=FRAME_PAD * 2 + COL_WIDTH,
            height=FRAME_TITLE + data_height,
        )
    )

    # Column 2: endpoints.
    endpoint_frame_id = "conn-frame-api"
    endpoint_frame_y = connector_frame_y
    cursor_y = endpoint_frame_y + FRAME_TITLE
    endpoint_ids: Dict[str, str] = {}
    for endpoint in connectivity.endpoints[:MAX_ENDPOINTS]:
        body = _endpoint_body(endpoint, tables_by_handler)
        card_id = _sanitize(f"conn-endpoint-{endpoint.method}-{endpoint.path}")
        endpoint_ids[endpoint.id] = card_id
        primitives.append(
            CardPrimitive(
                kind="card",
                id=card_id,
                frame=endpoint_frame_id,
                title=f"{endpoint.method} {endpoint.path}",
                body=body,
                x=FRAME_PAD + COL_WIDTH + COL_GAP,
                y=cursor_y,
                width=COL_WIDTH,
                accent="sky",
            )
        )
        cursor_y += _estimate_card_height(len(body)) + ROW_GAP
    if not connectivity.endpoints:
        primitives.append(
            NotePrimitive(
                kind="note",
                id="conn-api-empty",
                text="No HTTP route handlers detected (Next.js route.ts, Express, FastAPI, Flask).",
                x=FRAME_PAD + COL_WIDTH + COL_GAP,
                y=cursor_y,
            )
        )
        cursor_y += 160
    api_height = cursor_y - endpoint_frame_y - FRAME_TITLE - ROW_GAP + FRAME_PAD
    primitives.append(
        FramePrimitive(
            kind="frame",
            id=endpoint_frame_id,
            title="HTTP API",
            x=COL_WIDTH + COL_GAP,
            y=endpoint_frame_y,
            width=FRAME_PAD * 2 + COL_WIDTH,
            height=FRAME_TITLE + api_height,
        )
    )

    # Column 3: UI surfaces + state.
    ui_frame_id = "conn-frame-ui"
    ui_frame_y = connector_frame_y
    ui_x = FRAME_PAD + 2 * (COL_WIDTH + COL_GAP)
    cursor_y = ui_frame_y + FRAME_TITLE
    ui_calls: Dict[str, List[str]] = {}
    ui_tables: Dict[str, List[str]] = {}
    for call in connectivity.client_calls:
        if call.endpoint:
            ui_calls.setdefault(call.file, []).append(call.endpoint)
    for table in connectivity.tables:
        for path in table.files:
            ui_tables.setdefault(path, []).append(table.name)
    ui_paths = sorted(set(ui_calls) | set(ui_tables), key=lambda path: -(len(ui_calls.get(path, [])) + len(ui_tables.get(path, []))))
    for path in ui_paths[:MAX_UI_SURFACES]:
        body = _ui_body(path, ui_calls.get(path, []), ui_tables.get(path, []))
        card_id = _sanitize(f"conn-ui-{path}")
        primitives.append(
            CardPrimitive(
                kind="card",
                id=card_id,
                frame=ui_frame_id,
                title=path.rsplit("/", 1)[-1],
                body=[path, *body],
                x=ui_x,
                y=cursor_y,
                width=COL_WIDTH,
                accent="rose",
            )
        )
        cursor_y += _estimate_card_height(len(body) + 1) + ROW_GAP
    if connectivity.state:
        state_lines: List[str] = []
        for usage in connectivity.state[:MAX_STATE_ROWS]:
            line = usage.framework
            if usage.detail:
                line += f" — {usage.detail}"
            elif usage.files:
                line += f" ({len(usage.files)} file{'s' if len(usage.files) != 1 else ''})"
            state_lines.append(line)
        card_id = "conn-state"
        primitives.append(
            CardPrimitive(
                kind="card",
                id=card_id,
                frame=ui_frame_id,
                title="State management",
                body=state_lines,
                x=ui_x,
                y=cursor_y,
                width=COL_WIDTH,
                accent="violet",
            )
        )
        cursor_y += _estimate_card_height(len(state_lines)) + ROW_GAP
    if not ui_paths and not connectivity.state:
        primitives.append(
            NotePrimitive(
                kind="note",
                id="conn-ui-empty",
                text="No UI files found calling endpoints or tables.",
                x=ui_x,
                y=cursor_y,
            )
        )
        cursor_y += 160
    ui_height = cursor_y - ui_frame_y - FRAME_TITLE - ROW_GAP + FRAME_PAD
    primitives.append(
        FramePrimitive(
            kind="frame",
            id=ui_frame_id,
            title="UI & state",
            x=2 * (COL_WIDTH + COL_GAP),
            y=ui_frame_y,
            width=FRAME_PAD * 2 + COL_WIDTH,
            height=FRAME_TITLE + ui_height,
        )
    )

    # Edges: UI -> endpoint -> table -> connector.
    known = {card_id for card_id, _ in [*connector_cards, *table_cards]}
    known.update(endpoint_ids.values())
    known.update(_sanitize(f"conn-ui-{path}") for path in ui_paths[:MAX_UI_SURFACES])
    known.add("conn-state")
    known.update(connector_ids.values())

    edge_styles = {"http": ("solid", "sky"), "data": ("solid", "emerald"), "rpc": ("dashed", "emerald"), "storage": ("dashed", "sky")}
    for edge in connectivity.edges:
        source_ref, _, source_key = edge.source.partition(":")
        target_ref, _, target_key = edge.target.partition(":")
        if source_ref == "ui":
            source_id = _sanitize(f"conn-ui-{source_key}")
        elif source_ref == "endpoint":
            source_id = endpoint_ids.get(source_key)
        elif source_ref == "table":
            source_id = _sanitize(f"conn-table-{source_key}")
        elif source_ref == "rpc":
            source_id = _sanitize(f"conn-rpc-{source_key}")
        elif source_ref == "bucket":
            source_id = _sanitize(f"conn-bucket-{source_key}")
        else:
            source_id = None
        if target_ref == "endpoint":
            target_id = endpoint_ids.get(target_key)
        elif target_ref == "table":
            target_id = _sanitize(f"conn-table-{target_key}")
        elif target_ref == "connector":
            target_id = connector_ids.get(target_key) or _sanitize(f"conn-connector-{target_key}")
        else:
            target_id = None
        if not source_id or not target_id or source_id not in known or target_id not in known:
            continue
        style, accent = edge_styles.get(edge.kind, ("dashed", "slate"))
        primitives.append(
            RoutePrimitive.model_validate(
                {
                    "kind": "route",
                    "id": _sanitize(f"conn-edge-{edge.source}-{edge.target}"),
                    "from": source_id,
                    "to": target_id,
                    "label": edge.label,
                    "style": style,
                    "accent": accent,
                    "arrow": True,
                }
            )
        )

    tallest = max(FRAME_TITLE + data_height, FRAME_TITLE + api_height, FRAME_TITLE + ui_height)
    primitives.append(
        LegendPrimitive(
            kind="legend",
            id="conn-legend",
            title="Connectivity",
            items=[
                LegendItem(label="HTTP request (UI → endpoint)", accent="sky"),
                LegendItem(label="Data access (endpoint/UI → table → connector)", accent="emerald"),
                LegendItem(label="RPC / storage", accent="amber"),
            ],
            x=0,
            y=connector_frame_y + tallest + 80,
        )
    )
    return primitives
