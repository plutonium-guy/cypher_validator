# Validator

`CypherValidator` is the heart of this library. It takes a [`Schema`](schema.md) and validates
Cypher queries against it in two passes — first collecting variable bindings, then checking
every label, property, endpoint, scope and type usage.

The validator is implemented in **Rust**, releases the GIL during batch validation, and runs
at **~55 000 queries/s** on a single core. See [Performance](../dev/performance.md).

## Constructing a validator

```python
from cypher_validator import Schema, CypherValidator

schema = Schema(
    nodes={"Person": ["name", "age"], "Company": ["name"]},
    relationships={"WORKS_FOR": ("Person", "Company", ["since"])},
)
validator = CypherValidator(schema)
```

A `CypherValidator` is **stateless** — you can construct one once and use it from
multiple threads. The schema is cloned into the validator, so mutations to the
original `Schema` object after construction do not affect the validator.

## `validate(query) → ValidationResult`

```python
result = validator.validate(
    "MATCH (p:Persn)-[:WORKS_FOR]->(c:Company) RETURN p.nm, p.age"
)
print(result.is_valid)           # False
print(result.errors)             # [E201 ..., E303 ...]
print(result.fixed_query)        # auto-corrected query when every error is fixable
```

### `ValidationResult` fields

| Field | Type | Meaning |
|---|---|---|
| `is_valid` | `bool` | True iff there are no errors (warnings do not count). |
| `errors` | `list[str]` | All error messages (syntax + semantic) as formatted strings. |
| `syntax_errors` | `list[str]` | Parse errors only. |
| `semantic_errors` | `list[str]` | Schema-level errors only. |
| `warnings` | `list[str]` | Advisory warnings (`W101`, `W201`, …). Query still runs. |
| `diagnostics` | `list[ValidationDiagnostic]` | Structured form of every error and warning. |
| `fixed_query` | `str \| None` | Auto-fixed query if every error has a suggestion, else `None`. |

`result` is **truthy** when `is_valid` is `True`, and `len(result)` returns the number of errors:

```python
if result:
    db.execute(query)
else:
    print(f"{len(result)} errors")
```

### `to_dict()` / `to_json()`

```python
result.to_dict()
# {
#   "is_valid": False,
#   "errors": ["E201 ...", ...],
#   "syntax_errors": [],
#   "semantic_errors": [...],
#   "warnings": [],
#   "fixed_query": "MATCH (p:Person)-[:WORKS_FOR]...",
#   "diagnostics": [{"code": "E201", ...}, ...],
# }

result.to_json()
# Compact JSON form of the above.
```

## `ValidationDiagnostic`

Each diagnostic carries a structured error code, message, optional suggestion, and
optional source position:

```python
for d in result.diagnostics:
    print(d.code, d.code_name, d.severity)
    print(" ", d.message)
    if d.suggestion_replacement:
        print(" →", d.suggestion_description)
    if d.position_line is not None:
        print(f"  at line {d.position_line}:{d.position_col}")
```

| Field | Type |
|---|---|
| `code` | `str` (e.g. `"E201"`) |
| `code_name` | `str` (e.g. `"UnknownNodeLabel"`) |
| `severity` | `str` — `"error"` or `"warning"` |
| `message` | `str` |
| `suggestion_original` | `str \| None` |
| `suggestion_replacement` | `str \| None` |
| `suggestion_description` | `str \| None` |
| `position_line` | `int \| None` (1-based, parse errors only) |
| `position_col` | `int \| None` (1-based) |

See [Error codes](error-codes.md) for the full table of `E1xx` … `W2xx`.

## "Did you mean?" suggestions

The validator runs a **capped Levenshtein** edit-distance search (max distance 3,
1-D rolling array, early-exit on row-min > cap) over the schema's labels, relationship
types, and property names. When a close match is found within 3 edits, the
`suggestion_*` fields are populated and the error message ends with `, did you mean :Person?`.

```python
result = validator.validate("MATCH (p:Persn) RETURN p")

d = result.diagnostics[0]
d.message
# "Unknown node label: :Persn, did you mean :Person?"

d.suggestion_original     # ":Persn"
d.suggestion_replacement  # ":Person"
d.suggestion_description  # "Replace :Persn with :Person"
```

### Auto-fix

When **every** error in a query has a suggestion, the validator produces a fully
corrected query in `result.fixed_query`:

```python
result = validator.validate(
    "MATCH (p:Persn)-[:WORKS_FOR]->(c:Companyy) RETURN p.nm"
)
print(result.fixed_query)
# MATCH (p:Person)-[:WORKS_FOR]->(c:Company) RETURN p.name
```

If even one error lacks a suggestion (e.g. arity error, type error), `fixed_query` is `None`.

!!! tip "LLM repair loop"
    The [`repair_cypher()`](../llm/tools.md#repair_cypher) helper uses `fixed_query` first
    before falling back to an LLM call, so trivial typos do not consume tokens.

## `validate_batch(queries) → list[ValidationResult]`

Validate many queries in parallel:

```python
queries = ["MATCH (p:Person) RETURN p"] * 10_000
results = validator.validate_batch(queries)

failed = [r for r in results if not r.is_valid]
print(f"{len(failed)} failed of {len(results)}")
```

Under the hood:

1. The Python GIL is **released** (`py.detach`).
2. Queries are processed via Rayon's `par_iter()` — one thread per CPU.
3. Each `ValidationResult` is constructed independently.
4. The GIL is reacquired only when re-entering Python.

This means `asyncio` event loops and other Python threads stay responsive during a long batch.

## How validation works (two-pass)

The semantic validator walks the AST **twice**:

### Pass 1 — collect bindings

A `TypeEnv: HashMap<String, Vec<String>>` is built:

- Every `MATCH (p:Person)` adds `"p" → ["Person"]` to the environment.
- Pattern multi-labels accumulate: `(p:Person:Employee)` binds `"p"` to both labels.
- Relationship patterns bind variable names to their declared rel-types.
- `WITH x, y AS y2` and `RETURN x AS y` introduce new bindings in subsequent scopes.
- `OPTIONAL MATCH` bindings are preserved (variables remain typed even when null).

### Pass 2 — validate

Each clause is revisited with the full `TypeEnv` available:

- **Labels** — every `:Label` in a pattern is checked against `Schema.has_node_label`.
- **Rel types** — every `:REL_TYPE` against `Schema.has_rel_type`.
- **Endpoints** — when both endpoint labels are known via the env, the rel's source/target
  labels are checked against `Schema.rel_endpoints` → `E401`.
- **Properties** — `var.prop` lookups consult the env to find `var`'s label set, then
  check `Schema.node_has_property` for every candidate → `E303` if none match.
- **Scope** — bare identifier expressions like `p.name` require `p` to be bound → `E501`.
- **Functions** — calls are looked up in a built-in registry (count, sum, avg, exists, …);
  unknown functions emit `W103`; aggregate calls in forbidden contexts emit `E602`;
  wrong arity emits `E603`.
- **Type sanity** — `LIMIT '3'` emits `E611`; `LIMIT 1.5` emits `E614`; etc.
- **Warnings** — Cartesian products (`W101`), unlabeled full scans (`W201`), unbounded
  variable-length paths (`W202`) are emitted but do not flip `is_valid`.

### Why two passes?

Cypher allows variables to be used **before** their binding clause is complete (think
forward references in path patterns, `WITH` aliasing, and pattern comprehensions). A
single-pass walker would either miss bindings or have to backtrack. The two-pass design
keeps each phase linear in AST size and avoids any heuristic re-ordering.

## Composing with the LLM pipeline

`CypherValidator` is what powers the validate-and-repair loop in
[`LLMNLToCypher`](../llm/pipeline.md) and [`GraphRAGPipeline`](../llm/rag.md):

```python
from cypher_validator import LLMNLToCypher

pipe = LLMNLToCypher.from_openai(model="gpt-4o", schema=schema)
cypher = pipe("Alice works for Acme Corp.", mode="create")
# Internally: LLM call → extract_cypher_from_text → validator.validate
#             → (if invalid) auto-fix or repair-LLM-call → revalidate ...
```

Each repair iteration tries `result.fixed_query` first (zero tokens spent), then asks
the LLM to fix the remaining errors. The loop stops at `max_repair_retries` (default 2).
