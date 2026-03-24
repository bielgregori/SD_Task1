#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# run_benchmark.sh – Full benchmark sweep
#
# Runs unnumbered & numbered benchmarks for both architectures,
# then generates plots.
#
# Prerequisites:
#   - Redis, RabbitMQ, NGINX running  (see deploy.sh)
#   - REST servers running on ports 8001, 8002, …
#   - At least one RabbitMQ worker running
#   - Benchmark files generated (python benchmarks/generate.py)
#
# Usage:
#   chmod +x scripts/run_benchmark.sh
#   ./scripts/run_benchmark.sh
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

RESULTS_DIR="results"
PLOTS_DIR="analysis/plots"
URL="${REST_URL:-http://localhost:8080}"
CONCURRENCY="${CONCURRENCY:-200}"

mkdir -p "$RESULTS_DIR" "$PLOTS_DIR"

echo "═══════════════════════════════════════════════════"
echo "  Benchmark Sweep"
echo "  REST URL: $URL  |  Concurrency: $CONCURRENCY"
echo "═══════════════════════════════════════════════════"

# ── 0. Generate benchmarks if not present ───────────────────────────
if [ ! -f benchmarks/benchmark_unnumbered.txt ]; then
    echo "[gen] Generating benchmark files…"
    python3 benchmarks/generate.py
    python3 benchmarks/generate.py --high-contention
fi

# ── 1. Reset ticket state ──────────────────────────────────────────
echo ""
echo "[reset] Clearing Redis ticket data…"
curl -s -X POST "$URL/reset" || true
redis-cli FLUSHDB || true
sleep 1

# ── 2. Direct – Unnumbered ──────────────────────────────────────────
echo ""
echo "[direct/unnumbered] Running benchmark…"
redis-cli FLUSHDB > /dev/null
python3 direct/client.py \
    --benchmark benchmarks/benchmark_unnumbered.txt \
    --url "$URL" \
    --concurrency "$CONCURRENCY" \
    --output "$RESULTS_DIR/results_direct_unnumbered.json"

# ── 3. Direct – Numbered ────────────────────────────────────────────
echo ""
echo "[direct/numbered] Running benchmark…"
redis-cli FLUSHDB > /dev/null
python3 direct/client.py \
    --benchmark benchmarks/benchmark_numbered.txt \
    --url "$URL" \
    --concurrency "$CONCURRENCY" \
    --output "$RESULTS_DIR/results_direct_numbered.json"

# ── 4. Indirect – Unnumbered ────────────────────────────────────────
echo ""
echo "[indirect/unnumbered] Running benchmark…"
redis-cli FLUSHDB > /dev/null
python3 indirect/client.py \
    --benchmark benchmarks/benchmark_unnumbered.txt \
    --output "$RESULTS_DIR/results_indirect_unnumbered.json"

# ── 5. Indirect – Numbered ──────────────────────────────────────────
echo ""
echo "[indirect/numbered] Running benchmark…"
redis-cli FLUSHDB > /dev/null
python3 indirect/client.py \
    --benchmark benchmarks/benchmark_numbered.txt \
    --output "$RESULTS_DIR/results_indirect_numbered.json"

# ── 6. Plots ────────────────────────────────────────────────────────
echo ""
echo "[plots] Generating analysis plots…"
python3 analysis/plot_results.py \
    --results \
        "$RESULTS_DIR/results_direct_unnumbered.json" \
        "$RESULTS_DIR/results_direct_numbered.json" \
        "$RESULTS_DIR/results_indirect_unnumbered.json" \
        "$RESULTS_DIR/results_indirect_numbered.json" \
    --output-dir "$PLOTS_DIR"

echo ""
echo "═══════════════════════════════════════════════════"
echo "  All benchmarks complete!"
echo "  Results: $RESULTS_DIR/"
echo "  Plots:   $PLOTS_DIR/"
echo "═══════════════════════════════════════════════════"
