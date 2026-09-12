"""Architectural view of a repository: components by *role*, not by directory.

The file-per-card map answers "what files exist?".  This module answers the
question the whiteboard was designed for: "what are the moving parts and how
do they talk to each other?".  Every indexed file is assigned to one
architectural component (database, cache, web service, business logic, UI,
auth, logging, ...) using three signals that tree-sitter gives us cheaply:

* which **external packages** it imports  (``@supabase/supabase-js`` -> database)
* which **calls** it makes                (``logger.info`` -> logging, ``app.get`` -> web service)
* where it lives / what it is called      (``src/app/**/page.tsx`` -> UI, ``**/models/**`` -> data)

Import edges between files are then collapsed into weighted edges between
components, and the repository's manifests (package.json, pyproject.toml,
go.mod, Dockerfile, CI config...) are read for the environment panel: external
packages, runtime, analytics and execution environment.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

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
# Roles
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Role:
    id: str
    label: str
    accent: str
    order: int  # layout column (left -> right = data -> delivery)
    description: str


ROLES: Dict[str, Role] = {
    role.id: role
    for role in [
        Role("database", "Database", "emerald", 0, "Persistence: ORMs, SQL clients, BaaS SDKs"),
        Role("cache", "Cache", "amber", 0, "In-memory / KV stores and memoisation"),
        Role("queue", "Queue / Events", "amber", 0, "Message brokers, jobs, pub/sub"),
        Role("business", "Business Logic", "indigo", 1, "Domain rules, services, use-cases"),
        Role("auth", "Auth", "violet", 1, "Sessions, identity, permissions"),
        Role("web_service", "Web Service", "sky", 2, "HTTP/RPC handlers, routers, servers"),
        Role("ui", "UI", "rose", 3, "Pages, components, views"),
        Role("logging", "Logging", "slate", 3, "Loggers, tracing, error reporting"),
        Role("analytics", "Analytics", "coral", 3, "Product analytics and metrics SDKs"),
        Role("config", "Config", "slate", 4, "Build, tooling and runtime configuration"),
        Role("types", "Types / Models", "violet", 0, "Shared types, schemas, DTOs"),
        Role("tests", "Tests", "slate", 4, "Test suites and fixtures"),
        Role("shared", "Shared / Utils", "slate", 1, "Helpers with no dominant role"),
    ]
}

# External package -> role.  Prefixes are matched against the first path segment
# (or scope + name for `@scope/pkg`).
PACKAGE_ROLES: Dict[str, str] = {
    # database
    "@supabase/supabase-js": "database", "@supabase/ssr": "database", "@supabase/auth-helpers-nextjs": "auth",
    "@prisma/client": "database", "prisma": "database", "drizzle-orm": "database", "mongoose": "database",
    "pg": "database", "mysql2": "database", "sqlite3": "database", "better-sqlite3": "database", "knex": "database",
    "typeorm": "database", "sequelize": "database", "firebase": "database", "firebase-admin": "database",
    "@planetscale/database": "database", "@neondatabase/serverless": "database", "@vercel/postgres": "database",
    "sqlalchemy": "database", "psycopg2": "database", "psycopg": "database", "asyncpg": "database", "pymongo": "database",
    "motor": "database", "peewee": "database", "django.db": "database", "alembic": "database", "sqlmodel": "database",
    "gorm.io": "database", "database/sql": "database", "github.com/jackc/pgx": "database", "sqlx": "database",
    "diesel": "database", "sea-orm": "database", "mongodb": "database", "boto3": "database",
    # cache
    "redis": "cache", "ioredis": "cache", "@upstash/redis": "cache", "memcached": "cache", "node-cache": "cache",
    "lru-cache": "cache", "aiocache": "cache", "cachetools": "cache", "github.com/go-redis/redis": "cache",
    "github.com/redis/go-redis": "cache", "moka": "cache", "@tanstack/react-query": "cache", "swr": "cache",
    # queue / events
    "bullmq": "queue", "bull": "queue", "kafkajs": "queue", "amqplib": "queue", "celery": "queue", "pika": "queue",
    "aiokafka": "queue", "@aws-sdk/client-sqs": "queue", "github.com/segmentio/kafka-go": "queue", "rq": "queue",
    # web service
    "express": "web_service", "fastify": "web_service", "koa": "web_service", "hono": "web_service",
    "@nestjs/common": "web_service", "@nestjs/core": "web_service", "next/server": "web_service", "@trpc/server": "web_service",
    "fastapi": "web_service", "flask": "web_service", "django.http": "web_service", "django.urls": "web_service",
    "starlette": "web_service", "aiohttp": "web_service", "tornado": "web_service", "uvicorn": "web_service",
    "net/http": "web_service", "github.com/gin-gonic/gin": "web_service", "github.com/labstack/echo": "web_service",
    "github.com/gorilla/mux": "web_service", "github.com/go-chi/chi": "web_service", "axum": "web_service",
    "actix-web": "web_service", "rocket": "web_service", "warp": "web_service", "sinatra": "web_service", "rails": "web_service",
    "graphql": "web_service", "apollo-server": "web_service", "@apollo/server": "web_service", "grpc": "web_service",
    # ui
    "react": "ui", "react-dom": "ui", "next/link": "ui", "next/navigation": "ui", "next/router": "ui", "next/image": "ui",
    "next/font": "ui", "vue": "ui", "svelte": "ui", "@angular/core": "ui", "solid-js": "ui", "preact": "ui",
    "framer-motion": "ui", "motion": "ui", "@radix-ui": "ui", "lucide-react": "ui", "@mui/material": "ui",
    "tailwindcss": "config", "clsx": "ui", "class-variance-authority": "ui", "streamlit": "ui", "tkinter": "ui",
    # auth
    "next-auth": "auth", "@auth/core": "auth", "passport": "auth", "jsonwebtoken": "auth", "jose": "auth", "bcrypt": "auth",
    "bcryptjs": "auth", "@clerk/nextjs": "auth", "@auth0/nextjs-auth0": "auth", "python-jose": "auth", "passlib": "auth",
    "authlib": "auth", "django.contrib.auth": "auth", "github.com/golang-jwt/jwt": "auth", "jsonwebtoken-rs": "auth",
    # logging
    "winston": "logging", "pino": "logging", "morgan": "logging", "bunyan": "logging", "loglevel": "logging", "debug": "logging",
    "@sentry/node": "logging", "@sentry/nextjs": "logging", "@sentry/react": "logging", "sentry_sdk": "logging",
    "logging": "logging", "loguru": "logging", "structlog": "logging", "log": "logging", "go.uber.org/zap": "logging",
    "github.com/sirupsen/logrus": "logging", "github.com/rs/zerolog": "logging", "tracing": "logging", "env_logger": "logging",
    "@opentelemetry/api": "logging", "opentelemetry": "logging", "@vercel/analytics": "analytics",
    # analytics
    "posthog-js": "analytics", "posthog-node": "analytics", "posthog": "analytics", "mixpanel": "analytics",
    "mixpanel-browser": "analytics", "@segment/analytics-next": "analytics", "analytics-node": "analytics",
    "@amplitude/analytics-browser": "analytics", "react-ga4": "analytics", "@google-analytics/data": "analytics",
    "plausible-tracker": "analytics", "@vercel/speed-insights": "analytics", "segment": "analytics", "datadog": "analytics",
    "prom-client": "analytics", "prometheus_client": "analytics",
    # types / validation
    "zod": "types", "yup": "types", "valibot": "types", "pydantic": "types", "typing": "types", "dataclasses": "types",
    "io-ts": "types", "serde": "types",
}

# Called-name fragments -> role (checked against `a.b.c` call names).
CALL_ROLES: List[Tuple[re.Pattern[str], str]] = [
    (re.compile(r"(^|\.)(from|select|insert|update|upsert|delete|rpc|findMany|findUnique|findFirst|createMany|query|execute|fetchall|fetchone|commit|rollback|aggregate|save|find_one|find_many|insert_one|collection)$"), "database"),
    (re.compile(r"(^|\.)(getPublicUrl|upload|storage|bucket)$"), "database"),
    (re.compile(r"(^|\.)(hget|hset|setex|expire|mget|mset|incr|decr|zadd|lpush|rpush|cache|memoize|revalidate|revalidatePath|revalidateTag|unstable_cache)$"), "cache"),
    (re.compile(r"(^|\.)(publish|subscribe|enqueue|dequeue|add_job|addJob|emit|on_message|produce|consume)$"), "queue"),
    (re.compile(r"^(app|router|server|api|fastify|express|Router|APIRouter)\.(get|post|put|patch|delete|use|route|listen|handle|websocket|ws|options|head|all)$"), "web_service"),
    (re.compile(r"^(NextResponse|Response|res)\.(json|send|status|redirect|next|rewrite)$"), "web_service"),
    (re.compile(r"(^|\.)(signIn|signUp|signOut|signInWithPassword|signInWithOAuth|getSession|getUser|onAuthStateChange|authenticate|authorize|login|logout|verify_password|hash_password|create_access_token|getServerSession|useSession|jwt\.sign|jwt\.verify|verifyToken|resetPasswordForEmail)$"), "auth"),
    (re.compile(r"^(logger|log|logging|console|winston|pino|Sentry|sentry|tracer|span)\.(info|warn|warning|error|debug|trace|log|exception|critical|fatal|captureException|captureMessage|child)$"), "logging"),
    (re.compile(r"^(posthog|mixpanel|analytics|amplitude|gtag|ga|segment|plausible|track|dataLayer)\.(capture|track|identify|page|event|push|init)$|^(gtag|track|trackEvent)$"), "analytics"),
    (re.compile(r"^(useState|useEffect|useMemo|useCallback|useRef|useContext|useReducer|useRouter|usePathname|useSearchParams|createContext|render|createRoot|hydrateRoot|defineComponent|ref|reactive|computed)$"), "ui"),
    (re.compile(r"^(z|yup|Joi)\.(object|string|number|array|enum|infer|boolean)$"), "types"),
]

# Path fragments -> role (matched against the lower-cased relative path).
PATH_ROLES: List[Tuple[re.Pattern[str], str]] = [
    (re.compile(r"(^|/)(migrations?|prisma|schema\.prisma|db|database|repositories|repository|dao|models?/.*(model|entity|schema))\b"), "database"),
    (re.compile(r"(^|/)(cache|caching)(/|\.)"), "cache"),
    (re.compile(r"(^|/)(queues?|jobs?|workers?|tasks|events?|consumers?|producers?)(/|\.)"), "queue"),
    (re.compile(r"(^|/)(api|routes?|routers?|controllers?|handlers?|endpoints?|server|middlewares?|rpc|graphql|resolvers?)(/|\.)|(^|/)route\.[jt]sx?$|(^|/)main\.(py|go|rs)$|(^|/)(app|server|wsgi|asgi)\.py$"), "web_service"),
    (re.compile(r"(^|/)(auth|authentication|authorization|session|login|signup|sign-in|sign-up|register|permissions?)(/|\.)"), "auth"),
    (re.compile(r"(^|/)(log|logs|logging|logger|telemetry|tracing|monitoring|observability)(/|\.)"), "logging"),
    (re.compile(r"(^|/)(analytics|metrics|tracking)(/|\.)"), "analytics"),
    (re.compile(r"(^|/)(components?|pages?|views?|screens?|layouts?|ui|widgets?|templates?)(/|\.)|(^|/)(page|layout|loading|error|not-found|template)\.[jt]sx$|\.(vue|svelte|css|scss)$"), "ui"),
    (re.compile(r"(^|/)(types?|typings|interfaces?|schemas?|dto|dtos|models?|entities|domain/.*types?)(/|\.)|\.d\.ts$|(^|/)types\.[jt]s$"), "types"),
    (re.compile(r"(^|/)(services?|domain|core|business|logic|usecases?|use-cases?|application|features?|lib|libs?|utils?|helpers?|hooks?|store|stores?|state)(/|\.)"), "business"),
    (re.compile(r"(^|/)(config|configs?|settings|\.github|\.gitlab-ci|docker|deploy|infra|scripts?)(/|\.)|(^|/)(package\.json|pyproject\.toml|tsconfig\.json|go\.mod|cargo\.toml|dockerfile|makefile|requirements\.txt|compose\.ya?ml|docker-compose\.ya?ml|next\.config\.[jm]?js|vite\.config\.[jt]s|tailwind\.config\.[jt]s|postcss\.config\.[jt]s|eslint\.config\.[jt]s|\.env.*)$"), "config"),
]

ANALYTICS_PACKAGES = {pkg for pkg, role in PACKAGE_ROLES.items() if role == "analytics"}
LOGGING_PACKAGES = {pkg for pkg, role in PACKAGE_ROLES.items() if role == "logging"}

# Weights: a direct SDK import is the strongest evidence, then calls, then location.
W_PACKAGE = 3.0
W_CALL = 1.0
W_PATH = 2.0
W_SYMBOL = 0.5


# --------------------------------------------------------------------------- #
# Model
# --------------------------------------------------------------------------- #


@dataclass
class Component:
    role: Role
    files: List[CodeNode] = field(default_factory=list)
    packages: Dict[str, int] = field(default_factory=dict)  # external package -> files using it
    evidence: Dict[str, str] = field(default_factory=dict)  # file path -> short reason

    @property
    def loc(self) -> int:
        return sum(node.loc for node in self.files)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role.id,
            "label": self.role.label,
            "files": [node.path for node in self.files],
            "loc": self.loc,
            "packages": sorted(self.packages, key=lambda p: -self.packages[p])[:8],
            "symbols": self.top_symbols(8),
        }

    def top_symbols(self, limit: int) -> List[str]:
        names: List[str] = []
        for node in sorted(self.files, key=lambda n: -n.loc):
            for symbol in node.symbols:
                if symbol.kind in {"class", "function", "interface", "struct", "trait", "enum", "type"} and symbol.name not in names:
                    names.append(symbol.name)
                    if len(names) >= limit:
                        return names
        return names


@dataclass
class ComponentEdge:
    source: str
    target: str
    weight: int
    examples: List[Tuple[str, str]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"source": self.source, "target": self.target, "weight": self.weight, "examples": self.examples[:3]}


@dataclass
class Environment:
    external_packages: List[str] = field(default_factory=list)  # ordered by usage
    dev_packages: List[str] = field(default_factory=list)
    runtime: List[str] = field(default_factory=list)  # "Node >=18", "Next.js 14", "Python >=3.10"
    analytics: List[str] = field(default_factory=list)
    execution: List[str] = field(default_factory=list)  # "Dockerfile", "Vercel", "GitHub Actions"
    package_manager: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "externalPackages": self.external_packages,
            "devPackages": self.dev_packages,
            "runtime": self.runtime,
            "analytics": self.analytics,
            "execution": self.execution,
            "packageManager": self.package_manager,
        }


@dataclass
class Architecture:
    root: str
    name: str
    components: List[Component]
    edges: List[ComponentEdge]
    environment: Environment
    file_roles: Dict[str, str]  # node id -> role id
    parser: str = "regex"

    def to_summary(self) -> Dict[str, Any]:
        return {
            "root": self.root,
            "name": self.name,
            "parser": self.parser,
            "components": [component.to_dict() for component in self.components],
            "edges": [edge.to_dict() for edge in self.edges],
            "environment": self.environment.to_dict(),
        }


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #


def external_package_name(raw: str, language: str) -> Optional[str]:
    """Normalise an import specifier to the package that provides it, or None if local."""
    if not raw or raw.startswith((".", "/", "~/", "@/", "http")):
        return None
    if language == "python":
        return raw.split(".")[0]
    if language == "go":
        parts = raw.split("/")
        if "." not in parts[0]:  # stdlib: net/http -> net/http
            return raw
        return "/".join(parts[:3]) if len(parts) >= 3 else raw
    if language == "rust":
        return raw.split("::")[0]
    if language in {"java", "kotlin", "csharp"}:
        return ".".join(raw.split(".")[:2])
    # JS/TS: scope + name, or the first segment; keep well-known subpaths like next/link.
    if raw.startswith("@"):
        return "/".join(raw.split("/")[:2])
    head, _, rest = raw.partition("/")
    if head == "next" and rest:
        return f"next/{rest.split('/')[0]}"
    return head


def _score_node(node: CodeNode) -> Tuple[Dict[str, float], str]:
    scores: Dict[str, float] = {}
    reasons: Dict[str, str] = {}

    def bump(role: str, weight: float, reason: str) -> None:
        scores[role] = scores.get(role, 0.0) + weight
        reasons.setdefault(role, reason)

    if node.is_test:
        return {"tests": 100.0}, "test file"
    lowered = node.path.lower()
    for pattern, role in PATH_ROLES:
        if pattern.search(lowered):
            bump(role, W_PATH, f"path matches {role}")
            break  # first path rule wins; they are ordered most-specific first
    for raw in node.imports:
        package = external_package_name(raw, node.language)
        if not package:
            continue
        role = PACKAGE_ROLES.get(package) or PACKAGE_ROLES.get(package.split("/")[0])
        if role:
            # UI framework imports are ubiquitous in front-ends; weight them lightly so a
            # page that talks to the database is still recognised as doing so.
            weight = W_PACKAGE if role not in {"ui", "types"} else W_PACKAGE / 3
            bump(role, weight, f"imports {package}")
    for call in node.calls:
        for pattern, role in CALL_ROLES:
            if pattern.search(call):
                bump(role, W_CALL if role not in {"ui"} else W_CALL / 4, f"calls {call}")
                break
    for symbol in node.symbols:
        name = symbol.name.lower()
        if any(token in name for token in ("repository", "repo", "store", "dao", "model")):
            bump("database", W_SYMBOL, f"defines {symbol.name}")
        elif any(token in name for token in ("controller", "handler", "router", "endpoint")):
            bump("web_service", W_SYMBOL, f"defines {symbol.name}")
        elif any(token in name for token in ("service", "usecase", "manager", "engine", "policy")):
            bump("business", W_SYMBOL, f"defines {symbol.name}")
        elif any(token in name for token in ("logger", "tracer")):
            bump("logging", W_SYMBOL, f"defines {symbol.name}")
        elif "auth" in name or "session" in name:
            bump("auth", W_SYMBOL, f"defines {symbol.name}")
    if not scores:
        return {"shared": 0.1}, "no strong signal"
    best = max(scores, key=lambda r: (scores[r], -ROLES[r].order))
    return scores, reasons.get(best, "")


def classify(node: CodeNode) -> Tuple[str, str]:
    """Return ``(role_id, reason)`` for a file."""
    scores, reason = _score_node(node)
    role = max(scores, key=lambda r: (scores[r], -ROLES[r].order))
    return role, reason


# --------------------------------------------------------------------------- #
# Environment (manifests)
# --------------------------------------------------------------------------- #

EXECUTION_MARKERS: Dict[str, str] = {
    "dockerfile": "Docker",
    "docker-compose.yml": "Docker Compose",
    "docker-compose.yaml": "Docker Compose",
    "compose.yaml": "Docker Compose",
    "compose.yml": "Docker Compose",
    "vercel.json": "Vercel",
    "netlify.toml": "Netlify",
    "fly.toml": "Fly.io",
    "render.yaml": "Render",
    "railway.json": "Railway",
    "railway.toml": "Railway",
    "procfile": "Heroku (Procfile)",
    "app.yaml": "Google App Engine",
    "serverless.yml": "Serverless Framework",
    "wrangler.toml": "Cloudflare Workers",
    "amplify.yml": "AWS Amplify",
    "cdk.json": "AWS CDK",
    "template.yaml": "AWS SAM",
    "skaffold.yaml": "Kubernetes (Skaffold)",
    "helmfile.yaml": "Kubernetes (Helm)",
    "chart.yaml": "Kubernetes (Helm)",
    "main.tf": "Terraform",
    ".gitlab-ci.yml": "GitLab CI",
    "jenkinsfile": "Jenkins",
    ".travis.yml": "Travis CI",
    "bitbucket-pipelines.yml": "Bitbucket Pipelines",
    "azure-pipelines.yml": "Azure Pipelines",
    "cloudbuild.yaml": "Google Cloud Build",
    ".nvmrc": None,  # runtime hint, handled separately
}

RUNTIME_PACKAGES: Dict[str, str] = {
    "next": "Next.js", "react": "React", "vue": "Vue", "nuxt": "Nuxt", "svelte": "Svelte", "@sveltejs/kit": "SvelteKit",
    "@angular/core": "Angular", "express": "Express", "fastify": "Fastify", "hono": "Hono", "@nestjs/core": "NestJS",
    "@remix-run/node": "Remix", "astro": "Astro", "vite": "Vite", "electron": "Electron", "react-native": "React Native",
    "expo": "Expo", "bun-types": "Bun", "@types/bun": "Bun", "typescript": "TypeScript",
    "fastapi": "FastAPI", "django": "Django", "flask": "Flask", "starlette": "Starlette", "uvicorn": "Uvicorn",
    "gunicorn": "Gunicorn", "celery": "Celery", "streamlit": "Streamlit",
}


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _read_toml(path: Path) -> Optional[Dict[str, Any]]:
    try:
        import tomllib  # Python 3.11+
    except ImportError:  # pragma: no cover
        return None
    try:
        return tomllib.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return None


def _version_label(name: str, spec: Any) -> str:
    text = str(spec or "").strip()
    text = re.sub(r"^[\^~=v]+", "", text)
    return f"{name} {text}" if text and text not in {"*", "latest"} else name


def build_environment(workspace: Workspace, graph: CodeGraph) -> Environment:
    env = Environment()
    root = workspace.root
    used: Dict[str, int] = {}
    for node in graph.nodes:
        for raw in node.imports:
            package = external_package_name(raw, node.language)
            if package:
                used[package] = used.get(package, 0) + 1

    declared: Dict[str, str] = {}
    dev_declared: Dict[str, str] = {}

    package_json = _read_json(root / "package.json") if (root / "package.json").is_file() else None
    if package_json:
        declared.update({k: str(v) for k, v in (package_json.get("dependencies") or {}).items()})
        dev_declared.update({k: str(v) for k, v in (package_json.get("devDependencies") or {}).items()})
        engines = package_json.get("engines") or {}
        if isinstance(engines, dict):
            for engine, spec in engines.items():
                env.runtime.append(_version_label({"node": "Node.js", "bun": "Bun", "pnpm": "pnpm", "npm": "npm"}.get(engine, engine), spec))
        pm = str(package_json.get("packageManager") or "")
        if pm:
            env.package_manager = pm.split("@")[0]
        for lock, manager in (("bun.lock", "bun"), ("bun.lockb", "bun"), ("pnpm-lock.yaml", "pnpm"), ("yarn.lock", "yarn"), ("package-lock.json", "npm")):
            if env.package_manager is None and (root / lock).is_file():
                env.package_manager = manager
        if not any(r.startswith("Node") for r in env.runtime):
            nvmrc = root / ".nvmrc"
            if nvmrc.is_file():
                env.runtime.append(_version_label("Node.js", nvmrc.read_text().strip()))
            else:
                env.runtime.append("Node.js")
        for package, label in RUNTIME_PACKAGES.items():
            spec = declared.get(package) or dev_declared.get(package)
            if spec is not None:
                env.runtime.append(_version_label(label, spec))

    pyproject = _read_toml(root / "pyproject.toml") if (root / "pyproject.toml").is_file() else None
    if pyproject:
        project = pyproject.get("project") or {}
        requires = project.get("requires-python")
        env.runtime.append(f"Python {requires}" if requires else "Python")
        for dep in project.get("dependencies") or []:
            name = re.split(r"[<>=!~\[; ]", str(dep), 1)[0].strip()
            if name:
                declared[name] = str(dep)[len(name):].strip()
        for group in (project.get("optional-dependencies") or {}).values():
            for dep in group or []:
                name = re.split(r"[<>=!~\[; ]", str(dep), 1)[0].strip()
                if name:
                    dev_declared[name] = ""
        poetry = (pyproject.get("tool") or {}).get("poetry") or {}
        for name, spec in (poetry.get("dependencies") or {}).items():
            if name.lower() == "python":
                env.runtime[-1] = f"Python {spec}"
            else:
                declared[name] = str(spec)
        for package, label in RUNTIME_PACKAGES.items():
            if package in declared:
                env.runtime.append(_version_label(label, declared[package]))
        env.package_manager = env.package_manager or ("poetry" if poetry else "uv" if (root / "uv.lock").is_file() else "pip")
    elif (root / "requirements.txt").is_file():
        env.runtime.append("Python")
        for line in (root / "requirements.txt").read_text(errors="replace").splitlines():
            line = line.strip()
            if line and not line.startswith(("#", "-")):
                name = re.split(r"[<>=!~\[; ]", line, 1)[0]
                declared[name] = line[len(name):].strip()
        env.package_manager = env.package_manager or "pip"

    go_mod = root / "go.mod"
    if go_mod.is_file():
        text = go_mod.read_text(errors="replace")
        match = re.search(r"^go\s+(\S+)", text, re.MULTILINE)
        env.runtime.append(f"Go {match.group(1)}" if match else "Go")
        for match in re.finditer(r"^\s*([\w.\-/]+)\s+v([\w.\-+]+)", text, re.MULTILINE):
            declared[match.group(1)] = match.group(2)
        env.package_manager = env.package_manager or "go modules"

    cargo = _read_toml(root / "Cargo.toml") if (root / "Cargo.toml").is_file() else None
    if cargo:
        package = cargo.get("package") or {}
        edition = package.get("edition")
        env.runtime.append(f"Rust (edition {edition})" if edition else "Rust")
        for name, spec in (cargo.get("dependencies") or {}).items():
            declared[name] = spec if isinstance(spec, str) else str((spec or {}).get("version", ""))
        env.package_manager = env.package_manager or "cargo"

    # External packages: declared ones first (ordered by how many files import them), then
    # anything imported but undeclared (stdlib, transitive) that is clearly not local.
    def usage(name: str) -> int:
        return used.get(name, 0) + sum(count for pkg, count in used.items() if pkg.startswith(name + "/"))

    ordered = sorted(declared, key=lambda name: (-usage(name), name))
    env.external_packages = [_version_label(name, declared[name]) if declared[name] else name for name in ordered]
    env.dev_packages = sorted(dev_declared)
    env.analytics = sorted(
        {label for label in (set(declared) | set(used)) if label in ANALYTICS_PACKAGES or label.split("/")[0] in ANALYTICS_PACKAGES}
    )

    # Execution environment: deployment / CI / container markers.
    seen_exec: List[str] = []
    for path in workspace.iter_files():
        rel = workspace.relative(path)
        lowered = path.name.lower()
        label = EXECUTION_MARKERS.get(lowered)
        if label is None and rel.startswith(".github/workflows/"):
            label = "GitHub Actions"
        if label is None and rel.startswith((".circleci/",)):
            label = "CircleCI"
        if label is None and lowered.endswith((".tf",)):
            label = "Terraform"
        if label is None and (rel.startswith(("k8s/", "kubernetes/", "manifests/")) and lowered.endswith((".yaml", ".yml"))):
            label = "Kubernetes"
        if label and label not in seen_exec:
            seen_exec.append(label)
    if not seen_exec:
        if "Next.js" in " ".join(env.runtime) or any(r.startswith("Next.js") for r in env.runtime):
            seen_exec.append("Node server / Vercel-style (no deploy config found)")
        elif env.runtime:
            seen_exec.append("Local process (no deploy config found)")
    env.execution = seen_exec
    env.runtime = list(dict.fromkeys(env.runtime))
    return env


# --------------------------------------------------------------------------- #
# Build
# --------------------------------------------------------------------------- #


def build_architecture(workspace: Workspace, graph: CodeGraph) -> Architecture:
    components: Dict[str, Component] = {}
    file_roles: Dict[str, str] = {}
    for node in graph.nodes:
        role_id, reason = classify(node)
        file_roles[node.id] = role_id
        component = components.setdefault(role_id, Component(role=ROLES[role_id]))
        component.files.append(node)
        component.evidence[node.path] = reason
        for raw in node.imports:
            package = external_package_name(raw, node.language)
            if package and PACKAGE_ROLES.get(package) == role_id:
                component.packages[package] = component.packages.get(package, 0) + 1

    edge_index: Dict[Tuple[str, str], ComponentEdge] = {}
    for edge in graph.edges:
        source = file_roles.get(edge.source)
        target = file_roles.get(edge.target)
        if not source or not target or source == target:
            continue
        key = (source, target)
        entry = edge_index.get(key)
        if entry is None:
            entry = edge_index[key] = ComponentEdge(source=source, target=target, weight=0)
        entry.weight += 1
        if len(entry.examples) < 3:
            entry.examples.append((edge.source.removeprefix("file:"), edge.target.removeprefix("file:")))

    ordered = sorted(components.values(), key=lambda c: (c.role.order, -c.loc, c.role.label))
    for component in ordered:
        component.files.sort(key=lambda n: (-n.loc, n.path))
    return Architecture(
        root=str(workspace.root),
        name=workspace.root.name,
        components=ordered,
        edges=sorted(edge_index.values(), key=lambda e: -e.weight),
        environment=build_environment(workspace, graph),
        file_roles=file_roles,
        parser=graph.parser,
    )


# --------------------------------------------------------------------------- #
# Layout
# --------------------------------------------------------------------------- #

BOX_WIDTH = 300
BOX_GAP_X = 140  # room for arrows between columns
BOX_GAP_Y = 48
FRAME_PAD = 48
FRAME_TITLE = 64
PANEL_WIDTH = 300
PANEL_GAP = 40
MAX_FILES_IN_BOX = 4
MAX_PACKAGES = 10
ROLE_EDGE_ACCENT = {"database": "emerald", "cache": "amber", "auth": "violet", "logging": "slate", "analytics": "coral"}


def _sanitize(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in value)


def _estimate_card_height(body_lines: int) -> float:
    # Title row + ~22px per body line + padding. Kept generous so frames never clip.
    return 64 + 22 * max(body_lines, 1) + 24


def _component_body(component: Component) -> List[str]:
    files = component.files
    lines = [f"{len(files)} file{'s' if len(files) != 1 else ''} · {component.loc} loc"]
    for node in files[:MAX_FILES_IN_BOX]:
        symbols = [s.name for s in node.symbols if s.kind in {"class", "function", "interface", "struct"}][:2]
        suffix = f"  ({', '.join(symbols)})" if symbols else ""
        lines.append(f"{node.path}{suffix}")
    if len(files) > MAX_FILES_IN_BOX:
        lines.append(f"… +{len(files) - MAX_FILES_IN_BOX} more")
    if component.packages:
        top = sorted(component.packages, key=lambda p: -component.packages[p])[:3]
        lines.append("via " + ", ".join(top))
    return lines


def architecture_to_primitives(
    architecture: Architecture,
    *,
    title: Optional[str] = None,
    include_environment: bool = True,
    include_minor: bool = True,
) -> List[Primitive]:
    """Lay the architecture out like the whiteboard sketch.

    A ``Codebase`` frame holds one box per component, arranged in columns from
    data (left) to delivery (right) so dependency arrows mostly flow one way;
    below it sit the environment panels (external packages, runtime, analytics,
    execution environment).
    """
    title = title or f"{architecture.name} · architecture"
    primitives: List[Primitive] = []
    components = [c for c in architecture.components if include_minor or c.role.id not in {"config", "tests", "shared"}]
    total_files = sum(len(c.files) for c in architecture.components)
    heading = HeadingPrimitive(
        kind="heading",
        id="arch-heading",
        text=title,
        subtitle=f"{len(components)} components · {total_files} files · {len(architecture.edges)} dependencies · parsed with {architecture.parser}",
        x=0,
        y=0,
        size="xl",
    )
    primitives.append(heading)
    if not components:
        primitives.append(NotePrimitive(kind="note", id="arch-empty", text="No source files were indexed.", x=0, y=120))
        return primitives

    # Columns by role order; within a column, biggest component first.
    columns: Dict[int, List[Component]] = {}
    for component in components:
        columns.setdefault(component.role.order, []).append(component)
    column_keys = sorted(columns)

    frame_id = "arch-frame-codebase"
    frame_y = 120.0
    cards: List[Tuple[CardPrimitive, float]] = []
    column_heights: List[float] = []
    x = FRAME_PAD
    for key in column_keys:
        y = frame_y + FRAME_TITLE
        for component in columns[key]:
            body = _component_body(component)
            card = CardPrimitive(
                kind="card",
                id=_sanitize(f"arch-{component.role.id}"),
                frame=frame_id,
                title=component.role.label,
                body=body,
                x=x,
                y=y,
                width=BOX_WIDTH,
                accent=component.role.accent,
            )
            height = _estimate_card_height(len(body))
            cards.append((card, height))
            y += height + BOX_GAP_Y
        column_heights.append(y - (frame_y + FRAME_TITLE) - BOX_GAP_Y)
        x += BOX_WIDTH + BOX_GAP_X

    frame_width = FRAME_PAD * 2 + len(column_keys) * BOX_WIDTH + (len(column_keys) - 1) * BOX_GAP_X
    frame_height = FRAME_TITLE + max(column_heights) + FRAME_PAD
    primitives.append(
        FramePrimitive(kind="frame", id=frame_id, title="Codebase", x=0, y=frame_y, width=frame_width, height=frame_height)
    )
    primitives.extend(card for card, _ in cards)

    present = {c.role.id for c in components}
    for edge in architecture.edges:
        if edge.source not in present or edge.target not in present:
            continue
        label = f"{edge.weight} import{'s' if edge.weight != 1 else ''}"
        primitives.append(
            RoutePrimitive.model_validate(
                {
                    "kind": "route",
                    "id": _sanitize(f"arch-edge-{edge.source}-{edge.target}"),
                    "from": _sanitize(f"arch-{edge.source}"),
                    "to": _sanitize(f"arch-{edge.target}"),
                    "label": label if edge.weight > 1 else None,
                    "style": "solid" if edge.weight > 1 else "dashed",
                    "accent": ROLE_EDGE_ACCENT.get(edge.target, "slate"),
                    "arrow": True,
                }
            )
        )

    cursor_y = frame_y + frame_height + 80
    if include_environment:
        env = architecture.environment
        panels: List[Tuple[str, str, List[str]]] = []
        packages = env.external_packages[:MAX_PACKAGES]
        extra = len(env.external_packages) - len(packages)
        panels.append(("External packages", "sky", (packages or ["No manifest found"]) + ([f"… +{extra} more"] if extra > 0 else [])))
        runtime = list(env.runtime)
        if env.package_manager:
            runtime.append(f"package manager: {env.package_manager}")
        panels.append(("Runtime", "indigo", runtime or ["Unknown — no package.json / pyproject / go.mod"]))
        analytics_component = next((c for c in architecture.components if c.role.id == "analytics"), None)
        analytics_lines = list(env.analytics)
        if analytics_component:
            analytics_lines.extend(node.path for node in analytics_component.files[:3])
        panels.append(("Analytics", "coral", analytics_lines or ["None detected"]))
        panels.append(("Execution environment", "emerald", env.execution or ["Not detected"]))

        panel_frame_id = "arch-frame-environment"
        panel_x = FRAME_PAD
        tallest = 0.0
        panel_cards: List[CardPrimitive] = []
        for index, (label, accent, lines) in enumerate(panels):
            panel_cards.append(
                CardPrimitive(
                    kind="card",
                    id=_sanitize(f"arch-env-{label}"),
                    frame=panel_frame_id,
                    title=label,
                    body=lines,
                    x=panel_x,
                    y=cursor_y + FRAME_TITLE,
                    width=PANEL_WIDTH,
                    accent=accent,
                )
            )
            tallest = max(tallest, _estimate_card_height(len(lines)))
            panel_x += PANEL_WIDTH + PANEL_GAP
        env_width = max(frame_width, FRAME_PAD * 2 + len(panels) * PANEL_WIDTH + (len(panels) - 1) * PANEL_GAP)
        primitives.append(
            FramePrimitive(
                kind="frame",
                id=panel_frame_id,
                title="Environment",
                x=0,
                y=cursor_y,
                width=env_width,
                height=FRAME_TITLE + tallest + FRAME_PAD,
            )
        )
        primitives.extend(panel_cards)
        cursor_y += FRAME_TITLE + tallest + FRAME_PAD + 60

    primitives.append(
        LegendPrimitive(
            kind="legend",
            id="arch-legend",
            title="Components",
            items=[LegendItem(label=f"{c.role.label} — {c.role.description}", accent=c.role.accent) for c in components[:8]],
            x=0,
            y=cursor_y,
        )
    )
    return primitives
