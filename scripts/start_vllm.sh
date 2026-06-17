#!/usr/bin/env bash
#
# Start vLLM with your chosen configuration.
# Reference: https://docs.vllm.ai/en/latest/serving/openai_compatible_server.html

set -euo pipefail

MODEL="Qwen/Qwen3-30B-A3B-Instruct-2507"
#MODEL="Qwen/Qwen3-0.6B"

# Flag rationale (for REPORT.md, Phase 1):
#   --dtype bfloat16          Qwen3 is trained in bf16; float16 risks overflow/NaN. H100 runs bf16 natively.
#   --quantization fp8        Online FP8 weights ~30GB instead of ~61GB bf16 -> frees ~30GB of the 80GB
#                             for KV cache. Biggest concurrency lever; H100 has native FP8. Verify eval
#                             pass rate survives (Phase 5/6) — if it regresses, drop this line.
#   --kv-cache-dtype fp8      Halves KV bytes/token -> ~2x more concurrent sequences. Tiny quality risk; verify.
#   --gpu-memory-utilization  0.92: give the KV cache as much of the 80GB as is safe.
#   --max-model-len 8192      ~2x the largest agent prompt (schema + question, or schema+failed SQL+result on
#                             revise). Smaller = more KV slots; this is enough headroom without wasting them.
#   --max-num-seqs 128        High concurrency target: ~10 RPS x 2-3 sequential calls each. Phase-6 knob —
#                             lower it if you see KV eviction/preemption; raise if the cache has headroom.
#   --max-num-batched-tokens  16384: large batches = better prefill throughput on the 1.5-3K-token prompts.
#   --enable-prefix-caching   Schema + system prompt are identical across the 2-3 calls per request AND across
#                             all questions on the same DB -> the big shared prefix is computed once. Huge here.
#   --enable-chunked-prefill  Interleave prefill with decode so long prompts don't stall in-flight decodes;
#                             steadier inter-token latency under load -> protects P95.

exec uv run python -m vllm.entrypoints.openai.api_server \
    --model "$MODEL" \
    --host 0.0.0.0 \
    --port 8000 \
    --dtype bfloat16 \
    --quantization fp8 \
    --kv-cache-dtype fp8 \
    --gpu-memory-utilization 0.92 \
    --max-model-len 8192 \
    --max-num-seqs 128 \
    --max-num-batched-tokens 16384 \
    --enable-prefix-caching \
    --enable-chunked-prefill