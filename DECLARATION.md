# DECLARATION.md — Fe Builders Challenge Declaration

## 1. Pre-Existing Work

- **Before November 3, 2026 (Contest Build Window Open):** None. Zero code or design documents existed prior to the contest build window.
- **Starting template:** I started from the official [fe-lang/builders-challenge-starter](https://github.com/fe-lang/builders-challenge-starter) repository (commit `f9d9aa9`, Apache-2.0 license). The starter example (`src/lib.fe` time-locked vault) was replaced entirely with the OUTLIER multi-ingot workspace (`ingots/outlier_core`, `ingots/outlier_table`, `ingots/outlier_cli`, `ingots/testkit`), the Python verification oracle (`oracle/outlier_model.py`), verification scripts (`scripts/`), and documentation (`docs/`).

## 2. Third-Party Code

- **Domain / application code:** **None.** Every line of Fe and Python code in this repository was written specifically for OUTLIER during the contest window.
- **Standard libraries & tools used:**
  - Fe `26.6.0 (5b3f96a)` built-in `core` and `std` ingots (Apache-2.0 / MIT, Argot Collective).
  - Foundry (`cast 1.9.0` and `anvil 1.9.0`) used in test/verification scripts for Keccak-256 test vector generation and local EVM node end-to-end testing.
  - Python `3.13.7` standard library only (zero third-party pip packages).

## 3. My Role & How I Used AI Assistance

I built OUTLIER using an AI-assisted workflow while maintaining direct ownership over the game design, protocol invariants, and verification blueprint:

### What I Did
- **Concept, Mechanism Design & Scope:** I chose the project direction, designed the three-player odd-one-out hidden-move rules (`Advance` vs. `Push`), and defined the core architectural goal: writing the entire protocol as a single pure Fe state machine (`outlier_core::step`) so the on-chain EVM contract (`outlier_table`) and the off-chain native CLI verifier (`outlier_cli`) compile from the **exact same Fe source code** with zero rules drift.
- **Learning Fe & Auditing via a Python Blueprint:** I worked through and completed the Fe starter guide to understand Fe's syntax, payload enums, `msg`/`recv` contract dispatch, and `uses` effect system, allowing me to review the core Fe implementation for structural and type-level correctness.
- **Cross-Checking Fe Against Python:** Because I am very comfortable with Python, I used the Python reference model (`oracle/outlier_model.py`) as my personal executable blueprint. By verifying that the Python oracle accurately encoded my intended game rules and protocol invariants (conservation, bounded loss, survivor safety, and position-independent forfeit splits), I was able to use it both to audit the Fe implementation and to generate conformance vectors tested directly against `outlier_core`.
- **Verification & Gate Execution:** I reviewed the architectural decisions, ran the build/test gates (`fe check`, `fe test`, `fe test --backend native`, and `./scripts/run_demo.sh`) in my local environment, and curated the final submission.

### How AI Assisted
| Tool | What I used it for |
|---|---|
| **Claude** (chat) | Brainstorming the initial specification structure (`SPEC.md`), architecture layout (`ARCHITECTURE.md`), and staged build plan (`PLAN.md`) against the contest rubric. |
| **Google Antigravity** (coding agent using Gemini and Claude Sonnet) | Translating the specification into the multi-ingot Fe workspace (`ingots/outlier_core`, `ingots/outlier_table`, `ingots/outlier_cli`, `ingots/testkit`); implementing the Python model checker and verification scripts (`oracle/outlier_model.py`, `scripts/`); running `fe check` / `fe test` compile-fix loops; and drafting the documentation (`README.md`, `SUBMISSION.md`, `docs/PATTERN.md`, `docs/FE_FINDINGS.md`, `docs/ANALYSIS.md`). |
