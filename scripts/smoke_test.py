"""Phase 1 smoke test: fire 5 questions from the eval set at vLLM directly.

Calls the OpenAI-compatible /chat/completions endpoint with a minimal
text-to-SQL prompt and prints the generated SQL. Does NOT use the agent graph
(verify/revise are Phase 3). The goal is just to confirm vLLM is up and
returning sensible output.

Usage:
    uv run python scripts/smoke_test.py
    uv run python scripts/smoke_test.py --n 3 --url http://localhost:8000/v1
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from openai import OpenAI

from agent.execution import execute_sql
from agent.schema import render_schema

MODEL = "Qwen/Qwen3-0.6B"
QUEStiONS_COUNT = 5

SYSTEM_PROMPT = textwrap.dedent("""\
    You are a SQL expert. Given a database schema and a user question
    in a natural language question, write a single SQLite SELECT
    statement that answers the question. Always respond in English.
    IMPORTANT:
    - Always respond in English.
    - Output ONLY the SQL query nothing else — no explanation, no
    markdown fences.
""")

USER_TEMPLATE = """\
Schema:
{schema}

Question: {question}

SQL:"""


def strip_thinking(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def extract_sql(text: str) -> str:
    text = strip_thinking(text)
    fenced = re.search(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    return (fenced.group(1) if fenced else text).strip()


def load_questions(n: int) -> list[dict]:
    path = ROOT / "evals" / "eval_set.jsonl"
    questions = []
    with open(path) as f:
        for line in f:
            if line.strip():
                questions.append(json.loads(line))
            if len(questions) == n:
                break
    return questions


def run(n: int, base_url: str, model: str) -> None:
    client = OpenAI(base_url=base_url, api_key=os.environ.get("OPENAI_API_KEY", "not-needed"))
    questions = load_questions(n)

    print(f"Firing {len(questions)} questions at {base_url} ({model})\n{'─' * 70}")

    passed = 0
    for i, q in enumerate(questions, 1):
        db_id = q["db_id"]
        question = q["question"]
        gold = q["gold_sql"]

        try:
            schema = render_schema(db_id)
        except FileNotFoundError as e:
            print(f"[{i}] SKIP — {e}\n")
            continue

        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": USER_TEMPLATE.format(schema=schema, question=question)},
            ],
            temperature=0.0,
            max_tokens=512,
            # Qwen3 defaults to thinking mode; disable it so we get SQL directly.
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )

        generated = extract_sql(resp.choices[0].message.content)
        tokens_in = resp.usage.prompt_tokens
        tokens_out = resp.usage.completion_tokens

        result = execute_sql(db_id, generated)
        exec_status = f"rows={result.row_count}" if result.ok else f"ERROR: {result.error}"
        if result.ok:
            passed += 1

        print(f"[{i}] DB: {db_id}")
        print(f"     Q:      {question}")
        print(f"     SQL:    {generated}")
        print(f"     Exec [{' OK' if result.ok else 'FAIL'}]: {exec_status}")
        print(f"     Gold:   {gold}")
        print(f"     Tokens in/out: {tokens_in}/{tokens_out}")
        print()

    print('─' * 70)
    print(f"Result: {passed}/{len(questions)} queries executed successfully")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=QUEStiONS_COUNT, help="number of questions to fire")
    parser.add_argument(
        "--url",
        default=os.environ.get("VLLM_BASE_URL", "http://localhost:8000/v1"),
        help="vLLM base URL",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("VLLM_MODEL", MODEL),
        help="model name as served by vLLM",
    )
    args = parser.parse_args()
    run(args.n, args.url, args.model)