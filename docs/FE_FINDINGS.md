# FE_FINDINGS.md — Fe 26.6.0 Experience Report & Fe-vs-Solidity Comparison

Written from hands-on compilation and dual-target verification with **`fe 26.6.0 (5b3f96a)`**.

---

## 1. Where Fe 26.6.0 Genuinely Outperformed Solidity

### A. Dual EVM + Native Compilation of the Same Protocol Core (Zero Drift)
In Solidity, the on-chain contract and any off-chain replay verifier, CLI simulator, or game-theoretic solver must be written in two different languages (e.g., Solidity + TypeScript/Python/Rust), creating permanent drift risk around integer overflow, ABI packing, or Keccak padding.

In Fe 26.6.0, `core::intrinsic::__keccak_words` compiles to the native EVM `KECCAK256` opcode under `--backend sonatina` **and** executes natively under `--backend native`. As a result, [ingots/outlier_core](file:///home/devid/codes/projects/outlier-fe/ingots/outlier_core/src/lib.fe) is compiled into:
1. **`OutlierTable` (`22,616 B` EVM runtime bytecode)** — the on-chain referee and pull-payment escrow.
2. **`outlier_cli` (`332 KB` Linux x86-64 ELF binary)** — the off-chain simulator, `OUTLIER-LOG 1` replay verifier, and 2,500-state backward-induction value-iteration solver.

When we deployed `OutlierTable` on live Foundry `anvil` ([scripts/anvil_replay_e2e.py](file:///home/devid/codes/projects/outlier-fe/scripts/anvil_replay_e2e.py)) and piped the real emitted `Transition` event logs into `./out/outlier_cli replay`, the native binary verified all 31 transitions of Game #1 and all 9 time-warped forfeit transitions of Game #2 bit-for-bit on the first run.

### B. `uses` Effect System as an Architectural Firewall
In Solidity, nothing prevents a "pure" helper library or internal function from reading `block.timestamp`, `msg.sender`, or `address(this)` unless marked `pure`—and Solidity's `pure` cannot be composed with fine-grained host capabilities in off-chain tools.

In Fe 26.6.0:
- Every function in `ingots/outlier_core` has **no `uses` clause**. Attempting to call an effectful function fails with `error[8-0036]: missing effect Ctx` ([test/compile_fail/cf_01_pure_effect.fe](file:///home/devid/codes/projects/outlier-fe/test/compile_fail/cf_01_pure_effect.fe)).
- In `ingots/outlier_cli`, `pub fn main() uses (host: mut Host)` projects only the exact capabilities each subcommand is allowed to touch:
  - `cmd_explain`, `cmd_vectors`, `cmd_analyze`: `uses (out: mut Stdout)` (cannot read or write files, cannot exit early).
  - `cmd_replay`: `uses (args: Args, out: mut Stdout, err: mut Stderr, fs: Fs, proc: Exit)` — receives **read-only `fs: Fs`** rather than `mut Fs`, statically guaranteeing the replay verifier cannot modify the log file it is auditing.

### C. Payload `enum`s Directly in Contract Storage (Option A) + Exhaustive `match`
In Solidity, representing a phase machine where `WinnerMove` carries a `winner` seat and `deadline`, while `Finished` carries a 4-variant `GameResult` (`Won(Seat)`, `CapReached(Option<Seat>)`, `Forfeited(mask)`, `Cancelled(joined)`), requires a flat struct full of dead fields and sentinel zeros that can fall out of sync.

In Fe 26.6.0, payload `enum`s work directly inside contract storage fields (`mut state: GameState`):

```fe
pub enum Phase {
    Idle,
    Registration { pub deadline: u256 },
    Commit { pub round: u8, pub deadline: u256 },
    Reveal { pub round: u8, pub deadline: u256 },
    WinnerMove { pub round: u8, pub winner: Seat, pub deadline: u256 },
    Finished { pub result: GameResult },
}
```

Omitting any `Phase` variant in a `match` fails at compile time with `error[8-0034]: non-exhaustive patterns` ([test/compile_fail/cf_02_nonexhaustive_phase.fe](file:///home/devid/codes/projects/outlier-fe/test/compile_fail/cf_02_nonexhaustive_phase.fe)).

### D. Exact Custom Error Selector Testing Without Foundry Test Boilerplate
Fe 26.6.0's `#[error] pub struct BadReveal {}` + `std::evm::effects::revert_error` + `evm.try_call` + `std::evm::returndata::is_error<BadReveal>(out.returndata())` allowed us to test all 14 custom error selectors and assert state immutability on revert directly in `fe test` without needing bare, vacuous `#[test(should_revert)]` attributes.

---

## 2. Side-by-Side Comparison: Fe 26.6.0 vs Solidity

| Dimension | Solidity (`0.8.x`) | Fe (`26.6.0`) in OUTLIER |
|---|---|---|
| **Phase & result representation** | Flat `enum Phase { Idle, ... }` + separate `uint8 winner; uint8 resultKind; uint8 mask;` storage variables that can become inconsistent | Algebraic payload `enum Phase` & `enum GameResult` stored directly in `mut state: GameState`; illegal combinations are unconstructible |
| **Exhaustiveness** | `if / else if` chains on `enum` values silently miss newly added variants | `match state.phase` fails compilation (`error[8-0034]`) if any variant is unhandled |
| **Effect & storage isolation** | Modifiers and internal functions freely read `msg.sender`, `block.timestamp`, or storage unless manually audited | `uses (ctx, mut state, ...)` explicitly declares every capability; omitting `uses` on `outlier_core` is compiler-enforced (`error[8-0036]`) |
| **Off-chain replay & solver parity** | Must re-implement rules in TS/Python/Rust or spin up an EVM VM for every replay step | Same `outlier_core` compiles via `--backend native` into a `332 KB` native binary (`outlier_cli`) |
| **Anti-kingmaking forfeit rule** | Convention / code comment ("don't read `positions` in forfeit split") | `pub fn settle_forfeit(_ mask: u8, _ stake: u256)` signature rejects `Positions` at compile time (`cf_04_forfeit_takes_positions.fe`) |

---

## 3. Concrete Compiler & Toolchain Findings (Useful for the Fe Team)

1. **`#[inline(never)]` on Storage Adapter Helpers Saved 9,829 Bytes of Runtime Bytecode:**
   - When all 5 `recv TableMsg` handlers (`Join`, `Commit`, `Reveal`, `MakeMove`, `Poke`) directly loaded and stored `mut state: GameState` (a nested struct containing payload enums and fixed arrays), Sonatina emitted ~2,600 bytes of `SLOAD`/`SSTORE` unpacking/packing code *per handler*, pushing `OutlierTable` to `32,445 bytes` (above EIP-170's `24,576 B` limit).
   - Extracting a single `#[inline(never)] fn execute_transition(_ input: Input, _ stake_paid: u256) uses (ctx: Ctx, state: mut GameState, ...)` shared across the 5 handlers dropped runtime bytecode to **`22,616 bytes`** (`-9,829 bytes`, `-30.3%`) in one change.
   - *Suggestion for Sonatina/Fe codegen:* auto-outline composite storage struct load/store thunks when a storage field is accessed across multiple `recv` arms.

2. **`core::result::Result<E, T>` Type Parameter Order:**
   - Fe's `core::result::Result<E, T>` places the error type `E` first and the success type `T` second (opposite of Rust's `Result<T, E>`). Once discovered via `fe doc --builtins json`, it was completely consistent (`std::fs::Fs::read` returns `Result<Error, MemBuffer>`), Worth highlighting prominently in the Fe Getting Started guide for Rust developers.

3. **Visibility of Fields Inside `pub enum` Struct Variants:**
   - In Rust, fields of a `pub enum` variant inherit `pub` visibility automatically. In Fe 26.6.0, struct-variant fields inside a `pub enum` default to private unless explicitly marked `pub` (e.g., `Commit { pub round: u8, pub deadline: u256 }`). The compiler diagnostic (`error[2-0003]: round is not visible`) pointed directly to the definition line and made the fix trivial.

4. **`fe test` EVM Per-Test Gas Cap & Cheatcode Ergonomics:**
   - `fe test` enforces a `1,000,000,000` (1B) gas ceiling per `#[test]` function on the EVM backend. Running 1,000 full games in a single `#[test]` hit `OutOfGas(Basic)`, whereas partitioning into 10 `#[test]` functions of 100 games each ran across 8 parallel worker threads in `3.2s` on EVM (`0.6s` on `--backend native`).
   - `std::evm::effects::Evm` intentionally models pure EVM capabilities (`Ctx + RawOps + Log + Create + Call`) without Foundry-style `warp` or `prank` cheatcodes. Our explicit `StepCtx.now` design + 25-line `PlayerProxy` test contract + live `anvil` E2E script worked around this cleanly, though optional `evm.set_timestamp(...)` / `evm.set_caller(...)` methods on the test-only `Evm` struct would make timeout testing inside `fe test` even smoother.

