#!/usr/bin/env python3
"""Interactively normalize legacy Sonarr episode names.

The script replaces one unambiguous ``X-YY`` token in a video filename with
``SXXEYY``. It groups proposals by the directory containing the files and, in
apply mode, asks for one confirmation per directory. It never overwrites an
existing path.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, TextIO


VIDEO_EXTENSIONS = {
    ".avi",
    ".m2ts",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".ts",
    ".webm",
    ".wmv",
}

# Do not match tokens embedded in words, longer numbers, or date-like chains.
# In particular, canonical names such as S01E02 and ISO dates are left alone.
LEGACY_TOKEN = re.compile(
    r"(?<!\d{4}-)(?<!\d{2}-)(?<![A-Za-z0-9])"
    r"(?P<season>\d{1,2})-(?P<episode>\d{2})(?!\d)(?!-\d{2}(?!\d))"
)


@dataclass(frozen=True)
class Rename:
    source: Path
    destination: Path


@dataclass
class DirectoryPlan:
    directory: Path
    renames: list[Rename]
    ambiguous: list[Path]
    problems: list[str]

    @property
    def blocked(self) -> bool:
        return bool(self.ambiguous or self.problems)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Replace legacy X-YY episode tokens with SXXEYY, grouped by "
            "directory and guarded by collision checks."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  # Read-only preview
  %(prog)s --root /mnt/media/shows

  # Interactive rename with one confirmation per directory
  %(prog)s --root /mnt/media/shows --apply \\
    --log ./sonarr-rename.jsonl
""",
    )
    parser.add_argument("--root", required=True, type=Path, help="Series library root")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Interactively apply proposals; without this option only scan",
    )
    parser.add_argument(
        "--log",
        type=Path,
        help="Append-only JSONL audit log (required with --apply)",
    )
    return parser.parse_args()


def normalized_name(name: str) -> tuple[str | None, bool]:
    """Return (new name, ambiguous) for a video filename."""
    matches = list(LEGACY_TOKEN.finditer(name))
    if not matches:
        return None, False
    if len(matches) != 1:
        return None, True

    match = matches[0]
    replacement = f"S{int(match.group('season')):02d}E{int(match.group('episode')):02d}"
    return f"{name[:match.start()]}{replacement}{name[match.end():]}", False


def iter_video_files(root: Path) -> Iterable[Path]:
    for current, directories, files in os.walk(root):
        directories.sort(key=str.casefold)
        for filename in sorted(files, key=str.casefold):
            path = Path(current, filename)
            if path.suffix.lower() in VIDEO_EXTENSIONS and not path.is_symlink():
                yield path


def build_plans(root: Path) -> list[DirectoryPlan]:
    by_directory: dict[Path, DirectoryPlan] = {}

    for source in iter_video_files(root):
        new_name, ambiguous = normalized_name(source.name)
        if new_name is None and not ambiguous:
            continue

        plan = by_directory.setdefault(
            source.parent,
            DirectoryPlan(source.parent, [], [], []),
        )
        if ambiguous:
            plan.ambiguous.append(source)
        else:
            plan.renames.append(Rename(source, source.with_name(new_name)))

    for plan in by_directory.values():
        destinations: dict[Path, list[Path]] = {}
        sources = {rename.source for rename in plan.renames}
        for rename in plan.renames:
            destinations.setdefault(rename.destination, []).append(rename.source)

        for destination, source_paths in destinations.items():
            if len(source_paths) > 1:
                joined = ", ".join(path.name for path in source_paths)
                plan.problems.append(
                    f"Mehrere Quellen würden zu {destination.name!r}: {joined}"
                )
            if destination.exists() and destination not in sources:
                plan.problems.append(f"Ziel existiert bereits: {destination.name}")

        plan.renames.sort(key=lambda item: item.source.name.casefold())
        plan.ambiguous.sort(key=lambda path: path.name.casefold())

    return sorted(by_directory.values(), key=lambda item: str(item.directory).casefold())


def relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)) or "."
    except ValueError:
        return str(path)


def print_plan(plan: DirectoryPlan, root: Path, number: int, total: int) -> None:
    print()
    print(f"[{number}/{total}] {relative(plan.directory, root)}")
    for rename in plan.renames:
        print(f"  ALT: {rename.source.name}")
        print(f"  NEU: {rename.destination.name}")
    for path in plan.ambiguous:
        print(f"  BLOCKIERT (mehrdeutig): {path.name}")
    for problem in plan.problems:
        print(f"  BLOCKIERT: {problem}")


def log_event(handle: TextIO, root: Path, plan: DirectoryPlan, status: str, **extra: object) -> None:
    event: dict[str, object] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "root": str(root),
        "directory": str(plan.directory),
        "renames": [
            {"source": rename.source.name, "destination": rename.destination.name}
            for rename in plan.renames
        ],
        "ambiguous": [path.name for path in plan.ambiguous],
        "problems": plan.problems,
    }
    event.update(extra)
    handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    handle.flush()
    os.fsync(handle.fileno())


def apply_plan(plan: DirectoryPlan) -> None:
    # Recheck immediately before writing. Sonarr and Jellyfin should still be
    # stopped, but this also protects against changes after the initial scan.
    for rename in plan.renames:
        if not rename.source.is_file():
            raise RuntimeError(f"Quelle fehlt: {rename.source.name}")
        if rename.destination.exists():
            raise RuntimeError(f"Ziel existiert inzwischen: {rename.destination.name}")

    completed: list[Rename] = []
    try:
        for rename in plan.renames:
            rename.source.rename(rename.destination)
            completed.append(rename)
    except Exception as error:
        rollback_errors: list[str] = []
        for rename in reversed(completed):
            try:
                rename.destination.rename(rename.source)
            except Exception as rollback_error:  # pragma: no cover - emergency path
                rollback_errors.append(
                    f"{rename.destination.name} -> {rename.source.name}: {rollback_error}"
                )
        if rollback_errors:
            raise RuntimeError(
                f"Umbenennen fehlgeschlagen ({error}); Rollback unvollständig: "
                + "; ".join(rollback_errors)
            ) from error
        raise RuntimeError(f"Umbenennen fehlgeschlagen; Rollback erfolgreich: {error}") from error


def prompt_for_directory() -> str:
    while True:
        try:
            answer = input("Ordner umbenennen? [j]a / [n]ein / [q]uit: ").strip().lower()
        except EOFError:
            return "q"
        if answer in {"j", "ja", "y", "yes"}:
            return "yes"
        if answer in {"", "n", "nein", "no"}:
            return "no"
        if answer in {"q", "quit", "ende"}:
            return "quit"
        print("Bitte j, n oder q eingeben.")


def main() -> int:
    args = parse_args()
    root = args.root.resolve()

    if not root.is_dir():
        print(f"Fehler: Root-Verzeichnis nicht gefunden: {root}", file=sys.stderr)
        return 2
    if args.apply and args.log is None:
        print("Fehler: --log ist zusammen mit --apply erforderlich.", file=sys.stderr)
        return 2
    if args.apply and not sys.stdin.isatty():
        print("Fehler: --apply benötigt ein interaktives Terminal (TTY).", file=sys.stderr)
        return 2

    plans = build_plans(root)
    candidate_count = sum(len(plan.renames) for plan in plans)
    blocked_count = sum(1 for plan in plans if plan.blocked)
    actionable_count = len(plans) - blocked_count

    print(f"Root: {root}")
    print(f"Treffer: {candidate_count} Dateien in {len(plans)} Ordnern")
    print(f"Ausführbar: {actionable_count} Ordner; blockiert: {blocked_count} Ordner")

    if not plans:
        print("Keine X-YY-Dateinamen gefunden.")
        return 0

    if not args.apply:
        for number, plan in enumerate(plans, start=1):
            print_plan(plan, root, number, len(plans))
        print()
        print("Vorschau beendet; es wurde nichts verändert.")
        return 1 if blocked_count else 0

    assert args.log is not None
    log_path = args.log.resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    applied_folders = 0
    applied_files = 0
    skipped_folders = 0
    failed_folders = 0

    with log_path.open("a", encoding="utf-8") as log_handle:
        for number, plan in enumerate(plans, start=1):
            print_plan(plan, root, number, len(plans))
            if plan.blocked:
                print("  Dieser Ordner wird wegen der obigen Prüfung nicht angeboten.")
                log_event(log_handle, root, plan, "blocked")
                failed_folders += 1
                continue

            answer = prompt_for_directory()
            if answer == "quit":
                log_event(log_handle, root, plan, "quit")
                print("Abgebrochen. Ein erneuter Lauf setzt bei den übrigen X-YY-Namen fort.")
                break
            if answer == "no":
                log_event(log_handle, root, plan, "skipped")
                skipped_folders += 1
                continue

            log_event(log_handle, root, plan, "approved")
            try:
                apply_plan(plan)
            except Exception as error:
                print(f"  FEHLER: {error}", file=sys.stderr)
                log_event(log_handle, root, plan, "failed", error=str(error))
                failed_folders += 1
                continue

            log_event(log_handle, root, plan, "applied")
            applied_folders += 1
            applied_files += len(plan.renames)
            print(f"  OK: {len(plan.renames)} Dateien umbenannt.")

    print()
    print(
        "Ergebnis: "
        f"{applied_files} Dateien in {applied_folders} Ordnern umbenannt; "
        f"{skipped_folders} übersprungen; {failed_folders} blockiert/fehlgeschlagen."
    )
    print(f"Protokoll: {log_path}")
    return 1 if failed_folders else 0


if __name__ == "__main__":
    raise SystemExit(main())
