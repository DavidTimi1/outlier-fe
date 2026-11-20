#!/usr/bin/env bash
# Automated compile-fail verification suite (T2.9).
# Verifies that Fe 26.6.0's type and effect system statically rejects illegal code patterns.

set -euo pipefail

check_fail() {
    local file="$1"
    local expected_pattern="$2"
    local label="$3"

    local out
    if out=$(fe check --standalone "$file" 2>&1); then
        echo "[FAIL] $label ($file) unexpectedly compiled!"
        exit 1
    fi

    if echo "$out" | grep -qE "$expected_pattern"; then
        echo "[PASS] $label -> rejected with expected diagnostic ($expected_pattern)"
    else
        echo "[FAIL] $label ($file) failed to compile, but diagnostic did not match '$expected_pattern':"
        echo "$out"
        exit 1
    fi
}

check_fail "test/compile_fail/cf_01_pure_effect.fe" "error\[8-0036\]: missing effect" "C-05: Pure function cannot touch ambient effect (Ctx)"
check_fail "test/compile_fail/cf_02_nonexhaustive_phase.fe" "error\[8-0034\]: non-exhaustive patterns" "C-06: Non-exhaustive match on Phase rejected"
check_fail "test/compile_fail/cf_03_seat_position_confusion.fe" "error\[8-0000\]: type mismatch" "C-07: Position cannot be passed where Seat is expected"
check_fail "test/compile_fail/cf_04_forfeit_takes_positions.fe" "error\[8-00" "C-03/P5: settle_forfeit rejects board Positions argument"

echo "All 4/4 compile-fail checks passed."

