# ARCHITECTURE.md — OUTLIER

**Principle:** the EVM contract is a thin adapter around a pure, exhaustively tested Fe state machine. The **exact same Fe source** compiles to the EVM (`OutlierTable`) and to native executables (`outlier` CLI and solver).

---

## 1. Layered Architecture

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
        │          storage           │      │          Stderr, Fs        │
        │ thin msg/recv adapters     │      │ explain·play·replay·solve  │
        └────────────────────────────┘      └────────────────────────────┘
                         ▲
        ┌────────────────┴──────────────────────────────────────────────┐
        │ ingots/testkit (EVM + native, tests only):                    │
        │ SplitMix64, scripted game generator, golden digests           │
        └───────────────────────────────────────────────────────────────┘
        oracle/ (Python, test-side): independent model + test generators
```

Dependency direction: `outlier_core` depends on nothing of ours (only `core`). Adapters depend on `outlier_core`. Nothing depends on an adapter.

---

## 2. Workspace & Ingots (Decision D-01)

Multi-ingot Fe 26.6.0 workspace (`fe.toml` with `members = ["ingots/*"]`):

| Ingot | Target | Allowed effects | Contents |
|---|---|---|---|
| `outlier_core` | EVM + native | **none** on protocol functions | `params`, `types`, `errors`, `rules`, `commit_reveal`, `machine`, `settle`, `encode` |
| `outlier_table` | EVM | `Ctx`, `Log`, `Call`, contract storage | `OutlierTable` contract, `msg`/`recv`, `#[event]` structs, `#[error]` structs, `owed`/`withdraw` |
| `outlier_cli` | native | `Host` split into `Args`, `Stdout`, `Stderr`, `Fs` (read-only for `replay`) | `explain`, `play`, `replay`, `vectors`, `analyze` (native value-iteration solver + agent sims) |
| `testkit` | EVM + native | none (pure test utilities) | SplitMix64 PRNG, deterministic game-script generator, parity helpers |

`outlier_core::commit_reveal` has **zero OUTLIER-specific game logic**: it exposes a reusable `CommitmentHash` newtype, generic `CommitSlot<T>` (`Empty | Committed(CommitmentHash) | Revealed(T)`), and domain-separated 7-word `commit_hash` helper documented in `docs/PATTERN.md`.

---

## 3. Pure Core API (`ingots/outlier_core`)

Verified against Fe 26.6.0 (`core::result::Result<E, T>` has `Err` first, `Ok` second!):

```fe
// params.fe
pub const FINISH: u8 = 4
pub const PUSH: u8 = 1
pub const ROUND_CAP: u8 = 20
pub const JOIN_WINDOW: u256 = 3600
pub const COMMIT_WINDOW: u256 = 600
pub const REVEAL_WINDOW: u256 = 600
pub const MOVE_WINDOW: u256 = 600
pub const DOMAIN_TAG: u256 = 0x350026eb9d43d1ca67d039dd30760600db6ca312c02ce29ba9e06e098de9e370

// rules.fe (pure)
pub fn resolve(_ a: Colour, _ b: Colour, _ c: Colour) -> Outcome
pub fn apply_move(_ pos: Positions, winner: Seat, mv: Move) -> Result<StepError, Positions>
pub fn leader(_ pos: Positions) -> Option<Seat>

// commit_reveal.fe (pure, game-agnostic reusable module)
pub fn commit_hash(
    domain_tag: u256,
    table: u256,
    game_id: u256,
    round: u256,
    seat: u256,
    payload: u256,
    nonce: u256,
) -> CommitmentHash

// settle.fe (pure)
pub fn settle_forfeit(mask: u8, stake: u256) -> [u256; 3]   // NOTE: no positions/round parameter!
pub fn settle(result: GameResult, stake: u256) -> [u256; 3]

// machine.fe (pure)
pub fn step(state: GameState, input: Input, ctx: StepCtx) -> Result<StepError, StepOut>

// encode.fe (pure)
pub fn encode_state(_ s: GameState) -> [u256; 15]
pub fn digest_next(prev: u256, _ s: GameState) -> u256
```

---

## 4. Contract Adapter (`ingots/outlier_table`)

- **Storage strategy (D-03 = Option A, verified in Spike V9):** Fe 26.6.0 natively stores structs containing payload enums and fixed arrays (`mut game: GameState`), plus `mut digest: u256`, `stake: Wei`, and `mut owed: StorageMap<Address, Wei>`.
- **Thin adapter invariant (H2):** Every `recv` handler follows the exact 4-step pattern:
  1. Build `StepCtx { now: ctx.timestamp().as_seconds(), caller: ctx.caller().word(), table: ctx.address().word(), stake_paid: ctx.value().as_wei() }`.
  2. Call `outlier_core::step(game, input, step_ctx)`.
  3. On `Result::Err(e)` → `revert_step_error(e)` (maps each of the 14 `StepError` variants to its typed `#[error]` struct via `revert_error(...)`).
  4. On `Result::Ok(out)` → write `game = out.state`, update `digest = out.digest`, credit `owed` if `Finished`, emit input event + `Transition`.
- **Pull payments:** `withdraw()` reads `owed[caller]`, zeroes it first (checks-effects-interactions), then calls `call.send_value(...)`. Zero external calls happen inside any state transition.

---

## 5. Native CLI (`ingots/outlier_cli`) and Log Format v1

Subcommands:
- `outlier explain` (`uses (out: mut Stdout)`) — prints rules, constants, `DOMAIN_TAG`
- `outlier vectors` (`uses (out: mut Stdout)`) — self-checks embedded Foundry `cast` hash vectors
- `outlier play --seed N [--strategy ...] [--out <path>]` — runs deterministic game, prints readable trace, writes Log v1
- `outlier replay <log>` (`uses (out: mut Stdout, err: mut Stderr, fs: Fs)`) — recomputes digest chain using shared `outlier_core::step`; prints `VERIFIED <n> transitions, final digest 0x...` or `DIVERGENCE at step k: expected ..., got ...` (non-zero exit)
- `outlier analyze` (`uses (out: mut Stdout)`) — native Fe best-response value-iteration solver + biased-opponent simulation + Advance-vs-Push decision table

Log v1 format (line-based text):
```
OUTLIER-LOG 1
PARAMS finish=4 push=1 cap=20 stake=1001 join=3600 commit=600 reveal=600 move=600
TABLE 0x<hex>
GAME 1
IN 1 <ts> <caller-hex> JOIN                        -> 0x<digest-hex>
IN 4 <ts> <caller-hex> COMMIT 0x<hash-hex>         -> 0x<digest-hex>
IN 7 <ts> <caller-hex> REVEAL <colour> 0x<nonce>   -> 0x<digest-hex>
IN 10 <ts> <caller-hex> MOVE ADV|PUSH <seat>       -> 0x<digest-hex>
IN 11 <ts> <caller-hex> POKE                       -> 0x<digest-hex>
```

---

## 6. What Enforces What (Honesty Table — H4)

| Claim | Compiler-enforced | Runtime-checked | Test / model-verified |
|---|---|---|---|
| Protocol functions cannot touch storage, clock, caller, or I/O | ✅ No `uses` clause (`error[8-0036]`) | — | Compile-fail test |
| Every `Phase`/`Input` combination is handled | ✅ Exhaustive `match` (`error[8-0034]`) | — | P12 exhaustive table test |
| `Seat`, `Colour`, `Position`, `CommitmentHash` cannot be confused | ✅ Distinct structs (`error[8-0000]`) | Validating constructors reject bad raw values | Compile-fail + decode tests |
| Forfeit settlement cannot depend on positions or round | ✅ `settle_forfeit(mask, stake)` lacks those params | — | P5 oracle + Fe test |
| Caller identity / turn ownership | — | ✅ In `step` | Exact-selector revert tests |
| Deadlines (`<=` action vs `>` poke) | — | ✅ In `step` | P9, P12, `anvil` time-warp test |
| Reveal matches 7-word Keccak commitment | — | ✅ In `step` | P11 + `cast` vectors |
| Money conservation & pull-payment safety | — | — | P2 + contract `withdraw` tests |
| Termination & liveness | — | — | P6, P8, P9 (oracle) |
| EVM contract and native binary agree | — | — | P10 parity (1,000+ scripts + `anvil` log bridge) |

