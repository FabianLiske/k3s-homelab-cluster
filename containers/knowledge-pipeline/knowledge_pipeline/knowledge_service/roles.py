"""Per-Request-Rollen fuer REST- und MCP-Anfragen.

Die Middleware setzt `current_role` pro Anfrage; MCP-Tools (die im
gleichen Task ausgefuehrt werden) lesen es daraus.
"""

from __future__ import annotations

from contextvars import ContextVar

current_role: ContextVar[str | None] = ContextVar("knowledge_role", default=None)


def require_readwrite() -> None:
    """Erhebt die readwrite-Rolle, wirft sonst PermissionError."""
    if current_role.get() != "readwrite":
        raise PermissionError("dazu ist die Rolle 'readwrite' erforderlich")
