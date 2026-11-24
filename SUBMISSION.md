# OUTLIER — A Three-Player Hidden-Move Game as One Pure Fe State Machine

**Pitch:** OUTLIER is a three-player hidden-move game whose whole protocol is one pure Fe state machine, so the on-chain contract and the off-chain verifier run the same rules code and every game can be replayed and re-verified step by step.

---

## 60-second tour
Three players secretly pick a colour; the odd one out wins the round and moves. The whole rule set is one pure Fe function (`outlier_core::step`), so the EVM contract and the native CLI verifier compile from the same source.

```sh
fe build -i outlier_cli --backend native --emit executable --out-dir out
./scripts/run_demo.sh                 # deterministic suite: play, replay, tamper-check, analyze
./scripts/walkthrough.sh --auto 2.5   # human-speed visual round cards & live 3-lane race track
```

Start with [docs/PATTERN.md](./docs/PATTERN.md) (reusable pattern, 18-line sealed-bid auction)
or [docs/FE_FINDINGS.md](./docs/FE_FINDINGS.md) (compiler findings, Fe vs Solidity).

---

## The Problem

Simultaneous hidden-move protocols on the EVM — sealed-bid auctions, commit-reveal voting, MEV-resistant batching, and multi-player games — fail in practice for three reasons:

1. **Abort & Forfeit-Timing Kingmaking Attacks:** The last revealer sees earlier reveals and can withhold their reveal if they would lose, or deliberately time an abort in a $N \ge 3$ participant protocol to choose *which* opponent wins the forfeited pot.
2. **State-Machine & Storage Corruption:** Solidity encodes multi-phase protocols using flat structs of loose integers, booleans, and sentinel zeros that allow illegal phase/payload combinations and forgotten deadline paths.
3. **On-Chain vs. Off-Chain Rules Drift:** Because Solidity only compiles to the EVM, off-chain replay verifiers, simulators, and strategic solvers must be rewritten in TypeScript, Python, or Rust — creating subtle ABI, integer-width, or Keccak padding divergences.

**OUTLIER** solves all three problems as a reusable architectural pattern in **Fe 26.6.0**, demonstrated through a non-trivial three-player game of hidden information and positional interference.

---

## Approach

### The Game & Protocol (`docs/SPEC.md`)
Three players (`S0, S1, S2`) stake `STAKE` wei and race from position `0` to `FINISH = 4` (with `ROUND_CAP = 20`):
- **Commit-Reveal Stage Game:** Each round, all three players secretly commit to `{Red=0, Blue=1, Green=2}` using a 7-word domain-separated Keccak-256 commitment (`DOMAIN_TAG, table, game_id, round, seat, colour, nonce`). When all three reveal:
  - If all three colours are equal (`3` cases) or all three are distinct (`6` cases) → `Outcome::NoWinner`.
  - If **exactly two match** (`18` cases, `6` per seat) → the **odd one out (the outlier) wins the round**.
- **Positional Interference (`WinnerMove`):** The round winner chooses between **`Move::Advance`** (`+1` up to `FINISH`) or **`Move::Push(target)`** (`-1` down to `0` on an opponent `target != winner`).
- **Abort-Resistant Deadlines & Anti-Kingmaking Forfeits:** Every timed phase has a strict deadline (`now <= deadline` for actions, `now > deadline` for permissionless `Poke`). A player who stalls in `Commit` or `Reveal` forfeits their stake (`net = -STAKE`), which is split symmetrically between survivors (`ceil(STAKE/2)` and `floor(STAKE/2)`) **independently of board positions**; a round winner who stalls in `WinnerMove` is defaulted to `Move::Advance`.
- **16-Word Hash-Chained State Digest (`Transition`):** Every transition updates `digest_n = keccak_words([digest_{n-1}, w0..w14])`, allowing any game to be replayed and re-verified step by step from its public input trace.

---

## Fe Highlight

In [ingots/outlier_core](./ingots/outlier_core/src/lib.fe):
- **Effect system:** the entire protocol is one pure function, `outlier_core::step`, with no `uses` clause. The compiler verifies it is free of storage, clock, caller, and I/O effects (`error[8-0036]`), so the EVM contract (`outlier_table`) and the native CLI verifier/solver (`outlier_cli`) compile from the exact same source.
- **Enums with payloads and exhaustive `match`:** a payload `Phase` enum is stored directly in contract storage (`error[8-0034]` on missing arms), so illegal phase/payload states are unconstructible.
- **Type-level guarantees:** `settle_forfeit(mask, stake)` omits board `Positions` from its signature, so forfeit splits cannot depend on game state (anti-kingmaking).

```fe
// ingots/outlier_core/src/types.fe — Illegal phase/payload combinations are unconstructible
pub enum Phase {
    Idle,
    Registration { pub deadline: u256 },
    Commit { pub round: u8, pub deadline: u256 },
    Reveal { pub round: u8, pub deadline: u256 },
    WinnerMove { pub round: u8, pub winner: Seat, pub deadline: u256 },
    Finished { pub result: GameResult },
}

// ingots/outlier_core/src/settle.fe — Property P5: Position-independent forfeit split by type signature
pub fn settle_forfeit(_ mask: u8, _ stake: u256) -> [u256; 3]

// ingots/outlier_core/src/machine.fe — Pure protocol state machine (no `uses` clause!)
pub fn step(_ state: GameState, _ prev_digest: u256, _ input: Input, _ ctx: StepCtx) -> Result<StepError, StepOut>
```

*(The native CLI's per-command capability projection is described in [docs/FE_FINDINGS.md](./docs/FE_FINDINGS.md).)*

---

## Architecture

```
                 ┌──────────────────────────────────────────┐
                 │ ingots/outlier_core  (EVM + native)      │
                 │ NO storage, NO clock, NO caller, NO I/O  │
                 │ params · types · errors · rules          │
                 │ commit_reveal · machine · settle · encode│
                 └───────────────▲──────────────▲───────────┘
                                 │              │
        ┌────────────────────────┴───┐      ┌───┴────────────────────────┐
        │ ingots/outlier_table (EVM) │      │ ingots/outlier_cli (native)│
        │ effects: Ctx, Call, Log,   │      │ effects: Args, Stdout,     │
        │          storage (22.6 KB) │      │          Stderr, Fs, Exit  │
        │ thin msg/recv + withdraw() │      │ explain·play·replay·analyze│
        └────────────────────────────┘      └────────────────────────────┘
                         ▲
        ┌────────────────┴──────────────────────────────────────────────┐
        │ ingots/testkit (EVM + native, tests only):                    │
        │ SplitMix64 PRNG, 1,000-game parity runner, golden digests     │
        └───────────────────────────────────────────────────────────────┘
        oracle/outlier_model.py: independent bounded model checker (5,618 states)
```

| Component | Path | Target | Description |
|---|---|---|---|
| **`outlier_core`** | [ingots/outlier_core](./ingots/outlier_core/src/lib.fe) | EVM + Native | Pure types, rules, reusable `commit_reveal`, `step`, `settle`, 15-word `encode_state` & 16-word `digest_next` |
| **`outlier_table`** | [ingots/outlier_table](./ingots/outlier_table/src/lib.fe) | EVM (`sonatina`) | Thin `OutlierTable` contract (`22,616 B` runtime), 14 typed `#[error]`s, 8 `#[event]`s, pull-payment `withdraw()` |
| **`outlier_cli`** | [ingots/outlier_cli](./ingots/outlier_cli/src/lib.fe) | Native (`x86-64`) | Native Fe CLI (`explain`, `vectors`, `play`, `replay`, and `analyze` 2,500-state DP solver & agent simulator) |
| **`testkit`** | [ingots/testkit](./ingots/testkit/src/lib.fe) | EVM + Native | `SplitMix64` PRNG and 1,000-game dual-backend parity suite |
| **Oracle & Scripts** | [oracle/outlier_model.py](./oracle/outlier_model.py), `scripts/` | Python 3 / Bash | Independent bounded model checker, oracle conformance codegen, compile-fail & Fe mutation testers, live `anvil` E2E bridge |

### What Enforces What (Radical Honesty Table)

| Guarantee | Compiler-Enforced (`fe check`) | Runtime-Checked (`step` / `recv`) | Test / Model-Verified |
|---|---|---|---|
| Protocol core cannot touch storage, clock, caller, or I/O | ✅ No `uses` clause (`error[8-0036]`) | — | `scripts/check_compile_fail.sh` |
| Every `Phase` variant is handled | ✅ Exhaustive `match` (`error[8-0034]`) | — | `test_p12_phase_input_matrix_and_all_14_errors` |
| `Seat`, `Position`, `Colour`, `CommitmentHash` cannot be mixed | ✅ Distinct structs (`error[8-0000]`) | Validating `from_u8` / `from_word` constructors | Exhaustive decode tests |
| Forfeit settlement cannot depend on board positions (no timed-abort kingmaking, P5) | ✅ `settle_forfeit(mask, stake)` signature rejects `Positions` | — | `oracle/outlier_model.py` + `tests.fe` |
| Caller identity, turn ownership, deadlines (`<=` vs `>`), & 7-word commitment match | — | ✅ Checked inside `step`; reverts with 4-byte `#[error]` selector | All 14 errors verified via `evm.try_call` + `is_error<E>` |
| Conservation, bounded loss, survivor safety, unilateral & coalition abort non-profit (P1–P4, P13) | — | — | ✅ Exhaustive Fe test + `5,618`-state model checker + `9/9` Fe mutants killed |
| Zero rules drift between EVM contract and native binary (P10) | — | — | ✅ `1,000` seeded games on EVM & native + live `anvil` E2E event log replay |

> **Why 5,618 states, not 2,500 or more?** The model checker exhaustively explores the *protocol* (phases, deadlines, forfeits, payouts) at reduced parameters `FINISH=3, ROUND_CAP=5` to keep the search small; it was **not** run at the shipped `FINISH=4, ROUND_CAP=20`. The solver's `2,500` states are a different thing: the board states of the shipped game, used to compute Seat 0's best-response equity. Don't compare the two numbers.

### Threat Model (what the contract really does)

- **Copy / replay:** a commitment hashes `(domain tag, table address, game id, round, seat, colour, nonce)`, so a copied hash fails at reveal for another seat, round, game or table. Tested in `test_security_copy_commitment_round_replay_and_zero_stake`.
- **Last-revealer abort:** whoever stalls in Commit or Reveal forfeits their stake. Anyone can call `poke()` after the deadline. The forfeit split is computed from the set of stallers and the stake only, never from board positions (`settle_forfeit(mask, stake)`).
- **Reentrancy in `withdraw()`:** `owed` is set to zero before the external `send_value` call (checks-effects-interactions), and payouts are pull-based. There is no separate reentrancy lock, and no dedicated malicious-receiver test exists.
- **Timestamp reliance:** deadlines use `block.timestamp` (passed into `step` as `now`). Block producers can shift it slightly; the windows are 600 s (3,600 s for joining), so this is a small effect, but it is not eliminated.
- **Size:** `OutlierTable` runtime is 22,616 B against the EIP-170 limit of 24,576 B (from `fe build --emit sizes`).
- **Not covered:** no audit, no mainnet deployment, no fee or gas-griefing analysis.

---

## Build and Test

Verified with **`fe 26.6.0 (5b3f96a)`**, Foundry **`cast` / `anvil 1.9.0`**, and **`Python 3.13.7`** on Linux x86-64:

```sh
fe --version                                                                   # fe 26.6.0 (5b3f96a)
fe fmt --check ingots                                                          # Formatting check
fe check && fe check ingots/outlier_cli --backend native                       # Type-check both backends

# Run dual-backend unit, exhaustive, contract, and 1,000-game parity suites
fe test -i outlier_core && fe test -i outlier_core --backend native            # 8/8 core tests on EVM & native
fe test -i outlier_table                                                       # EVM contract + exact error selectors
fe test -i testkit && fe test -i testkit --backend native                      # 1,000-game parity (10 batches)
fe test -i outlier_cli --backend native                                        # Log v1 replay & tamper tests

# Build EVM contract artifacts (22,616 B runtime) and native CLI executable (332 KB)
fe build -i outlier_table --emit sizes,bytecode,abi --out-dir out
fe build -i outlier_cli --backend native --emit executable --out-dir out

# Run compile-fail (4/4), independent model checker (5,618 states), Fe mutation (9/9 killed), & live Anvil E2E bridge
./scripts/check_compile_fail.sh
python3 oracle/outlier_model.py --finish 3 --cap 5 --stake 3
python3 scripts/check_mutations.py
python3 scripts/anvil_replay_e2e.py
```

---

## Demo

### 1. Deterministic Full-Suite Demo (Recommended for Judges)
Run the entire deterministic demo in one non-interactive command (`make demo` or `./scripts/run_demo.sh`), which reproduces [demo/transcript.txt](./demo/transcript.txt) byte-for-byte:

```sh
./scripts/run_demo.sh
diff <(./scripts/run_demo.sh) demo/transcript.txt && echo "transcript reproduces"
```

### 2. Human-Speed Step-by-Step Visual Walkthrough (`--steps`)
To watch a game unfold round by round—showing the 3 sealed 7-word Keccak-256 commitment lockboxes, the opened colour cards, the odd-one-out outlier resolution, the live 3-lane race track (`[0] .. [4* WIN]`), and the 16-word hash-chain digest at every transition:

```sh
./scripts/walkthrough.sh              # press [Enter] to step through each round
./scripts/walkthrough.sh --auto 2.5   # auto-advance every 2.5s at human reading speed
./scripts/walkthrough.sh --forfeit    # step through the anti-kingmaking reveal stall & poke
./out/outlier_cli play --seed 1 --stake 1001 --steps --out demo/game1.log
```
*(Optional interactive mode: `./scripts/walkthrough.sh --play` lets you play Seat S0 against Bot S1 & Bot S2 and verifies your resulting `demo/human_game.log` through `./out/outlier_cli replay`.)*

What `./scripts/run_demo.sh` executes using the native Fe binary `./out/outlier_cli`:
1. **`./out/outlier_cli explain` & `./out/outlier_cli vectors`**: Prints protocol parameters and verifies embedded Foundry `cast` Keccak vectors (`COMMIT_VEC_0`, `COMMIT_VEC_1`, `DIGEST_JOIN_1`, `PARITY_BATCH_1_100`).
2. **`./out/outlier_cli play --seed 1 --stake 1001 --out demo/game1.log` → `./out/outlier_cli replay demo/game1.log`**: Plays a 6-round, 43-transition game to completion and independently verifies its hash-chained digest (`VERIFIED 43 transitions, final digest 0x9930ed42...`).
3. **`./out/outlier_cli play --seed 42 --stake 1001 --strategy forfeit --out demo/game2_forfeit.log` → `./out/outlier_cli replay demo/game2_forfeit.log`**: Demonstrates Seat 2 withholding their reveal on Round 2, triggering `POKE` after `REVEAL_WINDOW` and settling the odd stake `1001` into `(1502, 1501, 0)` (`VERIFIED 16 transitions`).
4. **Tamper Detection**: Corrupts 1 hex character at step 8 of `demo/game1.log` and runs `./out/outlier_cli replay` → exits non-zero with `DIVERGENCE at step 8: expected 0x48b61fd7...6a, got 0x48b61fd7...6c`.
5. **`./out/outlier_cli analyze` (Native Fe Solver & Strategic Simulator)**:
   - Exhaustively proves the 27-triple stage-game uniform indifference theorem (`2/9 = 22.22%` per colour).
   - Solves all `2,500` `(round, p0, p1, p2)` states by backward induction (`V(1,(0,0,0)) = 34.52%` for Seat 0 against opponents that follow a fixed policy: advance if that reaches `FINISH`, else push a leader sitting at `FINISH - 1`, else advance; this is a best-response value, not a Nash equilibrium) and prints the **Advance-vs-Push Decision Boundary Table**, uncovering the **3-Player Free-Rider Effect**: pushing a leader at `FINISH - 1 (3)` is optimal when the third player is at `0` (`(2,3,0)`: `PUSH(S1) = 44.84% > ADVANCE = 43.26%`), but advancing dominates when the third player is in contention (`(1,3,1)`: `ADVANCE = 28.07% > PUSH(S1) = 27.53%`).
   - Simulates 300 full commit-reveal games per regime (seeds `1..=300`, one run, no confidence interval) through `outlier_core::step`, showing a Laplace frequency-tracking agent increasing Seat 0's win rate from **`27.33%` → `46.00%`** against a `70%`-Red biased opponent (Seat 2 uniform) without breaking commitment hiding.

### Deep-Dive Documentation
- [docs/SPEC.md](./docs/SPEC.md) — Authoritative protocol specification, 15-word state layout, and properties P0–P13.
- [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) — Layered pure-core / thin-adapter architecture and honesty table.
- [docs/PATTERN.md](./docs/PATTERN.md) — Reusable Fe pattern guide with an illustrative (untested) sealed-bid auction sketch built on `outlier_core::commit_reveal`.
- [docs/ANALYSIS.md](./docs/ANALYSIS.md) — Full game-theoretic proofs, solver decision boundary analysis, and empirical simulation tables.
- [docs/FE_FINDINGS.md](./docs/FE_FINDINGS.md) — Fe 26.6.0 vs. Solidity comparison and compiler/codegen findings (including the 9,829-byte `#[inline(never)]` storage-adapter optimization).

---

## Limitations

- **Synchrony assumption (P4):** Abort-resistance assumes honest players can land a transaction within each phase window (`COMMIT_WINDOW = REVEAL_WINDOW = MOVE_WINDOW = 600s`, `JOIN_WINDOW = 3600s`). A player censored past a deadline forfeits.
- **Off-chain colour collusion & Sybil resistance:** As in any 3-player game without identity verification, two seats controlled by the same human (or coordinating colours via an off-chain side channel) cannot be prevented on-chain. What *is* verified (**P13**) is that no coalition causing all forfeits in a game can ever extract positive net profit (`coalition_net <= 0`).
- **Best-response MDP vs. full 3-player Nash equilibrium:** The native Fe solver computes exact backward-induction best-response values against a fixed opponent policy class and empirical Monte-Carlo rollouts; we do not claim a unique 3-player mixed-strategy Nash equilibrium.
- **Sequential single-table deployment:** Each `OutlierTable` instance runs one active game at a time (`game_id = 1, 2, ...` sequentially).

---

## Declaration

See [DECLARATION.md](./DECLARATION.md) for the complete declaration:
- **Pre-existing work:** None prior to November 3, 2026 (started from `fe-lang/builders-challenge-starter`).
- **Third-party code:** None (100% original Fe and Python test-oracle code written for this entry).
- **My role & AI assistance:** I chose the project direction, designed the three-player odd-one-out mechanism and anti-kingmaking invariants, completed the Fe starter guide to review the Fe implementation for structural/type correctness, and used my Python familiarity to treat the Python reference model (`oracle/outlier_model.py`) as my verification blueprint against the Fe code. I used AI tools (Claude and Google Antigravity) to accelerate drafting the specs/docs, writing the multi-ingot Fe implementation and Python model checker/scripts, and iterating on compiler/test loops.

---

## Team

- **David Timi** ([`DavidTimi1`](https://github.com/DavidTimi1))

---

## License

Apache-2.0 — see [LICENSE](./LICENSE).
