#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1]))

import vllm_power_bench as bench  # noqa: E402


def make_result(
    *,
    power_limit_watts: int,
    scenario: str,
    concurrency: int,
    output_tokens_per_s: float,
    median_ttft_ms: float,
    completed: int = 5,
    failed: int = 0,
    num_prompts: int = 5,
) -> dict:
    # --metadata KEY=VALUE lands as flat top-level string fields in the real
    # vllm-bench result JSON, not nested under a "metadata" key - confirmed
    # against a live run against the vLLM pod.
    return {
        "power_limit_watts": str(power_limit_watts),
        "scenario": scenario,
        "max_concurrency": concurrency,
        "completed": completed,
        "failed": failed,
        "num_prompts": num_prompts,
        "output_throughput": output_tokens_per_s,
        "total_token_throughput": output_tokens_per_s * 1.2,
        "median_ttft_ms": median_ttft_ms,
        "median_e2el_ms": median_ttft_ms * 10,
    }


class BuildCommandTest(unittest.TestCase):
    def test_includes_metadata_and_lengths(self) -> None:
        args = bench.parse_args(["--power-limit", "150", "--scenarios", "short"])
        profile = bench.length_profiles(args)["short"]
        command = bench.build_command(args, profile, 1)

        self.assertIn("--metadata", command)
        idx = command.index("--metadata")
        self.assertEqual(command[idx + 1 : idx + 3], ["power_limit_watts=150", "scenario=short"])
        self.assertIn("--sonnet-input-len", command)
        self.assertIn(str(profile.sonnet_input_len), command)
        self.assertNotIn("--sweep-max-concurrency", command)
        self.assertIn("--max-concurrency", command)
        self.assertEqual(command[command.index("--max-concurrency") + 1], "1")
        self.assertEqual(command[command.index("--num-prompts") + 1], "5")
        self.assertEqual(command[command.index("--temperature") + 1], "0.0")

    def test_dry_run_flag_forwarded(self) -> None:
        args = bench.parse_args(["--power-limit", "150", "--dry-run"])
        profile = bench.length_profiles(args)["short"]
        command = bench.build_command(args, profile, 1)
        self.assertIn("--dry-run", command)


class ParseArgsTest(unittest.TestCase):
    def test_power_limit_required_unless_summary(self) -> None:
        with self.assertRaises(SystemExit):
            bench.parse_args([])

        args = bench.parse_args(["--summary"])
        self.assertIsNone(args.power_limit)

    def test_default_concurrency_ramp_is_gradual(self) -> None:
        args = bench.parse_args(["--power-limit", "160"])
        self.assertEqual(args.concurrency_levels, [1, 2, 4, 8])

    def test_concurrency_levels_must_be_positive_unique_and_ascending(self) -> None:
        self.assertEqual(bench.parse_concurrency_levels("1,2,8"), [1, 2, 8])
        for invalid in ("", "0,1", "1,1", "4,2"):
            with self.subTest(invalid=invalid), self.assertRaises(bench.argparse.ArgumentTypeError):
                bench.parse_concurrency_levels(invalid)


class SummaryTest(unittest.TestCase):
    def test_groups_by_power_limit_scenario_and_concurrency(self) -> None:
        import tempfile

        raw = [
            make_result(power_limit_watts=150, scenario="short", concurrency=1, output_tokens_per_s=10.0, median_ttft_ms=50.0),
            make_result(power_limit_watts=150, scenario="short", concurrency=1, output_tokens_per_s=12.0, median_ttft_ms=60.0),
            make_result(power_limit_watts=200, scenario="short", concurrency=1, output_tokens_per_s=20.0, median_ttft_ms=30.0),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            result_dir = Path(tmp)
            for i, entry in enumerate(raw):
                (result_dir / f"run{i}.json").write_text(json.dumps(entry))
            loaded_rows = bench.load_results(result_dir)

        summary = bench.summarize(loaded_rows)
        self.assertEqual(len(summary), 2)

        group_150 = next(row for row in summary if row["power_limit_watts"] == 150)
        self.assertEqual(group_150["num_runs"], 2)
        self.assertEqual(group_150["median_output_tokens_per_s"], 11.0)

        group_200 = next(row for row in summary if row["power_limit_watts"] == 200)
        self.assertEqual(group_200["num_runs"], 1)
        self.assertEqual(group_200["median_output_tokens_per_s"], 20.0)

    def test_different_prompt_counts_are_not_aggregated(self) -> None:
        rows = [
            {
                "power_limit_watts": 200,
                "scenario": "short",
                "concurrency": 1,
                "num_prompts": prompts,
                "output_tokens_per_s": throughput,
                "total_tokens_per_s": throughput,
                "median_ttft_ms": 1.0,
                "median_e2el_ms": 1.0,
            }
            for prompts, throughput in ((1, 8.0), (5, 20.0))
        ]

        summary = bench.summarize(rows)

        self.assertEqual(len(summary), 2)

    def test_load_results_skips_files_without_metadata(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            result_dir = Path(tmp)
            (result_dir / "good.json").write_text(
                json.dumps(make_result(power_limit_watts=150, scenario="short", concurrency=1, output_tokens_per_s=10.0, median_ttft_ms=50.0))
            )
            (result_dir / "bad.json").write_text(json.dumps({"max_concurrency": 1}))

            rows = bench.load_results(result_dir)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["power_limit_watts"], 150)

    def test_load_results_skips_failed_and_partial_runs(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            result_dir = Path(tmp)
            failed = make_result(
                power_limit_watts=160,
                scenario="short",
                concurrency=8,
                output_tokens_per_s=4.8,
                median_ttft_ms=1200,
                completed=4,
                failed=1,
            )
            partial = make_result(
                power_limit_watts=200,
                scenario="long",
                concurrency=8,
                output_tokens_per_s=27.1,
                median_ttft_ms=7900,
                completed=4,
                failed=0,
            )
            (result_dir / "failed.json").write_text(json.dumps(failed))
            (result_dir / "partial.json").write_text(json.dumps(partial))

            self.assertEqual(bench.load_results(result_dir), [])


class RunMeasurementTest(unittest.TestCase):
    def test_failed_requests_abort_and_are_preserved_separately(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            result_dir = Path(tmp)
            args = bench.parse_args(
                [
                    "--power-limit",
                    "160",
                    "--scenarios",
                    "short",
                    "--result-dir",
                    str(result_dir),
                    "--cooldown-seconds",
                    "0",
                ]
            )
            profile = bench.length_profiles(args)["short"]

            def fake_run(command: list[str], **_: object) -> SimpleNamespace:
                output_dir = Path(command[command.index("--result-dir") + 1])
                result = make_result(
                    power_limit_watts=160,
                    scenario="short",
                    concurrency=8,
                    output_tokens_per_s=4.8,
                    median_ttft_ms=1200,
                    completed=4,
                    failed=1,
                )
                (output_dir / "failed-run.json").write_text(json.dumps(result))
                return SimpleNamespace(returncode=0)

            with (
                mock.patch.object(bench, "endpoint_health", side_effect=[(True, "HTTP 200"), (True, "HTTP 200")]),
                mock.patch.object(bench.subprocess, "run", side_effect=fake_run),
            ):
                self.assertFalse(bench.run_measurement(args, profile, 8))

            self.assertTrue((result_dir / "failed" / "failed-run.json").exists())
            self.assertEqual(list(result_dir.glob("*.json")), [])


if __name__ == "__main__":
    unittest.main()
