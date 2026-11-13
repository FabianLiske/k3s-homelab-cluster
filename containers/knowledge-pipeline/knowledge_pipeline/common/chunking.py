"""Heading-orientierte Markdown-Chunkung (Design-Doku: ~600 Token/Chunk).

Chunker-Version wird in die Content-Hash einbezogen: Bei Algorithmus-
aenderung indexiert der Sync alle Notes neu.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

CHUNKER_VERSION = "v1"

# Zeichen-basierte Heuristik (~4 Zeichen pro Token bei Qwen3-Embedding-0.6B):
# 2600 Zeichen ~= 650 Token, gut unter der 8192-Token-TEI-Grenze.
MAX_CHUNK_CHARS = 2600
# Ueberlappung zwischen aufgeteilten Abschnitten, damit Saeetze an Grenzen
# nicht verloren gehen.
OVERLAP_CHARS = 300

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


@dataclass
class Chunk:
    index: int
    heading_path: str
    text: str


def split_sections(text: str) -> list[tuple[str, str]]:
    """Teilt Markdown in (Heading-Pfad, Body)-Sektionen auf.

    Heading-Pfad = aktuelle Titelkette aus "#" bis "######" (z.B.
    "Abschnitt > Unterpunkt"). Text ohne Headings ergibt eine Sektion mit
    leerem Pfad. Leere Sektionen werden verworfen.
    """
    out: list[tuple[str, str]] = []
    stack: list[tuple[int, str]] = []
    buf: list[str] = []

    def flush() -> None:
        body = "\n".join(buf).strip()
        if body:
            out.append((" > ".join(t for _, t in stack), body))
        buf.clear()

    for line in text.splitlines():
        m = _HEADING_RE.match(line)
        if m:
            flush()
            level = len(m.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, m.group(2).strip()))
        else:
            buf.append(line)
    flush()
    return out


def _split_long(body: str) -> list[str]:
    """Teilt ueberlaengige Sektionen an Absatzgrenzen (mit Ueberlappung)."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    pieces: list[str] = []
    cur = ""
    for para in paragraphs:
        if len(para) > MAX_CHUNK_CHARS:
            # Einzelner Riese-Absatz: harte Teilung.
            if cur:
                pieces.append(cur)
                cur = ""
            for i in range(0, len(para), MAX_CHUNK_CHARS):
                pieces.append(para[i : i + MAX_CHUNK_CHARS])
            continue
        if not cur:
            cur = para
        elif len(cur) + len(para) + 2 <= MAX_CHUNK_CHARS:
            cur = f"{cur}\n\n{para}"
        else:
            pieces.append(cur)
            cur = para
    if cur:
        pieces.append(cur)

    overlapped = [pieces[0]]
    for prev, nxt in zip(pieces, pieces[1:]):
        tail = prev[-OVERLAP_CHARS:]
        # Ueberlappung an Wortgrenze beginnen
        space = tail.find(" ")
        if space > 0:
            tail = tail[space + 1 :]
        overlapped.append(f"{tail}\n{nxt}")
    return overlapped


def chunk_note(note_title: str, path: str, text: str) -> list[Chunk]:
    """Erzeugt die Chunks fuer eine Note.

    Jeder Chunk beginnt mit einer Kontextzeile "<Title> — <Heading-Pfad>",
    damit auch Titel-/Pfad-Worte in Dichte und BM25 greifen.
    """
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        return []

    chunks: list[Chunk] = []
    for heading, body in split_sections(text):
        prefix = note_title or path
        if prefix and heading:
            prefix = f"{prefix} — {heading}"
        pieces = _split_long(body) if len(body) > MAX_CHUNK_CHARS else [body]
        for piece in pieces:
            chunk_text = f"{prefix}\n{piece}" if prefix else piece
            if not chunk_text.strip():
                continue
            chunks.append(Chunk(index=len(chunks), heading_path=heading, text=chunk_text))
    return chunks
