# Run Checklist — all phases on the H100
 config 
Sequential, top to bottom. `📸` = screenshot, `💾` = saved file. Tear down the VM
after Phase 6; write `REPORT.md` (Phase 7) afterwards.

## Phase 0 — Setup
- [ ] Forward ports 3000 / 9090 / 3001 / 8000 / 8001
- [ ] `uv sync` && `cp .env.example .env`
- [ ] `uv run python scripts/load_data.py`  (BIRD under `data/bird/`)
- [ ] `docker compose up -d`  (Grafana / Prometheus / Langfuse up)
- [ ] In `start_vllm.sh`: model = `Qwen/Qwen3-30B-A3B-Instruct-2507`, `--max-model-len` ≥ 8192
- [ ] In `.env`: `VLLM_MODEL` matches the served name (or unset); add Langfuse keys after B4

## Phase 1 — vLLM
- [ ] `bash scripts/start_vllm.sh`  → wait for `curl -s localhost:8000/v1/models`
- [ ] `uv run python scripts/vllm_test.py --n 5`  → SQL looks sane
- [ ] 📸 `screenshots/vllm_manual_query.png`
- [ ] Note chosen flags + 1-line rationale each → REPORT.md

## Phase 2 — Grafana (panels exist; verify they react under load in Phase 5)
- [ ] Open dashboard; confirm latency / throughput / KV-cache panels load
- [ ] 📸 `screenshots/grafana_serving.png`  (capture during the Phase 5 eval burst)

## Phase 3 — Agent
- [ ] Start agent: `uv run uvicorn agent.server:app --host 0.0.0.0 --port 8001`
- [ ] `uv run python scripts/agent_test.py --n 10`  → ≥1 question triggers a revise

## Phase 4 — Langfuse
- [ ] Sign up at :3001 → create project → keys into `.env` → restart agent
- [ ] Re-fire 10: `uv run python scripts/agent_test.py --n 10`
- [ ] Inspect a trace: generate_sql → verify → (revise) waterfall
- [ ] 📸 `screenshots/langfuse_trace.png`   📸 `screenshots/langfuse_tags.png`

## Phase 5 — Evals
- [ ] `uv run python evals/run_eval.py --out results/eval_baseline.json`  (watch Grafana)
- [ ] 💾 `results/eval_baseline.json`     📸 `screenshots/grafana_eval_run.png`
- [ ] Check `pass_rate_at_iteration`: is `iter_last` > `iter_0`?

## Phase 6 — SLO  (target: P95 < 5s, ≥10 RPS, 5 min)
- [ ] `uv run python load_test/driver.py --rps 10 --duration 300`  → 💾 `results/load_test.json`
- [ ] 📸 `screenshots/grafana_before.png`
- [ ] Diagnose from dashboard → change ONE thing → restart vLLM → re-run load
- [ ] 📸 `screenshots/grafana_after.png`
- [ ] Log each iter in REPORT.md: "saw X → hypothesized Y → changed Z → result W"
- [ ] Final-config eval: `uv run python evals/run_eval.py --out results/eval_after_tuning.json`
- [ ] 💾 `results/eval_after_tuning.json`
- [ ] Pull all screenshots + JSONs to laptop → **tear down VM**

## Phase 7 — Report (off-GPU)
- [ ] `REPORT.md` (≤3 pages): serving config · baseline eval · SLO iteration log + final numbers · agent value (cite per-iter pass rate) · what you'd do with more time
- [ ] Confirm all artifacts present, commit

## Artifacts gate
`REPORT.md` · `serving.json` · `agent/graph.py` `agent/prompts.py` · `evals/run_eval.py`
· `results/eval_baseline.json` `results/eval_after_tuning.json` `results/load_test.json`
· screenshots: `vllm_manual_query` `grafana_serving` `langfuse_trace` `langfuse_tags`
`grafana_eval_run` `grafana_before` `grafana_after`