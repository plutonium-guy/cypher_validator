# Performance

The Rust core is the hot path. Every microsecond shaved off `validate` shows
up at the top of an ingestion run that's processing thousands of LLM
responses. This page documents the numbers, the optimisations that got us
there, and what's still on the table.

## Numbers

Microbenchmark on release-mode wheels, Apple M-series, single process:

| Workload | Throughput |
|---|---|
| `CypherValidator.validate()` (single-thread) | **~55 000 queries/s** |
| `parse_query()` (schema-free) | **~57 000 queries/s** |
| `CypherValidator.validate_batch()` (Rayon, GIL released) | scales near-linearly with cores |

For an 8-core machine `validate_batch` lands around 400 000 q/s on the
same workload. The test in [Testing → Performance regression sanity
check](testing.md#performance-regression-sanity-check) is the canonical
benchmark.

## Optimisations applied

The current numbers are the result of a deliberate sweep. Each item below is
referenced by file and function so you can read the diff.

### `closest_match` — shrinking cap + length-delta pre-filter

`src/diagnostics.rs` — used to suggest "did you mean?" replacements for
unknown labels / properties / variable names.

- **Shrinking cap.** Each successful match tightens the Levenshtein cap
  used for subsequent candidates — once we know the best is 2, we won't
  bother computing distances above 2 for the rest of the candidates.
- **Length-delta pre-filter.** Skip candidates whose length differs from
  the target by more than the current cap.
- **Early return on `d == 0`.** Exact match — no point continuing.

Combined, this turned the suggestion lookup from O(n × m × cap²) into
something close to O(n) on typical schemas.

### `compute_fixed_query` — HashSet dedup

`src/diagnostics.rs`. The auto-fix code previously called
`Vec::contains` in an O(n²) inner loop while accumulating already-applied
suggestions. Switched to a `HashSet<(usize, usize)>` keyed by the
substitution span — O(1) per check, O(n) total.

### `collect_node_bindings` / `collect_rel_bindings` — split `entry`

`src/validator/semantic.rs`. The two-pass validator's first pass collects
every node and relationship variable into a `HashMap<String, Binding>`.
Original code:

```rust
let entry = bindings.entry(var.clone()).or_insert_with(...);
entry.labels.extend(labels.iter().cloned());
```

— this cloned `labels` even when the var was already bound. Rewritten:

```rust
match bindings.get_mut(var) {
    Some(b) => b.labels.extend(labels.iter().cloned()),
    None    => { bindings.insert(var.clone(), Binding { labels, ... }); }
}
```

Now we avoid the redundant clone on every revisit of the same var. Saves
allocator pressure on large queries with many `MATCH` clauses.

### `levenshtein_capped` — 1-D rolling array

`src/diagnostics.rs`. The classic two-row dynamic-programming Levenshtein
allocated `O(m × n)` cells. Switched to:

- 1-D rolling array — `O(n)` space.
- Length-delta early exit — if `|len_a - len_b| > cap`, return `cap + 1`
  without computing.
- Row-min early exit — after computing row `i`, if its minimum already
  exceeds `cap`, return `cap + 1`.

About 4× faster than the previous implementation on typical inputs.

### Regex hoisting

`python/cypher_validator/llm_utils.py` and `python/cypher_validator/llm_pipeline.py`.
Every regex used in the hot path is now compiled once at module scope:

```python
_RE_FENCED_TAGGED   = re.compile(r"```(?:cypher|sql|sparql)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
_RE_FENCED_ANY      = re.compile(r"```\w*\s*\n(.*?)```", re.DOTALL)
_RE_BACKTICK        = re.compile(r"`([^`\n]+)`")
_RE_CYPHER_LINE     = re.compile(r"^\s*(MATCH|CREATE|MERGE|WITH|CALL|UNWIND|OPTIONAL)\b", re.IGNORECASE)
_RE_JSON_BLOCK      = re.compile(r"```json\s*\n(.*?)```", re.DOTALL)
_RE_CYPHER_BLOCK    = re.compile(r"```cypher\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
_RE_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")
```

Previously these were compiled per-call inside `extract_cypher_from_text` and
`_parse_inferred_schema`. On a 10 000-text batch that's 10 000 unnecessary
`re.compile` calls per pattern.

### `Schema` — `HashSet<String>` for properties

`src/schema/mod.rs`. Property lookup used to be a `Vec<String>` walk —
`has_property` was O(n). Now properties are stored as `HashSet<String>` and
`has_property` is O(1).

Schema construction is unchanged from the user's perspective:

```rust
Schema::new(nodes: HashMap<String, Vec<String>>, ...)
// internally converts to HashMap<String, HashSet<String>>
```

`property_names()` still returns the original order because we keep both
representations.

### `CypherGenerator::new` — precompute label / rel_type / props vecs

`src/generator/mod.rs`. The generator used to walk the schema to extract
labels and rel_types on every `generate()` call. The constructor now caches
`labels: Vec<String>`, `rel_types: Vec<String>`, and `props_by_label:
HashMap<String, Vec<String>>` once. Generation is now ~3× faster and
allocation-light.

### `validate_batch` — Rayon + GIL release

`src/bindings/py_validator.rs`. The batch-validate path releases the GIL
via `Python::allow_threads`, then drives `rayon::par_iter`:

```rust
fn validate_batch(&self, py: Python<'_>, queries: Vec<String>)
    -> PyResult<Vec<PyValidationResult>>
{
    let results = py.allow_threads(|| {
        queries.par_iter().map(|q| self.validate_internal(q)).collect()
    });
    Ok(results)
}
```

This lets other Python threads (or async tasks bouncing through
`asyncio.to_thread`) run while the validator chews through the batch.

## What's not yet optimised

Profiling notes for the next sweep:

- **`parser/builder.rs::build_pattern`** — recursive descent over pest
  Pairs allocates a fresh `Vec<Pattern>` for each level. Could pool
  these via a `bumpalo` arena.
- **`semantic.rs::validate_expr`** — the `match` arms for every expression
  variant rebuild a `HashSet<String>` of in-scope variables on each call.
  Threading the set down by reference instead of cloning would save a
  measurable amount of allocator churn on deeply nested `WHERE` clauses.
- **Python `Query.build`** — the `_node_pattern` / `_rel_pattern` helpers
  use f-strings inside a loop. Could batch into a single `str.join`.
- **`gliner2_integration.py::_collect_entity_status`** — sends one
  `MATCH (n {name: ...}) RETURN count(n) > 0` per unique entity. A
  single `UNWIND $names AS name MATCH (n {name: name}) RETURN name, ...`
  query would cut DB round-trips from N to 1.
- **`llm_pipeline.py::_chunk_text`** — currently O(n²) in the worst case
  because of the rewind for overlap. Fine up to ~100 KB of input.

!!! tip "Profile before optimising"
    All of the wins above came from running `cargo flamegraph` on the
    Rust side and `py-spy --rate 250` on the Python side. If you find
    a new bottleneck, generate a flamegraph and post it on the PR — it
    makes the review trivial.

## Benchmark caveats

The 55 000 q/s number assumes:

- **Release build.** Debug is 5-10× slower.
- **Short queries** — typical `MATCH (n:Label) WHERE n.prop > 30 RETURN n`
  shape. Long queries with deeply nested subqueries are 2-5× slower.
- **Warm schema cache.** Cold `Schema::new` adds ~50 µs of setup.
- **No `validate_batch` GIL contention** — measured single-threaded.

The reported throughput is **steady-state** after a warm-up pass. Cold
JIT/parser caches add ~200 ms before throughput stabilises.

## Where to next

- [Architecture](architecture.md) — what these modules actually do.
- [Testing](testing.md) — the canonical regression benchmark.
- [Contributing](contributing.md) — how to ship a perf PR.
