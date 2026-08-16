# navrules development targets.
# The wheel itself is built by maturin (see pyproject.toml [build-system]);
# these targets cover local development loops.

.PHONY: build-rust test test-python cargo-test bench clean

# Compile the Rust extension into the active venv (release profile).
build-rust:
	uv run --with maturin maturin develop --release

# Full Python suite (builds the extension via the maturin backend).
test:
	uv run --no-project --isolated --with pytest --with pytest-asyncio \
		--with-editable . python -m pytest tests -q

# Force the pure-Python fallback (parity tests auto-skip).
test-python:
	NAVRULES_DISABLE_RUST=1 uv run --no-project --isolated --with pytest \
		--with pytest-asyncio --with-editable . python -m pytest tests -q

# Rust crate unit tests (links against libpython; see RUSTFLAGS note).
cargo-test:
	cd rust && cargo test

# Fieldsync-like benchmark: 1000 rules x 10k contexts + p99 latency.
bench:
	RUN_BENCH=1 uv run --no-project --isolated --with pytest \
		--with pytest-asyncio --with-editable . \
		python -m pytest tests/benchmarks -q -s

clean:
	rm -rf rust/target dist build *.egg-info
