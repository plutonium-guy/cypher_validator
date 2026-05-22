# Parser

The `parse_query` function performs **syntactic** parsing of a Cypher query and returns
a `QueryInfo` summary — no schema required. Use it when you want to know whether a query
*could* parse, and what labels / rel-types / property keys it references.

The parser uses a [Pest](https://pest.rs) PEG grammar (`src/grammar/cypher.pest`, 312 lines)
and an AST builder (`src/parser/builder.rs`, 1040 lines). All of it runs in Rust at
**~57 000 queries/s** on a single core.

## `parse_query(query) → QueryInfo`

```python
from cypher_validator import parse_query

info = parse_query(
    "MATCH (p:Person)-[:WORKS_FOR]->(c:Company) "
    "WHERE p.age > 30 "
    "RETURN p.name, c.name"
)

info.is_valid        # True
info.errors          # []
info.labels_used     # ['Company', 'Person']     — sorted
info.rel_types_used  # ['WORKS_FOR']
info.properties_used # ['age', 'name']
```

`QueryInfo` is **truthy** when `is_valid` is `True`:

```python
if parse_query(query):
    db.execute(query)
```

| Field | Type | Notes |
|---|---|---|
| `is_valid` | `bool` | True iff the parser produced an AST without errors. |
| `errors` | `list[str]` | One string per parse error, with line/col when known. |
| `labels_used` | `list[str]` | Sorted, deduplicated; collected from every pattern (incl. subqueries). |
| `rel_types_used` | `list[str]` | Sorted, deduplicated. |
| `properties_used` | `list[str]` | Property *keys* referenced in patterns, WHERE, RETURN, etc. |

## When to use `parse_query` vs `CypherValidator`

| Need | Tool |
|---|---|
| Schema-aware validation, "did you mean?", auto-fix | [`CypherValidator`](validator.md) |
| Fast filter — "is this string even valid Cypher?" | `parse_query` |
| Provenance — "which labels does this query touch?" | `parse_query` |
| LLM repair loop with structured diagnostics | [`CypherValidator`](validator.md) |

`parse_query` is the building block used by the LLM pipeline's provenance generation:
to construct `(:Chunk)<-[:MENTIONED_IN]-(domain_node)` edges, it parses the
LLM-generated Cypher to pull out the domain labels involved.

## Labels collected from every nested construct

A recent bugfix made the parser walk the **entire** AST when collecting labels and
rel-types. Previously, the following constructs would not surface their labels:

| Construct | Now collected? |
|---|---|
| Top-level `MATCH (p:Person)` | yes (always was) |
| `CREATE` / `MERGE` patterns | yes (always was) |
| `EXISTS { (p)-[:LIVES_IN]->(:City) }` subqueries | **yes (fixed)** |
| `[(p)-[:KNOWS]->(f) WHERE f.age > 30 \| f.name]` pattern comprehensions | **yes (fixed)** |
| `shortestPath((a)-[*..5]-(b))` | **yes (fixed)** |
| `reduce(s = 0, n IN nodes(path) \| s + n.value)` inner sources | **yes (fixed)** |
| `CALL { ... }` subqueries (regular form) | **yes (fixed)** |
| `COUNT { MATCH (n:City) RETURN n }` subqueries | **yes (fixed)** |
| `COLLECT { MATCH (n:Tag) RETURN n.name }` subqueries | **yes (fixed)** |

```python
info = parse_query(
    "MATCH (p:Person) "
    "WHERE EXISTS { (p)-[:LIVES_IN]->(:City) } "
    "  AND [(p)-[:KNOWS]->(f:Friend) | f.name] <> [] "
    "RETURN p.name, "
    "       COUNT { MATCH (m:Movie)<-[:ACTED_IN]-(p) } AS films"
)

info.labels_used      # ['City', 'Friend', 'Movie', 'Person']
info.rel_types_used   # ['ACTED_IN', 'KNOWS', 'LIVES_IN']
info.properties_used  # ['name']
```

This matters because the LLM pipeline's provenance step depends on it — without these
collections, MERGE-generated edges would only attach to top-level pattern nodes, missing
entities mentioned via `EXISTS` or pattern comprehensions.

## Error reporting

When the query is syntactically invalid, `is_valid` is `False`, `errors` contains one or
more formatted strings (each typically including `line N:M`), and the label/rel-type/property
lists are empty:

```python
info = parse_query("MATCH (n:Person RETURN n")
info.is_valid   # False
info.errors     # ["Parse error at line 1:17 — expected ')' ..."]
```

For richer diagnostics with positions and "did you mean?" hints, use
[`CypherValidator`](validator.md) — its parse errors are also represented as
`E101 ParseError` diagnostics with `position_line` and `position_col` set.

## What the parser actually understands

The PEG grammar covers the practical subset of Cypher used in production:

- `MATCH` / `OPTIONAL MATCH` / `WHERE`
- `CREATE` / `MERGE` (with `ON CREATE SET` / `ON MATCH SET`)
- `SET` (assignment, property update, label addition)
- `REMOVE` (property removal, label removal)
- `DELETE` / `DETACH DELETE`
- `WITH` (incl. `WITH DISTINCT`, alias, `WHERE`, `ORDER BY`, `SKIP`, `LIMIT`)
- `RETURN` (incl. `RETURN DISTINCT`, alias, `ORDER BY`, `SKIP`, `LIMIT`)
- `UNWIND list AS item`
- `UNION` / `UNION ALL`
- `CALL { ... }` subqueries (read or write)
- `CALL proc.name(...)` standalone procedure calls
- `FOREACH (x IN list | actions)`
- Expressions: arithmetic, comparison, boolean, list, map, list comprehension,
  pattern comprehension, `EXISTS`, `COUNT { ... }`, `COLLECT { ... }`, `reduce`,
  `shortestPath`, `allShortestPaths`, function calls, parameters (`$x`), literals.
- Patterns: node patterns with multi-labels and inline maps, relationship patterns with
  variable-length (`*`, `*1..5`), direction (`->`, `<-`, `-`), and inline rel maps.

If you hit a Cypher construct the parser does not understand, please open an issue
with the failing query — the grammar is extended in `src/grammar/cypher.pest` and the
AST builder in `src/parser/builder.rs`.
