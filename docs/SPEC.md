# OUTLIER — Specification v1.0 (authoritative)

**Status:** locked defaults. Change only via an ADR in `docs/DECISIONS.md`, and regenerate oracle vectors and golden digests in the same commit.
**Executable counterpart:** [oracle/outlier_model.py](../oracle/outlier_model.py) implements this spec independently and checks properties P0–P9 and P13 exhaustively for small parameters (see §12 for what was actually run).
**Notation:** MUST / MUST NOT are requirements on the implementation. "Seat" = player slot 0, 1, 2.

---

## 1. Overview

Three players each secretly choose a colour (Red, Blue, Green) using commit-reveal. If exactly two colours match, the **odd one out (the outlier) wins the round**. Otherwise nobody wins. The round winner then moves: advance themselves, or push one opponent back. First to the finish line wins. Every phase has a deadline; missing one forfeits.

The whole protocol (permission checks, deadlines, forfeits, settlement) is **one pure function**, `step`. The EVM contract and the native CLI are thin adapters around it.

## 2. Parameters

All live in one file (`ingots/outlier_core/src/params.fe`) as `pub const`s. No magic numbers anywhere else, including tests (tests iterate over `0..=FINISH` etc.).

| Name | Default | Notes |
|---|---|---|
| `FINISH` | `4` | Position that wins immediately. Positions are `0..=FINISH`. |
| `PUSH` | `1` | Cells an opponent is pushed back (saturating at `0`). |
| `ROUND_CAP` | `20` | Max rounds started. Guarantees termination. |
| `STAKE` | contract config; tests use an **odd** value (e.g. `3` or `1001`) | Odd stake exercises the dust rule. `0` is legal and means "no money" (Tier A). |
| `JOIN_WINDOW` | `3600` s | Registration deadline after first join. |
| `COMMIT_WINDOW` | `600` s | |
| `REVEAL_WINDOW` | `600` s | |
| `MOVE_WINDOW` | `600` s | |

Tuning: after the native Fe solver (Stage S5) reports game-length and cap-hit statistics, `FINISH`/`PUSH`/`ROUND_CAP` MAY be retuned once, by ADR. Windows must stay ≥ 60 s (block timestamps can skew by seconds).

## 3. Types

| Type | Definition |
|---|---|
| `Colour` | `Red=0, Blue=1, Green=2`. Raw values > 2 MUST be rejected with `InvalidColour` at the decode boundary. |
| `Seat` | `S0=0, S1=1, S2=2` (validated newtype). |
| `Position` | integer in `0..=FINISH` (validated newtype). |
| `Positions` | one `Position` per seat. Initial `(0, 0, 0)`. |
| `Outcome` | `NoWinner` or `Winner(Seat)`. |
| `Move` | `Advance` or `Push(Seat)`. `Push(t)` requires `t != winner`. |
| `SeatState` | `Empty`, `Committed { hash }`, `Revealed { colour }`. |
| `Phase` | `Idle`, `Registration { deadline }`, `Commit { round, deadline }`, `Reveal { round, deadline }`, `WinnerMove { round, winner, deadline }`, `Finished { result }`. |
| `GameResult` | `Won(Seat)`, `CapReached { leader: Option<Seat> }`, `Forfeited { mask }`, `Cancelled { joined }`. `mask` = non-empty 3-bit set of seats (`1..=7`). |
| `Input` | `Join`, `Commit { hash }`, `Reveal { colour_raw, nonce }`, `MoveInput { mv }`, `Poke`. |
| `StepCtx` | `{ now, caller, table, stake_paid }` — everything ambient, passed explicitly. |

`Phase` payloads make illegal combinations unconstructible: there is no `WinnerMove` without a winner, no `Finished` without a result. Anything with a numeric invariant (`Position`, `Seat`, `Colour`) is built through a validating constructor.

## 4. Round rules

`resolve(c0, c1, c2) -> Outcome`:
- all equal → `NoWinner`
- all distinct → `NoWinner`
- exactly two equal → `Winner(seat holding the different colour)`

Exhaustive facts (the Fe test MUST assert all of them; the oracle already does): 27 combinations = **18 winner + 9 no-winner** (3 all-same + 6 all-distinct); **6 wins per seat**; for a fixed own colour against all 9 opponent combinations, each seat wins exactly **2 of 9** (so against uniform opponents every colour is equally good).

`apply_move(positions, winner, mv)`:
- `Advance`: `positions[winner] = min(FINISH, positions[winner] + 1)`
- `Push(t)`: requires `t != winner` (else `InvalidMove`); `positions[t] = max(0, positions[t] - PUSH)` — **saturating, never underflows**. Pushing a player at `0` is a legal no-op.

## 5. State machine

### 5.1 Time semantics (exact)

A timed phase has `deadline = now_at_entry + WINDOW`.
- An action input is valid iff `now <= deadline`; otherwise `DeadlinePassed`.
- `Poke` is valid iff `now > deadline`; otherwise `DeadlineNotPassed`.

These conditions are mutually exclusive and exhaustive: no gap, no overlap. `Poke` may be sent by **anyone**.

### 5.2 Transition table

`step(state, input, ctx) -> Result<StepError, StepOut>` (note Fe 26.6.0 `core::result::Result<E, T>`). A failed step MUST leave state unchanged (on-chain: revert with typed custom error).

**Idle / Finished** (a new game may start from either; `game_id` increments, starting at 1; `step_no` resets to 1 on first transition of the new game; `digest` chains from `0` per game)
| Input | Effect |
|---|---|
| `Join` | Requires `stake_paid == stake` else `WrongStake`. Seat 0 = caller. Positions `(0,0,0)`, seats empty, `joined = 1`, `round = 0`, `step_no = 1`, `game_id += 1`. → `Registration { deadline = now + JOIN_WINDOW }`. |
| any other | `Idle`: `WrongPhase`. `Finished`: `GameFinished`. |

**Registration**
| Input | Effect |
|---|---|
| `Join` | `DeadlinePassed` if `now > deadline`. `DuplicatePlayer` if caller already seated. `WrongStake` if `stake_paid != stake`. Seat = next free (`1` or `2`). If 3 seated → `Commit { round = 1, deadline = now + COMMIT_WINDOW }`. |
| `Poke` | If `now <= deadline` → `DeadlineNotPassed`. Else → `Finished(Cancelled { joined })`. |
| other | `WrongPhase` |

**Commit { round, deadline }**
| Input | Effect |
|---|---|
| `Commit { hash }` | `NotAPlayer` if caller unseated. `DeadlinePassed` if `now > deadline`. `AlreadyCommitted` if seat not `Empty`. `InvalidCommitment` if `hash == 0`. Stores hash. When all three committed → `Reveal { round, deadline = now + REVEAL_WINDOW }`. |
| `Poke` | If `now <= deadline` → `DeadlineNotPassed`. Else → `Finished(Forfeited { mask = seats still Empty })`. |
| other | `WrongPhase` |

**Reveal { round, deadline }**
| Input | Effect |
|---|---|
| `Reveal { colour_raw, nonce }` | `NotAPlayer`. `DeadlinePassed`. `AlreadyRevealed`. `InvalidColour` if `colour_raw > 2`. `BadReveal` if `commitment(table, game_id, round, seat, colour, nonce) != stored hash`. Otherwise seat → `Revealed { colour }`. When all three revealed: `resolve`. `NoWinner`: if `round == ROUND_CAP` → `Finished(CapReached { leader })` else `Commit { round + 1, deadline = now + COMMIT_WINDOW }` with all seats reset to `Empty`. `Winner(w)`: → `WinnerMove { round, winner: w, deadline = now + MOVE_WINDOW }`. |
| `Poke` | If `now <= deadline` → `DeadlineNotPassed`. Else → `Finished(Forfeited { mask = seats still Committed })`. |
| other | `WrongPhase` |

**WinnerMove { round, winner, deadline }**
| Input | Effect |
|---|---|
| `MoveInput { mv }` | `NotAPlayer` if unseated; `NotYourMove` if caller is not `winner`; `DeadlinePassed`; `InvalidMove` if `Push(winner)`. Apply `apply_move`. Then: `positions[winner] == FINISH` → `Finished(Won(winner))`; else `round == ROUND_CAP` → `Finished(CapReached { leader })`; else `Commit { round + 1, deadline = now + COMMIT_WINDOW }` (seats reset). |
| `Poke` | If `now <= deadline` → `DeadlineNotPassed`. Else apply default `Advance` as if the winner chose it, then the same continuation. A winner who stalls therefore cannot hurt anyone. |
| other | `WrongPhase` |

`leader` = the seat with the strictly highest position, or `None` if the maximum is shared.

### 5.3 Why a forfeit ends the game

Removing one player breaks the three-player odd-one-out rule. Ending the game keeps the state space small and the settlement rule auditable.

## 6. Settlement (pure, money-free)

`settle(result, stake) -> Payouts` returns gross payout per seat `[u256; 3]`. **Sum of payouts always equals total deposited.**

| Result | Payout |
|---|---|
| `Won(w)` | `3·stake` to `w`, `0` to others |
| `CapReached { Some(l) }` | `3·stake` to `l`, `0` to others |
| `CapReached { None }` | refund each own `stake` (draw) |
| `Forfeited` with 3 seats in mask | refund all (nobody can be blamed over anyone else) |
| `Forfeited` with 2 seats in mask | the single survivor takes `3·stake` |
| `Forfeited` with 1 seat in mask | forfeiter gets `0`. Each survivor gets own stake back **plus** half of forfeiter's stake: **lower-indexed survivor receives `stake + (stake - stake / 2)` (`ceil(stake/2)`), higher receives `stake + stake / 2` (`floor(stake/2)`)** |
| `Cancelled { joined }` | each seated joiner (`0..joined`) refunded `stake` |

The forfeit rows depend **only on the mask**. In Fe, `settle_forfeit(mask, stake)` does not accept positions or round: "a timed abort cannot favour a particular opponent" is true **by type**, not by convention (P5).

Pull payments: the contract credits `owed[address] += payout` inside the transition that enters `Finished` and sends ETH only in a separate `withdraw()` (checks-effects-interactions; zero external calls inside a state transition).

## 7. Commitment

```
commitment = keccak256(abi.encode(
    DOMAIN_TAG,      // keccak256("OUTLIER_V1") = 0x350026eb9d43d1ca67d039dd30760600db6ca312c02ce29ba9e06e098de9e370
    table,           // contract address as u256 word
    game_id,
    round,
    seat,            // 0..2
    colour,          // 0..2
    nonce            // 256-bit random
))                   // 7 words × 32 bytes = 224 bytes
```

- `seat` binds the commitment to a player (prevents copying another player's hash).
- `round` and `game_id` prevent replaying old reveals.
- `table` + `DOMAIN_TAG` give domain separation.
- `nonce` MUST be 256-bit uniformly random, chosen by the client.
- Implemented in Fe via `core::intrinsic::__keccak_words([DOMAIN_TAG, table, game_id, round, seat, colour, nonce])`, which matches Foundry `cast keccak $(cast abi-encode ...)` byte-for-byte on both EVM (`sonatina`) and `native` backends.
- Hash `0` is reserved for "empty".

## 8. Events and the canonical digest chain

Every successful transition emits:
- one **input event** carrying the input: `Joined { caller }`, `Committed { seat, hash }`, `Revealed { seat, colour, nonce }`, `MoveMade { seat, kind, target }` / `MoveDefaulted { seat }`, `Poked { caller }`; and
- one `Transition { game_id, step_no, ts, digest }`.

`digest` is a hash chain: `digest_n = keccak_words([digest_{n-1}, w0, ..., w14])` (16 words total), with `digest_0 = 0` at the start of each game, where `w0..w14` are the 15 canonical words of the state **after** the transition:

| Word | Content |
|---|---|
| `w0` | `game_id` |
| `w1` | `step_no` |
| `w2` | phase tag: `Idle=0, Registration=1, Commit=2, Reveal=3, WinnerMove=4, Finished=5` |
| `w3` | `deadline` (`0` if none) |
| `w4` | `round` |
| `w5` | positions packed: `p0 | (p1 << 8) | (p2 << 16)` |
| `w6` | `(winner+1) | (result_tag << 8) | (result_data << 16)`; `result_tag`: `Won=1, Cap=2, Forfeited=3, Cancelled=4`; `result_data`: `seat` / `leader+1` (0 for None) / `mask` / `joined` |
| `w7` | seat states: 2 bits per seat (`Empty=0, Committed=1, Revealed=2`) `| (revealed colours: 2 bits per seat) << 8` |
| `w8–w10` | stored commitment hash per seat (`0` if none) |
| `w11–w13` | player address per seat as a `u256` word (`0` if none) |
| `w14` | `joined` count |

## 9. Errors

14 typed errors:
`WrongPhase`, `GameFinished`, `NotAPlayer`, `NotYourMove`, `DuplicatePlayer`, `WrongStake`, `DeadlinePassed`, `DeadlineNotPassed`, `AlreadyCommitted`, `AlreadyRevealed`, `InvalidCommitment`, `InvalidColour`, `BadReveal`, `InvalidMove`.

Each MUST have: a positive trigger test, an exact error/selector check (`is_error<E>(outcome.returndata())` on EVM), and a state-unchanged assertion.

## 10. Properties

| ID | Property | Verified by |
|---|---|---|
| P0 | Stage game: 18/9/3/6, 6 per seat, 2 of 9 per own colour | oracle + Fe exhaustive test |
| P1 | Bounded loss: no player's net payoff < `-stake` | oracle + Fe test over all `GameResult`s |
| P2 | Conservation: Σ payouts = Σ deposits | oracle + Fe test |
| P3 | Non-forfeiter never has negative net payoff due to others' forfeits | oracle + Fe test |
| P4 | Unilateral forfeit never beats honest play (`-stake <= worst_honest_net`, assuming synchrony) | oracle + Fe test |
| P5 | Forfeit settlement is independent of positions and round (no kingmaking by timed abort) | oracle + **type-level** (`settle_forfeit` signature) |
| P6 | Liveness: from every reachable state, `Finished` is reachable | oracle |
| P7 | Invariants: positions ≤ `FINISH`, round ≤ `ROUND_CAP`, `WinnerMove` always has a winner | oracle + Fe property tests |
| P8 | Termination: transition graph is acyclic; non-Tick inputs per game ≤ `3 + 7·ROUND_CAP + 1` | oracle + analytic bound |
| P9 | Timeout-completeness: from any non-idle state, `Tick`/`Poke` alone reach `Finished` in ≤ 4 steps | oracle |
| P10 | Replay determinism: identical inputs ⇒ identical digest chain on EVM and native | golden digests on 1,000+ seeded games |
| P11 | Commitment binding: changing any of `game_id`/`round`/`seat`/`colour`/`nonce`/`table` fails verification; matches `cast` vectors | Fe tests + `cast` vectors |
| P12 | Every `(phase, input)` pair is either a specified transition or a specified error | exhaustive table test |
| P13 | No coalition that causes every forfeit in a game profits from it (`coalition_net <= 0`) | oracle + Fe test over all masks & coalitions |

## 11. Assumptions and Limitations

- **Synchrony (P4):** an honest player can land a transaction inside each window. Windows are ≥ 60 s. Censorship past a deadline forfeits.
- **Collusion via side channels:** off-chain colour coordination in a 3-player game cannot be prevented on-chain and is NOT claimed prevented. Only P13 (forfeit-induced coalition profit ≤ 0) is verified.
- **Sybil:** one human controlling two seats via two addresses cannot be prevented on-chain; only duplicate addresses are rejected.
- **Single table:** one active game per contract deployment; games run sequentially.
- **Timestamp skew:** validator timestamp skew of a few seconds is negligible relative to windows ≥ 60 s.
- **Equilibria:** solver reports exact best-response MDPs against fixed opponent policies and empirical iterated best-response / Monte-Carlo results, NOT unique 3-player Nash equilibria.

## 12. Executable Oracle Baseline (`oracle/outlier_model.py`)

Verified on 2026-11-19 with `python3 oracle/outlier_model.py` (Python 3.13.7, stdlib only):

| Params | Reachable states | Transitions | Longest run (incl. Ticks) | Tick/Poke bound |
|---|---|---|---|---|
| `FINISH=2, PUSH=1, CAP=3, STAKE=3` | `1,239` | `3,115` | `27` | `≤ 4` |
| `FINISH=3, PUSH=1, CAP=5, STAKE=3` | `5,618` | `14,252` | `43` | `≤ 4` |

P0–P9 and P13 all passed across `STAKE ∈ {0, 1, 2, 3, 1001}`. Mutation check: **7/7 deliberate spec mutants killed** (all-distinct counted as winner; leader-favoured forfeit split; free abort; missing default move on timeout; unclamped push underflow; disabled round cap; dust creation).

