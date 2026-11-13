"""Trilium-Write-Pfad (remember/forget) fuer die readwrite-Rolle.

Konvention (Design-Doku C1):
- Notes landen unter Resources/Agent-Notizen/<agent>/
- Titelformat: "YYYY-MM-DD HH:MM – <Titel>" (UTC)
- Labels: #dateNote=<ISO>, #agentNote, #source=<agent>, optional #topic
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone

import requests

from .roles import require_readwrite

log = logging.getLogger(__name__)

AGENT_NOTIZEN = "Agent-Notizen"
RESOURCES = "Resources"
_AGENT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


class TriliumWriteError(RuntimeError):
    pass


def _check_agent(agent: str) -> str:
    agent = (agent or "unknown").strip().lower()
    if not _AGENT_RE.match(agent):
        raise TriliumWriteError(
            f"Agent-Name '{agent}' ungültig (erlaubt: a-z, 0-9, '_', '-', max. 32)"
        )
    return agent or "unknown"


class TriliumWriter:
    def __init__(self, client, sync_admin_url: str = "", timeout: float = 60.0):
        """client: TriliumClient aus dem kb_sync-Paket (Session wiederverwenden)."""
        self.trilium = client
        self.sync_admin_url = (sync_admin_url or "").rstrip("/")
        self.timeout = timeout

    # ---------- Helpers ----------

    def _get_note(self, note_id: str) -> dict:
        r = self.trilium.session.get(
            f"{self.trilium.url}/etapi/notes/{note_id}", timeout=self.timeout
        )
        if r.status_code == 404:
            raise TriliumWriteError(f"Note {note_id} nicht gefunden")
        if r.status_code >= 400:
            raise TriliumWriteError(f"Trilium {r.status_code}: {r.text[:200]}")
        return r.json()

    def _children(self, parent_id: str) -> list[dict]:
        parent = self._get_note(parent_id)
        out: list[dict] = []
        for cid in parent.get("childNoteIds") or []:
            try:
                out.append(self._get_note(cid))
            except TriliumWriteError:
                continue
        return out

    def _find_child(self, parent_id: str, title: str) -> dict | None:
        for c in self._children(parent_id):
            if (c.get("title") or "") == title:
                return c
        return None

    def _create_note(self, parent_id: str, title: str, note_type: str, content: str = "") -> dict:
        r = self.trilium.session.post(
            f"{self.trilium.url}/etapi/create-note",
            json={
                "parentNoteId": parent_id,
                "title": title,
                "type": note_type,
                "mime": "text/html",
                "content": content,
            },
            timeout=self.timeout,
        )
        if r.status_code >= 400:
            raise TriliumWriteError(f"create-note: HTTP {r.status_code}: {r.text[:300]}")
        return r.json()

    def _set_label(self, note_id: str, name: str, value: str = "", position: int = 0) -> None:
        r = self.trilium.session.post(
            f"{self.trilium.url}/etapi/attributes",
            json={
                "attributeId": uuid.uuid4().hex,
                "noteId": note_id,
                "type": "label",
                "name": name,
                "value": value,
                "isInheritable": False,
                "position": position,
            },
            timeout=self.timeout,
        )
        if r.status_code >= 400:
            raise TriliumWriteError(f"Label {name}: HTTP {r.status_code}: {r.text[:300]}")

    def _trigger_sync(self, note_id: str | None) -> None:
        """Stoessen einen Sync an: Einzel-Note (remember) oder Volllauf (forget)."""
        if not self.sync_admin_url:
            return
        try:
            requests.post(
                f"{self.sync_admin_url}/admin/sync",
                params={"note_id": note_id} if note_id else None,
                timeout=900,
            )
        except requests.RequestException as exc:
            # Nicht kritisch: der Sync-Zyklus (SYNC_INTERVAL) holt es nach.
            log.warning("Sync-Trigger fehlgeschlagen: %s", exc)

    # ---------- Öffentliche API ----------

    def remember(self, title: str, content: str, agent: str, topic: str | None = None) -> dict:
        """Legt eine Note unter Resources/Agent-Notizen/<agent>/ an."""
        require_readwrite()
        title = (title or "").strip()
        if not title:
            raise TriliumWriteError("Titel darf nicht leer sein")
        content = (content or "").strip()
        if not content:
            raise TriliumWriteError("Inhalt darf nicht leer sein")
        agent = _check_agent(agent)

        root = self._get_note("root")
        resources = self._find_child(root["noteId"], RESOURCES) or self._create_note(
            root["noteId"], RESOURCES, "branch"
        )
        agent_notizen = self._find_child(resources["noteId"], AGENT_NOTIZEN) or self._create_note(
            resources["noteId"], AGENT_NOTIZEN, "branch"
        )
        agent_dir = self._find_child(agent_notizen["noteId"], agent) or self._create_note(
            agent_notizen["noteId"], agent, "branch"
        )

        now = datetime.now(timezone.utc)
        full_title = f"{now:%Y-%m-%d %H:%M} – {title}"
        note = self._create_note(agent_dir["noteId"], full_title, "text", content)
        note_id = note["noteId"]

        self._set_label(note_id, "dateNote", now.isoformat(timespec="seconds"), position=0)
        self._set_label(note_id, "agentNote", "", position=1)
        self._set_label(note_id, "source", agent, position=2)
        if topic:
            self._set_label(note_id, "topic", topic.strip()[:200], position=3)

        self._trigger_sync(note_id)
        return {
            "note_id": note_id,
            "title": full_title,
            "path": f"{RESOURCES} > {AGENT_NOTIZEN} > {agent}",
            "message": "Note angelegt und Indexierung angestoßen.",
        }

    def forget(self, note_id: str) -> dict:
        """Loescht eine Note (nur in Agent-Notizen erlaubt)."""
        require_readwrite()
        note = self._get_note(note_id)
        path_titles: list[str] = []
        cur: dict | None = note
        seen: set[str] = set()
        while cur and cur["noteId"] not in seen:
            seen.add(cur["noteId"])
            path_titles.append(cur.get("title", ""))
            parent_ids = cur.get("parentNoteIds") or []
            if not parent_ids:
                break
            try:
                cur = self._get_note(parent_ids[0])
            except TriliumWriteError:
                break
        if AGENT_NOTIZEN not in path_titles:
            raise TriliumWriteError(
                "forget() ist nur fuer Notes unter Resources/Agent-Notizen/ erlaubt"
            )
        r = self.trilium.session.delete(
            f"{self.trilium.url}/etapi/notes/{note_id}", timeout=self.timeout
        )
        if r.status_code not in (200, 204) and r.status_code >= 400:
            raise TriliumWriteError(f"Delete: HTTP {r.status_code}: {r.text[:300]}")
        self._trigger_sync(None)
        return {"note_id": note_id, "message": "Note gelöscht; Index wird beim nächsten Sync entfernt."}
