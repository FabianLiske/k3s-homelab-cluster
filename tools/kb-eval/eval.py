#!/usr/bin/env python3
"""Golden-Set-Evaluation fuer den knowledge-service /search-Endpunkt.

Beispiel:
    export KB_TOKEN=<read-only key>
    python3 eval.py --base-url http://127.0.0.1:8000

Metriken: Recall@5, Recall@top_k (Standard 8), MRR.
Exit 0, wenn Recall@top_k >= --min-recall8 (Default 0.8).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def search(base_url: str, token: str, query: str, top_k: int) -> list[dict]:
    payload = json.dumps({"query": query, "top_k": top_k}).encode()
    req = urllib.request.Request(
        base_url.rstrip("/") + "/search",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)["results"]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--base-url",
        default="http://knowledge-service.svc-rag.svc.cluster.local:80",
    )
    p.add_argument("--token", default=os.environ.get("KB_TOKEN"))
    p.add_argument(
        "--golden",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden_set.json"),
    )
    p.add_argument("--top-k", type=int, default=8)
    p.add_argument("--min-recall8", type=float, default=0.8)
    args = p.parse_args()

    if not args.token:
        sys.exit("Token erforderlich: --token oder Umgebungsvariable KB_TOKEN")
    top_k = max(args.top_k, 8)

    golden = json.load(open(args.golden, encoding="utf-8"))
    hit5 = hitk = 0
    ranks: list[int] = []
    failures: list[dict] = []

    for item in golden:
        try:
            results = search(args.base_url, args.token, item["query"], top_k)
        except urllib.error.HTTPError as e:
            body = e.read()[:200].decode("utf-8", "replace")
            print(f"[--] {item['query']}: HTTP {e.code} {body}")
            failures.append(item)
            continue
        except Exception as e:  # noqa: BLE001
            print(f"[--] {item['query']}: {type(e).__name__}: {e}")
            failures.append(item)
            continue

        ids = [r.get("note_id") for r in results]
        rank = next((i for i, nid in enumerate(ids, 1) if nid in item["expected_note_ids"]), None)
        top_title = results[0].get("title", "?")[:50] if results else "-"
        mark = f"#{rank:<2}" if rank else "-- "
        print(f"{mark} {item['query'][:62]:<62} top={top_title}")
        if rank:
            ranks.append(rank)
            hitk += 1
            if rank <= 5:
                hit5 += 1
        else:
            failures.append(item)

    n = len(golden)
    recall5 = hit5 / n
    recallk = hitk / n
    mrr = sum(1.0 / r for r in ranks) / n if n else 0.0

    print()
    print(f"Recall@5   = {recall5:.2%} ({hit5}/{n})")
    print(f"Recall@{top_k:<3}  = {recallk:.2%} ({hitk}/{n})")
    print(f"MRR        = {mrr:.3f}")
    if failures:
        print("\nNicht erwischt:")
        for item in failures:
            print(f"  - {item['query']}  (erwartet: {item.get('note_title', item['expected_note_ids'])})")
    ok = recallk >= args.min_recall8
    print(f"\nErgebnis: {'OK' if ok else 'NICHT OK'} (Schwelle Recall@{top_k} >= {args.min_recall8:.0%})")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
