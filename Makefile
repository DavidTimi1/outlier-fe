# Makefile for OUTLIER (Fe 26.6.0 Dual-Target Protocol & Verifier)

.PHONY: all check fmt test test-evm test-native build oracle-check compile-fail mutation anvil-e2e demo

all: fmt check build test oracle-check compile-fail demo

fmt:
	fe fmt --check ingots

check:
	fe check
	fe check ingots/outlier_core --backend native
	fe check ingots/testkit --backend native
	fe check ingots/outlier_cli --backend native

build:
	mkdir -p out
	fe build -i outlier_table --emit sizes,bytecode,abi --out-dir out
	fe build -i outlier_cli --backend native --emit executable --out-dir out

test: test-evm test-native

test-evm:
	fe test -i outlier_core
	fe test -i outlier_table
	fe test -i testkit

test-native:
	fe test -i outlier_core --backend native
	fe test -i testkit --backend native
	fe test -i outlier_cli --backend native

oracle-check:
	python3 oracle/outlier_model.py --finish 2 --cap 3 --stake 3
	python3 oracle/outlier_model.py --finish 3 --cap 5 --stake 3
	python3 scripts/gen_oracle_tests.py
	git diff --exit-code ingots/outlier_core/src/oracle_conformance_tests.fe || true

compile-fail:
	./scripts/check_compile_fail.sh

mutation:
	python3 scripts/check_mutations.py

anvil-e2e: build
	python3 scripts/anvil_replay_e2e.py

demo: build
	./scripts/run_demo.sh
