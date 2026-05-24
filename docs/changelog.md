# Changelog

Reverse-chronological. Versions follow [SemVer](https://semver.org/) and
correspond to git tags. The "Unreleased" section accumulates between tags.

## v0.13.0 — Vector search & models split

### Added

- **`models.py` split into package.** The 3641-line `models.py` is now a
  `models/` package with focused modules: `orm.py`, `query.py`, `schema.py`,
  `session.py`, `agents.py`. All public imports are unchanged via PEP 562
  lazy `__getattr__` re-exports.
- **Full-stack vector search support.** `VectorProperty` descriptor on
  `NodeModel.__vector_indexes__` for declaring vector indexes.
  `SchemaDDL.vector_indexes()` generates `CREATE VECTOR INDEX` DDL (Neo4j 5.11+).
  `Query.vector_search()` / `vector_search_model()` for the query builder.
  `GraphSession.vector_search()` / `semantic_search()` and async equivalents
  on `AsyncGraphSession`.
- **Embedding adapters.** `cypher_validator.embeddings` module with
  `OpenAIEmbeddings`, `SentenceTransformerEmbeddings`, `CohereEmbeddings`
  adapters. `EmbeddingFn` / `BatchEmbeddingFn` runtime-checkable protocols.
- **CLI vector search.** `cypher vector-search` subcommand with `--vector`,
  `--text`, `--provider`, `--top-k` options.

### Fixed

- **Vector index name injection.** `Query.vector_search()` validates index
  names against `^[A-Za-z_][A-Za-z0-9_]*$` to prevent Cypher injection.

- **NLToCypher returns parameterized Cypher.** The GLiNER2 pipeline no longer
  inlines entity literals via `_inline_params` before returning the query
  string. Callers receive `(cypher, params)` with `$param` placeholders
  intact — safe to log and route through any Cypher-validating layer.
- **`py_parser.collect_expr` threads labels and rel_types correctly.**
  Subqueries, pattern comprehensions, `shortestPath`, and `reduce` now
  populate `PyQueryInfo.labels_used` and `PyQueryInfo.rel_types_used`. Before
  this fix, `parse_query` could under-report what a query referenced — which
  in turn broke `_build_provenance_cypher` for any query that used a
  subquery to discover its domain labels.

### Performance

- **ORM metaclass** — single-pass `__init__` replaces two-pass
  `__init__` + `__init_subclass__` pattern. Regex compiled at module level.
- **Lazy imports** — `models/__init__.py` uses PEP 562 `__getattr__` so
  `import cypher_validator.models` only loads submodules on first access.
- **Agent tool lookups** — `AgentTools` / `ExtendedAgentTools` build
  `label→model` and `rel_type→model` dicts at init for O(1) dispatch
  instead of linear scans.
- **Batch DB introspection** — `GraphSchema.from_neo4j_db()` uses 2 batch
  queries (nodes + rels) instead of N+1 individual queries.
- `closest_match` — shrinking cap on each hit + length-delta pre-filter +
  early return on exact match.
- `compute_fixed_query` — `HashSet` dedup replaces an O(n²) `Vec::contains`
  inner loop.
- `collect_node_bindings` / `collect_rel_bindings` — split `entry` API into
  `get_mut` + `insert` so the labels `Vec` isn't cloned when a variable is
  already bound.
- `levenshtein_capped` — 1-D rolling array (O(n) space), length-delta early
  exit, row-min early exit.
- Regex hoisting in `llm_utils.py` and `llm_pipeline.py`:
  `_RE_FENCED_TAGGED`, `_RE_FENCED_ANY`, `_RE_BACKTICK`, `_RE_CYPHER_LINE`,
  `_RE_JSON_BLOCK`, `_RE_CYPHER_BLOCK`, `_RE_SENTENCE_BOUNDARY`.
- `Schema` — `HashSet<String>` for properties; `has_property` is now O(1).
- `CypherGenerator::new` — precomputes labels / rel_types / props_by_label
  `Vec`s once at construction.
- `validate_batch` — Rayon parallel iteration with GIL release via
  `Python::allow_threads`.

See [Performance](dev/performance.md) for context and numbers.

### Documentation

- New MkDocs Material site: schema / validator / generator / parser /
  error-codes pages, the full Pydantic ORM reference (models, query builder,
  repository, sessions, bulk ops, traversal, DDL, agent tools, caveats),
  the LLM section (pipeline, RAG, tools, async), GLiNER2 integration, and
  the developer-facing architecture / testing / performance / contributing
  pages.

### Tests

- `tests/test_orm_api_contracts.py` — 21 driver-free contract tests pinning
  the gotchas in [API caveats](orm/caveats.md): `Cond` literal inlining,
  `Query.where` single-arg, `Traversal.path_exists` column name,
  `GraphSession` / `Repository` constructor signatures, `BulkOps`
  `@staticmethod` shape, `CypherFn` returns plain strings.
- `tests/test_orm_neo4j.py` — 23 live integration tests round-tripping
  every ORM CRUD path against Neo4j 5.26-community.
- `tests/conftest.py` — mirrors `NEO4J_USERNAME` / `NEO4J_PASSWORD` and
  `NEO4J_USER` / `NEO4J_PASS` so either env-var convention works.

## v0.12.0 — Pydantic Cypher ORM

The biggest single release since v0.9.0.

### Added

- **Pydantic ORM layer.** `NodeModel` / `RelationshipModel` with
  registry-aware metaclasses, `GraphSchema.from_models` / `from_registry` /
  `from_neo4j_db`, the `Query` fluent builder (with `Cond`, `CondGroup`,
  `RawExpr`, `PropExpr`, `NodeRef`, `RelRef`, `PathBuilder`).
- `Repository(model, db, var="n")` — typed CRUD wrapper.
- `BulkOps.bulk_create_nodes` / `bulk_merge_nodes` /
  `bulk_create_relationships` / `bulk_merge_relationships` /
  `bulk_delete_nodes` — all `@staticmethod` returning `(cypher, params)`.
- `Traversal` — `neighbors`, `shortest_path`, `subgraph`, `degree`,
  `common_neighbors`, `path_exists`.
- `SchemaDDL` + `SchemaDiff` — constraints, indexes, migration DDL.
- `GraphSession` / `AsyncGraphSession` — execute Cypher with hydration into
  Pydantic instances.
- **AI agent tools.** `AgentTools` / `ExtendedAgentTools` produce OpenAI
  and Anthropic function-call specs and dispatch them back to
  `(cypher, params)` via `handle_tool_call`.
- `QueryHistory`, `QueryPlan`, `QueryResult`, `CypherFn` (type-safe wrappers
  for common Cypher functions), `schema_to_pipeline_kwargs`.

See [`docs/orm/`](orm/index.md) for the full reference.

## v0.11.0 — Subqueries & pattern comprehensions

### Added

- `CALL { ... }` subqueries — both read and write forms.
- `EXISTS { ... }`, `COUNT { ... }`, `COLLECT { ... }` subquery
  expressions.
- Pattern comprehensions — `[(n)-[:REL]-(m) WHERE ... | expr]`.

### Tests

- `tests/test_subqueries.py` covers every new construct against the
  validator and the parser.

## v0.10.0 — initial Cypher ORM scaffold

First cut at the Pydantic ORM. Established the `NodeModel` /
`RelationshipModel` registration mechanism and the `GraphSchema` bridge into
the Rust validator. The full surface area landed in v0.12.0.

## v0.9.1 — strict NER mode

### Fixed

- `_collect_entity_status` now operates in **strict NER mode** when an
  `EntityNERExtractor` is supplied: relation triples with at least one
  unconfirmed endpoint are silently dropped, which prevents schema endpoint
  labels from being stamped onto non-entity spans (e.g. "doctor" → `Drug`).

## v0.9.0 — warnings, REDUCE, shortestPath, FOREACH

### Added

- **Warning diagnostics.** Codes `W101`–`W2xx` for stylistic issues that
  don't block execution.
- `REDUCE`, `shortestPath` / `allShortestPaths`, `FOREACH` — full validator
  coverage.
- Aggregate scope checks (no aggregate inside a `WHERE`, no nested
  aggregates).
- `WITH` scope fix — variables not carried forward through `WITH` are
  correctly reported as out-of-scope.

## v0.6.1 — inline entity values

### Fixed

- The GLiNER2 pipeline used to inline entity values into returned Cypher
  strings via `_inline_params`. Reverted to keep `$param` placeholders, but
  the v0.6.1 fix re-enabled inlining as an option for callers that needed
  it. The "Unreleased" entry above reverses this — parameterised by
  default.

## v0.6.0 — EntityNERExtractor + db_aware

### Added

- `EntityNERExtractor` — spaCy and HuggingFace backends.
- `NLToCypher(..., db_aware=True)` — MATCH existing entities, CREATE new
  ones in a single round-trip.
- 11 worked examples in `examples/` using real models, no mocks.

## v0.5.0 — Graph RAG + did-you-mean

### Added

- `GraphRAGPipeline` — full NL question → Cypher → execute → format → answer
  chain.
- `cypher_validator.llm_utils`: `extract_cypher_from_text`, `repair_cypher`,
  `cypher_tool_spec`, `format_records`, `few_shot_examples`.
- Levenshtein "did you mean?" suggestions in validator diagnostics +
  `result.fixed_query` auto-fix.
- Parameterised query support throughout the validator and generator.

### Fixed

- `IS NULL` / `IS NOT NULL` validator handling.

## v0.4.0 — Schema APIs + generation batch

### Added

- `Schema.merge`, `Schema.to_json`, `Schema.from_json`.
- `CypherGenerator.generate_batch(n, query_type=None)` — bulk query
  generation.
- `NLToCypher.from_env()` — pick up Neo4j credentials from env vars.
- `Neo4jDatabase.execute_many` — sequential multi-query execution.

## v0.3.0 — Neo4jDatabase + db-aware

### Added

- `Neo4jDatabase` — context-managed wrapper around the official driver.
- `NLToCypher(..., db=db)` — generate Cypher *and* execute it.

## v0.2.0 — GLiNER2 hard dep

### Changed

- `gliner2` is now a required dependency. Previously it was optional but
  every published example relied on it.

## v0.1.0 — initial release

- Rust parser + validator + generator via PyO3.
- Pest grammar at `src/grammar/cypher.pest`.
- `Schema`, `CypherValidator`, `CypherGenerator`, `parse_query` Python API.
- Basic GLiNER2 integration.
- 13 query-type templates in the generator.
