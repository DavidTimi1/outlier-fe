# PATTERN.md — Reusable Fe Pattern: Simultaneous Hidden Moves with Abort-Resistant Forfeits & Zero-Drift Replay

OUTLIER is designed so that future Fe builders can pick up its core pattern for **any multi-party hidden-move protocol** — including sealed-bid auctions, commit-reveal voting, MEV-resistant order batching, and peer-to-peer games.

---

## 1. The Four Pillars of the Pattern

1. **Game-Agnostic 7-Word Domain-Separated Commit-Reveal ([ingots/outlier_core/src/commit_reveal.fe](../ingots/outlier_core/src/commit_reveal.fe)):**
   - Every commitment binds `(domain_tag, context/contract_addr, session_id, round, participant_seat, choice_payload, nonce_256bit)` via `core::intrinsic::__keccak_words`.
   - Omitting `participant_seat` allows a copy-attack (Player B copies Player A's commitment hash); omitting `session_id` or `round` allows a replay attack; omitting `context` or `domain_tag` allows cross-contract collisions.
   - Hash `0` is rejected at the type boundary (`CommitmentHash::from_word(0) -> Option::None`) so an uninitialized storage word can never collide with a valid commitment.

2. **Pure Protocol State Machine (`step`) with Explicit `StepCtx` ([ingots/outlier_core/src/machine.fe](../ingots/outlier_core/src/machine.fe)):**
   - The entire protocol transition table (`step(state, prev_digest, input, ctx) -> Result<StepError, StepOut>`) has **no `uses` clause**.
   - All ambient EVM quantities (`now`, `caller`, `table`, `stake_paid`) are passed in via `StepCtx`.
   - Because `step` is pure and uses `core::intrinsic::__keccak_words`, **the exact same Fe source compiles to an EVM contract (`--backend sonatina`) and a native verifier/CLI/solver (`--backend native`) with zero code drift**.

3. **Non-Overlapping Deadlines & Position-Free Forfeit Settlement ([ingots/outlier_core/src/settle.fe](../ingots/outlier_core/src/settle.fe)):**
   - Every timed phase sets `deadline = now_at_entry + WINDOW`.
   - Participant actions require `now <= deadline` (else `DeadlinePassed`); permissionless timeout `Poke` requires `now > deadline` (else `DeadlineNotPassed`). There is no gap and no overlap.
   - `settle_forfeit(mask: u8, stake: u256)` does **not** accept protocol progress or board positions in its signature, guaranteeing at the type level that a losing participant cannot time an abort to kingmake a preferred survivor.

4. **Hash-Chained Canonical State Digest (`digest_next`) ([ingots/outlier_core/src/encode.fe](../ingots/outlier_core/src/encode.fe)):**
   - Every transition emits the input event plus `Transition { game_id, step_no, ts, digest }`, where `digest_n = __keccak_words([digest_{n-1}, w0..w14])`.
   - An off-chain verifier only needs the input trace and claimed digests: it re-runs `step` natively and reports either `VERIFIED` or the exact `DIVERGENCE at step k`.

---

## 2. Illustrative Example: 2-Bidder Sealed-Bid Auction in 18 Lines of Fe

> **Illustrative only.** This auction sketch is not in the workspace and has no test. Only the `commit_reveal` module it builds on is tested (in `outlier_core` and via the game).

`outlier_core::commit_reveal` has **zero dependency on OUTLIER's game rules**. You can import `CommitmentHash`, `CommitSlot`, `commit_hash`, and `verify_commit` directly into a sealed-bid auction or governance module:

```fe
use outlier_core::{CommitSlot, CommitmentHash, commit_hash, verify_commit}

// keccak256("SEALED_AUCTION_V1")
pub const AUCTION_DOMAIN: u256 = 0x71a8b51d93f3b6a91d28e2b2009a585118116e5a8dc5816b61b70492340b7123

pub fn make_bid_commit(auction_addr: u256, auction_id: u256, bidder: u256, bid_wei: u256, salt: u256) -> CommitmentHash {
    commit_hash(
        domain_tag: AUCTION_DOMAIN,
        context: auction_addr,
        session_id: auction_id,
        round: 1,
        participant: bidder,
        choice: bid_wei,
        nonce: salt,
    )
}

pub fn reveal_bid(slot: CommitSlot<u256>, auction_addr: u256, auction_id: u256, bidder: u256, bid_wei: u256, salt: u256) -> Option< CommitSlot<u256> > {
    match slot {
        CommitSlot::Committed { hash } => {
            if verify_commit(stored: hash, domain_tag: AUCTION_DOMAIN, context: auction_addr, session_id: auction_id, round: 1, participant: bidder, choice: bid_wei, nonce: salt) {
                Option::Some(CommitSlot::Revealed { value: bid_wei })
            } else {
                Option::None
            }
        },
        _ => Option::None,
    }
}
```

---

## 3. Checklist for Adapting This Pattern to Your Protocol

- [ ] **Define a unique `DOMAIN_TAG`** (`cast keccak "YOUR_PROTOCOL_V1"`) and include `ctx.address().word()` (`context`), `session_id`, `round`, and `participant` in every `commit_hash` call.
- [ ] **Keep your `step` function effect-free** (no `uses` clause) and verify it with a compile-fail test (`error[8-0036]`).
- [ ] **Deduplicate contract storage loads/stores** into a single `#[inline(never)] fn execute_transition(...)` helper in your contract adapter (saved **9,829 bytes** of runtime bytecode in `OutlierTable`).
- [ ] **Use pull payments (`owed` + `withdraw()`)** so no external `call.send_value` ever runs inside a state transition.

