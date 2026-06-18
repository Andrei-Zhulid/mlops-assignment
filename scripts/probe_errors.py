"""Probe which agent requests 500, sequentially (no concurrency).

Fires unique perf_pool questions one at a time at /answer and prints the
exception detail for any non-200. Low concurrency isolates deterministic
failures (specific questions/schemas) from load-induced ones.

    uv run python scripts/probe_errors.py --n 60
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
POOL = ROOT / "load_test" / "perf_pool.jsonl"
URL = "http://localhost:8001/answer"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=60, help="number of unique questions to probe")
    args = ap.parse_args()

    seen: set[tuple[str, str]] = set()
    items = []
    for line in POOL.read_text().splitlines():
        if not line.strip():
            continue
        q = json.loads(line)
        key = (q["db_id"], q["question"])
        if key in seen:
            continue
        seen.add(key)
        items.append(q)
        if len(items) >= args.n:
            break

    fails: list[dict] = []
    by_db: Counter = Counter()
    with httpx.Client(timeout=120.0) as c:
        for i, q in enumerate(items, 1):
            try:
                r = c.post(URL, json={"question": q["question"], "db": q["db_id"]})
                if r.status_code != 200:
                    detail = r.json().get("detail", r.text)[:200] if r.headers.get("content-type", "").startswith("application/json") else r.text[:200]
                    fails.append({"db": q["db_id"], "code": r.status_code, "detail": detail, "q": q["question"][:60]})
                    by_db[q["db_id"]] += 1
                    print(f"[{i}] {r.status_code} db={q['db_id']} :: {detail}")
            except Exception as e:  # noqa: BLE001
                fails.append({"db": q["db_id"], "code": "exc", "detail": f"{type(e).__name__}: {e}", "q": q["question"][:60]})
                print(f"[{i}] EXC db={q['db_id']} :: {type(e).__name__}: {e}")

    print("\n" + "=" * 60)
    print(f"{len(fails)}/{len(items)} failed sequentially")
    if by_db:
        print("failures by db:", dict(by_db))
    print("distinct error prefixes:", Counter(f["detail"].split(":")[0] for f in fails))


if __name__ == "__main__":
    main()