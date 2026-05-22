# Contributing

A short guide to getting a development build running, the conventions we
follow, and the pre-commit hygiene that keeps CI green.

## Dev setup

```bash
git clone https://github.com/plutonium-guy/cypher_validator.git
cd cypher_validator

uv venv --python 3.11 .venv
source .venv/bin/activate

uv pip install maturin pytest pytest-asyncio pydantic neo4j openai anthropic langchain-core

maturin develop --release
```

`maturin develop --release` rebuilds the Rust core and drops the compiled
`.so` straight into the active venv. Without `--release` the wheel is built
in debug mode — fine for iterating, but parser benchmarks are 5-10× slower.

!!! tip "Multiple Python versions"
    The wheels in the repo target 3.11, 3.13, and 3.14. To rebuild against
    a specific interpreter:

    ```bash
    uv venv --python 3.13 .venv-313 && source .venv-313/bin/activate
    maturin develop --release
    ```

## Before every commit

```bash
cargo test --release            # 13 Rust unit tests
cargo clippy                    # lints
cargo fmt --check               # formatting

pytest tests/ -q                # 977 driver-free Python tests
```

If you touched anything involving the live database integration, also run
the Neo4j-gated tests — see [Testing](testing.md#python--live-neo4j).

There is **no enforced pre-commit hook** in the repo. The above is a
checklist, not a script. Skipping it doesn't break anything locally but it
will burn CI minutes when you push.

## Commit conventions

We follow [Conventional Commits](https://www.conventionalcommits.org/):

| Prefix | When |
|---|---|
| `feat:` | New feature visible to users. |
| `fix:` | Bug fix. |
| `perf:` | Performance improvement, no behaviour change. |
| `docs:` | Docs-only change. |
| `test:` | New or updated tests, no production code change. |
| `refactor:` | Internal cleanup with no behaviour change. |
| `chore:` | Tooling, CI, version bumps. |

Examples from the recent log:

```
fix:  parameterized cypher + subquery label collection; perf wins
chore: update Cargo.lock for v0.12.0
feat: add Pydantic Cypher ORM with AI agent tools (v0.12.0)
docs: add async & parallel ingestion documentation to README
feat: add async/parallel LLM pipeline with TPM rate limiting
```

Keep the subject line under 72 characters. The body, when present, should
explain **why** not **what** — the diff already says what.

## Versioning

`Cargo.toml`'s `version` field is the source of truth. Bumping it requires:

```bash
# edit Cargo.toml — bump version
cargo update --workspace        # regenerate Cargo.lock
git commit -am "chore: bump to vX.Y.Z"
git tag vX.Y.Z
git push --follow-tags
```

!!! warning "Cargo.lock must match"
    CI runs with `cargo --locked`. If you bump `Cargo.toml`'s version
    without regenerating `Cargo.lock`, every `cargo` step in CI fails
    with `error: the lock file ... needs to be updated`. Run
    `cargo update --workspace` before tagging.

`python/cypher_validator/__init__.py`'s `__version__` is derived at build
time from `Cargo.toml` — no Python edit needed.

## CI overview

GitHub Actions runs on every push and PR:

1. `cargo build --release --locked`
2. `cargo test --release --locked`
3. `maturin build --release`
4. `pytest tests/ -q` (driver-free)
5. Spin up Neo4j 5.26 community → `pytest tests/` (full suite, 1 039 tests)

Wheel publishing happens on tag pushes (`vX.Y.Z`). The `Cargo.lock` lock-step
above means a missed `cargo update` will fail CI immediately.

## Code style — Rust

- **Edition 2024.** No `unwrap()` in non-test code; prefer `?` with a
  typed error.
- `thiserror` for error enums in library code, `anyhow` is **not** a
  dependency — keep typed errors all the way out to the bindings.
- Format with `cargo fmt`. Lints we honour: `cargo clippy --all-targets
  -- -D warnings`.
- `unsafe` is allowed but must be commented with an explanation of the
  invariant the caller upholds.

## Code style — Python

- **Python 3.10+.** Use `X | Y` union types, not `Optional[X]` aliases.
- Avoid runtime `isinstance` chains in hot paths — prefer dispatching on
  a small set of subclasses via `singledispatch` or a method override.
- Keep `from __future__ import annotations` at the top of every module —
  speeds up import and defers all type evaluation.
- All public functions / methods get a NumPy-style docstring. Private
  helpers can be one-liners.
- Public API surface (`__init__.py` exports) is **append-only between
  minor versions**. Removing or renaming a symbol is a major-version
  break.

## Adding a new feature

1. **Open a sketch in `docs/`** before any code. A new doc page (or a new
   section in an existing one) forces you to think through the public
   API.
2. **Write the test first.** For ORM features that mirrors
   `tests/test_orm_api_contracts.py`. For validator features
   `tests/test_validator.py`. For grammar `tests/test_syntax.py`.
3. **Implement.** Rust for parser/validator/generator additions; Python
   for ORM, LLM pipeline, RAG, NER.
4. **Profile if it's on a hot path.** `cargo flamegraph` for Rust;
   `py-spy --rate 250` for Python.
5. **Update the changelog.** [`docs/changelog.md`](../changelog.md) has the
   "Unreleased" section ready for new entries.
6. **Open the PR.** Include the docs diff, the test diff, and any
   flamegraph evidence in the description.

## Reporting bugs

When filing an issue, include:

- The exact Cypher query that triggered it.
- The `Schema` you constructed (or a minimal reproduction).
- `cypher_validator.__version__` and `python --version`.
- Whether you're running the prebuilt wheel or a local
  `maturin develop` build.

A 5-line failing test you can paste into `tests/` is worth more than a
500-line bug description.

## Where to next

- [Architecture](architecture.md) — to know which file to edit.
- [Testing](testing.md) — to know how to verify your change.
- [Performance](performance.md) — to know whether to flamegraph first.
- [Changelog](../changelog.md) — to know what version your fix will ship in.
