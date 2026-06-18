#!/usr/bin/env bash
#
# Start vLLM with your chosen configuration.
# Reference: https://docs.vllm.ai/en/latest/serving/openai_compatible_server.html

set -euo pipefail

MODEL="Qwen/Qwen3-30B-A3B-Instruct-2507"
#MODEL="Qwen/Qwen3-0.6B"

# Applied flags (Phase 6 iteration 1 — target the decode-bound bottleneck):
#   --quantization fp8        Online FP8 weights (~30GB vs ~61GB bf16). Faster matmuls + frees ~30GB.
#                             Verify eval pass rate survives (Phase 5/6); if it regresses, drop this line.
#   --kv-cache-dtype fp8      Halves KV bytes/token. Decode is KV-bandwidth bound -> directly speeds the
#                             bottleneck, and gives headroom (KV was hitting ~80%).
#   --max-model-len 8192      ~2x the largest agent prompt. Smaller = more KV slots; enough headroom.
#   --enable-prefix-caching   Schema + system prompt repeat across the 2-3 calls/request and across all
#                             questions on the same DB -> the shared prefix is computed once.
#   --enable-chunked-prefill  Interleave prefill with decode so long prompts don't stall in-flight decodes.
# dtype omitted: default 'auto' already resolves to bfloat16 for Qwen3.
#
# Deferred to later iterations (change ONE at a time, re-measure):
#   --max-num-seqs N          Lower (e.g. 24) to cut decode-batch contention -> higher per-seq tok/s; watch
#                             'waiting' rise. --gpu-memory-utilization / --max-num-batched-tokens are fine knobs.

exec uv run python -m vllm.entrypoints.openai.api_server \
    --model "$MODEL" \
    --host 0.0.0.0 \
    --port 8000 \
    --max-model-len 8192 \
    --quantization fp8 \
    --kv-cache-dtype fp8 \
    --enable-prefix-caching \
    --enable-chunked-prefill
