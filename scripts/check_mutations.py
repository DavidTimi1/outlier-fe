#!/usr/bin/env python3
"""
Fe Core Mutation Testing Suite (T2.10).

Applies 8 targeted semantic mutations directly to `ingots/outlier_core/src/*.fe`
in an isolated temporary workspace copy and runs `fe test -i outlier_core --backend native`.
Every single mutant MUST fail at least one test (100% kill rate).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MUTANTS = [
    (
        "M1: all-distinct counted as winner in resolve()",
        "src/rules.fe",
        "if !c0.eq(c1) && !c1.eq(c2) && !c0.eq(c2) {\n        return Outcome::NoWinner\n    }",
        "if false {\n        return Outcome::NoWinner\n    }",
    ),
    (
        "M2: forfeit split gives entire forfeiter stake to lower survivor",
        "src/settle.fe",
        "let low_share = stake + (stake - (stake / 2))\n    let high_share = stake + (stake / 2)",
        "let low_share = stake + stake\n    let high_share = stake",
    ),
    (
        "M3: forfeiter refunded own stake (free abort)",
        "src/settle.fe",
        "if f0 {\n        // Survivors are S1 (lower) and S2 (higher)\n        [0, low_share, high_share]",
        "if f0 {\n        [stake, low_share, high_share]",
    ),
    (
        "M4: Push self-targeting check removed in apply_move()",
        "src/rules.fe",
        "if target.eq(winner) {\n                Result::Err(StepError::InvalidMove)\n            }",
        "if false {\n                Result::Err(StepError::InvalidMove)\n            }",
    ),
    (
        "M5: Push back saturates at 1 instead of 0",
        "src/types.fe",
        "if self.raw <= PUSH {\n            Position { raw: 0 }",
        "if self.raw <= PUSH {\n            Position { raw: 1 }",
    ),
    (
        "M6: Commit deadline off-by-one (`>=` instead of `>`)",
        "src/machine.fe",
        "if ctx.now > deadline {\n                    return Result::Err(StepError::DeadlinePassed)\n                }",
        "if ctx.now >= deadline {\n                    return Result::Err(StepError::DeadlinePassed)\n                }",
    ),
    (
        "M7: Seat omitted from commitment hash (copy-attack vulnerability)",
        "src/rules.fe",
        "participant: seat.to_u256(),",
        "participant: 0,",
    ),
    (
        "M8: ROUND_CAP check ignored after MoveInput in after_move_transition()",
        "src/machine.fe",
        "    if round >= ROUND_CAP {\n        let res = GameResult::CapReached { leader: leader(new_positions) }",
        "    if false {\n        let res = GameResult::CapReached { leader: leader(new_positions) }",
    ),
    (
        "M9: ROUND_CAP check ignored on NoWinner in Reveal()",
        "src/machine.fe",
        "                        Outcome::NoWinner => {\n                            if round >= ROUND_CAP {",
        "                        Outcome::NoWinner => {\n                            if false {",
    ),
]


def main() -> int:
    killed = 0
    with tempfile.TemporaryDirectory() as td:
        ws = os.path.join(td, "ws")
        os.makedirs(os.path.join(ws, "ingots"))
        shutil.copy(os.path.join(ROOT, "fe.toml"), os.path.join(ws, "fe.toml"))
        core_src = os.path.join(ROOT, "ingots", "outlier_core")
        core_dst = os.path.join(ws, "ingots", "outlier_core")

        for name, rel_file, old, new in MUTANTS:
            if os.path.exists(core_dst):
                shutil.rmtree(core_dst)
            shutil.copytree(core_src, core_dst)

            target_path = os.path.join(core_dst, rel_file)
            text = open(target_path).read()
            if old not in text:
                print(f"[ERROR] Pattern not found for {name} in {rel_file}")
                return 1
            open(target_path, "w").write(text.replace(old, new, 1))

            res = subprocess.run(
                ["fe", "test", ws, "-i", "outlier_core", "--backend", "native"],
                capture_output=True,
                text=True,
            )
            if res.returncode != 0:
                killed += 1
                failed_lines = [ln.strip() for ln in res.stdout.splitlines() if "FAIL" in ln]
                summary = failed_lines[0] if failed_lines else "test failed"
                print(f"[KILLED  ] {name} :: {summary}")
            else:
                print(f"[SURVIVED] {name} <-- TEST SUITE TOO WEAK")
                return 1

    print(f"\nMutation summary: {killed}/{len(MUTANTS)} Fe core mutants killed (100%).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

