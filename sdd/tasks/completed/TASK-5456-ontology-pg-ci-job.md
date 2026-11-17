# TASK-5456: Add CI job for ontology vocabulary PostgreSQL tests

- **Feature**: ontology-pg-live-validation
- **Feature ID**: FEAT-864
- **Spec**: sdd/specs/ontology-pg-live-validation.spec.md
- **Status**: pending
- **Priority**: high
- **Estimated effort**: small
- **Depends-on**: [TASK-5455]

## Context

The vocabulary PostgreSQL tests require a live PostgreSQL 17 server with
pgvector and pg_trgm extensions. Without a CI job, they are perpetually
SKIPPED and regressions go undetected.

**Discovered-from**: `issue:a985902092e3`

## Scope

Add a `test-ontology-pg` job to `.github/workflows/ci.yml`.

## Files to Modify

- `.github/workflows/ci.yml`

## Codebase Contract

### Verified Imports
- N/A (YAML workflow file)

### Existing Signatures
- N/A

## Implementation Notes

Add a job after the existing `test-core` job. Use `pgvector/pgvector:pg17`
Docker image as the service container (includes pgvector; pg_trgm is a
contrib module bundled with PostgreSQL).

```yaml
test-ontology-pg:
  name: "Test ontology vocabulary (PostgreSQL)"
  runs-on: ubuntu-latest
  services:
    postgres:
      image: pgvector/pgvector:pg17
      env:
        POSTGRES_USER: test
        POSTGRES_PASSWORD: test
        POSTGRES_DB: ontology_test
      options: >-
        --health-cmd "pg_isready -U test"
        --health-interval 10s
        --health-timeout 5s
        --health-retries 5
      ports:
        - 5432:5432
  steps:
    - uses: actions/checkout@v6
    - uses: actions/setup-python@v6
      with: { python-version: "3.12" }
    - uses: astral-sh/setup-uv@v10.2.0
      with: { version: "latest" }
    - name: Install Rust
      uses: dtolnay/rust-toolchain@stable
    - name: Sync workspace with ontology extra
      run: uv sync --all-packages --extra ontology
    - name: Scaffold NavConfig environment
      run: mkdir -p env/dev && touch env/dev/.env
    - name: Enable pg_trgm extension
      run: PGPASSWORD=test psql -h localhost -U test -d ontology_test -c 'CREATE EXTENSION IF NOT EXISTS pg_trgm;'
    - name: Run ontology vocabulary PG tests
      env:
        ONTOLOGY_PG_DSN: "postgresql://test:test@localhost:5432/ontology_test"
      run: uv run pytest packages/ai-parrot/tests/knowledge/ontology/vocabulary/ -q --tb=short -k "pg or postgres or publisher or conformance or temporal or schema"
```

## Acceptance Criteria

1. `test-ontology-pg` job present in `ci.yml`.
2. Job uses PostgreSQL 17 service with pgvector + pg_trgm.
3. Tests scoped to vocabulary PG tests only.

## Validation Commands

```bash
python3 -c "import yaml; y=yaml.safe_load(open('.github/workflows/ci.yml')); assert 'test-ontology-pg' in y['jobs'], 'job missing'"
```

## Completion Note

_To be filled on completion._
