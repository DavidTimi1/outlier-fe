# DECLARATION.md — Fe Builders Challenge Declaration

## 1. Pre-Existing Work

- **Before November 3, 2026 (Contest Build Window Open):** None. Zero code or design documents existed prior to the contest build window.
- **Starting template:** Cloned from the official [fe-lang/builders-challenge-starter](https://github.com/fe-lang/builders-challenge-starter) repository (commit `f9d9aa9`, Apache-2.0 license). The starter example (`src/lib.fe` time-locked vault) was replaced entirely with the OUTLIER multi-ingot workspace (`ingots/outlier_core`, `ingots/outlier_table`, `ingots/outlier_cli`, `ingots/testkit`), independent Python oracle (`oracle/outlier_model.py`), verification scripts (`scripts/`), and documentation (`docs/`).

## 2. Third-Party Code

- **Domain / application code:** **None.** Every line of Fe and Python code in this repository was written specifically for OUTLIER during the contest window.
- **Standard libraries & tools used:**
  - Fe `26.6.0 (5b3f96a)` built-in `core` and `std` ingots (Apache-2.0 / MIT, Argot Collective).
  - Foundry (`cast 1.9.0` and `anvil 1.9.0`) used strictly in test/verification scripts for Keccak-256 test vector generation and local EVM node end-to-end testing.
  - Python `3.13.7` standard library only (zero third-party pip packages).

## 3. AI Assistance

| Tool | What it produced |
|---|---|
| **Claude** (chat, before usage limits were reached) | First drafts of the idea evaluation against the judging rubric, `SPEC.md`, `ARCHITECTURE.md`, `PLAN.md`, and the agent operating rules (`AGENTS.md`). |
| **Google Antigravity coding agent** (models selected in the app: Gemini and Claude Sonnet) | Consolidated and updated the plan and docs; wrote the Fe code in `ingots/` (core, contract, CLI, solver, testkit); wrote the Python oracle and scripts in `oracle/` and `scripts/`; wrote the tests; wrote the README, SUBMISSION, ANALYSIS, PATTERN and FE_FINDINGS docs; and ran compile/test loops, fixing its own errors. |

**What the human author did:** chose the project, the rules of the game and the judging-driven scope; ran the agent, reviewed its output and decisions, and committed the work. The gate commands listed in the README ("Build and Test") were run in the author's workspace, and the demo transcript was produced by `scripts/run_demo.sh`. The author is still learning parts of the code and relies on the tests and the oracle, not on personal line-by-line review, for correctness evidence.

**Limits of that evidence:** the Python oracle and the Fe code were both produced with AI assistance from the same `SPEC.md`, so they are independent *implementations* but not independent *readings of the spec*. A spec misreading would not be caught by them.

A session-by-session log, including dead ends, is kept in `docs/AI_LOG.md` (kept out of the public repo by `.gitignore`; available on request).

## 4. Other Projects Consulted

No other contest entry was copied or used as a source. (`devprashant19/Leash` was not consulted.)
