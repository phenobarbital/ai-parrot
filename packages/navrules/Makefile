# navrules development targets.
# The wheel itself is built by maturin (see pyproject.toml [build-system]);
# these targets cover local development loops.

.PHONY: build-rust build-rust-wheel test test-python cargo-test bench clean

# Compile the Rust extension into the active venv (release profile).
build-rust:
	uv run --with maturin maturin develop --release

# Build the Rust extension as a wheel and unpack ONLY its .so into src/,
# installing nothing into the active environment (FEAT-722). `maturin develop`
# would reinstall navrules into the SHARED venv, which worktree agents must
# never mutate; `--locked` guarantees an automated build never rewrites
# rust/Cargo.lock. Recipe lines are TAB-indented; `$$` is a literal `$`.
build-rust-wheel:
	@tmp=$$(mktemp -d) && \
		uv run --no-sync --with maturin maturin build --release --locked --out "$$tmp" && \
		uv run --no-sync python -c 'import glob,sys,zipfile; w=glob.glob(sys.argv[1]+"/*.whl")[0]; z=zipfile.ZipFile(w); [z.extract(n, sys.argv[2]) for n in z.namelist() if n.endswith(".so")]' "$$tmp" src && \
		rm -rf "$$tmp"

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
