"""Structural index of a repository: files, symbols, and the import graph.

This is what lets Diorama *visualize a codebase* rather than improvise boxes.
It is deliberately dependency-free: Python is parsed with :mod:`ast`, other
languages get a fast regex scan for imports/exports.  The output is a
:class:`CodeGraph` that can be summarised for the model or laid out into canvas
primitives for the user.
"""

from __future__ import annotations

import ast
import fnmatch
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from diorama.codebase.parsers import TREE_SITTER_AVAILABLE, parse_source
from diorama.codebase.workspace import Workspace

# --------------------------------------------------------------------------- #
# Language detection
# --------------------------------------------------------------------------- #

LANGUAGE_BY_SUFFIX: Dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".rb": "ruby",
    ".cs": "csharp",
    ".kt": "kotlin",
    ".swift": "swift",
    ".php": "php",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".vue": "vue",
    ".svelte": "svelte",
}

# Files worth indexing even though they are not source code.
CONFIG_NAMES = {
    "package.json",
    "pyproject.toml",
    "tsconfig.json",
    "cargo.toml",
    "go.mod",
    "dockerfile",
    "makefile",
    "requirements.txt",
    "compose.yaml",
    "docker-compose.yml",
}

IGNORED_DIR_HINTS = ("test", "tests", "__tests__", "spec", "specs", "e2e", "fixtures")
IGNORED_FILE_PATTERNS = ("*.min.js", "*.min.css", "*.map", "*.d.ts", "*_pb2.py", "*.generated.*")

MAX_FILE_BYTES = 500_000


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #


@dataclass
class CodeSymbol:
    name: str
    kind: str  # module | class | function | method | interface | type | constant | export
    line: int
    end_line: Optional[int] = None
    signature: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {"name": self.name, "kind": self.kind, "line": self.line}
        if self.end_line is not None:
            data["endLine"] = self.end_line
        if self.signature:
            data["signature"] = self.signature
        return data


@dataclass
class CodeNode:
    id: str
    path: str
    name: str
    language: str
    loc: int = 0
    module: str = ""
    symbols: List[CodeSymbol] = field(default_factory=list)
    imports: List[str] = field(default_factory=list)
    calls: List[str] = field(default_factory=list)
    is_test: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "path": self.path,
            "name": self.name,
            "language": self.language,
            "loc": self.loc,
            "module": self.module,
            "isTest": self.is_test,
            "imports": self.imports,
            "calls": self.calls[:40],
            "symbols": [s.to_dict() for s in self.symbols],
        }


@dataclass
class CodeEdge:
    source: str
    target: str
    kind: str = "imports"

    def to_dict(self) -> Dict[str, Any]:
        return {"source": self.source, "target": self.target, "kind": self.kind}


@dataclass
class CodeGraph:
    root: str
    nodes: List[CodeNode]
    edges: List[CodeEdge]
    languages: Dict[str, int] = field(default_factory=dict)
    total_files: int = 0
    truncated: bool = False
    parser: str = "tree-sitter" if TREE_SITTER_AVAILABLE else "regex"

    # ------------------------------------------------------------- summaries

    def node_by_id(self) -> Dict[str, CodeNode]:
        return {node.id: node for node in self.nodes}

    def to_summary(self, *, max_nodes: int = 200) -> Dict[str, Any]:
        """Compact overview for the model (or the UI sidebar)."""
        nodes = self.nodes[:max_nodes]
        included = {node.id for node in nodes}
        edges = [e for e in self.edges if e.source in included and e.target in included]
        return {
            "root": self.root,
            "totalFiles": self.total_files,
            "indexedFiles": len(self.nodes),
            "truncated": self.truncated,
            "parser": self.parser,
            "languages": self.languages,
            "nodes": [node.to_dict() for node in nodes],
            "edges": [edge.to_dict() for edge in edges],
            "nodeCount": len(self.nodes),
            "edgeCount": len(self.edges),
        }

    # --------------------------------------------------------------- layout

    def layered_layout(self, *, nodes: Optional[Sequence[CodeNode]] = None) -> Dict[str, int]:
        """Assign each node a column via longest-path layering (Sugiyama-lite).

        Deterministic: ties are broken by node id so repeated builds are stable.
        """
        selected = list(nodes if nodes is not None else self.nodes)
        ids = {node.id for node in selected}
        adjacency: Dict[str, List[str]] = {node.id: [] for node in selected}
        indegree: Dict[str, int] = {node.id: 0 for node in selected}
        for edge in self.edges:
            if edge.source in ids and edge.target in ids and edge.source != edge.target:
                adjacency[edge.source].append(edge.target)
                indegree[edge.target] += 1

        layer: Dict[str, int] = {node_id: 0 for node_id in ids}
        # Kahn's algorithm; nodes left in a cycle get their best-known layer.
        remaining = dict(indegree)
        queue = sorted(node_id for node_id, degree in remaining.items() if degree == 0)
        processed: List[str] = []
        while queue:
            current = queue.pop(0)
            processed.append(current)
            for neighbor in sorted(adjacency[current]):
                layer[neighbor] = max(layer[neighbor], layer[current] + 1)
                remaining[neighbor] -= 1
                if remaining[neighbor] == 0:
                    queue.append(neighbor)
            queue.sort()
        for node_id in ids:
            if node_id not in processed:
                # Part of a cycle: place it after its earliest predecessor.
                predecessors = [e.source for e in self.edges if e.target == node_id and e.source in ids]
                layer[node_id] = max((layer[p] + 1 for p in predecessors), default=0)
        return layer


# --------------------------------------------------------------------------- #
# Parsers
# --------------------------------------------------------------------------- #

_JS_IMPORT_RE = re.compile(
    r"""(?:^|\n)\s*(?:import|export)\s+(?:[^'"]*?\s+from\s+)?["']([^"']+)["']""",
    re.MULTILINE,
)
_JS_REQUIRE_RE = re.compile(r"""require\(\s*["']([^"']+)["']\s*\)""")
_JS_SYMBOL_RE = re.compile(
    r"""(?:^|\n)\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?"""
    r"""(?P<kind>class|function|const|let|var|interface|type|enum)\s+(?P<name>[A-Za-z_$][\w$]*)""",
    re.MULTILINE,
)
_GENERIC_IMPORT_RE = re.compile(
    r"""^\s*(?:use|import|from|require|using|extern)\b.*?([A-Za-z_][\w:./\-]*)""",
    re.MULTILINE,
)


def _parse_python(path: Path, source: str) -> Tuple[List[CodeSymbol], List[str], List[str]]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return [], [], []
    symbols: List[CodeSymbol] = []
    imports: List[str] = []
    calls: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _python_call_name(node.func)
            if name and name not in calls:
                calls.append(name)
                if len(calls) >= 400:
                    break
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.extend(_python_imports(node))
        elif isinstance(node, ast.ClassDef):
            symbols.append(
                CodeSymbol(
                    name=node.name,
                    kind="class",
                    line=node.lineno,
                    end_line=getattr(node, "end_lineno", None),
                    signature=_python_bases(node),
                )
            )
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbols.append(
                        CodeSymbol(
                            name=f"{node.name}.{child.name}",
                            kind="method",
                            line=child.lineno,
                            end_line=getattr(child, "end_lineno", None),
                        )
                    )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append(
                CodeSymbol(
                    name=node.name,
                    kind="function",
                    line=node.lineno,
                    end_line=getattr(node, "end_lineno", None),
                    signature=_python_signature(node),
                )
            )
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            target = node.targets[0] if isinstance(node, ast.Assign) and node.targets else getattr(node, "target", None)
            if isinstance(target, ast.Name) and target.id.isupper():
                symbols.append(CodeSymbol(name=target.id, kind="constant", line=node.lineno))
    return symbols, imports, calls


def _python_call_name(node: ast.AST) -> Optional[str]:
    """`a.b.c(...)` -> "a.b.c"; `f(...)` -> "f"."""
    parts: List[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    elif not parts:
        return None
    return ".".join(reversed(parts))


def _python_imports(node: ast.AST) -> List[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        module = node.module or ""
        prefix = "." * node.level
        return [f"{prefix}{module}" if module else prefix] if module or prefix else []
    return []


def _python_signature(node: ast.AST) -> Optional[str]:
    args = getattr(node, "args", None)
    if args is None:
        return None
    names = [arg.arg for arg in getattr(args, "args", [])]
    if getattr(args, "vararg", None):
        names.append("*" + args.vararg.arg)
    names.extend(kwarg.arg for kwarg in getattr(args, "kwonlyargs", []))
    if getattr(args, "kwarg", None):
        names.append("**" + args.kwarg.arg)
    return f"({', '.join(names)})"


def _python_bases(node: ast.ClassDef) -> Optional[str]:
    bases = [_name_of(base) for base in node.bases if _name_of(base)]
    return f"({', '.join(bases)})" if bases else None


def _name_of(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _parse_script(source: str) -> Tuple[List[CodeSymbol], List[str]]:
    """Regex fallback for JS/TS (kept for tests and environments without tree-sitter)."""
    imports = _JS_IMPORT_RE.findall(source) + _JS_REQUIRE_RE.findall(source)
    symbols: List[CodeSymbol] = []
    for match in _JS_SYMBOL_RE.finditer(source):
        line = source.count("\n", 0, match.start()) + 1
        symbols.append(CodeSymbol(name=match.group("name"), kind=match.group("kind"), line=line))
    return symbols, imports


def _parse_generic(source: str) -> Tuple[List[CodeSymbol], List[str]]:
    return [], _GENERIC_IMPORT_RE.findall(source)


def _parse_with_tree_sitter(suffix: str, source: str) -> Tuple[List[CodeSymbol], List[str], List[str]]:
    """Syntax-aware extraction; transparently falls back to regex inside :mod:`parsers`."""
    parsed = parse_source(suffix, source)
    symbols = [
        CodeSymbol(name=s.name, kind=s.kind, line=s.line, end_line=s.end_line, signature=s.signature)
        for s in parsed.symbols
    ]
    return symbols, parsed.imports, sorted(parsed.calls)


# --------------------------------------------------------------------------- #
# Import resolution
# --------------------------------------------------------------------------- #


def _module_for_path(path: str, language: str) -> str:
    stem = path
    for suffix in (".pyi", ".py", ".tsx", ".ts", ".jsx", ".js", ".mjs", ".cjs"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    parts = [part for part in stem.split("/") if part and part != "src"]
    if language == "python":
        if parts and parts[-1] == "__init__":
            parts = parts[:-1]
        return ".".join(parts)
    return "/".join(parts)


def _python_module(path: str, package_dirs: Set[str]) -> str:
    """Dotted module for a Python file, anchored at its package root.

    A file like ``server/diorama/agents/base.py`` lives in a package chain
    (``server/diorama`` and ``server/diorama/agents`` both hold ``__init__.py``)
    so its module is ``diorama.agents.base`` -- not ``server.diorama.agents.base``.
    Anchoring at the package root is what lets absolute imports such as
    ``from diorama.agents.base import ...`` resolve, which matters whenever the
    repo root is not itself the import root (e.g. a ``server/`` or ``src/`` layout).
    """
    stem = path
    for suffix in (".pyi", ".py"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    parts = [part for part in stem.split("/") if part]
    if not parts:
        return ""
    name = parts[-1]
    dirs = parts[:-1]
    # Longest suffix of directories that form a contiguous package chain.
    start = len(dirs)
    for i in range(len(dirs)):
        if all("/".join(parts[: j + 1]) in package_dirs for j in range(i, len(dirs))):
            start = i
            break
    module_parts = dirs[start:] + ([name] if name != "__init__" else [])
    return ".".join(module_parts)


def _build_resolver(nodes: Iterable[CodeNode]) -> Dict[str, str]:
    """Map many candidate module strings to a node id."""
    index: Dict[str, str] = {}
    for node in nodes:
        for key in _module_keys(node):
            index.setdefault(key, node.id)
    return index


def _module_keys(node: CodeNode) -> List[str]:
    keys = {node.module}
    path_no_ext = node.path.rsplit(".", 1)[0]
    keys.add(path_no_ext)
    keys.add(path_no_ext.replace("src/", "", 1))
    if node.language == "python":
        keys.add(node.module.replace(".", "/"))
        keys.add(node.module.replace(".", "/").replace("src/", "", 1))
        if node.module.endswith(".__init__"):
            keys.add(node.module[: -len(".__init__")])
        if node.module.endswith(".index"):
            keys.add(node.module[: -len(".index")])
    return [key for key in keys if key]


def _resolve_import(
    raw: str,
    node: CodeNode,
    index: Dict[str, str],
) -> Optional[str]:
    if not raw or raw.startswith("http"):
        return None
    # Path aliases (`@/lib/auth`, `~/components/x`) are the norm in Next/Vite/Nuxt
    # projects and conventionally point at the repo root or `src/`. Scoped npm
    # packages (`@scope/pkg`) never have a bare `@/` prefix, so this is unambiguous.
    for alias in ("@/", "~/"):
        if raw.startswith(alias):
            target = raw[len(alias):]
            return _first_match([target, f"src/{target}", f"{target}/index", f"src/{target}/index"], index)
    if raw.startswith("@"):
        return None
    if node.language == "python":
        candidates = [raw]
        if raw.startswith("."):
            base = node.module.rsplit(".", 1)[0] if "." in node.module else node.module
            depth = len(raw) - len(raw.lstrip("."))
            remainder = raw.lstrip(".").replace(".", "/")
            parts = base.split(".") if base else []
            parts = parts[: len(parts) - (depth - 1)] if depth > 1 else parts
            joined = "/".join(parts + ([remainder] if remainder else []))
            candidates.append(joined)
            candidates.append(joined.replace("/", "."))
        return _first_match(candidates, index)
    # Relative JS/TS imports.
    if raw.startswith("."):
        base_dir = node.path.rsplit("/", 1)[0] if "/" in node.path else ""
        joined = os.path.normpath(os.path.join(base_dir, raw)).replace(os.sep, "/")
        candidates = [joined, joined + "/index", joined + "/index.ts", joined + "/index.tsx"]
        return _first_match(candidates, index)
    return _first_match([raw], index)


def _first_match(candidates: Sequence[str], index: Dict[str, str]) -> Optional[str]:
    for candidate in candidates:
        if not candidate:
            continue
        if candidate in index:
            return index[candidate]
        trimmed = candidate.rstrip("/")
        if trimmed in index:
            return index[trimmed]
    return None


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #


def build_code_graph(
    workspace: Workspace,
    *,
    max_files: int = 600,
    include_tests: bool = True,
    languages: Optional[Sequence[str]] = None,
) -> CodeGraph:
    """Walk ``workspace`` and return a structural graph of the repository."""
    wanted = {lang.lower() for lang in languages} if languages else None
    nodes: List[CodeNode] = []
    languages_count: Dict[str, int] = {}
    total = 0
    truncated = False

    for path in workspace.iter_files():
        name = path.name
        language = LANGUAGE_BY_SUFFIX.get(path.suffix.lower())
        if language is None and name.lower() not in CONFIG_NAMES:
            continue
        if any(fnmatch.fnmatch(name, pattern) for pattern in IGNORED_FILE_PATTERNS):
            continue
        if wanted is not None and language is not None and language not in wanted:
            continue
        rel = workspace.relative(path)
        is_test = _looks_like_test(rel, name)
        if is_test and not include_tests:
            continue
        total += 1
        if len(nodes) >= max_files:
            truncated = True
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "\x00" in source[:4096]:
            continue

        if language == "python":
            symbols, imports, calls = _parse_python(path, source)
        elif language is not None:
            symbols, imports, calls = _parse_with_tree_sitter(path.suffix, source)
        else:
            symbols, imports, calls = [], [], []

        node_language = language or "config"
        languages_count[node_language] = languages_count.get(node_language, 0) + 1
        module = _module_for_path(rel, node_language)
        nodes.append(
            CodeNode(
                id=f"file:{rel}",
                path=rel,
                name=name,
                language=node_language,
                loc=source.count("\n") + 1,
                module=module,
                symbols=symbols,
                imports=[imp for imp in imports if imp],
                calls=calls,
                is_test=is_test,
            )
        )

    # Anchor Python modules at their package root so absolute imports resolve
    # even when the repo root is not the import root (e.g. a ``server/`` layout).
    package_dirs = {
        node.path.rsplit("/", 1)[0]
        for node in nodes
        if node.language == "python"
        and node.name in {"__init__.py", "__init__.pyi"}
        and "/" in node.path
    }
    for node in nodes:
        if node.language == "python":
            module = _python_module(node.path, package_dirs)
            if module:
                node.module = module

    index = _build_resolver(nodes)
    edges: List[CodeEdge] = []
    seen: set[Tuple[str, str]] = set()
    for node in nodes:
        for raw in node.imports:
            target = _resolve_import(raw, node, index)
            if target and target != node.id and (node.id, target) not in seen:
                seen.add((node.id, target))
                edges.append(CodeEdge(source=node.id, target=target))

    return CodeGraph(
        root=str(workspace.root),
        nodes=nodes,
        edges=edges,
        languages=dict(sorted(languages_count.items(), key=lambda item: (-item[1], item[0]))),
        total_files=total,
        truncated=truncated,
    )


def _looks_like_test(rel: str, name: str) -> bool:
    lowered = rel.lower()
    if any(f"/{hint}/" in f"/{lowered}" or lowered.startswith(f"{hint}/") for hint in IGNORED_DIR_HINTS):
        return True
    return name.startswith("test_") or ".test." in lowered or ".spec." in lowered
