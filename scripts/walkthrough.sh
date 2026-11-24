#!/usr/bin/env bash
# Human-speed step-by-step walkthrough & interactive play mode for OUTLIER.
#
# Usage:
#   ./scripts/walkthrough.sh                  # Interactive step-by-step (press ENTER each round)
#   ./scripts/walkthrough.sh --auto 2.5       # Auto-advance every 2.5 seconds (human reading speed)
#   ./scripts/walkthrough.sh --forfeit        # Step through the anti-kingmaking forfeit scenario
#   ./scripts/walkthrough.sh --play           # YOU play Seat S0 against Bot S1 & Bot S2!
#                                             # (generates demo/human_game.log & verifies via Fe CLI!)

set -euo pipefail

mkdir -p out demo

if [ ! -x out/outlier_cli ]; then
    fe build -i outlier_cli --backend native --emit executable --out-dir out
fi

MODE="step"
PACE=""
SEED="1"
STRATEGY_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --auto|--pace)
            if [[ $# -ge 2 && ! "$2" =~ ^-- ]]; then
                PACE="$2"
                shift 2
            else
                PACE="2.5"
                shift 1
            fi
            ;;
        --seed)
            SEED="${2:-1}"
            shift 2
            ;;
        --forfeit)
            SEED="42"
            STRATEGY_ARGS=(--strategy forfeit)
            shift
            ;;
        --play|--interactive)
            MODE="play"
            shift
            ;;
        *)
            shift
            ;;
    esac
done

pause_step() {
    local prompt_msg="${1:-Press [ENTER] for next round (or Ctrl+C to quit)...}"
    if [[ -n "$PACE" ]]; then
        sleep "$PACE"
    elif [[ -t 0 ]]; then
        printf "\n  \033[1;36m>>> %s\033[0m" "$prompt_msg"
        read -r _
        echo ""
    fi
}

if [[ "$MODE" == "play" ]]; then
    ./out/outlier_cli explain
    echo ""
    python3 - <<'PY'
import os, random, subprocess, sys
sys.path.insert(0, os.path.abspath("oracle"))
import outlier_model as m

NAMES = {0: "Red  ", 1: "Blue ", 2: "Green"}

def short_hex(w: int) -> str:
    h = f"{w:064x}"
    return f"0x{h[:6]}..{h[-6:]}"

def word_hex(w: int) -> str:
    return f"0x{w:064x}"

def render_track(positions):
    print("      LANE    START [0]    TILE [1]     TILE [2]     TILE [3]    FINISH [4*]")
    print("            +-----------+-----------+-----------+-----------+-----------+")
    for s in range(3):
        row = f"       S{s}   |"
        for col in range(5):
            if positions[s] == col:
                if col == 4:
                    row += f"   <S{s}*>   |"
                else:
                    row += f"   [ S{s} ]  |"
            else:
                row += "     .     |"
        print(row)
        print("            +-----------+-----------+-----------+-----------+-----------+")

stake = 1001
table = 0xCAFE
players = [0x1001, 0x1002, 0x1003]
st = m.GameState.new(stake)
digest = 0
now = 1000
log_lines = [
    "OUTLIER-LOG 1",
    f"PARAMS finish=4 push=1 cap=20 stake={stake} join=3600 commit=600 reveal=600 move=600",
    f"TABLE {word_hex(table)}",
    "GAME 1",
]

print("==============================================================================")
print("  INTERACTIVE MODE: YOU ARE SEAT S0 (0x1001) vs. BOT S1 & BOT S2")
print("  Every transition is recorded to demo/human_game.log and verified by Fe CLI!")
print("==============================================================================")

for s in range(3):
    now += 10
    res = m.step(st, digest, ("JOIN",), m.StepCtx(now, players[s], table, stake))
    assert res.ok
    st, digest = res.out.state, res.out.digest
    log_lines.append(f"IN {st.step_no} {now} {word_hex(players[s])} JOIN -> {word_hex(digest)}")

print(f"\n[Registration] Seats S0 (YOU), S1 (Bot), S2 (Bot) joined (stake={stake} each).")
print(f"               Initial Chain Digest: {short_hex(digest)}\n")
render_track(st.positions)

rng = random.Random()
out_res = None

while st.phase[0] != "Finished":
    rnd = st.round
    print("\n==============================================================================")
    print(f"  ROUND {rnd}  //  YOUR TURN TO COMMIT A SECRET COLOUR")
    print("==============================================================================")
    while True:
        try:
            raw_in = input("  Choose S0 colour — [0] Red   [1] Blue   [2] Green  (or q to quit): ").strip().lower()
        except EOFError:
            sys.exit(0)
        if raw_in in ("q", "quit"):
            sys.exit(0)
        if raw_in in ("0", "r", "red"):
            c0 = 0
            break
        if raw_in in ("1", "b", "blue"):
            c0 = 1
            break
        if raw_in in ("2", "g", "green"):
            c0 = 2
            break
        print("  Please enter 0 (Red), 1 (Blue), or 2 (Green).")

    c1 = rng.randint(0, 2)
    c2 = rng.randint(0, 2)
    cols = [c0, c1, c2]
    nonces = [rng.getrandbits(64) + 0xA00001 + i for i in range(3)]
    hashes = [m.commitment(table, st.game_id, rnd, i, cols[i], nonces[i]) for i in range(3)]

    now += 5
    for s in range(3):
        res = m.step(st, digest, ("COMMIT", hashes[s]), m.StepCtx(now, players[s], table, 0))
        assert res.ok
        st, digest, out_res = res.out.state, res.out.digest, res.out
        log_lines.append(f"IN {st.step_no} {now} {word_hex(players[s])} COMMIT {word_hex(hashes[s])} -> {word_hex(digest)}")

    print("\n  [1] SEALED KECCAK-256 COMMITMENTS (7-word lockboxes placed on table):")
    print(f"      S0 (YOU): [SEALED {short_hex(hashes[0])}]")
    print(f"      S1 (BOT): [SEALED {short_hex(hashes[1])}]")
    print(f"      S2 (BOT): [SEALED {short_hex(hashes[2])}]")

    now += 5
    for s in range(3):
        res = m.step(st, digest, ("REVEAL", cols[s], nonces[s]), m.StepCtx(now, players[s], table, 0))
        assert res.ok
        st, digest, out_res = res.out.state, res.out.digest, res.out
        log_lines.append(
            f"IN {st.step_no} {now} {word_hex(players[s])} REVEAL {cols[s]} {word_hex(nonces[s])} -> {word_hex(digest)}"
        )

    print("\n  [2] ENVELOPES OPENED (keccak256(colour, nonce) verified):")
    print("      +--------------------+     +--------------------+     +--------------------+")
    print(f"      | S0 (YOU): {NAMES[cols[0]]}    |     | S1 (BOT): {NAMES[cols[1]]}    |     | S2 (BOT): {NAMES[cols[2]]}    |")
    print("      +--------------------+     +--------------------+     +--------------------+")

    if st.phase[0] == "WinnerMove":
        winner = st.phase[2]
        if winner == 0:
            print("      >>> ★ YOU (Seat S0) ARE THE OUTLIER! ★ <<<")
            while True:
                mv_in = input("  Choose move — [A] ADVANCE (+1 ===>)  [1] PUSH S1 (-1)  [2] PUSH S2 (-1): ").strip().lower()
                if mv_in in ("a", "adv", "advance", ""):
                    mv = ("ADV",)
                    mv_log = "MOVE ADV 0"
                    print("\n  [3] YOU chose ADVANCE (+1 ===> towards FINISH 4*)!\n")
                    break
                if mv_in in ("1", "s1", "p1"):
                    mv = ("PUSH", 1)
                    mv_log = "MOVE PUSH 1"
                    print("\n  [3] YOU chose PUSH(S1) (-1 <=== defensive block)!\n")
                    break
                if mv_in in ("2", "s2", "p2"):
                    mv = ("PUSH", 2)
                    mv_log = "MOVE PUSH 2"
                    print("\n  [3] YOU chose PUSH(S2) (-1 <=== defensive block)!\n")
                    break
        else:
            print(f"      >>> ODD-ONE-OUT: Bot Seat S{winner} is the OUTLIER! <<<")
            w_pos = st.positions[winner]
            mv = ("ADV",)
            mv_log = "MOVE ADV 0"
            if w_pos + 1 < 4:
                for opp in range(3):
                    if opp != winner and st.positions[opp] >= 3:
                        mv = ("PUSH", opp)
                        mv_log = f"MOVE PUSH {opp}"
                        break
            if mv[0] == "ADV":
                print(f"\n  [3] Bot S{winner} chooses ADVANCE (+1 ===>)\n")
            else:
                print(f"\n  [3] Bot S{winner} chooses PUSH(S{mv[1]}) (-1 <===)\n")

        now += 5
        res = m.step(st, digest, ("MOVE", mv), m.StepCtx(now, players[winner], table, 0))
        assert res.ok
        st, digest, out_res = res.out.state, res.out.digest, res.out
        log_lines.append(f"IN {st.step_no} {now} {word_hex(players[winner])} {mv_log} -> {word_hex(digest)}")
    else:
        print("      >>> NO WINNER (all 3 distinct or all 3 equal — nobody moves) <<<\n")

    render_track(st.positions)
    print(f"      Step #{st.step_no} Hash-Chain Digest: {word_hex(digest)}")

log_path = "demo/human_game.log"
with open(log_path, "w") as f:
    f.write("\n".join(log_lines) + "\n")

print("\n==============================================================================")
print(f"  GAME FINISHED! Payouts: S0(YOU)={out_res.payouts[0]}, S1={out_res.payouts[1]}, S2={out_res.payouts[2]}")
print(f"  Saved full transition trace to {log_path}. Now verifying with Native Fe CLI:")
print("==============================================================================")
print(f"$ ./out/outlier_cli replay {log_path}")
subprocess.run(["./out/outlier_cli", "replay", log_path], check=True)
PY
    exit 0
fi

# Step-by-step walkthrough mode using the Native Fe CLI (`--steps`)
./out/outlier_cli explain
pause_step "Press [ENTER] to start stepping through the game round-by-round..."

LOG_OUT="$(mktemp "${TMPDIR:-/tmp}/outlier_walkthrough.XXXXXX.log")"
trap 'rm -f "$LOG_OUT"' EXIT
TRACE_OUTPUT="$(./out/outlier_cli play --seed "$SEED" --stake 1001 "${STRATEGY_ARGS[@]}" --steps --out "$LOG_OUT")"

# Split the output at each `==============================================================================` round header
python3 - "$TRACE_OUTPUT" "$PACE" <<'PY'
import sys, time

raw = sys.argv[1]
pace = sys.argv[2]
marker = "\n==============================================================================\n"
chunks = raw.split(marker)

for idx, chunk in enumerate(chunks):
    if idx == 0:
        print("\n")
        print(chunk)
    else:
        print("\n\n")
        print("==============================================================================")
        print(chunk)
    if idx + 1 < len(chunks):
        if pace:
            time.sleep(float(pace))
        elif sys.stdin.isatty():
            sys.stdout.write("\n  \033[1;36m>>> Press [ENTER] for next round...\033[0m")
            sys.stdout.flush()
            sys.stdin.readline()
            print("")
PY

echo ""
echo ""
echo "$ ./out/outlier_cli replay $LOG_OUT"
./out/outlier_cli replay "$LOG_OUT"
echo ""

