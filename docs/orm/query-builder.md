# Query builder

`Query` is the fluent Cypher builder at the heart of the ORM. Every method returns `self`,
so calls chain naturally. `build()` returns `(cypher_string, params_dict)` — the same
tuple shape used everywhere else in this library.

```python
from cypher_validator import Query, Cond, NodeModel

class Person(NodeModel):
    __label__ = "Person"
    name: str
    age: int = 0

q = (Query()
     .match(Person, "p")
     .where(Cond("p.age", ">=", 18))
     .return_("p.name", "p.age")
     .order_by("p.name")
     .limit(10))

cypher, params = q.build()
# MATCH (p:Person) WHERE p.age >= 18 RETURN p.name, p.age ORDER BY p.name LIMIT 10
# params = {}   (Cond inlined the literal 18)
```

## Method reference

### MATCH / OPTIONAL MATCH

```python
q.match(Person, "p")                          # MATCH (p:Person)
q.match(Person, "p", props={"name": "Alice"}) # MATCH (p:Person {name: $p_1})
q.match(pattern="(p:Person)-[:KNOWS]->(q)")   # raw pattern string
q.optional_match(Movie, "m")                  # OPTIONAL MATCH (m:Movie)
```

`match(model, var, props=None, *, pattern=None)` accepts:

- `model_or_label` — a `NodeModel` subclass **or** a raw label string (`"Person"`).
- `var` — the Cypher variable name. Omit to produce `(:Person)`.
- `props` — inline property map, auto-parameterised through `$var_N` placeholders.
- `pattern` (keyword-only) — full raw pattern string, bypasses model/label/props.

### `match_path` — tuple syntax

For path matching, each "node" or "rel" is a 3-tuple `(model_or_label, var, props)`:

```python
q.match_path(
    (Person, "p", None),
    (ActedIn, "r", None),
    (Movie, "m", {"year": 1999}),
    direction="out",          # "in" / "both" also valid
    min_hops=1,
    max_hops=3,
    optional=False,
)
# MATCH (p:Person)-[r:ACTED_IN*1..3]->(m:Movie {year: $m_1})
```

`direction` is one of `"out"` (default, `-->`), `"in"` (`<--`), `"both"` (`--`).

### WHERE / AND / OR

!!! warning "Single-argument API"
    `Query.where()` accepts **exactly one** argument — either a `Cond`/`CondGroup` or a
    raw string. There is **no kwargs-style auto-parameterisation**. Bind values via
    `.params(name=...)` or pass a `Cond` (which inlines scalar literals — see
    [API caveats](caveats.md)).

```python
q.where(Cond("p.name", "=", "$name")).params(name="Alice")
q.where("p.age > $min_age").params(min_age=30)
q.where(Cond("p.age", ">", 18) & Cond("p.age", "<", 65))   # AND
q.where(Cond("p.age", "<", 18) | Cond("p.age", ">", 65))   # OR
```

`and_where()` / `or_where()` produce `AND` / `OR` continuation clauses for readability:

```python
(Query()
 .match(Person, "p")
 .where(Cond("p.age", ">", 18))
 .and_where(Cond("p.age", "<", 65))
 .or_where(Cond("p.name", "STARTS WITH", "$prefix"))
 .return_("p"))
# MATCH (p:Person) WHERE p.age > 18 AND p.age < 65 OR p.name STARTS WITH $prefix RETURN p
```

### CREATE / MERGE / CREATE path

```python
q.create(Person, "p", props={"name": "Bob"})              # CREATE (p:Person {name: $p_1})
q.merge(Person, "p", props={"name": "Alice"})             # MERGE (p:Person {name: $p_1})
q.create_path((Person, "p", None),
              (ActedIn, "r", {"roles": ["Trinity"]}),
              (Movie, "m", {"title": "Matrix"}))
# CREATE (p:Person)-[r:ACTED_IN {roles: $r_1}]->(m:Movie {title: $m_2})
```

### SET / REMOVE / DELETE

```python
q.set("p.age = 31", "p.updated = timestamp()")            # raw assignments
q.set_props("p", {"age": 31, "email": "p@example.com"})   # parameterised
q.on_create_set("p.created = datetime()")                 # paired with MERGE
q.on_match_set("p.updated = datetime()")
q.remove("p.deprecated_field", "p:OldLabel")
q.delete("p")                                             # DELETE p
q.delete("p", "r", detach=True)                           # DETACH DELETE p, r
```

`set_props(var, props)` auto-parameterises — each value goes into a fresh `$var_N` slot.
This is the safe default for user-supplied data.

### WITH / RETURN

```python
q.with_("p", "count(r) AS knows_count")
q.with_("p.name AS name", distinct=True)                  # WITH DISTINCT
q.return_("p.name", "p.age")
q.return_("p.name", distinct=True)                        # RETURN DISTINCT
```

### ORDER BY / SKIP / LIMIT / UNWIND

```python
q.order_by("p.age DESC", "p.name")
q.skip(20).limit(10)
q.unwind("[1, 2, 3]", "x")                                # UNWIND [1, 2, 3] AS x
q.unwind("$items", "item")                                # UNWIND $items AS item
```

### CALL subquery

```python
inner = Query().match(Movie, "m").where(Cond("m.year", ">", 2000)).return_("m")
q.call_subquery(inner)
# CALL {
#   MATCH (m:Movie) WHERE m.year > 2000 RETURN m
# }

q.call_subquery("MATCH (n:Tag) RETURN count(n) AS tag_count")   # raw string also works
```

When passing a `Query`, its parameters are merged into the outer query's params dict.

### FOREACH / UNION / raw

```python
q.foreach("x", "[1, 2, 3]", "CREATE (:Index {n: x})")
# FOREACH (x IN [1, 2, 3] | CREATE (:Index {n: x}))

q.union(other_query, all=False)                           # or all=True for UNION ALL

q.raw("CALL db.indexes() YIELD name")                     # append arbitrary text
```

### Parameters

```python
q.param("name", "Alice")            # single binding
q.params(name="Alice", age=30)      # multiple
```

`.params()` is the **only** way to pass scalar values into a `where("…")` string clause.

### `build()` / `build_cypher()`

```python
cypher, params = q.build()          # tuple
cypher = q.build_cypher()           # string only
print(q)                            # uses build_cypher()
```

### `to_dict()` / `to_json()` / `from_dict()` / `from_json()`

Serialise a query for agent message passing:

```python
d = q.to_dict()
# {
#   "cypher": "MATCH (p:Person) WHERE p.age >= 18 RETURN p",
#   "parameters": {},
#   "clauses": [("MATCH", "(p:Person)"), ("WHERE", "p.age >= 18"), ("RETURN", "p")],
# }

q2 = Query.from_dict(d)
assert q2.build() == q.build()
```

If `"clauses"` is present, the full builder is reconstructed (chainable downstream).
Otherwise the query is rebuilt as a single raw clause.

### `validate(schema)` and `explain()`

```python
result = q.validate(schema)         # accepts CypherValidator, Schema, or GraphSchema
assert result.is_valid

print(q.explain())
# Find pattern: (p:Person)
# Filter: p.age >= 18
# Return: p.name, p.age
```

`explain()` produces a human-readable breakdown — handy for surfacing to non-technical
users or as part of an LLM chain-of-thought.

## Conditions — `Cond`, `CondGroup`, `Op`

`Cond(left, op, right=None)` builds a single condition. The `op` argument may be a string
or an `Op` enum value:

```python
from cypher_validator import Cond, Op

Cond("p.name", "=", "$name")
Cond("p.age", ">", 18)
Cond("p.status", "IS NULL")
Cond("p.email", "CONTAINS", "@example.com")
Cond("p.score", Op.GTE, 80)
```

`Op` enum values:

| `Op` | Cypher token |
|---|---|
| `EQ` | `=` |
| `NEQ` | `<>` |
| `LT` | `<` |
| `LTE` | `<=` |
| `GT` | `>` |
| `GTE` | `>=` |
| `CONTAINS` | `CONTAINS` |
| `STARTS_WITH` | `STARTS WITH` |
| `ENDS_WITH` | `ENDS WITH` |
| `IN` | `IN` |
| `IS_NULL` | `IS NULL` (right ignored) |
| `IS_NOT_NULL` | `IS NOT NULL` (right ignored) |
| `REGEX` | `=~` |

### How `Cond` renders the right-hand side

`Cond` **inlines literal scalars directly into the Cypher string**. This is intentional
for readability, but it means values are *not* added to the params dict:

```python
Cond("p.age", ">", 18).render()            # 'p.age > 18'
Cond("p.name", "=", "Alice").render()      # "p.name = 'Alice'"
Cond("p.active", "=", True).render()       # 'p.active = true'
Cond("p.deleted", "=", None).render()      # 'p.deleted = null'
```

If the right-hand side starts with `$`, it is preserved as a parameter reference:

```python
Cond("p.name", "=", "$name").render()      # 'p.name = $name'
```

This is the **safe** way to bind user-supplied data — wrap the value as `"$name"` in
the `Cond` and supply the actual value via `q.params(name=actual_value)`. See
[API caveats](caveats.md) for the full discussion.

### Composing with `&` and `|`

```python
c = (Cond("p.age", ">", 18) & Cond("p.age", "<", 65)) | Cond("p.is_admin", "=", True)
# (p.age > 18 AND p.age < 65) OR p.is_admin = true
q.where(c)
```

`&` and `|` return `CondGroup` objects. Parentheses are added automatically when a
nested group has a different operator from its parent.

## `RawExpr`

The escape hatch for arbitrary Cypher expressions:

```python
from cypher_validator.models import RawExpr

q.where(RawExpr("apoc.text.levenshtein(p.name, $target) < 3"))
```

`RawExpr.render()` returns the expression verbatim — no escaping, no parameter binding.

## `PropExpr` / `NodeRef` / `RelRef`

These let you write expressions that look like Python attribute access:

```python
from cypher_validator import NodeRef

p = NodeRef(Person, "p")

q = (Query()
     .match(p)
     .where(p.age > 18)
     .where(p.name.starts_with("$prefix"))
     .return_(p))
```

`p.age` returns a `PropExpr` whose comparison operators (`==`, `!=`, `<`, `<=`, `>`, `>=`)
return `Cond` objects. String / list methods produce the right `Cond` for `CONTAINS`,
`STARTS WITH`, `ENDS WITH`, `IN`, `IS NULL`, `IS NOT NULL`, `=~` (regex).

`RelRef` is the same idea for relationships:

```python
from cypher_validator import RelRef
r = RelRef(ActedIn, "r")
q.where(r.year > 1990).return_(r.roles)
```

## `CypherFn` / `fn`

Type-safe wrappers for common built-in functions. Use `fn` (alias of `CypherFn`) for
brevity in projections:

```python
from cypher_validator import fn, NodeRef

p = NodeRef(Person, "p")
q = (Query()
     .match(p)
     .return_(
         fn.count(p),
         fn.avg(p.age),
         fn.as_(fn.count_distinct(p.name), "unique_names"),
     ))
# RETURN count(p), avg(p.age), count(DISTINCT p.name) AS unique_names
```

Available helpers — `count`, `count_distinct`, `sum`, `avg`, `min`, `max`, `collect`,
`collect_distinct`, `coalesce`, `head`, `last`, `size`, `length`, `type`, `labels`,
`id`, `element_id`, `to_lower`, `to_upper`, `trim`, `replace`, `substring`,
`abs`, `ceil`, `floor`, `round`, `timestamp`, `date`, `datetime`, `as_`.

## `PathBuilder`

For complex multi-hop patterns, `PathBuilder` chains nodes and relationships fluently:

```python
from cypher_validator import PathBuilder

path = (PathBuilder(Person, "actor")
        .rel(ActedIn, "r")
        .to(Movie, "movie")
        .rel("DIRECTED", direction="in")
        .to(Person, "director"))

q = (Query()
     .match(pattern=path.build())
     .return_("actor", "director"))
# MATCH (actor:Person)-[r:ACTED_IN]->(movie:Movie)<-[:DIRECTED]-(director:Person)
# RETURN actor, director
```

`PathBuilder.params` holds any literal property maps converted to parameters; use
`path.to_query()` to obtain a `Query` pre-seeded with them.

## `QueryPlan` / `QueryStep` / `QueryResult`

For multi-step agent workflows, `QueryPlan` lets you express dependencies between steps:

```python
from cypher_validator import QueryPlan, QueryStep

plan = QueryPlan(
    goal="Find Alice's co-workers and their projects",
    steps=[
        QueryStep(
            description="Look up Alice",
            cypher="MATCH (a:Person {name: $name}) RETURN a",
            parameters={"name": "Alice"},
            depends_on=[],
            is_read=True,
        ),
        QueryStep(
            description="Find her colleagues",
            cypher="MATCH (a:Person {name: $name})-[:WORKS_WITH]->(c) RETURN c",
            parameters={"name": "Alice"},
            depends_on=[0],
        ),
    ],
)

# Topological sort into parallel waves
for wave in plan.to_execution_order():
    print("wave:", wave)
print(plan.explain())
```

`plan.validate_all(schema)` validates every step against a schema and returns a list of
`(step_index, ValidationResult)` tuples.

`QueryResult` is the structured wrapper for execution output — useful when handing results
back to an LLM:

```python
from cypher_validator import QueryResult

qr = QueryResult(
    cypher=cypher,
    parameters=params,
    records=session.execute(cypher, params),
    summary="Found N actors",
)
print(qr.success)                # True if no error and validation passed
print(qr.count)                  # len(records)
print(qr.to_markdown())          # markdown table
print(qr.to_natural_language())  # one-sentence NL summary
```
