# ANALYSIS.md — Strategic & Game-Theoretic Analysis of OUTLIER

All numbers in this document are produced directly by the **native Fe solver** (`./out/outlier_cli analyze`, source in [ingots/outlier_cli/src/solver.fe](../ingots/outlier_cli/src/solver.fe)) and the **independent Python bounded model checker** ([oracle/outlier_model.py](../oracle/outlier_model.py)). Reproduce every table with:

```sh
./out/outlier_cli analyze
python3 oracle/outlier_model.py --finish 3 --cap 5 --stake 3
```

---

## 1. Stage-Game Uniform Indifference Theorem (Property P0)

In each round, three seated players (`S0, S1, S2`) simultaneously commit to a colour in `{Red=0, Blue=1, Green=2}`. Let `resolve(c0, c1, c2)` be the stage-game outcome function ([ingots/outlier_core/src/rules.fe](../ingots/outlier_core/src/rules.fe#L13-L28)):

| Category | Count (out of $3^3 = 27$) | Share | Details |
|---|---|---|---|
| **Winner combinations** | `18` | `2/3` (`66.67%`) | Exactly two players match; the **odd one out (the outlier)** wins (`6` triples per seat). |
| **No-winner (all same)** | `3` | `1/9` (`11.11%`) | `(R,R,R)`, `(B,B,B)`, `(G,G,G)`. |
| **No-winner (all distinct)** | `6` | `2/9` (`22.22%`) | All $3! = 6$ permutations of `(R,B,G)`. |

### Uniform Indifference Property
Fix Seat 0's colour $c_0 \in \{R, B, G\}$. Across the $3^2 = 9$ possible opponent pairs $(c_1, c_2)$:
- Seat 0 wins iff $c_1 = c_2 \neq c_0$, which occurs for **exactly 2 of the 9** opponent pairs (e.g., if $c_0 = R$, Seat 0 wins on $(B,B)$ and $(G,G)$).
- Therefore, against opponents who randomize uniformly ($(1/3, 1/3, 1/3)$), **every colour yields the exact same win probability of $2/9 \approx 22.22\%$**.

**Strategic implication:** Because the stage game is completely symmetric and uniform-indifferent against rational uniform play, **two sources of strategic edge** exist in OUTLIER:
1. **Positional movement decisions (`Move::Advance` vs `Move::Push(target)`)** on the progression track.
2. **Adaptive opponent modeling** when an opponent deviates from uniform colour selection.

---

## 2. Best-Response Value Iteration & the 3-Player Free-Rider Effect

We solve the exact best-response Markov Decision Process (MDP) for Seat 0 in **native Fe** ([ingots/outlier_cli/src/solver.fe](../ingots/outlier_cli/src/solver.fe)) using backward induction over all $20 \times 5 \times 5 \times 5 = 2,500$ non-terminal `(round, p0, p1, p2)` states (`FINISH = 4, PUSH = 1, ROUND_CAP = 20`) in fixed-point integer arithmetic (`SCALE = 1_000_000`, where `1_000_000 = 100.00%` pot share and a 3-way tie at `ROUND_CAP` pays `1/3 = 33.33%`).

Opponent baseline policy for `S1` and `S2`: advance if advancing reaches `FINISH (4)`; otherwise push the strict leader if that leader is at `FINISH - 1 (3)`; otherwise advance.

### Exact DP Initial Equity
- At the initial state `(round = 1, pos = (0,0,0))`, Seat 0's exact best-response equity is **`34.52%`** (a `+1.19%` edge over the `33.33%` symmetric baseline achieved solely through optimal Advance-vs-Push selection).

### Canonical Advance-vs-Push Decision Boundary Table (Round 5, Seat 0 Wins Round)

| Board State `(p0, p1, p2)` | Equity(`ADVANCE`) | Equity(`PUSH S1`) | Equity(`PUSH S2`) | Optimal Move | Strategic Mechanism |
|---|---|---|---|---|---|
| `(0, 0, 0)` | **`47.41%`** | `34.23%` | `34.23%` | **`ADVANCE`** | Early race: advancing builds own tempo; pushing at `0` is a clamped no-op. |
| `(2, 2, 2)` | **`57.56%`** | `41.75%` | `41.75%` | **`ADVANCE`** | Symmetric mid-game race: advancing to `3` reaches match point. |
| `(3, 3, 3)` | **`100.00%`** | `42.00%` | `42.00%` | **`ADVANCE`** | Advancing to `FINISH (4)` wins immediately. |
| `(0, 3, 0)` | `20.40%` | **`20.47%`** | `13.49%` | **`PUSH(S1)`** | **Defensive block:** `S1` is at match point (`3`) while `S2` is at `0`; blocking `S1` prevents an immediate loss. |
| `(2, 3, 0)` | `43.26%` | **`44.84%`** | `29.84%` | **`PUSH(S1)`** | **2-way race equalization (`+1.58%`):** With `S2` far behind at `0`, pushing `S1` from `3 → 2` creates a tied `(2,2,0)` board without helping `S2` and avoids becoming a `3`-position target. |
| `(1, 3, 1)` | **`28.07%`** | `27.53%` | `20.40%` | **`ADVANCE`** | **3-Player Free-Rider Effect:** Because `S2` is at `1`, spending your move to push `S1` is a public good that gifts free relative tempo to `S2`. Advancing yourself (`1 → 2`) dominates. |
| `(1, 2, 2)` | **`36.48%`** | `27.53%` | `27.53%` | **`ADVANCE`** | Catching up to `(2,2,2)` dominates pushing only one of two tied leaders. |
| `(2, 1, 3)` | **`42.66%`** | `29.84%` | `41.75%` | **`ADVANCE`** | Reaching match point (`3`) alongside `S2` (`(3,1,3)`) beats pushing `S2` (`(2,1,2)`) when `S1` is at `1`. |

> **Key Game-Theoretic Insight (The 3-Player Free-Rider Boundary):**
> Regressing an opponent (`Move::Push`) is only optimal when **one opponent is at match point (`FINISH - 1 = 3`) AND the third player is too far behind (`0`) to free-ride on the defensive block** (as in `(0,3,0)` and `(2,3,0)`). Whenever the third player is in contention (`(1,3,1)` or `(2,1,3)`), pushing the leader acts as an uncompensated public good for the third player, making personal advancement (`Move::Advance`) strictly superior.

*(Honesty note: These values are exact best-response MDP values against a fixed opponent policy class, not a claim of a unique 3-player Nash equilibrium.)*

---

## 3. Adaptive Opponent Modeling Under Cryptographic Commit-Reveal

Can an adaptive player exploit a colour-biased opponent without being able to peek at their commitment?
Suppose Seat 1 is biased toward Red (`70% Red, 15% Blue, 15% Green`) while Seat 2 plays uniformly (`1/3, 1/3, 1/3`).
- If Seat 0 plays Red (`c0 = Red`), Seat 0 only wins when `(S1, S2) ∈ {(B,B), (G,G)}`, which happens with probability $0.15 \times \frac{1}{3} + 0.15 \times \frac{1}{3} = \mathbf{10.00\%}$.
- If Seat 0 plays a non-Red colour (e.g., `c0 = Blue`), Seat 0 wins when `(S1, S2) ∈ {(R,R), (G,G)}`, which happens with probability $0.70 \times \frac{1}{3} + 0.15 \times \frac{1}{3} = \mathbf{28.33\%}$ (**nearly $3\times$ higher round-win rate!**).

Our native Fe simulator runs **300 full commit-reveal games per regime** through `outlier_core::step` (`seeds 1..=300`, `STAKE = 1001`):

| Regime | Seat 0 Strategy | Seat 1 Strategy | Seat 2 Strategy | Seat 0 Wins (`/300`) | Seat 1 Wins (`/300`) | Seat 2 Wins (`/300`) | Draws (`CapReached(None)`) | Avg Steps / Game |
|---|---|---|---|---|---|---|---|---|
| **A (Baseline)** | Uniform | Uniform | Uniform | `82` (`27.33%`) | `97` (`32.33%`) | `79` (`26.33%`) | `42` (`14.00%`) | `97` |
| **B (Unadapted)** | Uniform | Biased Red (`70%`) | Uniform | `102` (`34.00%`) | `87` (`29.00%`) | `80` (`26.67%`) | `31` (`10.33%`) | `97` |
| **C (Adaptive Exploiter)** | **Laplace Frequency Exploiter** | Biased Red (`70%`) | Uniform | **`138` (`46.00%`)** | `125` (`41.67%`) | `10` (`3.33%`) | `27` (`9.00%`) | `91` |

- **Result:** By maintaining Laplace-smoothed frequency counts of Seat 1's *previously revealed* colours and choosing `(argmax(s1_counts) + 1) % 3`, Seat 0 increases its full-game win rate from **`27.33%` (Regime A) / `34.00%` (Regime B) to `46.00%` (Regime C)** while commit-reveal cryptographically prevents any player from peeking at unrevealed moves in the current round.

---

## 4. Abort-Resistance & Anti-Kingmaking Verification (P1–P9, P13)

In simultaneous hidden-move protocols, the last revealer observes the earlier revealers' choices and is tempted to **withhold their reveal (abort)** if the round outcome is unfavorable, or to **kingmake** which opponent wins the pot.

OUTLIER eliminates both attacks structurally:
1. **Unilateral abort never beats honest play (P1–P4):** A player who misses a `Commit` or `Reveal` deadline forfeits their entire `STAKE` (`net = -STAKE`), which equals the worst possible honest-play net payoff (`-STAKE`), while survivors receive their own stake back plus `ceil(STAKE/2)` and `floor(STAKE/2)` (`net >= 0`).
2. **Stalling `WinnerMove` cannot grieve opponents:** A round winner who fails to submit a move before `MOVE_WINDOW` expires is defaulted to `Move::Advance` upon any permissionless `Poke`.
3. **Anti-kingmaking by type signature (P5):** `settle_forfeit(_ mask: u8, _ stake: u256) -> [u256; 3]` ([ingots/outlier_core/src/settle.fe](../ingots/outlier_core/src/settle.fe#L12-L59)) does **not** accept board `Positions` or `round` as arguments. A losing player cannot time an abort to steer the forfeited pot toward whichever opponent is currently leading on the board.
4. **Coalition forfeit non-profit (P13):** For any non-empty coalition $C \subseteq \{S_0, S_1, S_2\}$ that causes all forfeits in a game ($\text{mask} \subseteq C$), total coalition net profit is $\sum_{i \in C} (\text{payout}_i - \text{STAKE}) \le 0$ for all stakes (`0, 1, 2, 3, 1001`).

### Bounded Model Checker & Mutation Summary

| Verification Suite | Scope | Result |
|---|---|---|
| `oracle/outlier_model.py --finish 2 --cap 3` | Exhaustive BFS (`1,239` states, `3,115` transitions) | **P0–P9 & P13 hold** (longest path `27`, Tick/Poke `≤ 4`) |
| `oracle/outlier_model.py --finish 3 --cap 5` | Exhaustive BFS (`5,618` states, `14,252` transitions) | **P0–P9 & P13 hold** (longest path `43`, Tick/Poke `≤ 4`) |
| Oracle mutation testing | 7 deliberate spec mutations | **7/7 mutants killed (`100%`)** |
| `scripts/check_mutations.py` | 9 semantic mutations of Fe source (`ingots/outlier_core`) | **9/9 mutants killed (`100%`)** |
| `scripts/check_compile_fail.sh` | 4 negative Fe compilation fixtures | **4/4 rejected by `fe check` (`100%`)** |
