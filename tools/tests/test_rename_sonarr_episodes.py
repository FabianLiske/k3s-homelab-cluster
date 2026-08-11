#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "rename-sonarr-episodes.py"
SPEC = importlib.util.spec_from_file_location("sonarr_renamer", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
RENAMER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = RENAMER
SPEC.loader.exec_module(RENAMER)


class NormalizedNameTest(unittest.TestCase):
    def test_replaces_legacy_token_and_pads_season(self) -> None:
        self.assertEqual(
            RENAMER.normalized_name("Charlotte 1-12.mkv"),
            ("Charlotte S01E12.mkv", False),
        )

    def test_leaves_canonical_name_alone(self) -> None:
        self.assertEqual(
            RENAMER.normalized_name("Charlotte S01E12.mkv"),
            (None, False),
        )

    def test_leaves_iso_date_alone(self) -> None:
        self.assertEqual(
            RENAMER.normalized_name("Special 2024-01-01.mkv"),
            (None, False),
        )

    def test_marks_multiple_tokens_ambiguous(self) -> None:
        self.assertEqual(
            RENAMER.normalized_name("Show 1-01 and 2-02.mkv"),
            (None, True),
        )


class DirectoryPlanTest(unittest.TestCase):
    def test_groups_candidates_and_ignores_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            season = root / "Show" / "Season 1"
            season.mkdir(parents=True)
            (season / "Show 1-01.mkv").touch()
            (season / "Show 1-01.mkv.filepart").touch()
            (season / "Show S01E02.mkv").touch()

            plans = RENAMER.build_plans(root)

            self.assertEqual(len(plans), 1)
            self.assertEqual(len(plans[0].renames), 1)
            self.assertEqual(plans[0].renames[0].destination.name, "Show S01E01.mkv")
            self.assertFalse(plans[0].blocked)

    def test_blocks_existing_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Show 1-01.mkv").touch()
            (root / "Show S01E01.mkv").touch()

            plan = RENAMER.build_plans(root)[0]

            self.assertTrue(plan.blocked)
            self.assertIn("Ziel existiert bereits", plan.problems[0])

    def test_applies_a_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "Show 2-03.mkv"
            source.touch()
            plan = RENAMER.build_plans(root)[0]

            RENAMER.apply_plan(plan)

            self.assertFalse(source.exists())
            self.assertTrue((root / "Show S02E03.mkv").exists())

    def test_prints_one_old_to_new_line_per_episode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Show 1-01.mkv").touch()
            (root / "Show 1-02.mkv").touch()
            plan = RENAMER.build_plans(root)[0]
            output = io.StringIO()

            with redirect_stdout(output):
                RENAMER.print_plan(plan, root, 1, 1)

            lines = output.getvalue().splitlines()
            self.assertIn("Show 1-01.mkv  ->  Show S01E01.mkv", lines[3])
            self.assertIn("Show 1-02.mkv  ->  Show S01E02.mkv", lines[4])


if __name__ == "__main__":
    unittest.main()
