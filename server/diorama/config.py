"""Central runtime configuration, read once from the environment.

Everything that differs between local development and a deployed instance lives
here so the rest of the server never reaches for ``os.getenv`` directly:

  DIORAMA_WORKSPACE     - repository the code tools may read/write (default: cwd)
  DIORAMA_ALLOW_EXEC    - "off" to forbid run_command entirely (default: on)
  DIORAMA_EXEC_TIMEOUT  - seconds before a run_command is killed (default: 120)
  DIORAMA_HOST / PORT   - bind address for `python -m diorama.server`
  DIORAMA_RELOAD        - "on" for uvicorn autoreload (default: off)
  DIORAMA_CORS_ORIGINS  - comma-separated allowed origins (default: local dev)
  DIORAMA_DB            - sqlite path for session persistence (default: disabled)
  DIORAMA_WEB_DIST      - built frontend to serve at "/" (default: ../web/dist)
  DIORAMA_MAX_READ_BYTES / DIORAMA_MAX_OUTPUT_BYTES
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

DEFAULT_CORS_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
)

# ``server/diorama/config.py`` -> repo root -> ``web/dist``.
DEFAULT_WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    workspace_root: Optional[Path] = None
    allow_exec: bool = True
    exec_timeout: float = 120.0
    max_read_bytes: int = 400_000
    max_output_bytes: int = 40_000
    host: str = "127.0.0.1"
    port: int = 8000
    reload: bool = False
    cors_origins: List[str] = field(default_factory=lambda: list(DEFAULT_CORS_ORIGINS))
    database_path: Optional[Path] = None
    allow_credentials: bool = False
    web_dist: Optional[Path] = None

    @property
    def code_enabled(self) -> bool:
        return self.workspace_root is not None

    @property
    def frontend_enabled(self) -> bool:
        """True when a built frontend is present and can be served at "/"."""
        return self.web_dist is not None and (self.web_dist / "index.html").is_file()


def load_settings() -> Settings:
    workspace = os.getenv("DIORAMA_WORKSPACE")
    database = os.getenv("DIORAMA_DB")
    web_dist = os.getenv("DIORAMA_WEB_DIST")
    origins_env = os.getenv("DIORAMA_CORS_ORIGINS")
    if origins_env:
        origins = [origin.strip() for origin in origins_env.split(",") if origin.strip()]
    else:
        origins = list(DEFAULT_CORS_ORIGINS)
    # A wildcard origin cannot be combined with credentialed requests.
    allow_credentials = "*" not in origins and _env_bool("DIORAMA_CORS_CREDENTIALS", False)
    return Settings(
        workspace_root=Path(workspace).expanduser().resolve() if workspace else None,
        allow_exec=_env_bool("DIORAMA_ALLOW_EXEC", True),
        exec_timeout=_env_float("DIORAMA_EXEC_TIMEOUT", 120.0),
        max_read_bytes=_env_int("DIORAMA_MAX_READ_BYTES", 400_000),
        max_output_bytes=_env_int("DIORAMA_MAX_OUTPUT_BYTES", 40_000),
        host=os.getenv("DIORAMA_HOST", "127.0.0.1"),
        port=_env_int("DIORAMA_PORT", 8000),
        reload=_env_bool("DIORAMA_RELOAD", False),
        cors_origins=origins,
        database_path=Path(database).expanduser() if database else None,
        allow_credentials=allow_credentials,
        web_dist=Path(web_dist).expanduser().resolve() if web_dist else DEFAULT_WEB_DIST,
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()


def reset_settings_cache() -> None:
    """For tests and for the CLI, which sets env vars before importing the app."""
    get_settings.cache_clear()
