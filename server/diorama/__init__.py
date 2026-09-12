"""Diorama server package.

Deliberately import-light: importing any ``diorama.*`` submodule must not eagerly
construct the FastAPI app.  The app binds the workspace at import time (reading
``DIORAMA_WORKSPACE``), so re-exporting it here would run *before* the CLI can set
that variable -- ``diorama dev <path>`` would then serve an unbound server.

Import it explicitly where needed: ``from diorama.app import app``.  (A lazy
``__getattr__`` re-export cannot work here: ``diorama.app`` is a real submodule,
and ``from diorama import app`` probes ``hasattr`` first, which imports the
submodule and shadows the re-export with the module object.)
"""

from __future__ import annotations

__all__: list[str] = []
