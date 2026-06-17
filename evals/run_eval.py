"""Eval runner using execution accuracy.

Reads evals/eval_set.jsonl, calls the agent at AGENT_URL on each question,
then compares the agent's SQL output to the gold SQL by *executed rows*
(canonicalized: sorted, stringified, None-coerced to empty).

Helpers (run_sql / canonicalize / matches) are provided. You implement
eval_one() and summarize().

Run:
    uv run python evals/run_eval.py --out results/eval_baseline.json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EVAL_FILE = ROOT / "evals" / "eval_set.jsonl"
DEFAULT_OUT_FILE = ROOT / "results" / "eval_baseline.json"
DB_DIR = ROOT / "data" / "bird"
AGENT_URL_DEFAULT = "http://localhost:8001/answer"


# ---------- Helpers (provided) -----------------------------------------

def run_sql(db_id: str, sql: str, timeout: float = 5.0) -> tuple[bool, list[tuple] | None, str | None]:
    """Run sql against db_id in read-only mode. Returns (ok, rows, error)."""
    path = DB_DIR / f"{db_id}.sqlite"
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=timeout) as conn:
            cur = conn.execute(sql)
            rows = cur.fetchall()
            return True, rows, None
    except Exception as e:  # noqa: BLE001
        return False, None, f"{type(e).__name__}: {e}"


def canonicalize(rows: list[tuple] | None) -> list[tuple] | None:
    """Sort rows; coerce cells to str; None -> ''."""
    if rows is None:
        return None
    return sorted(tuple("" if c is None else str(c) for c in row) for row in rows)


def matches(gold_rows: list[tuple] | None, pred_rows: list[tuple] | None) -> bool:
    if gold_rows is None or pred_rows is None:
        return False
    return canonicalize(gold_rows) == canonicalize(pred_rows)


# ---------- Implement these (Phase 5) ----------------------------------

def _candidate_steps(history: list[dict]) -> list[dict]:
    """The SQL the agent produced at each iteration, in order.

    generate_sql -> iter 0, each revise -> iter 1, 2, ... Both node types
    carry an "sql" field in the agent's history (see agent/graph.py).
    """
    return [s for s in history if s.get("node") in ("generate_sql", "revise")]


def eval_one(question: dict, agent_url: str) -> dict:
    """Score one question by execution accuracy, per agent iteration.

    Calls the agent over HTTP, then re-runs the SQL it emitted at each
    iteration against the target DB and compares the canonicalized row set
    to the gold query's. The last candidate is the agent's final answer.
    """
    db_id = question["db_id"]
    gold_sql = question["gold_sql"]
    gold_ok, gold_rows, gold_err = run_sql(db_id, gold_sql)

    base = {
        "question": question["question"],
        "db_id": db_id,
        "gold_sql": gold_sql,
        "gold_exec_ok": gold_ok,
        "gold_error": gold_err,
    }

    t0 = time.monotonic()
    try:
        resp = httpx.post(
            agent_url,
            json={
                "question": question["question"],
                "db": db_id,
                # Tag so the eval batch is filterable in Langfuse (Phase 6).
                "tags": {"phase": "eval", "db": db_id},
            },
            timeout=180.0,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:  # noqa: BLE001
        return {
            **base,
            "final_sql": "",
            "iterations": 0,
            "num_revises": 0,
            "agent_ok": False,
            "candidates": [],
            "final_correct": False,
            "latency_seconds": round(time.monotonic() - t0, 3),
            "error": f"{type(e).__name__}: {e}",
        }
    latency = round(time.monotonic() - t0, 3)

    candidates: list[dict] = []
    for k, step in enumerate(_candidate_steps(data.get("history", []))):
        sql = step.get("sql", "")
        ok, rows, err = run_sql(db_id, sql)
        candidates.append({
            "iter": k,
            "node": step.get("node"),
            "sql": sql,
            "exec_ok": ok,
            "correct": bool(gold_ok and ok and matches(gold_rows, rows)),
            "exec_error": err,
        })

    return {
        **base,
        "final_sql": data.get("sql", ""),
        "iterations": data.get("iterations", len(candidates)),
        "num_revises": sum(1 for c in candidates if c["node"] == "revise"),
        "agent_ok": data.get("ok", False),
        "candidates": candidates,
        "final_correct": candidates[-1]["correct"] if candidates else False,
        "latency_seconds": latency,
        "error": None,
    }


def summarize(results: list[dict]) -> dict:
    """Aggregate per-question results.

    Per-iteration carry-forward: if the agent terminated at iteration j < k
    (verify said ok at j, or it hit MAX_ITERATIONS at j < k), treat the
    question's iteration-k result as identical to its iteration-j result.
    The agent stopped emitting; whatever it had at termination is what
    would have been served had we polled at iteration k.
    """
    n = len(results)
    if n == 0:
        return {"total": 0}

    passed = sum(1 for r in results if r.get("final_correct"))
    errored = sum(1 for r in results if r.get("error"))

    # Widest iteration depth any question reached; report pass rate up to it.
    depth = max((len(r.get("candidates", [])) for r in results), default=0)
    depth = max(depth, 1)

    pass_rate_at_iteration: dict[str, float] = {}
    for k in range(depth):
        correct_k = 0
        for r in results:
            cands = r.get("candidates", [])
            if cands:
                # carry-forward: clamp to the last candidate the agent produced.
                if cands[min(k, len(cands) - 1)]["correct"]:
                    correct_k += 1
        pass_rate_at_iteration[f"iter_{k}"] = round(correct_k / n, 4)

    # Histogram of how many candidates (1 = no revise, 2 = one revise, ...).
    hist: dict[str, int] = {}
    for r in results:
        key = str(len(r.get("candidates", [])))
        hist[key] = hist.get(key, 0) + 1

    total_candidates = sum(len(r.get("candidates", [])) for r in results)

    return {
        "total": n,
        "passed": passed,
        "pass_rate": round(passed / n, 4),
        "errored": errored,
        "questions_with_revise": sum(1 for r in results if r.get("num_revises", 0) > 0),
        "avg_candidates_per_question": round(total_candidates / n, 2),
        "candidate_count_histogram": hist,
        "pass_rate_at_iteration": pass_rate_at_iteration,
    }


# ---------- Main (provided) --------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval-set", type=Path, default=DEFAULT_EVAL_FILE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_FILE)
    parser.add_argument("--agent-url", default=AGENT_URL_DEFAULT)
    args = parser.parse_args()

    questions = [json.loads(line) for line in args.eval_set.read_text().splitlines() if line.strip()]
    print(f"Loaded {len(questions)} eval questions from {args.eval_set}")

    results: list[dict] = []
    t0 = time.monotonic()
    for i, q in enumerate(questions, 1):
        print(f"[{i}/{len(questions)}] {q['db_id']}: {q['question'][:60]}...", flush=True)
        results.append(eval_one(q, args.agent_url))
    elapsed = time.monotonic() - t0

    summary = summarize(results)
    out = {
        "summary": summary,
        "wall_clock_seconds": elapsed,
        "results": results,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2))
    print(f"Wrote {args.out}")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
