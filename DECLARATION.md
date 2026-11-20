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

AI coding assistants were used for specification refinement, Fe 26.6.0 stdlib exploration, dual-backend implementation, mutation testing, native Fe value-iteration solver verification, and documentation. The human author reviewed, tested, and takes full responsibility for all code and claims in this submission.
