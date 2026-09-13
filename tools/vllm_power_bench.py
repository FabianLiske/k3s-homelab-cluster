#!/usr/bin/env python3
"""Sweep GPU power limits against vLLM and compare throughput/latency.

Wraps the `vllm-bench` binary (see tools/install-vllm-bench.sh): for each
selected prompt-length profile it runs a concurrency sweep directly against
the vLLM pod (bypass LiteLLM via `kubectl port-forward`) and tags the result
JSON files with the power limit that was manually set on the node beforehand.
`--summary` then groups the accumulated result files by power limit,
scenario and concurrency and reports median throughput/latency, to help spot
the performance/power sweetspot.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BIN = REPO_ROOT / "tools" / ".bin" / "vllm-bench"
DEFAULT_RESULT_DIR = REPO_ROOT / "tools" / "vllm-power-bench-results"
DEFAULT_SUMMARY_CSV = REPO_ROOT / "tools" / "vllm-power-bench-summary.csv"

DEFAULT_MODEL = "local-chat"
DEFAULT_TOKENIZER = "Qwen/Qwen3.8-27B-FP8"

# Candidate JSON keys per logical metric. vllm-bench documents exact schema
# parity with Python's `vllm bench serve`, but if a future version renames a
# field, add the new name here rather than touching the summary logic below.
METRIC_KEYS: dict[str, list[str]] = {
    "output_tokens_per_s": ["output_throughput", "output_token_throughput"],
    "total_tokens_per_s": ["total_token_throughput"],
    "median_ttft_ms": ["median_ttft_ms"],
    "median_e2el_ms": ["median_e2el_ms"],
}


@dataclass(frozen=True)
class LengthProfile:
    name: str
    sonnet_input_len: int
    sonnet_output_len: int
    sonnet_prefix_len: int


def parse_concurrency_levels(value: str) -> list[int]:
    try:
        levels = [int(item.strip()) for item in value.split(",") if item.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("concurrency levels must be comma-separated integers") from exc
    if not levels or any(level <= 0 for level in levels):
        raise argparse.ArgumentTypeError("concurrency levels must contain positive integers")
    if len(levels) != len(set(levels)):
        raise argparse.ArgumentTypeError("concurrency levels must not contain duplicates")
    if levels != sorted(levels):
        raise argparse.ArgumentTypeError("concurrency levels must be in ascending order")
    return levels


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--power-limit",
        type=int,
        help="GPU power limit (watts) currently set on wk-5; only used as a "
        "result-tagging label, not enforced by this script. Required unless --summary.",
    )
    parser.add_argument("--summary", action="store_true", help="Aggregate existing results instead of running new ones")

    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="vLLM endpoint (default: kubectl port-forward target)")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--tokenizer", default=DEFAULT_TOKENIZER)
    parser.add_argument("--scenarios", nargs="+", choices=["short", "long"], default=["short", "long"])
    parser.add_argument(
        "--concurrency-levels",
        type=parse_concurrency_levels,
        default=[1, 2, 4, 8],
        help="Ascending comma-separated levels, run and validated separately (default: 1,2,4,8)",
    )
    parser.add_argument("--num-prompts-factor", type=int, default=5, help="num_prompts = concurrency * factor per sweep point")
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.0,
        help="Sampling temperature forwarded to vllm-bench (default: 0, deterministic greedy decoding)",
    )
    parser.add_argument(
        "--cooldown-seconds",
        type=float,
        default=30.0,
        help="Pause between successful measurement points (default: 30)",
    )
    parser.add_argument(
        "--health-timeout-seconds",
        type=int,
        default=10,
        help="Timeout for each pre/post-run /health check (default: 10)",
    )
    parser.add_argument(
        "--run-timeout-seconds",
        type=float,
        default=900.0,
        help="Maximum wall time for one measurement point (default: 900)",
    )

    parser.add_argument("--short-input-len", type=int, default=250)
    parser.add_argument("--short-output-len", type=int, default=64)
    parser.add_argument("--short-prefix-len", type=int, default=50)
    parser.add_argument("--long-input-len", type=int, default=3000)
    parser.add_argument("--long-output-len", type=int, default=512)
    parser.add_argument("--long-prefix-len", type=int, default=200)

    parser.add_argument("--vllm-bench-bin", type=Path, default=DEFAULT_BIN)
    parser.add_argument("--result-dir", type=Path, default=DEFAULT_RESULT_DIR)
    parser.add_argument("--summary-csv", type=Path, default=DEFAULT_SUMMARY_CSV)
    parser.add_argument("--dry-run", action="store_true", help="Forwarded to vllm-bench: generate prompts, send nothing")

    args = parser.parse_args(argv)
    if not args.summary and args.power_limit is None:
        parser.error("--power-limit is required unless --summary is set")
    if args.num_prompts_factor <= 0:
        parser.error("--num-prompts-factor must be positive")
    if args.warmups < 0:
        parser.error("--warmups must not be negative")
    if args.temperature < 0:
        parser.error("--temperature must not be negative")
    if args.cooldown_seconds < 0:
        parser.error("--cooldown-seconds must not be negative")
    if args.health_timeout_seconds <= 0:
        parser.error("--health-timeout-seconds must be positive")
    if args.run_timeout_seconds <= 0:
        parser.error("--run-timeout-seconds must be positive")
    return args


def length_profiles(args: argparse.Namespace) -> dict[str, LengthProfile]:
    return {
        "short": LengthProfile("short", args.short_input_len, args.short_output_len, args.short_prefix_len),
        "long": LengthProfile("long", args.long_input_len, args.long_output_len, args.long_prefix_len),
    }


def build_command(
    args: argparse.Namespace,
    profile: LengthProfile,
    concurrency: int,
    result_dir: Path | None = None,
) -> list[str]:
    output_dir = result_dir or args.result_dir
    command = [
        str(args.vllm_bench_bin),
        "--backend", "openai-chat",
        "--base-url", args.base_url,
        "--model", args.model,
        "--tokenizer", args.tokenizer,
        "--trust-remote-code",
        "--dataset-name", "sonnet",
        "--sonnet-input-len", str(profile.sonnet_input_len),
        "--sonnet-output-len", str(profile.sonnet_output_len),
        "--sonnet-prefix-len", str(profile.sonnet_prefix_len),
        "--max-concurrency", str(concurrency),
        "--num-prompts", str(concurrency * args.num_prompts_factor),
        "--num-warmups", str(args.warmups),
        "--temperature", str(args.temperature),
        "--metadata",
        f"power_limit_watts={args.power_limit}",
        f"scenario={profile.name}",
        f"client_concurrency={concurrency}",
        "--label", f"pl{args.power_limit}-{profile.name}",
        "--save-result",
        "--save-detailed",
        "--result-dir", str(output_dir),
        "--ready-check-timeout-sec", str(args.health_timeout_seconds),
    ]
    if args.dry_run:
        command.append("--dry-run")
    return command


def endpoint_health(base_url: str, timeout_seconds: float) -> tuple[bool, str]:
    health_url = f"{base_url.rstrip('/')}/health"
    try:
        with urllib.request.urlopen(health_url, timeout=timeout_seconds) as response:
            if 200 <= response.status < 300:
                return True, f"HTTP {response.status}"
            return False, f"HTTP {response.status}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return False, str(exc)


def result_validation_errors(data: Any) -> list[str]:
    entries = data if isinstance(data, list) else [data]
    if not entries or not all(isinstance(entry, dict) for entry in entries):
        return ["result JSON must contain an object or a non-empty list of objects"]

    errors = []
    for index, entry in enumerate(entries):
        prefix = f"entry {index}: " if len(entries) > 1 else ""
        try:
            completed = int(entry["completed"])
            failed = int(entry["failed"])
            expected = int(entry["num_prompts"])
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"{prefix}missing or invalid completion counters ({exc})")
            continue
        if failed:
            errors.append(f"{prefix}{failed} of {expected} requests failed")
        if completed != expected:
            errors.append(f"{prefix}only {completed} of {expected} requests completed")
    return errors


def unique_destination(directory: Path, filename: str) -> Path:
    destination = directory / filename
    counter = 2
    while destination.exists():
        destination = directory / f"{Path(filename).stem}-{counter}{Path(filename).suffix}"
        counter += 1
    return destination


def preserve_results(source_dir: Path, destination_dir: Path) -> list[Path]:
    destination_dir.mkdir(parents=True, exist_ok=True)
    preserved = []
    for source in sorted(source_dir.glob("*.json")):
        destination = unique_destination(destination_dir, source.name)
        shutil.move(str(source), destination)
        preserved.append(destination)
    return preserved


def run_measurement(args: argparse.Namespace, profile: LengthProfile, concurrency: int) -> bool:
    if args.dry_run:
        command = build_command(args, profile, concurrency)
        print(f"==> DRY RUN {profile.name}/C{concurrency}: {' '.join(command)}", flush=True)
        return subprocess.run(command, check=False).returncode == 0

    healthy, detail = endpoint_health(args.base_url, args.health_timeout_seconds)
    if not healthy:
        print(f"ABORT: vLLM is not healthy before {profile.name}/C{concurrency}: {detail}", file=sys.stderr)
        return False

    started_at = dt.datetime.now(dt.UTC)
    print(
        f"==> {profile.name}/C{concurrency}: power-limit label={args.power_limit} W, "
        f"temperature={args.temperature}, health={detail}",
        flush=True,
    )

    with tempfile.TemporaryDirectory(prefix=".vllm-power-bench-", dir=args.result_dir) as temporary:
        temporary_dir = Path(temporary)
        command = build_command(args, profile, concurrency, temporary_dir)
        print(f"    {' '.join(command)}", flush=True)
        process_error = None
        try:
            completed_process = subprocess.run(command, check=False, timeout=args.run_timeout_seconds)
            if completed_process.returncode:
                process_error = f"vllm-bench exited with status {completed_process.returncode}"
        except subprocess.TimeoutExpired:
            process_error = f"vllm-bench exceeded {args.run_timeout_seconds:g} seconds"

        result_files = sorted(temporary_dir.glob("*.json"))
        validation_errors = []
        if not result_files:
            validation_errors.append("vllm-bench produced no result JSON")
        for path in result_files:
            try:
                with path.open() as handle:
                    data = json.load(handle)
            except (OSError, json.JSONDecodeError) as exc:
                validation_errors.append(f"{path.name}: unreadable result JSON ({exc})")
                continue
            validation_errors.extend(f"{path.name}: {error}" for error in result_validation_errors(data))

        healthy_after, health_detail = endpoint_health(args.base_url, args.health_timeout_seconds)
        if not healthy_after:
            validation_errors.append(f"vLLM is not healthy after the run: {health_detail}")

        failed = process_error is not None or bool(validation_errors)
        destination_dir = args.result_dir / "failed" if failed else args.result_dir
        preserved = preserve_results(temporary_dir, destination_dir)

    ended_at = dt.datetime.now(dt.UTC)
    if failed:
        if process_error:
            print(f"ABORT: {process_error}", file=sys.stderr)
        for error in validation_errors:
            print(f"ABORT: {error}", file=sys.stderr)
        if preserved:
            print(f"failed result preserved under {destination_dir}", file=sys.stderr)
        return False

    elapsed = (ended_at - started_at).total_seconds()
    print(f"    PASS: {len(preserved)} result file(s), vLLM health={health_detail}, elapsed={elapsed:.1f}s")
    return True


def run_scenarios(args: argparse.Namespace) -> int:
    if not args.vllm_bench_bin.exists():
        print(f"vllm-bench binary not found at {args.vllm_bench_bin} - run tools/install-vllm-bench.sh first", file=sys.stderr)
        return 1

    args.result_dir.mkdir(parents=True, exist_ok=True)
    profiles = length_profiles(args)
    measurements = [(profiles[name], concurrency) for name in args.scenarios for concurrency in args.concurrency_levels]
    for index, (profile, concurrency) in enumerate(measurements):
        if not run_measurement(args, profile, concurrency):
            return 2
        if index < len(measurements) - 1 and args.cooldown_seconds and not args.dry_run:
            print(f"    cooldown: {args.cooldown_seconds:g}s")
            time.sleep(args.cooldown_seconds)
    return 0


def first_present(data: dict[str, Any], keys: list[str]) -> float | None:
    for key in keys:
        if key in data and data[key] is not None:
            return float(data[key])
    return None


def load_results(result_dir: Path) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(result_dir.glob("*.json")):
        try:
            with path.open() as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"skipping {path.name}: unreadable result JSON ({exc})", file=sys.stderr)
            continue
        entries = data if isinstance(data, list) else [data]
        for entry in entries:
            if not isinstance(entry, dict):
                print(f"skipping {path.name}: result entry is not an object", file=sys.stderr)
                continue
            # --metadata KEY=VALUE lands as top-level fields in the result JSON,
            # not nested under a "metadata" key.
            try:
                power_limit_watts = int(entry["power_limit_watts"])
                scenario = entry["scenario"]
            except (KeyError, TypeError, ValueError):
                print(f"skipping {path.name}: missing or invalid power_limit_watts/scenario metadata", file=sys.stderr)
                continue
            validation_errors = result_validation_errors(entry)
            if validation_errors:
                print(f"skipping {path.name}: {'; '.join(validation_errors)}", file=sys.stderr)
                continue
            rows.append(
                {
                    "power_limit_watts": power_limit_watts,
                    "scenario": scenario,
                    "concurrency": entry.get("max_concurrency"),
                    "num_prompts": entry.get("num_prompts"),
                    "output_tokens_per_s": first_present(entry, METRIC_KEYS["output_tokens_per_s"]),
                    "total_tokens_per_s": first_present(entry, METRIC_KEYS["total_tokens_per_s"]),
                    "median_ttft_ms": first_present(entry, METRIC_KEYS["median_ttft_ms"]),
                    "median_e2el_ms": first_present(entry, METRIC_KEYS["median_e2el_ms"]),
                    "source_file": path.name,
                }
            )
    return rows


def group_key(row: dict[str, Any]) -> tuple[int, str, Any, Any]:
    return (row["power_limit_watts"], row["scenario"], row["concurrency"], row["num_prompts"])


def summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[int, str, Any, Any], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(group_key(row), []).append(row)

    summary = []
    for (power_limit_watts, scenario, concurrency, num_prompts), group_rows in sorted(groups.items()):
        metrics = ["output_tokens_per_s", "total_tokens_per_s", "median_ttft_ms", "median_e2el_ms"]
        entry = {
            "power_limit_watts": power_limit_watts,
            "scenario": scenario,
            "concurrency": concurrency,
            "num_prompts": num_prompts,
            "num_runs": len(group_rows),
        }
        for metric in metrics:
            values = [row[metric] for row in group_rows if row[metric] is not None]
            entry[f"median_{metric}"] = statistics.median(values) if values else None
        summary.append(entry)
    return summary


def write_summary_csv(summary: list[dict[str, Any]], path: Path) -> None:
    fieldnames = [
        "power_limit_watts",
        "scenario",
        "concurrency",
        "num_prompts",
        "num_runs",
        "median_output_tokens_per_s",
        "median_total_tokens_per_s",
        "median_median_ttft_ms",
        "median_median_e2el_ms",
    ]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(summary)


def print_summary(summary: list[dict[str, Any]]) -> None:
    header = f"{'power_limit_watts':>18}  {'scenario':<10}  {'concurrency':>11}  {'prompts':>7}  {'tok/s':>10}  {'ttft_ms':>10}  {'e2el_ms':>10}  runs"
    print(header)
    for entry in summary:
        output_tokens = entry["median_output_tokens_per_s"]
        ttft = entry["median_median_ttft_ms"]
        e2el = entry["median_median_e2el_ms"]
        print(
            f"{entry['power_limit_watts']:>18}  {entry['scenario']:<10}  {str(entry['concurrency']):>11}  "
            f"{str(entry['num_prompts']):>7}  "
            f"{output_tokens if output_tokens is not None else float('nan'):>10.1f}  "
            f"{ttft if ttft is not None else float('nan'):>10.1f}  "
            f"{e2el if e2el is not None else float('nan'):>10.1f}  "
            f"{entry['num_runs']}"
        )


def run_summary(args: argparse.Namespace) -> int:
    rows = load_results(args.result_dir)
    if not rows:
        print(f"no result files with power_limit_watts/scenario metadata found in {args.result_dir}", file=sys.stderr)
        return 1
    summary = summarize(rows)
    write_summary_csv(summary, args.summary_csv)
    print_summary(summary)
    print(f"\nwrote {args.summary_csv}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.summary:
        return run_summary(args)
    return run_scenarios(args)


if __name__ == "__main__":
    raise SystemExit(main())
