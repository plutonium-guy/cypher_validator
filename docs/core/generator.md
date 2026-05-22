# Generator

`CypherGenerator` produces **valid** Cypher queries from a schema. It is useful for:

- Building few-shot examples for an LLM prompt (see [`few_shot_examples`](../llm/tools.md#few_shot_examples)).
- Synthetic load testing and benchmarking the validator.
- Property-based testing: round-trip a generated query through the validator and assert validity.

Like the validator and parser, the generator lives in Rust for speed (~57 000 queries/s).

## Constructing a generator

```python
from cypher_validator import Schema, CypherGenerator

schema = Schema(
    nodes={"Person": ["name", "age"], "Movie": ["title", "year"]},
    relationships={"ACTED_IN": ("Person", "Movie", ["role"])},
)

gen = CypherGenerator(schema, seed=42)   # seed is optional
```

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `schema` | `Schema` | required | Drives label / rel-type / property choices |
| `seed` | `int \| None` | `None` | When set, output is fully deterministic |

!!! note "Precomputation"
    On construction the generator clones the schema's label list, rel-type list, and per-label
    property lists into owned `Vec<String>`s, so every `generate()` call avoids reallocating
    from the schema's internal `HashMap`s.

## Supported query types

```python
CypherGenerator.supported_types()
```

Thirteen templates are supported:

| Type | Shape | Example |
|---|---|---|
| `match_return` | `MATCH (n:L) RETURN n [LIMIT …]` | `MATCH (n:Person) RETURN n LIMIT 23` |
| `match_where_return` | `MATCH (n:L) WHERE n.p = v RETURN n.p` | `MATCH (n:Person) WHERE n.name = $name RETURN n.name` |
| `create` | `CREATE (n:L {…}) RETURN n` | `CREATE (n:Movie {title: "Dune"}) RETURN n` |
| `merge` | `MERGE (n:L {…}) RETURN n` | `MERGE (n:Person {name: "Alice", age: 30}) RETURN n` |
| `aggregation` | `MATCH (n:L) RETURN count(n[.p]) AS result` | `MATCH (n:Person) RETURN count(n.name) AS result` |
| `match_relationship` | `[OPTIONAL] MATCH (a:L1)-[r:R]->(b:L2) RETURN a, r, b` | `MATCH (a:Person)-[r:ACTED_IN]->(b:Movie) RETURN a, r, b` |
| `create_relationship` | `MATCH (a:L1),(b:L2) CREATE (a)-[r:R]->(b) RETURN r` | as above |
| `match_set` | `MATCH (n:L) SET n.p = v RETURN n` | `MATCH (n:Person) SET n.age = 31 RETURN n` |
| `match_delete` | `MATCH (n:L) DETACH DELETE n` | `MATCH (n:Person) DETACH DELETE n` |
| `with_chain` | `MATCH (n:L) WITH n.p AS val RETURN count(*)` | uses `WITH` to project |
| `distinct_return` | `MATCH (n:L) RETURN DISTINCT n[.p] [LIMIT …]` | `MATCH (n:Person) RETURN DISTINCT n.name` |
| `order_by` | `MATCH (n:L) RETURN n ORDER BY n.p [DESC] [LIMIT …]` | sortable test cases |
| `unwind` | `UNWIND [list] AS item RETURN item` (or `MATCH … UNWIND n.p AS item`) | list expansion |

## `generate(query_type) → str`

```python
gen.generate("match_return")
# 'MATCH (n:Movie) RETURN n LIMIT 14'

gen.generate("create_relationship")
# 'MATCH (a:Person),(b:Movie) CREATE (a)-[r:ACTED_IN]->(b) RETURN r'
```

If `query_type` is not one of the supported names, a `ValueError` is raised
(`CypherError::GeneratorError` on the Rust side).

## `generate_batch(query_type, n) → list[str]`

Avoids per-call Python overhead when you need many queries of the same shape:

```python
batch = gen.generate_batch("match_where_return", 1000)
assert len(batch) == 1000
```

Internally this loops in Rust without crossing the Python/Rust boundary per query.

## Determinism via `seed`

When constructed with a seed, the RNG is a `SmallRng::seed_from_u64(seed)` — a
PCG-family stream that is reproducible across runs and platforms:

```python
g1 = CypherGenerator(schema, seed=7)
g2 = CypherGenerator(schema, seed=7)
assert g1.generate("merge") == g2.generate("merge")
```

Without a seed, the RNG is initialised from the OS entropy source (`SmallRng::from_os_rng`)
and you get fresh output on every run.

!!! warning "Sequence dependence"
    The RNG state is **per-instance** and advances on every call. Two generators with the
    same seed will diverge if you call them in a different order. For maximum determinism
    in tests, construct a fresh generator per scenario.

## How values are generated

Scalar values cycle through:

- String literals — `"Alice"`, `"Bob"`, `"Carol"`, `"Neo4j"`, `"hello"`
- Integers in `[1, 100]`
- Booleans — `true`, `false`
- Parameter references — `$name`, `$id`, `$value`, `$limit`

Property maps pick 1–3 properties per label (capped at the label's actual property count),
and `LIMIT n` is appended with probability 1/3.

Relationship endpoints always honour the schema — `gen_create_relationship` looks up
`(src, tgt)` from the rel-type's declared endpoints, so a generated query like
`(a:Person)-[r:ACTED_IN]->(b:Movie)` is **guaranteed** to validate against the same schema.

## Round-tripping with the validator

A standard sanity check:

```python
from cypher_validator import Schema, CypherGenerator, CypherValidator

schema = Schema(...)
gen = CypherGenerator(schema, seed=0)
val = CypherValidator(schema)

for qt in CypherGenerator.supported_types():
    for query in gen.generate_batch(qt, 100):
        result = val.validate(query)
        assert result.is_valid, f"{qt} produced invalid query: {query}\n{result.errors}"
```

The validator's microbench (`tests/test_perf_*.py`) uses exactly this round-trip to feed
its workload.

## Few-shot examples for LLMs

The [`few_shot_examples`](../llm/tools.md#few_shot_examples) helper wraps the generator
to produce labelled `(description, cypher)` pairs:

```python
from cypher_validator import CypherGenerator
from cypher_validator.llm_utils import few_shot_examples

gen = CypherGenerator(schema, seed=0)
for desc, cypher in few_shot_examples(gen, n=5):
    print(f"Q: {desc}")
    print(f"A: {cypher}\n")
```
