"""Syntax-aware symbol and import extraction backed by tree-sitter.

The indexer used to regex-scan every non-Python file.  That misses multi-line
imports, mis-fires inside strings/comments, and knows nothing about scope.  Here
each supported language is parsed with its real grammar (via
``tree-sitter-language-pack``) and the concrete syntax tree is walked for:

* **imports**  - module specifiers (``import x from 'y'``, ``require('y')``,
  ``use a::b``, ``import "fmt"``, ``require_relative``...)
* **symbols**  - top-level (and exported) declarations with their kind and line
* **calls**    - names of functions/methods invoked, used to infer a file's role
  (``supabase.from``, ``redis.get``, ``logger.info``, ``app.get``...)

tree-sitter is an optional dependency: when it is missing, or a grammar is not
available, :func:`parse_source` falls back to the regex scanners so indexing
never fails.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

try:  # pragma: no cover - exercised implicitly when the package is installed
    from tree_sitter_language_pack import get_parser as _get_parser

    TREE_SITTER_AVAILABLE = True
except Exception:  # noqa: BLE001 - any import problem just disables the backend
    _get_parser = None  # type: ignore[assignment]
    TREE_SITTER_AVAILABLE = False


@dataclass
class ParsedSymbol:
    name: str
    kind: str  # class | function | method | interface | type | enum | constant | struct | trait | module
    line: int
    end_line: Optional[int] = None
    signature: Optional[str] = None
    exported: bool = False


@dataclass
class ParseResult:
    imports: List[str] = field(default_factory=list)
    symbols: List[ParsedSymbol] = field(default_factory=list)
    calls: Set[str] = field(default_factory=set)
    backend: str = "regex"  # "tree-sitter" | "regex"


# Grammar names in tree-sitter-language-pack, keyed by (language, suffix).
GRAMMAR_BY_SUFFIX: Dict[str, str] = {
    ".ts": "typescript",
    ".tsx": "tsx",
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

MAX_CALLS = 400


@lru_cache(maxsize=None)
def _parser(grammar: str) -> Optional[Any]:
    if not TREE_SITTER_AVAILABLE or _get_parser is None:
        return None
    try:
        return _get_parser(grammar)
    except Exception:  # noqa: BLE001 - unknown grammar -> regex fallback
        return None


def parse_source(suffix: str, source: str) -> ParseResult:
    """Parse ``source`` for a file with ``suffix`` (e.g. ``.tsx``)."""
    grammar = GRAMMAR_BY_SUFFIX.get(suffix.lower())
    parser = _parser(grammar) if grammar else None
    if parser is None:
        return _parse_regex(source)
    try:
        tree = parser.parse(source.encode("utf-8", errors="replace"))
    except Exception:  # noqa: BLE001
        return _parse_regex(source)
    walker = _WALKERS.get(grammar, _walk_generic)
    result = walker(tree.root_node, source)
    result.backend = "tree-sitter"
    # Deduplicate while preserving order; drop anonymous declarations.
    result.imports = list(dict.fromkeys(imp for imp in result.imports if imp))
    result.symbols = [symbol for symbol in result.symbols if symbol.name]
    return result


# --------------------------------------------------------------------------- #
# Tree helpers
# --------------------------------------------------------------------------- #


def _text(node: Any) -> str:
    return node.text.decode("utf-8", errors="replace") if node is not None and node.text is not None else ""


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'`":
        return value[1:-1]
    return value


def _child(node: Any, field_name: str) -> Any:
    try:
        return node.child_by_field_name(field_name)
    except Exception:  # noqa: BLE001
        return None


def _iter(node: Any) -> Iterable[Any]:
    """Depth-first traversal over every node (iterative; big files are common)."""
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.children))


def _callee_name(node: Any) -> Optional[str]:
    """`a.b.c(...)` -> "a.b.c"; `foo(...)` -> "foo"."""
    if node is None:
        return None
    if node.type in {"identifier", "property_identifier", "field_identifier", "type_identifier", "constant"}:
        return _text(node)
    if node.type in {"member_expression", "attribute", "selector_expression", "field_expression", "scoped_identifier",
                     "method_invocation", "navigation_expression", "call", "scoped_call_expression"}:
        parts = [_text(child) for child in node.children if child.type in {
            "identifier", "property_identifier", "field_identifier", "type_identifier", "this", "self", "constant",
        }]
        if parts:
            return ".".join(parts)
    text = _text(node)
    return text if 0 < len(text) <= 80 and "\n" not in text else None


def _collect_calls(root: Any, call_types: Tuple[str, ...], func_field: str = "function") -> Set[str]:
    calls: Set[str] = set()
    for node in _iter(root):
        if node.type in call_types:
            callee = _child(node, func_field)
            if callee is None and node.type == "call":  # ruby: method field
                callee = _child(node, "method")
                receiver = _child(node, "receiver")
                if callee is not None and receiver is not None:
                    name = f"{_text(receiver)}.{_text(callee)}"
                    calls.add(name)
                    continue
            name = _callee_name(callee)
            if name:
                calls.add(name)
                if len(calls) >= MAX_CALLS:
                    break
    return calls


def _symbol(node: Any, name: str, kind: str, *, exported: bool = False, signature: Optional[str] = None) -> ParsedSymbol:
    return ParsedSymbol(
        name=name,
        kind=kind,
        line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        signature=signature,
        exported=exported,
    )


# --------------------------------------------------------------------------- #
# JavaScript / TypeScript
# --------------------------------------------------------------------------- #

_JS_DECL_KINDS = {
    "function_declaration": "function",
    "generator_function_declaration": "function",
    "class_declaration": "class",
    "abstract_class_declaration": "class",
    "interface_declaration": "interface",
    "type_alias_declaration": "type",
    "enum_declaration": "enum",
}


def _js_declaration_symbols(node: Any, exported: bool) -> List[ParsedSymbol]:
    kind = _JS_DECL_KINDS.get(node.type)
    if kind:
        name = _child(node, "name")
        params = _child(node, "parameters")
        return [_symbol(node, _text(name) or "default", kind, exported=exported, signature=_text(params) or None)]
    if node.type in {"lexical_declaration", "variable_declaration"}:
        symbols = []
        for declarator in node.children:
            if declarator.type != "variable_declarator":
                continue
            name = _child(declarator, "name")
            value = _child(declarator, "value")
            if name is None or name.type != "identifier":
                continue
            value_type = value.type if value is not None else ""
            if value_type in {"arrow_function", "function", "function_expression", "generator_function"}:
                kind = "function"
                signature = _text(_child(value, "parameters")) or None
            elif _text(name).isupper():
                kind, signature = "constant", None
            else:
                kind, signature = "variable", None
            symbols.append(_symbol(declarator, _text(name), kind, exported=exported, signature=signature))
        return symbols
    return []


def _walk_javascript(root: Any, source: str) -> ParseResult:
    result = ParseResult()
    for node in root.children:
        if node.type == "import_statement":
            spec = _child(node, "source")
            if spec is not None:
                result.imports.append(_unquote(_text(spec)))
        elif node.type == "export_statement":
            spec = _child(node, "source")
            if spec is not None:  # export ... from "x"
                result.imports.append(_unquote(_text(spec)))
            declaration = _child(node, "declaration")
            if declaration is not None:
                result.symbols.extend(_js_declaration_symbols(declaration, exported=True))
            else:
                # `export default function () {}` / `export default Foo`
                for child in node.children:
                    if child.type in _JS_DECL_KINDS or child.type in {"lexical_declaration", "variable_declaration"}:
                        result.symbols.extend(_js_declaration_symbols(child, exported=True))
        elif node.type == "expression_statement" and node.children and node.children[0].type == "assignment_expression":
            # module.exports = ... / exports.foo = ...
            left = _child(node.children[0], "left")
            if left is not None and _text(left).startswith(("module.exports", "exports.")):
                result.symbols.append(_symbol(node, _text(left), "export", exported=True))
        else:
            result.symbols.extend(_js_declaration_symbols(node, exported=False))

    # require("x") / import("x") anywhere in the file.
    for node in _iter(root):
        if node.type == "call_expression":
            callee = _child(node, "function")
            callee_text = _text(callee)
            if callee_text in {"require", "import"}:
                args = _child(node, "arguments")
                if args is not None:
                    for arg in args.children:
                        if arg.type in {"string", "template_string"}:
                            result.imports.append(_unquote(_text(arg)))
    result.calls = _collect_calls(root, ("call_expression", "new_expression"), "function") | _collect_calls(
        root, ("new_expression",), "constructor"
    )
    return result


# --------------------------------------------------------------------------- #
# Go
# --------------------------------------------------------------------------- #


def _walk_go(root: Any, source: str) -> ParseResult:
    result = ParseResult()
    for node in root.children:
        if node.type == "import_declaration":
            for spec in _iter(node):
                if spec.type == "import_spec":
                    path = _child(spec, "path")
                    if path is not None:
                        result.imports.append(_unquote(_text(path)))
        elif node.type == "function_declaration":
            name = _text(_child(node, "name"))
            result.symbols.append(_symbol(node, name, "function", exported=name[:1].isupper(),
                                          signature=_text(_child(node, "parameters")) or None))
        elif node.type == "method_declaration":
            name = _text(_child(node, "name"))
            receiver = _text(_child(node, "receiver"))
            recv_type = re.sub(r"[()*\s]", "", receiver.split()[-1]) if receiver else ""
            result.symbols.append(_symbol(node, f"{recv_type}.{name}" if recv_type else name, "method",
                                          exported=name[:1].isupper()))
        elif node.type == "type_declaration":
            for spec in node.children:
                if spec.type == "type_spec":
                    name = _text(_child(spec, "name"))
                    type_node = _child(spec, "type")
                    kind = {"struct_type": "struct", "interface_type": "interface"}.get(
                        type_node.type if type_node is not None else "", "type")
                    result.symbols.append(_symbol(spec, name, kind, exported=name[:1].isupper()))
    result.calls = _collect_calls(root, ("call_expression",))
    return result


# --------------------------------------------------------------------------- #
# Rust
# --------------------------------------------------------------------------- #

_RUST_KINDS = {
    "function_item": "function",
    "struct_item": "struct",
    "enum_item": "enum",
    "trait_item": "trait",
    "type_item": "type",
    "const_item": "constant",
    "static_item": "constant",
    "mod_item": "module",
}


def _walk_rust(root: Any, source: str) -> ParseResult:
    result = ParseResult()
    for node in root.children:
        if node.type == "use_declaration":
            arg = _child(node, "argument")
            text = _text(arg).replace(" ", "")
            # `use a::{b, c}` -> keep the crate/module root, which is what resolves.
            result.imports.append(text.split("::{")[0].split("{")[0].rstrip(":") or text)
        elif node.type == "extern_crate_declaration":
            name = _child(node, "name")
            result.imports.append(_text(name))
        elif node.type in _RUST_KINDS:
            name = _text(_child(node, "name"))
            exported = any(child.type == "visibility_modifier" for child in node.children)
            result.symbols.append(_symbol(node, name, _RUST_KINDS[node.type], exported=exported,
                                          signature=_text(_child(node, "parameters")) or None))
        elif node.type == "impl_item":
            type_name = _text(_child(node, "type"))
            body = _child(node, "body")
            for child in (body.children if body is not None else []):
                if child.type == "function_item":
                    name = _text(_child(child, "name"))
                    result.symbols.append(_symbol(child, f"{type_name}.{name}", "method"))
    result.calls = _collect_calls(root, ("call_expression", "macro_invocation"), "function") | {
        _text(_child(n, "macro")) + "!" for n in _iter(root) if n.type == "macro_invocation" and _child(n, "macro")
    }
    return result


# --------------------------------------------------------------------------- #
# Java / C# / Kotlin (class-oriented, similar shapes)
# --------------------------------------------------------------------------- #

_CLASS_KINDS = {
    "class_declaration": "class",
    "interface_declaration": "interface",
    "enum_declaration": "enum",
    "record_declaration": "class",
    "struct_declaration": "struct",
    "object_declaration": "class",
}


def _walk_classy(root: Any, source: str) -> ParseResult:
    result = ParseResult()
    for node in _iter(root):
        if node.type in {"import_declaration", "using_directive", "import_header"}:
            text = _text(node)
            text = re.sub(r"^\s*(import|using)\s+(static\s+)?", "", text).rstrip("; \n")
            result.imports.append(text)
        elif node.type in _CLASS_KINDS:
            name = _text(_child(node, "name"))
            if name:
                modifiers = " ".join(_text(c) for c in node.children if c.type in {"modifiers", "modifier"})
                result.symbols.append(_symbol(node, name, _CLASS_KINDS[node.type], exported="public" in modifiers))
        elif node.type in {"method_declaration", "function_declaration", "constructor_declaration"}:
            name = _text(_child(node, "name"))
            owner = node.parent.parent if node.parent is not None else None
            owner_name = _text(_child(owner, "name")) if owner is not None and owner.type in _CLASS_KINDS else ""
            if name:
                result.symbols.append(_symbol(node, f"{owner_name}.{name}" if owner_name else name,
                                              "method" if owner_name else "function",
                                              signature=_text(_child(node, "parameters")) or None))
    result.calls = _collect_calls(root, ("method_invocation", "invocation_expression", "call_expression"), "name") | \
        _collect_calls(root, ("invocation_expression", "call_expression"), "function")
    return result


# --------------------------------------------------------------------------- #
# Ruby
# --------------------------------------------------------------------------- #


def _walk_ruby(root: Any, source: str) -> ParseResult:
    result = ParseResult()
    for node in _iter(root):
        if node.type == "call":
            method = _text(_child(node, "method"))
            if method in {"require", "require_relative", "load"}:
                args = _child(node, "arguments")
                for arg in (args.children if args is not None else []):
                    if arg.type in {"string", "string_content"}:
                        result.imports.append(_unquote(_text(arg)))
        elif node.type in {"class", "module"}:
            result.symbols.append(_symbol(node, _text(_child(node, "name")), node.type, exported=True))
        elif node.type in {"method", "singleton_method"}:
            result.symbols.append(_symbol(node, _text(_child(node, "name")), "method"))
    result.calls = _collect_calls(root, ("call",), "method")
    return result


# --------------------------------------------------------------------------- #
# PHP / Swift / C / C++ / Vue / Svelte -> generic
# --------------------------------------------------------------------------- #

_GENERIC_IMPORT_TYPES = {
    "preproc_include", "import_declaration", "namespace_use_declaration", "import_statement", "use_declaration",
}
_GENERIC_SYMBOL_TYPES = {
    "function_definition": "function",
    "function_declaration": "function",
    "class_declaration": "class",
    "class_specifier": "class",
    "struct_specifier": "struct",
    "struct_declaration": "struct",
    "protocol_declaration": "interface",
    "interface_declaration": "interface",
    "method_declaration": "method",
    "enum_declaration": "enum",
    "enum_specifier": "enum",
}


def _walk_generic(root: Any, source: str) -> ParseResult:
    result = ParseResult()
    for node in _iter(root):
        if node.type in _GENERIC_IMPORT_TYPES:
            strings = [_unquote(_text(c)) for c in _iter(node) if c.type in {"string", "string_literal", "system_lib_string"}]
            if strings:
                result.imports.extend(s.strip("<>") for s in strings)
            else:
                text = re.sub(r"^\s*(import|use|#include|using)\s+", "", _text(node)).rstrip("; \n")
                if text:
                    result.imports.append(text)
        elif node.type in _GENERIC_SYMBOL_TYPES:
            name = _child(node, "name") or _child(node, "declarator")
            if name is not None:
                # C/C++: declarator wraps the identifier.
                ident = next((c for c in _iter(name) if c.type in {"identifier", "field_identifier"}), name)
                result.symbols.append(_symbol(node, _text(ident), _GENERIC_SYMBOL_TYPES[node.type]))
            if node.type not in {"method_declaration", "function_declaration", "function_definition"} and _child(node, "body") is None:
                pass
    result.calls = _collect_calls(root, ("call_expression", "function_call_expression", "member_call_expression"), "function")
    return result


_WALKERS: Dict[str, Callable[[Any, str], ParseResult]] = {
    "javascript": _walk_javascript,
    "typescript": _walk_javascript,
    "tsx": _walk_javascript,
    "go": _walk_go,
    "rust": _walk_rust,
    "java": _walk_classy,
    "csharp": _walk_classy,
    "kotlin": _walk_classy,
    "ruby": _walk_ruby,
}


# --------------------------------------------------------------------------- #
# Regex fallback (the pre-tree-sitter behaviour)
# --------------------------------------------------------------------------- #

_JS_IMPORT_RE = re.compile(
    r"""(?:^|\n)\s*(?:import|export)\s+(?:[^'"]*?\s+from\s+)?["']([^"']+)["']""",
    re.MULTILINE,
)
_JS_REQUIRE_RE = re.compile(r"""require\(\s*["']([^"']+)["']\s*\)""")
_JS_SYMBOL_RE = re.compile(
    r"""(?:^|\n)\s*(?P<export>export\s+)?(?:default\s+)?(?:async\s+)?"""
    r"""(?P<kind>class|function|const|let|var|interface|type|enum)\s+(?P<name>[A-Za-z_$][\w$]*)""",
    re.MULTILINE,
)
_GENERIC_IMPORT_RE = re.compile(
    r"""^\s*(?:use|import|from|require|using|extern|#include)\b.*?([A-Za-z_@][\w:./\-]*)""",
    re.MULTILINE,
)
_CALL_RE = re.compile(r"""\b([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*){0,3})\s*\(""")


def _parse_regex(source: str) -> ParseResult:
    result = ParseResult(backend="regex")
    imports = _JS_IMPORT_RE.findall(source) + _JS_REQUIRE_RE.findall(source)
    if not imports:
        imports = _GENERIC_IMPORT_RE.findall(source)
    result.imports = list(dict.fromkeys(i for i in imports if i))
    for match in _JS_SYMBOL_RE.finditer(source):
        line = source.count("\n", 0, match.start()) + 1
        kind = match.group("kind")
        result.symbols.append(ParsedSymbol(
            name=match.group("name"),
            kind={"const": "constant", "let": "variable", "var": "variable"}.get(kind, kind),
            line=line,
            exported=bool(match.group("export")),
        ))
    result.calls = set(_CALL_RE.findall(source)[:MAX_CALLS])
    return result
