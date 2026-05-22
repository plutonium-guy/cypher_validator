# Testing

The test suite is split across Rust unit tests, Python driver-free tests, and
Python tests that need a live Neo4j. All three should pass before any release.

## At a glance

| Suite | How to run | Count | Notes |
|---|---|---|---|
| Rust unit tests | `cargo test --release` | 13 | Parser-focused; no DB. |
| Python driver-free | `pytest tests/ -q` | 977 pass, 62 skip | 62 tests skip when Neo4j env vars are absent. |
| Python with live Neo4j | `NEO4J_URI=... NEO4J_PASSWORD=... pytest tests/` | 1 039 pass | Driver-free + 62 integration tests. |

## Rust tests

```bash
cargo test --release
```

13 unit tests covering the pest parser and AST builder. They live in
`#[cfg(test)] mod tests` blocks inside `src/parser/builder.rs` and
`src/validator/semantic.rs`. Running in `--release` mode is recommended —
debug builds are 5-10× slower on the parser benchmarks.

## Python — driver-free

```bash
pytest tests/ -q
```

977 tests that need only the compiled wheel — they cover the parser,
validator, generator, ORM contracts, LLM utility helpers, and prompt
construction. The 62 tests that need a live database are marked and
**skip** automatically when `NEO4J_URI` / `NEO4J_PASSWORD` aren't set.

Useful subsets:

```bash
pytest tests/test_validator.py -v          # semantic validator
pytest tests/test_syntax.py -v             # pest grammar via py_parser
pytest tests/test_diagnostics.py -v        # error codes + suggestions
pytest tests/test_subqueries.py -v         # CALL / EXISTS / COUNT subqueries
pytest tests/test_orm_api_contracts.py -v  # 21 pinned ORM contracts
```

## Python — live Neo4j

The fastest path is the Neo4j 5.26 community Docker image:

```bash
docker run -d --name neo4j-cv \
    -p 7687:7687 \
    -e NEO4J_AUTH=neo4j/testtest12 \
    neo4j:5.26-community
```

Wait ~10 seconds for the server to come up, then:

```bash
export NEO4J_URI=bolt://localhost:7687
export NEO4J_USERNAME=neo4j
export NEO4J_PASSWORD=testtest12
pytest tests/
```

Expected result: **1 039 pass, 0 skip**.

!!! tip "Two env-var families"
    Both `NEO4J_USERNAME` / `NEO4J_PASSWORD` and `NEO4J_USER` / `NEO4J_PASS`
    are accepted via `tests/conftest.py`. The conftest mirrors whichever
    pair is set onto the other, so you can use whatever convention your
    CI already speaks.

To tear down:

```bash
docker rm -f neo4j-cv
```

## Highlights — what each test file covers

- `tests/test_orm_api_contracts.py` (21 driver-free contract tests) — pins
  the gotchas in [API caveats](../orm/caveats.md): `Cond` literal inlining,
  `Query.where` single-arg, `Traversal.path_exists` column name,
  Session/Repository constructor signatures, `BulkOps` staticmethod shape,
  `CypherFn` returns strings.
- `tests/test_orm_neo4j.py` (23 live tests) — round-trips through every
  ORM CRUD path against a real Neo4j: `Repository.find_*`, `Repository.create`,
  `BulkOps.bulk_*`, `Traversal.neighbors / shortest_path`,
  `GraphSession.execute`, `SchemaDDL.generate_all`.
- `tests/test_models_integration.py` (39 live tests) — Pydantic model
  hydration from `neo4j.graph.Node`, `from_record` / `from_records`,
  multi-label nodes, default + optional property handling.
- `tests/test_validator.py` — semantic validator coverage: labels,
  properties, endpoints, scope, aggregates, types.
- `tests/test_syntax.py` — pest grammar coverage: clauses, patterns,
  expressions.
- `tests/test_diagnostics.py` — error code emission + Levenshtein
  suggestions + auto-fix paths.
- `tests/test_subqueries.py` — `CALL { ... }`, `EXISTS { ... }`, `COUNT {
  ... }`, `COLLECT { ... }`, pattern comprehensions.

## CI cheat-sheet

The GitHub Actions workflow runs everything:

```yaml
- run: cargo test --release --locked
- run: maturin develop --release
- run: pytest tests/ -q
- name: Start Neo4j
  run: docker run -d -p 7687:7687 -e NEO4J_AUTH=neo4j/testtest12 neo4j:5.26-community
- name: Wait for Neo4j
  run: |
    until cypher-shell -u neo4j -p testtest12 'RETURN 1' >/dev/null 2>&1; do
      sleep 1
    done
- name: Live tests
  env:
    NEO4J_URI: bolt://localhost:7687
    NEO4J_USERNAME: neo4j
    NEO4J_PASSWORD: testtest12
  run: pytest tests/
```

!!! warning "`--locked` matters for releases"
    CI uses `cargo build --locked` and `cargo test --locked`. If you bump
    `Cargo.toml`'s version without regenerating `Cargo.lock`, the CI
    build fails. Always run `cargo update --workspace` after a version
    bump.

## Common failures

| Symptom | Fix |
|---|---|
| `pytest: 62 skipped` | Neo4j env vars not set — see "Python — live Neo4j" above. |
| `ImportError: _cypher_validator` | Wheel not built — run `maturin develop --release`. |
| `ValueError: cannot import name 'X' from 'cypher_validator'` | Stale `_cypher_validator.so` after Rust changes — rerun `maturin develop --release`. |
| `neo4j.exceptions.ServiceUnavailable` | Neo4j hasn't finished booting; wait a few seconds. |
| `Unauthorized: The client is unauthorized` | Wrong `NEO4J_PASSWORD` — match what `NEO4J_AUTH=` set when you started the container. |

## Performance regression sanity check

A quick benchmark you can run after touching the parser or validator:

```bash
python -c "
import time
from cypher_validator import CypherValidator, Schema

schema = Schema(
    nodes={'Person': ['name', 'age'], 'Company': ['name']},
    relationships={'WORKS_FOR': ('Person', 'Company', [])},
)
v = CypherValidator(schema)
queries = ['MATCH (p:Person) WHERE p.age > 30 RETURN p'] * 50_000

start = time.perf_counter()
v.validate_batch(queries)
elapsed = time.perf_counter() - start
print(f'{len(queries) / elapsed:.0f} q/s')
"
```

On an Apple M-series chip you should see **~55 000 q/s** for the validator
and **~57 000 q/s** for `parse_query`. See [Performance](performance.md) for
the optimisation backstory.

## Related

- [Architecture](architecture.md) — what each module does.
- [Performance](performance.md) — the numbers you should expect.
- [Contributing](contributing.md) — pre-commit hygiene.
