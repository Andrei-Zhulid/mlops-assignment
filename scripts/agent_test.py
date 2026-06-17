"""Phase 3 Agent test: fire questions from the eval set through the AGENT.

Unlike scripts/vllm_test.py (which hits vLLM directly with a one-shot prompt),
this calls the agent HTTP server at /answer, so every request runs the full
generate_sql -> execute -> verify -> (revise) graph. We use the response's
`history` and `iterations` to see whether the verify->revise loop actually
fires on any question.

Prereqs: vLLM up, and the agent server running:
    uv run uvicorn agent.server:app --host 0.0.0.0 --port 8001

Usage:
    uv run python scripts/agent_test.py
    uv run python scripts/agent_test.py --n 5 --url http://localhost:8001
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

EVAL_FILE = ROOT / "evals" / "eval_set.jsonl"
QUESTIONS_COUNT = 10
AGENT_URL_DEFAULT = "http://localhost:8001"


def load_questions(n: int) -> list[dict]:
    questions: list[dict] = []
    with open(EVAL_FILE) as f:
        for line in f:
            if line.strip():
                questions.append(json.loads(line))
            if len(questions) == n:
                break
    return questions


def triggered_revise(history: list[dict]) -> bool:
    return any(step.get("node") == "revise" for step in history)


def run(n: int, base_url: str) -> None:
    questions = load_questions(n)
    url = base_url.rstrip("/") + "/answer"
    print(f"Firing {len(questions)} questions through the agent at {url}\n{'─' * 70}")

    passed = 0
    revised = 0
    for i, q in enumerate(questions, 1):
        db_id = q["db_id"]
        question = q["question"]
        gold = q["gold_sql"]

        try:
            resp = httpx.post(
                url,
                json={
                    "question": question,
                    "db": db_id,
                    # Tag the trace so it's easy to find in Langfuse (Phase 4).
                    "tags": {"phase": "agent-test", "db": db_id},
                },
                timeout=120.0,
            )
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            print(f"[{i}] DB: {db_id}\n     Q:      {question}\n     REQUEST FAILED: {exc}\n")
            continue

        data = resp.json()
        ok = data.get("ok", False)
        iterations = data.get("iterations", 0)
        history = data.get("history", [])
        sql = data.get("sql", "")
        error = data.get("error")
        did_revise = triggered_revise(history)

        if ok:
            passed += 1
        if did_revise:
            revised += 1

        rows = data.get("rows")
        exec_status = f"rows={len(rows)}" if ok and rows is not None else f"ERROR: {error}"
        nodes = " -> ".join(step.get("node", "?") for step in history)

        print(f"[{i}] DB: {db_id}")
        print(f"     Q:      {question}")
        print(f"     SQL:    {sql}")
        print(f"     Exec [{' OK' if ok else 'FAIL'}]: {exec_status}")
        print(f"     Iterations: {iterations}  Revise: {'YES' if did_revise else 'no'}")
        print(f"     Path:   {nodes}")
        print(f"     Gold:   {gold}")
        print()

    print("─" * 70)
    print(f"Result: {passed}/{len(questions)} queries executed successfully")
    print(f"Revise: {revised}/{len(questions)} questions triggered a verify->revise loop")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=QUESTIONS_COUNT, help="number of questions to fire")
    parser.add_argument("--url", default=AGENT_URL_DEFAULT, help="agent server base URL")
    args = parser.parse_args()
    run(args.n, args.url)