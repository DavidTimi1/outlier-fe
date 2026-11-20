#!/usr/bin/env python3
"""
Independent executable reference model for OUTLIER (docs/SPEC.md v1.0).

Implements the OUTLIER protocol independently from SPEC.md (never ported from Fe)
and exhaustively verifies properties P0-P9 and P13 over the reachable state space
for configurable small parameters (e.g. FINISH=2, CAP=3; FINISH=3, CAP=5).
"""

from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass
from itertools import combinations, product
from typing import Dict, Iterable, List, Optional, Tuple

SEATS = (0, 1, 2)
COLOURS = (0, 1, 2)  # Red=0, Blue=1, Green=2
ADV = ("ADV",)

# Configurable globals (overridden via CLI)
FINISH = 2
PUSH = 1
ROUND_CAP = 3
STAKE = 3
MAX_STATES = 3_000_000


def resolve(a: int, b: int, c: int) -> Optional[int]:
    """Return winning seat (0, 1, 2) if exactly two match, else None."""
    if a == b and b == c:
        return None
    if a != b and b != c and a != c:
        return None
    if a == b:
        return 2
    if a == c:
        return 1
    return 0


def leader(pos: Tuple[int, int, int]) -> Optional[int]:
    """Return seat with strictly highest position, or None if tied."""
    mx = max(pos)
    leaders = [s for s in SEATS if pos[s] == mx]
    return leaders[0] if len(leaders) == 1 else None


def settle_forfeit(mask: int, stake: int) -> List[int]:
    """Pure forfeit settlement depending ONLY on forfeit bitmask and stake (P5)."""
    assert 1 <= mask <= 7
    f = [s for s in SEATS if (mask >> s) & 1]
    o = [s for s in SEATS if not ((mask >> s) & 1)]
    out = [0, 0, 0]
    if len(f) == 3:
        return [stake, stake, stake]
    if len(f) == 2:
        out[o[0]] = 3 * stake
        return out
    # len(f) == 1: forfeiter gets 0; lower-indexed survivor gets ceil(S/2), higher gets floor(S/2)
    out[o[0]] = stake + (stake - stake // 2)
    out[o[1]] = stake + (stake // 2)
    return out


def settle(result: Tuple, stake: int) -> List[int]:
    """Return gross payouts per seat [p0, p1, p2]."""
    kind = result[0]
    if kind == "WON":
        w = result[1]
        out = [0, 0, 0]
        out[w] = 3 * stake
        return out
    if kind == "CAP":
        ldr = result[1]
        if ldr is None:
            return [stake, stake, stake]
        out = [0, 0, 0]
        out[ldr] = 3 * stake
        return out
    if kind == "FORFEIT":
        return settle_forfeit(result[1], stake)
    if kind == "CANCEL":
        joined = result[1]
        return [stake if s < joined else 0 for s in SEATS]
    raise ValueError(f"unknown result: {result}")


@dataclass(frozen=True)
class St:
    phase: str  # IDLE, REG, COMMIT, REVEAL, MOVE, FIN
    joined: int  # 0..3
    rnd: int  # 0..ROUND_CAP
    pos: Tuple[int, int, int]
    # In COMMIT: None or 1 (committed); in REVEAL: None (committed, unrevealed) or colour (0/1/2)
    seats: Tuple[Optional[int], Optional[int], Optional[int]]
    winner: int  # -1 if none, else 0..2
    expired: bool
    result: Optional[Tuple] = None


INIT = St(
    phase="IDLE",
    joined=0,
    rnd=0,
    pos=(0, 0, 0),
    seats=(None, None, None),
    winner=-1,
    expired=False,
    result=None,
)


def _after_move(st: St, w: int, mv: Tuple) -> St:
    pos = list(st.pos)
    if mv[0] == "ADV":
        pos[w] = min(FINISH, pos[w] + 1)
    elif mv[0] == "PUSH":
        t = mv[1]
        assert t != w
        pos[t] = max(0, pos[t] - PUSH)
    else:
        raise ValueError(mv)
    npos = (pos[0], pos[1], pos[2])
    if npos[w] == FINISH:
        return St("FIN", 3, st.rnd, npos, (None, None, None), -1, False, ("WON", w))
    if st.rnd >= ROUND_CAP:
        return St("FIN", 3, st.rnd, npos, (None, None, None), -1, False, ("CAP", leader(npos)))
    return St("COMMIT", 3, st.rnd + 1, npos, (None, None, None), -1, False, None)


def transitions(st: St) -> Iterable[Tuple[str, St]]:
    """Yield (label, next_state) for every valid transition from st."""
    if st.phase == "FIN":
        return

    if st.phase == "IDLE":
        yield ("Join(0)", St("REG", 1, 0, (0, 0, 0), (None, None, None), -1, False, None))
        return

    # Timed phases: can always Tick (advance past deadline) if not yet expired
    if not st.expired:
        yield ("Tick", St(st.phase, st.joined, st.rnd, st.pos, st.seats, st.winner, True, None))

    if st.phase == "REG":
        if not st.expired:
            nj = st.joined + 1
            if nj == 3:
                yield ("Join(2)", St("COMMIT", 3, 1, (0, 0, 0), (None, None, None), -1, False, None))
            else:
                yield (f"Join({st.joined})", St("REG", nj, 0, (0, 0, 0), (None, None, None), -1, False, None))
        else:
            yield ("Poke", St("FIN", st.joined, 0, st.pos, (None, None, None), -1, False, ("CANCEL", st.joined)))
        return

    if st.phase == "COMMIT":
        if not st.expired:
            for s in SEATS:
                if st.seats[s] is None:
                    ns = list(st.seats)
                    ns[s] = 1
                    nts = (ns[0], ns[1], ns[2])
                    if all(x is not None for x in nts):
                        # Transition to REVEAL: seats reset to None (meaning committed, not yet revealed)
                        yield (f"Commit({s})", St("REVEAL", 3, st.rnd, st.pos, (None, None, None), -1, False, None))
                    else:
                        yield (f"Commit({s})", St("COMMIT", 3, st.rnd, st.pos, nts, -1, False, None))
        else:
            mask = sum((1 << s) for s in SEATS if st.seats[s] is None)
            assert mask > 0
            yield ("Poke", St("FIN", 3, st.rnd, st.pos, (None, None, None), -1, False, ("FORFEIT", mask)))
        return

    if st.phase == "REVEAL":
        if not st.expired:
            for s in SEATS:
                if st.seats[s] is None:
                    for c in COLOURS:
                        ns = list(st.seats)
                        ns[s] = c
                        nts = (ns[0], ns[1], ns[2])
                        if all(x is not None for x in nts):
                            w = resolve(nts[0], nts[1], nts[2])  # type: ignore[arg-type]
                            if w is None:
                                if st.rnd >= ROUND_CAP:
                                    yield (
                                        f"Reveal({s},{c})",
                                        St("FIN", 3, st.rnd, st.pos, (None, None, None), -1, False, ("CAP", leader(st.pos))),
                                    )
                                else:
                                    yield (
                                        f"Reveal({s},{c})",
                                        St("COMMIT", 3, st.rnd + 1, st.pos, (None, None, None), -1, False, None),
                                    )
                            else:
                                yield (
                                    f"Reveal({s},{c})",
                                    St("MOVE", 3, st.rnd, st.pos, (None, None, None), w, False, None),
                                )
                        else:
                            yield (f"Reveal({s},{c})", St("REVEAL", 3, st.rnd, st.pos, nts, -1, False, None))
        else:
            mask = sum((1 << s) for s in SEATS if st.seats[s] is None)
            assert mask > 0
            yield ("Poke", St("FIN", 3, st.rnd, st.pos, (None, None, None), -1, False, ("FORFEIT", mask)))
        return

    if st.phase == "MOVE":
        w = st.winner
        if not st.expired:
            yield ("Move(ADV)", _after_move(st, w, ADV))
            for t in SEATS:
                if t != w:
                    yield (f"Move(PUSH,{t})", _after_move(st, w, ("PUSH", t)))
        else:
            yield ("Poke", _after_move(st, w, ADV))  # default action on timeout
        return

    raise ValueError(f"unknown phase: {st.phase}")


def check_stage_game() -> Dict:
    """P0: Exhaustive check over all 27 colour triples."""
    winner_combos = 0
    no_winner = 0
    all_same = 0
    all_distinct = 0
    per_seat = [0, 0, 0]
    seat0_per_colour = {0: 0, 1: 0, 2: 0}

    for a, b, c in product(COLOURS, repeat=3):
        w = resolve(a, b, c)
        if w is None:
            no_winner += 1
            if a == b == c:
                all_same += 1
            else:
                all_distinct += 1
        else:
            winner_combos += 1
            per_seat[w] += 1
            if w == 0:
                seat0_per_colour[a] += 1

    assert (per_seat, all_same, all_distinct, winner_combos - 18) == ([6, 6, 6], 3, 6, 0), (
        per_seat,
        all_same,
        all_distinct,
        winner_combos,
    )
    assert no_winner == 9
    assert seat0_per_colour == {0: 2, 1: 2, 2: 2}
    return {
        "winner_combos": winner_combos,
        "no_winner": no_winner,
        "all_same": all_same,
        "all_distinct": all_distinct,
        "per_seat": per_seat,
        "seat0_wins_per_own_colour": seat0_per_colour,
    }


def explore() -> Tuple[Dict[St, List[Tuple[str, St]]], int]:
    """BFS exploration of all reachable states."""
    adj: Dict[St, List[Tuple[str, St]]] = {}
    q: deque[St] = deque([INIT])
    seen = {INIT}
    edge_count = 0

    while q:
        st = q.popleft()
        edges = list(transitions(st))
        adj[st] = edges
        edge_count += len(edges)
        for _, n in edges:
            if n not in seen:
                seen.add(n)
                q.append(n)
                if len(seen) > MAX_STATES:
                    raise RuntimeError(
                        f"state space exceeded {MAX_STATES}: parameters too large, or a "
                        "termination bug (e.g. round cap not enforced). Lower --finish/--cap."
                    )
    return adj, edge_count


def verify_all() -> None:
    print(f"params: FINISH={FINISH} PUSH={PUSH} ROUND_CAP={ROUND_CAP} STAKE={STAKE}")

    # P0
    sg = check_stage_game()
    print(f"stage game: {sg}")

    adj, edge_count = explore()
    print(f"reachable states: {len(adj)}   transitions: {edge_count}")

    # P7: state invariants
    fin_counts: Dict[str, int] = {}
    for st in adj:
        for p in st.pos:
            assert 0 <= p <= FINISH, st
        assert 0 <= st.rnd <= ROUND_CAP, st
        if st.phase == "MOVE":
            assert st.winner in SEATS, st
        else:
            assert st.winner == -1, st
        if st.phase == "FIN":
            assert st.result is not None, st
            fin_counts[st.result[0]] = fin_counts.get(st.result[0], 0) + 1
    print("P7 invariants (positions in [0,FINISH], round <= cap, winner set in MOVE): OK")
    print(f"FIN states by kind: {fin_counts}")

    # P1, P2, P3, P4, P5, P13 on every FIN state
    worst_honest_net = 10**18
    forfeit_pay_by_mask: Dict[int, List[int]] = {}
    for st in adj:
        if st.phase != "FIN":
            continue
        r = st.result
        assert r is not None
        pay = settle(r, STAKE)
        deposited = [STAKE if s < st.joined else 0 for s in SEATS]

        # P2 conservation
        assert sum(pay) == sum(deposited), ("P2 conservation", r, pay)

        # P1 bounded loss
        for s in SEATS:
            net = pay[s] - deposited[s]
            assert net >= -STAKE, ("P1 bounded loss", r, s, net)

        if r[0] != "FORFEIT":
            for s in range(st.joined):
                worst_honest_net = min(worst_honest_net, pay[s] - deposited[s])
        else:
            mask = r[1]
            # P3 non-forfeiter never loses; P4 forfeiter net == -STAKE (when not all 3 forfeit)
            f = [s for s in SEATS if (mask >> s) & 1]
            o = [s for s in SEATS if not ((mask >> s) & 1)]
            for s in o:
                assert pay[s] - STAKE >= 0, ("P3 non-forfeiter never loses", r, s, pay[s] - STAKE)
            if len(f) < 3:
                for s in f:
                    assert pay[s] - STAKE == -STAKE, ("P4 forfeiter pays stake", r, s, pay)
            if len(f) == 1:
                # Symmetric split (within 1 wei dust)
                assert abs(pay[o[0]] - pay[o[1]]) <= 1, ("P5 symmetric split", r, pay)

            # P5 position/round independence: identical payout for identical mask across all FIN states
            if mask in forfeit_pay_by_mask:
                assert forfeit_pay_by_mask[mask] == pay, ("P5 position-dependent forfeit", r, pay)
            else:
                forfeit_pay_by_mask[mask] = pay

            # P13: a coalition that causes EVERY forfeit (mask subset of C) never profits
            for size in (1, 2, 3):
                for C in combinations(SEATS, size):
                    if all(fs in C for fs in f):
                        tot = sum(pay[i] - STAKE for i in C)
                        assert tot <= 0, ("P13 coalition abort profitable", r, C, tot)

    assert worst_honest_net >= -STAKE, ("P4'", worst_honest_net)
    print(
        "P1 bounded loss, P2 conservation, P3 survivors never lose, P4 forfeiter pays stake, "
        "P5 forfeit payout independent of positions (no kingmaking by timed abort), "
        "P13 no coalition profits from forfeits it fully causes: OK"
    )
    print(f"P4' worst honest net payoff = {worst_honest_net} >= forfeit net payoff {-STAKE}: OK")

    # P6 liveness: reverse BFS from all FIN states
    rev: Dict[St, List[St]] = {st: [] for st in adj}
    for u, edges in adj.items():
        for _, v in edges:
            rev[v].append(u)
    can_fin = {st for st in adj if st.phase == "FIN"}
    rq = deque(can_fin)
    while rq:
        v = rq.popleft()
        for u in rev[v]:
            if u not in can_fin:
                can_fin.add(u)
                rq.append(u)
    missing = len(adj) - len(can_fin)
    assert missing == 0, f"{missing} states cannot reach FIN"
    print("P6 liveness: every reachable state can reach FIN: OK")

    # P8 termination: Kahn's topological sort + longest path in DAG
    indeg: Dict[St, int] = {st: 0 for st in adj}
    for edges in adj.values():
        for _, v in edges:
            indeg[v] += 1
    tq = deque(st for st, d in indeg.items() if d == 0)
    dist: Dict[St, int] = {st: 0 for st in adj}
    visited = 0
    while tq:
        u = tq.popleft()
        visited += 1
        du = dist[u]
        for _, v in adj[u]:
            if du + 1 > dist[v]:
                dist[v] = du + 1
            indeg[v] -= 1
            if indeg[v] == 0:
                tq.append(v)
    assert visited == len(adj), f"cycle detected: visited {visited} of {len(adj)}"
    longest = max(dist.values())
    print(f"P8 termination: transition graph is acyclic; longest run = {longest} transitions: OK")

    # P9 timeout-completeness: from any non-IDLE state, Tick/Poke alone reach FIN in <= 4 steps
    max_tp_steps = 0
    for start in adj:
        if start.phase == "IDLE":
            continue
        cur = start
        steps = 0
        while cur.phase != "FIN":
            tp_edges = [v for lbl, v in adj[cur] if lbl in ("Tick", "Poke")]
            assert len(tp_edges) == 1, f"expected 1 Tick/Poke from {cur}, got {tp_edges}"
            cur = tp_edges[0]
            steps += 1
            assert steps <= 4, f"Tick/Poke exceeded 4 steps from {start}"
        if steps > max_tp_steps:
            max_tp_steps = steps
    print(f"P9 timeout-completeness: from every non-idle state, Tick/Poke alone reach FIN in <= {max_tp_steps} steps: OK")

    print("\nALL PROPERTIES HOLD for these parameters.")


def main() -> None:
    global FINISH, PUSH, ROUND_CAP, STAKE, MAX_STATES
    ap = argparse.ArgumentParser(description="Independent OUTLIER spec model checker")
    ap.add_argument("--finish", type=int, default=2)
    ap.add_argument("--push", type=int, default=1)
    ap.add_argument("--cap", type=int, default=3)
    ap.add_argument("--stake", type=int, default=3)
    ap.add_argument("--max-states", type=int, default=MAX_STATES)
    args = ap.parse_args()
    FINISH = args.finish
    PUSH = args.push
    ROUND_CAP = args.cap
    STAKE = args.stake
    MAX_STATES = args.max_states
    verify_all()


if __name__ == "__main__":
    main()

