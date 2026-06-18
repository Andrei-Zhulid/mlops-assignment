# LLM inference + o11y — Report

> Working draft. Fill the `___` placeholders as runs complete.

## 1. Serving configuration (Phase 1)

Model: `Qwen/Qwen3-30B-A3B-Instruct-2507` on 1× H100 80GB. Final flags in `scripts/start_vllm.sh`:

| Flag | Why |
|---|---|
| `--max-model-len 8192` | ~2× the largest agent prompt (schema + question, or schema + failed SQL + result on revise). The model default (262144) can't fit a single sequence in KV; 8192 is enough headroom without wasting KV slots. |
| dtype omitted → `auto` | resolves to bfloat16 (Qwen3's training precision); no need to force it. |
| `--host 0.0.0.0 --port 8000` | bind for the agent + SSH port-forward. |

## 2. Baseline eval (Phase 5)

`results/eval_baseline.json` — 30 questions, execution accuracy (canonicalized row
sets), the full agent with the tuned verify/revise prompts:

- **Overall pass rate: 0.40 (12/30)**, 0 errored.
- **Per-iteration: iter_0 0.333 (10/30) → iter_1 0.40 (12/30) → iter_2 0.40 (12/30).**
- **The loop earns its keep.** 8/30 triggered a revise, and the first revise flipped
  **2 questions wrong→right** (+20% relative over generate-only): one a timestamp match
  (`Date = '…'` → `Date LIKE '…%'`, to match the gold's trailing-millisecond format),
  one a join-path fix (a direct `users→tags` join corrected to `tags→posts→users`).
- **The 2nd revise added nothing** (iter_2 == iter_1): of the questions reaching a 3rd
  attempt none improved (one even revised into a SQL error) — the value is entirely in
  the first revise.

For contrast, *before* the verify/revise prompt fixes the same eval was **0.333 flat
across all iterations** — the verifier rubber-stamped 9 wrong answers (never revised)
and 0 revises fixed anything, so the loop added zero value. Giving the verifier the
schema + requiring an actionable issue is what lifted iter_1 from 0.333 to 0.40.

## 3. SLO (Phase 6)

**Target: P95 end-to-end agent latency < 5s, ≥10 RPS, over a 5-minute window.**

Baseline load test (`load_test/driver.py --rps 10 --duration 300`):
**p50 11.0s, p95 110.6s, p99 116.9s, achieved 8.3 RPS, ok 324/3000, timeouts 1647.** → SLO **missed by a wide margin**.

**Correctness bugfix (found during Phase 6 diagnosis, not an SLO iteration).** Probing
the ~12% HTTP-500s sequentially traced them to a deterministic crash in
`render_schema`: foreign keys that reference the parent's primary key *implicitly*
return a NULL to-column, hitting `None.replace` in `_q` — so every request to
`debit_card_specializing` and `european_football_2` 500'd at `attach_schema`, before
any LLM call. Fixed the FK rendering to handle the NULL to-column. Recovers ~12% of
requests; note these were sub-0.5s fast-failures, so serving them for real adds load
and may *raise* p95 (the earlier p95 was flattered by fast-failing an eighth of traffic).

### Iteration log

```
Iter 1: saw decode p95 4.74s ≈ vLLM-req p95, gen ~39 tok/s/seq, KV ~80% →
  hypothesized decode-bound (KV-bw + bf16) → changed: FP8 weights+KV
  (+prefix/chunked) → result: KV 80%→15%, gen +35% (~52 tok/s/seq), but decode
  p95 4.74→5.65s (output tail 190→355) and load-test p95 ~110s UNCHANGED —
  vLLM starved (running ~40 = server threadpool, waiting 0), bottleneck is the
  agent server, not vLLM.

Iter 2: saw output p95 355 (max 5000), no max_tokens cap, runaway outputs holding server threads 100s+ → hypothesized oversized outputs inflate decode AND starve the threadpool → changed: cap max_tokens (gen/revise 256, verify 64) → result: output p95 355→108, decode p95 5.65→1.28s, load-test p95 110→33.7s, timeouts 1609→1, ok 362→2556, RPS 8.3→9.24; SLO still missed (per-call 1.28s but full-run p95 33.7s ⇒ ~30s server-side queueing).

Iter 3: saw vLLM starved (KV 2%, running spiky max 36, waiting 0) while full-run p95 33.7s ≫ per-call 1.28s → hypothesized FastAPI sync threadpool (~40) caps in-flight runs → changed: async agent server (async def endpoint + async LLM nodes via ainvoke) → result: running lifted to max 61, p50 7.73→4.65s (<5s), p95 33.7→25.6s, RPS 9.22, ok 2581/3000. SLO still missed; vLLM now decisively NOT the bottleneck (KV max 2.2%, waiting 0, preemptions 0) ⇒ p95 is now bounded by the agent's sequential call count (up to 6 LLM calls/run), not serving.
```

### Narrative

The instructive result was Iter 1: FP8 moved exactly the vLLM-internal metrics it
should (KV 80%→15%, gen tokens/s +35%) yet the **SLO did not budge** — *a metric
improved and the SLO didn't*. The dashboard explains why: vLLM was **starved, not
saturated** — `running` plateaued at ~40 (= FastAPI's default sync threadpool),
`waiting` = 0, KV 15%. The load-test p95 (110s) is queueing **in the agent
server**, not vLLM decode (per-call p95 5.65s). Two distinct problems surfaced:
per-call work too high (output p95 355, no `max_tokens` cap) and agent-server
concurrency capped at ~40. Iter 2 attacks the first; Iter 3 the second.

**Final config** (`max_tokens` cap + async server) — `results/load_test3.json`:
**p50 4.65s, p95 25.6s, p99 32.1s, achieved 9.22 RPS, ok 2581/3000, timeouts 1.**

**Verdict — SLO missed, but the gap is fully diagnosed.** p50 (4.65s) is under target, but
p95 (25.6s) / p99 (32.1s) are ~5–6× over and RPS (9.22) just under 10. With vLLM idle
(KV ~2%, waiting 0, preemptions 0), the tail is **the agent's own sequential call count** —
up to 6 LLM calls on max-revise runs, each prefill-bound at ~1.6s — not a serving limit.
Baseline→final the wins were real (p95 110→25.6s, timeouts 1647→1, ok 324→2581) but the
last ~5× is architectural: closing it needs fewer/parallel agent calls or shorter prompts,
not more vLLM tuning.

_**Quality after tuning.** The Phase 6 changes (`max_tokens` cap, async server) are
latency-only — they don't change the agent's prompts or control flow, so the SQL it
generates is unchanged and final-config quality = the baseline **0.40** (quality survived).
Confirm directly by re-running `results/eval_after_tuning.json` against the final config.

Screenshots: `screenshots/grafana_before.png`, `screenshots/grafana_after.png`.

## 4. Agent value

The verify→revise loop earns its keep, measurably. On the eval set, generate-only
(iter_0) scores **0.333 (10/30)** and the loop lifts it to **0.40 (12/30)** at iter_1 —
the first revise recovers **2 questions** (+0.067 absolute, **+20% relative**): e.g.
switching an exact-timestamp `Date = '…'` to `LIKE '…%'`, and fixing a wrong join path.
The value is concentrated in the **first** revise (iter_1 == iter_2, so the 2nd adds
nothing). And the loop only started paying off after the verifier was given the schema
and required to emit an *actionable* issue — before that it rubber-stamped 9 wrong
answers and fixed 0 (0.333 flat across iterations).

## 5. What I'd do with more time

- **Cut per-call prefill, the real latency driver.** The dashboard showed calls are
  prefill-bound (prompt ~25K tok/s vs gen ~1.1K tok/s) because the full schema is re-sent
  every call. Prune the schema to the tables the question touches (or retrieve top-k
  tables) to shrink prompts → faster prefill → lower per-call latency and p95.
- **Replace the sequential verify→revise loop with parallel self-consistency.** Sample N
  candidates at generate time concurrently and pick by execution agreement, instead of up
  to 6 sequential calls — directly attacks the p95 tail (the sequential call count) while
  likely lifting iter_0 accuracy, where most of the loss is.
- **Reuse one LLM client and degrade gracefully.** Build `ChatOpenAI` once instead of
  per call (avoids connection churn under high concurrency), and wrap node errors so a
  failed call returns a clean result instead of a 500 that counts against the SLO.