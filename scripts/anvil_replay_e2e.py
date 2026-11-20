#!/usr/bin/env python3
"""
End-to-End Live EVM (`anvil`) Time-Warp & Native Fe CLI Replay Bridge (T3.6, T4.5).

1. Starts a local Foundry `anvil` chain on an ephemeral port.
2. Deploys the compiled Fe contract (`out/OutlierTable.bin`) with `STAKE = 1001 wei`.
3. Scenario A — Full 4-round game to `Won(S0)` + pull-payment `withdraw()`:
   - 3 distinct EOAs (`P0, P1, P2`) join, commit, reveal, and move on-chain.
   - Extracts real emitted EVM events (`Joined`, `Committed`, `Revealed`, `MoveMade`, `Transition`)
     from transaction receipts, formats them as `OUTLIER-LOG 1`, and passes the file to the
     compiled native Fe binary `./out/outlier_cli replay`.
   - Asserts `./out/outlier_cli replay` prints `VERIFIED 31 transitions` with the exact on-chain
     `OutlierTable.digest()`.
   - Tampers 1 byte in the extracted on-chain log and asserts `./out/outlier_cli replay` exits non-zero
     with `DIVERGENCE at step ...`.
4. Scenario B — Live on-chain time-warp (`evm_increaseTime`) timeout `poke()` -> Forfeit -> `withdraw()`:
   - Starts Game #2 (`gameId() == 2`) on the SAME deployed `OutlierTable` contract.
   - All 3 players join and commit; `P0` and `P1` reveal, while `P2` withholds their reveal.
   - Warps `anvil` block time forward by `+605s` (`> REVEAL_WINDOW = 600s`) and calls `poke()`.
   - Verifies position-independent forfeit payout split (`1502, 1501, 0`), executes on-chain ETH
     `withdraw()` for both survivors, and verifies Game #2's on-chain event trace via native
     `./out/outlier_cli replay` (`VERIFIED 9 transitions`).
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from typing import Dict, List, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOMAIN_TAG = "0x350026eb9d43d1ca67d039dd30760600db6ca312c02ce29ba9e06e098de9e370"

# Default Anvil test accounts (0, 1, 2)
ACCOUNTS = [
    (
        "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
        "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80",
    ),
    (
        "0x70997970C51812dc3A010C7d01b50e0d17dc79C8",
        "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d",
    ),
    (
        "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC",
        "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a",
    ),
]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def run_cmd(cmd: List[str]) -> str:
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Command failed ({' '.join(cmd)}):\n{res.stderr}\n{res.stdout}")
    return res.stdout.strip()


def cast_commitment(table_addr: str, game_id: int, rnd: int, seat: int, colour: int, nonce: int) -> str:
    preimage = run_cmd(
        [
            "cast",
            "abi-encode",
            "f(uint256,uint256,uint256,uint256,uint256,uint256,uint256)",
            DOMAIN_TAG,
            table_addr,
            str(game_id),
            str(rnd),
            str(seat),
            str(colour),
            str(nonce),
        ]
    )
    return run_cmd(["cast", "keccak", preimage])


def word_hex(val: int) -> str:
    return "0x" + f"{val:064x}"


def addr_to_word_hex(addr: str) -> str:
    return word_hex(int(addr, 16))


def send_tx(rpc: str, pk: str, to: str, sig: str, args: List[str], value_wei: int = 0) -> Dict:
    cmd = [
        "cast",
        "send",
        "--json",
        "--rpc-url",
        rpc,
        "--private-key",
        pk,
        "--value",
        str(value_wei),
        to,
        sig,
        *args,
    ]
    out = run_cmd(cmd)
    return json.loads(out)


def extract_transition_from_receipt(receipt: Dict, topic_transition: str) -> Tuple[int, int, str]:
    """Extract (step_no, ts, digest_hex) from the emitted `Transition` event in a tx receipt."""
    for lg in receipt.get("logs", []):
        topics = [t.lower() for t in lg.get("topics", [])]
        if topics and topics[0] == topic_transition.lower():
            data_hex = lg["data"][2:]  # 3 words: step_no, ts, digest
            step_no = int(data_hex[0:64], 16)
            ts = int(data_hex[64:128], 16)
            digest = "0x" + data_hex[128:192].lower()
            return step_no, ts, digest
    raise RuntimeError(f"Transition event not found in receipt: {receipt}")


def main() -> int:
    # Ensure contract bytecode and native CLI binary exist
    bin_path = os.path.join(ROOT, "out", "OutlierTable.bin")
    cli_path = os.path.join(ROOT, "out", "outlier_cli")
    if not os.path.exists(bin_path):
        run_cmd(["fe", "build", "-i", "outlier_table", "--emit", "sizes,bytecode,abi", "--out-dir", "out"])
    if not os.path.exists(cli_path):
        run_cmd(["fe", "build", "-i", "outlier_cli", "--backend", "native", "--emit", "executable", "--out-dir", "out"])

    topic_transition = run_cmd(["cast", "keccak", "Transition(uint256,uint256,uint256,uint256)"])

    port = free_port()
    rpc = f"http://127.0.0.1:{port}"
    anvil_proc = subprocess.Popen(
        ["anvil", "--port", str(port), "--silent"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        # Wait for anvil RPC
        for _ in range(30):
            try:
                run_cmd(["cast", "block-number", "--rpc-url", rpc])
                break
            except Exception:
                time.sleep(0.1)

        stake = 1001
        creation_hex = open(bin_path).read().strip()
        if not creation_hex.startswith("0x"):
            creation_hex = "0x" + creation_hex
        init_arg = run_cmd(["cast", "abi-encode", "f(uint256)", str(stake)])[2:]
        deploy_data = creation_hex + init_arg

        deploy_out = json.loads(
            run_cmd(
                [
                    "cast",
                    "send",
                    "--json",
                    "--rpc-url",
                    rpc,
                    "--private-key",
                    ACCOUNTS[0][1],
                    "--create",
                    deploy_data,
                ]
            )
        )
        table_addr = deploy_out["contractAddress"]
        table_word = addr_to_word_hex(table_addr)
        print(f"[Anvil E2E] Deployed OutlierTable at {table_addr} (stake={stake} wei)")

        # ====================================================================
        # SCENARIO A: Full 4-round game on-chain -> native `outlier_cli replay`
        # ====================================================================
        log_lines = [
            "OUTLIER-LOG 1",
            f"PARAMS finish=4 push=1 cap=20 stake={stake} join=3600 commit=600 reveal=600 move=600",
            f"TABLE {table_word}",
            "GAME 1",
        ]

        # 3 players join
        for seat_i in range(3):
            addr, pk = ACCOUNTS[seat_i]
            rcpt = send_tx(rpc, pk, table_addr, "join()", [], value_wei=stake)
            step_no, ts, digest = extract_transition_from_receipt(rcpt, topic_transition)
            log_lines.append(f"IN {step_no} {ts} {addr_to_word_hex(addr)} JOIN -> {digest}")

        # 4 rounds: S0 plays Blue(1), S1 plays Red(0), S2 plays Red(0) -> S0 wins each round and Advances to FINISH=4
        for rnd in range(1, 5):
            cols = [1, 0, 0]
            nonces = [rnd * 1000 + 11, rnd * 1000 + 22, rnd * 1000 + 33]
            hashes = [cast_commitment(table_addr, 1, rnd, s, cols[s], nonces[s]) for s in range(3)]

            for s in range(3):
                addr, pk = ACCOUNTS[s]
                rcpt = send_tx(rpc, pk, table_addr, "commit(uint256)", [hashes[s]])
                step_no, ts, digest = extract_transition_from_receipt(rcpt, topic_transition)
                log_lines.append(
                    f"IN {step_no} {ts} {addr_to_word_hex(addr)} COMMIT {word_hex(int(hashes[s], 16))} -> {digest}"
                )

            for s in range(3):
                addr, pk = ACCOUNTS[s]
                rcpt = send_tx(rpc, pk, table_addr, "reveal(uint8,uint256)", [str(cols[s]), str(nonces[s])])
                step_no, ts, digest = extract_transition_from_receipt(rcpt, topic_transition)
                log_lines.append(
                    f"IN {step_no} {ts} {addr_to_word_hex(addr)} REVEAL {cols[s]} {word_hex(nonces[s])} -> {digest}"
                )

            # S0 makes move Advance (kind=0, target=0)
            addr0, pk0 = ACCOUNTS[0]
            rcpt = send_tx(rpc, pk0, table_addr, "makeMove(uint8,uint8)", ["0", "0"])
            step_no, ts, digest = extract_transition_from_receipt(rcpt, topic_transition)
            log_lines.append(f"IN {step_no} {ts} {addr_to_word_hex(addr0)} MOVE ADV 0 -> {digest}")

        onchain_digest = run_cmd(["cast", "call", "--rpc-url", rpc, table_addr, "digest()(uint256)"]).split()[0]
        onchain_digest_hex = word_hex(int(onchain_digest))
        assert log_lines[-1].endswith(onchain_digest_hex), (log_lines[-1], onchain_digest_hex)

        # Verify S0 pull-payment withdrawal on-chain
        owed_s0 = int(run_cmd(["cast", "call", "--rpc-url", rpc, table_addr, "owed(address)(uint256)", ACCOUNTS[0][0]]).split()[0])
        assert owed_s0 == stake * 3, f"expected owed={stake * 3}, got {owed_s0}"
        send_tx(rpc, ACCOUNTS[0][1], table_addr, "withdraw(address)", [ACCOUNTS[0][0]])
        owed_after = int(run_cmd(["cast", "call", "--rpc-url", rpc, table_addr, "owed(address)(uint256)", ACCOUNTS[0][0]]).split()[0])
        assert owed_after == 0
        print(f"[Anvil E2E] Game #1 finished on-chain (Won S0); pull-payment withdraw({stake * 3} wei) verified.")

        # Feed real on-chain event log into native Fe `./out/outlier_cli replay`!
        with tempfile.TemporaryDirectory() as td:
            log_file = os.path.join(td, "anvil_game1.log")
            open(log_file, "w").write("\n".join(log_lines) + "\n")

            replay_out = run_cmd([cli_path, "replay", log_file])
            print(f"[Anvil E2E -> Native Fe CLI] {replay_out}")
            assert f"VERIFIED 31 transitions, final digest {onchain_digest_hex}" in replay_out

            # Tamper with step 5's action in the on-chain log and assert native CLI catches divergence at step 5!
            tampered_lines = list(log_lines)
            tampered_lines[8] = tampered_lines[8].replace("COMMIT 0x0", "COMMIT 0x1").replace("COMMIT 0x", "COMMIT 0x0", 0)
            # Flip last hex char of step 5's digest
            last_c = tampered_lines[8][-1]
            tampered_lines[8] = tampered_lines[8][:-1] + ("b" if last_c != "b" else "a")
            tampered_file = os.path.join(td, "anvil_game1_tampered.log")
            open(tampered_file, "w").write("\n".join(tampered_lines) + "\n")

            tamper_res = subprocess.run([cli_path, "replay", tampered_file], capture_output=True, text=True)
            assert tamper_res.returncode != 0, "Expected non-zero exit code on tampered log!"
            assert "DIVERGENCE at step 5:" in tamper_res.stdout, tamper_res.stdout
            print(f"[Anvil E2E -> Native Fe CLI Tamper Check] {tamper_res.stdout.strip()}")

        # ====================================================================
        # SCENARIO B: Live on-chain Time-Warp (`evm_increaseTime`) -> Forfeit
        # ====================================================================
        # Start Game #2 on the same deployed OutlierTable contract!
        g2_lines = [
            "OUTLIER-LOG 1",
            f"PARAMS finish=4 push=1 cap=20 stake={stake} join=3600 commit=600 reveal=600 move=600",
            f"TABLE {table_word}",
            "GAME 2",
        ]
        for s in range(3):
            addr, pk = ACCOUNTS[s]
            rcpt = send_tx(rpc, pk, table_addr, "join()", [], value_wei=stake)
            step_no, ts, digest = extract_transition_from_receipt(rcpt, topic_transition)
            g2_lines.append(f"IN {step_no} {ts} {addr_to_word_hex(addr)} JOIN -> {digest}")

        cols2 = [0, 1, 2]
        nonces2 = [9001, 9002, 9003]
        hashes2 = [cast_commitment(table_addr, 2, 1, s, cols2[s], nonces2[s]) for s in range(3)]
        for s in range(3):
            addr, pk = ACCOUNTS[s]
            rcpt = send_tx(rpc, pk, table_addr, "commit(uint256)", [hashes2[s]])
            step_no, ts, digest = extract_transition_from_receipt(rcpt, topic_transition)
            g2_lines.append(
                f"IN {step_no} {ts} {addr_to_word_hex(addr)} COMMIT {word_hex(int(hashes2[s], 16))} -> {digest}"
            )

        # S0 and S1 reveal; S2 withholds reveal!
        for s in (0, 1):
            addr, pk = ACCOUNTS[s]
            rcpt = send_tx(rpc, pk, table_addr, "reveal(uint8,uint256)", [str(cols2[s]), str(nonces2[s])])
            step_no, ts, digest = extract_transition_from_receipt(rcpt, topic_transition)
            g2_lines.append(
                f"IN {step_no} {ts} {addr_to_word_hex(addr)} REVEAL {cols2[s]} {word_hex(nonces2[s])} -> {digest}"
            )

        # Warp time forward by +605 seconds on Anvil (> REVEAL_WINDOW = 600s) and call poke()!
        run_cmd(["cast", "rpc", "--rpc-url", rpc, "evm_increaseTime", "605"])
        run_cmd(["cast", "rpc", "--rpc-url", rpc, "evm_mine"])

        rcpt_poke = send_tx(rpc, ACCOUNTS[0][1], table_addr, "poke()", [])
        step_no, ts, digest = extract_transition_from_receipt(rcpt_poke, topic_transition)
        g2_lines.append(f"IN {step_no} {ts} {addr_to_word_hex(ACCOUNTS[0][0])} POKE -> {digest}")

        # Verify odd-stake forfeit split on-chain: S0 gets 1001 + 501 = 1502, S1 gets 1001 + 500 = 1501, S2 gets 0!
        owed0 = int(run_cmd(["cast", "call", "--rpc-url", rpc, table_addr, "owed(address)(uint256)", ACCOUNTS[0][0]]).split()[0])
        owed1 = int(run_cmd(["cast", "call", "--rpc-url", rpc, table_addr, "owed(address)(uint256)", ACCOUNTS[1][0]]).split()[0])
        owed2 = int(run_cmd(["cast", "call", "--rpc-url", rpc, table_addr, "owed(address)(uint256)", ACCOUNTS[2][0]]).split()[0])
        assert (owed0, owed1, owed2) == (1502, 1501, 0), f"unexpected forfeit payouts: {(owed0, owed1, owed2)}"
        send_tx(rpc, ACCOUNTS[0][1], table_addr, "withdraw(address)", [ACCOUNTS[0][0]])
        send_tx(rpc, ACCOUNTS[1][1], table_addr, "withdraw(address)", [ACCOUNTS[1][0]])
        print("[Anvil E2E] Game #2 time-warp Poke -> Forfeited(mask=4) -> payouts (1502, 1501, 0) withdrawn on-chain.")

        with tempfile.TemporaryDirectory() as td:
            g2_file = os.path.join(td, "anvil_game2_forfeit.log")
            open(g2_file, "w").write("\n".join(g2_lines) + "\n")
            g2_replay = run_cmd([cli_path, "replay", g2_file])
            print(f"[Anvil E2E Game #2 -> Native Fe CLI] {g2_replay}")
            assert "VERIFIED 9 transitions" in g2_replay

        print("\nALL ANVIL ON-CHAIN E2E + NATIVE FE CLI REPLAY BRIDGE CHECKS PASSED.")
        return 0
    finally:
        anvil_proc.terminate()
        anvil_proc.wait()


if __name__ == "__main__":
    sys.exit(main())

