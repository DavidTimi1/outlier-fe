#!/usr/bin/env bash
# Generates deterministic `demo/transcript.txt`, `demo/game1.log`, and `demo/game2_forfeit.log` (T4.6).

set -euo pipefail

mkdir -p demo out

if [ ! -x out/outlier_cli ]; then
    fe build -i outlier_cli --backend native --emit executable --out-dir out
fi

{
    echo "========================================================================"
    echo "OUTLIER — Reproducible Native Fe CLI Demo Transcript"
    echo "========================================================================"
    echo ""
    echo "$ ./out/outlier_cli explain"
    ./out/outlier_cli explain
    echo ""
    echo "$ ./out/outlier_cli vectors"
    ./out/outlier_cli vectors
    echo ""
    echo "$ ./out/outlier_cli play --seed 1 --stake 1001 --out demo/game1.log"
    ./out/outlier_cli play --seed 1 --stake 1001 --out demo/game1.log
    echo ""
    echo "$ ./out/outlier_cli replay demo/game1.log"
    ./out/outlier_cli replay demo/game1.log
    echo ""
    echo "$ ./out/outlier_cli play --seed 42 --stake 1001 --strategy forfeit --out demo/game2_forfeit.log"
    ./out/outlier_cli play --seed 42 --stake 1001 --strategy forfeit --out demo/game2_forfeit.log
    echo ""
    echo "$ ./out/outlier_cli replay demo/game2_forfeit.log"
    ./out/outlier_cli replay demo/game2_forfeit.log
    echo ""
    echo "=== Tamper Detection Demo (corrupting step 8 reveal in demo/game1.log) ==="
    python3 - <<'PY'
lines = open("demo/game1.log").read().splitlines()
# Corrupt step 8 line (change REVEAL colour or digest)
for idx, ln in enumerate(lines):
    if ln.startswith("IN 8 "):
        lines[idx] = ln[:-1] + ("a" if ln[-1] != "a" else "b")
        break
open("demo/game1_tampered.log", "w").write("\n".join(lines) + "\n")
PY
    echo "$ ./out/outlier_cli replay demo/game1_tampered.log"
    if ./out/outlier_cli replay demo/game1_tampered.log; then
        echo "ERROR: tampered log unexpectedly verified!"
        exit 1
    else
        echo "(exited with non-zero status code 1 as expected)"
    fi
    rm -f demo/game1_tampered.log
    echo ""
    echo "$ ./out/outlier_cli analyze"
    ./out/outlier_cli analyze
} > demo/transcript.txt

cat demo/transcript.txt

