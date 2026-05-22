# Error codes

Every diagnostic produced by [`CypherValidator`](validator.md) carries a structured
`ErrorCode`. Codes are stable across versions and grouped by category.

| Range | Category |
|---|---|
| `E1xx` | Parse / syntax errors |
| `E2xx` | Unknown label / relationship type |
| `E3xx` | Unknown property |
| `E4xx` | Wrong endpoint label |
| `E5xx` | Scope / binding errors |
| `E6xx` | Type / aggregate / arity misuse |
| `W1xx` | Performance warnings |
| `W2xx` | Complexity warnings |

A code's severity is fixed: `W1xx` / `W2xx` are warnings; everything else is an error.
Errors flip `result.is_valid` to `False`; warnings do not.

## Parse errors

### `E101 ParseError`

**Severity:** error  •  **Fires when** the Pest grammar cannot parse the input.

```cypher
MATCH (n:Person RETURN n
```

Triggers `E101` at `line 1:17`. The diagnostic's `position_line` and `position_col` are
populated for parse errors (and only for parse errors).

**Suggestion:** none — the parser cannot know what you meant.

## Unknown label / relationship type

### `E201 UnknownNodeLabel`

**Severity:** error  •  **Fires when** a node pattern references a label not in the schema.

```cypher
MATCH (p:Persn) RETURN p
```

→ `Unknown node label: :Persn, did you mean :Person?`

**Suggestion:** if a schema label is within Levenshtein distance 3, the validator
populates `suggestion_original=":Persn"`, `suggestion_replacement=":Person"`.

### `E202 UnknownNodeLabelInSet`

**Severity:** error  •  **Fires** for unknown labels added via `SET`.

```cypher
MATCH (p:Person) SET p:Admn RETURN p
```

→ `Unknown node label in SET clause: :Admn, did you mean :Admin?`

**Suggestion:** label replacement suggested when within distance 3.

### `E203 UnknownNodeLabelInRemove`

**Severity:** error  •  **Fires** for unknown labels removed via `REMOVE`.

```cypher
MATCH (p:Person) REMOVE p:Admn RETURN p
```

**Suggestion:** label replacement suggested when within distance 3.

### `E211 UnknownRelType`

**Severity:** error  •  **Fires when** a relationship pattern uses an unknown rel-type.

```cypher
MATCH (p:Person)-[:WORK_FOR]->(c:Company) RETURN p, c
```

→ `Unknown relationship type: :WORK_FOR, did you mean :WORKS_FOR?`

**Suggestion:** rel-type replacement when within distance 3.

## Unknown property

### `E301 UnknownNodeProperty`

**Severity:** error  •  **Fires when** an inline node pattern uses an unknown property:
`(p:Person {nm: "Alice"})`.

```cypher
CREATE (p:Person {nm: "Alice"}) RETURN p
```

→ `Unknown property 'nm' on label :Person, did you mean 'name'?`

**Suggestion:** property replacement when within distance 3 of one of the label's
declared properties.

### `E302 UnknownRelProperty`

**Severity:** error  •  **Fires when** an inline relationship pattern uses an unknown
property: `[:WORKS_FOR {snc: 2020}]`.

```cypher
MATCH (p:Person)-[r:WORKS_FOR {snc: 2020}]->(c:Company) RETURN r
```

**Suggestion:** when within distance 3 of one of the rel-type's declared properties.

### `E303 UnknownNodePropertyOnVar`

**Severity:** error  •  **Fires when** an expression `var.prop` is used and `prop` is
not declared on any of the labels `var` is bound to.

```cypher
MATCH (p:Person) RETURN p.nm
```

→ `Unknown property 'nm' on variable 'p' with label :Person, did you mean 'name'?`

**Suggestion:** property replacement within distance 3.

### `E304 UnknownRelPropertyOnVar`

**Severity:** error  •  **Fires when** an expression `rel_var.prop` is used and `prop`
is not declared on the bound rel-type.

```cypher
MATCH (p:Person)-[r:WORKS_FOR]->(c:Company) RETURN r.yr
```

**Suggestion:** property replacement within distance 3.

## Wrong endpoint label

### `E401 WrongEndpointLabel`

**Severity:** error  •  **Fires when** a relationship is used between endpoint labels
that contradict the schema's `(src, tgt)` declaration.

Given `WORKS_FOR: (Person → Company)`:

```cypher
MATCH (m:Movie)-[:WORKS_FOR]->(c:Company) RETURN m
```

→ `Relationship :WORKS_FOR expected source :Person, got :Movie.`

**Suggestion:** none (changing one endpoint vs. the other vs. swapping is ambiguous).

## Scope / binding

### `E501 UnboundVariable`

**Severity:** error  •  **Fires when** a variable is referenced before it is bound.

```cypher
RETURN x.name
```

```cypher
MATCH (p:Person) RETURN q.name   // q never matched
```

**Suggestion:** none — the validator cannot guess which match clause you intended.

### `E502 DuplicateProjectionName`

**Severity:** error  •  **Fires when** a `RETURN` or `WITH` projects the same name twice.

```cypher
MATCH (p:Person) RETURN p.name AS name, p.email AS name
```

→ `Duplicate projection name: 'name'.`

**Suggestion:** none — choose a different alias.

## Type / aggregate / arity

### `E601 AggregateStringArg`

**Severity:** error  •  **Fires when** an aggregate function gets a string literal where
a numeric / node argument is required.

```cypher
MATCH (n:Person) RETURN sum("hello")
```

**Suggestion:** none.

### `E602 AggregateInForbiddenContext`

**Severity:** error  •  **Fires when** an aggregate is used inside `WHERE` (Cypher forbids
this — use `WITH` to stage aggregates first).

```cypher
MATCH (p:Person)-[:KNOWS]->(f)
WHERE count(f) > 5
RETURN p
```

→ `Aggregate function 'count' is not allowed in WHERE clause; use WITH first.`

**Suggestion:** none.

### `E603 WrongArity`

**Severity:** error  •  **Fires when** a built-in function is called with the wrong
number of arguments.

```cypher
MATCH (n) RETURN coalesce()        // needs ≥1 arg
MATCH (n) RETURN length()          // needs 1 arg
MATCH (n) RETURN substring("abc")  // needs 2 or 3 args, got 1
```

**Suggestion:** none — the message tells you the expected range.

### `E611 PaginationTypeString`

**Severity:** error  •  **Fires when** `SKIP` or `LIMIT` receives a string literal.

```cypher
MATCH (n) RETURN n LIMIT '3'
```

→ `LIMIT requires an integer expression, got string literal '3'.`

**Suggestion:** none.

### `E612 PaginationTypeBool`

**Severity:** error  •  As `E611` but for boolean literals.

```cypher
MATCH (n) RETURN n LIMIT true
```

### `E613 PaginationTypeNull`

**Severity:** error  •  As `E611` but for `null`.

```cypher
MATCH (n) RETURN n SKIP null
```

### `E614 PaginationTypeFloat`

**Severity:** error  •  As `E611` but for float literals.

```cypher
MATCH (n) RETURN n LIMIT 1.5
```

## Warnings (`W1xx` / `W2xx`)

Warnings are advisory — the query *will* execute. The validator emits them so an LLM
agent or human reviewer can choose whether to refine the query.

### `W101 CartesianProduct`

**Severity:** warning  •  **Fires when** two disconnected `MATCH` clauses share no
variables, producing an implicit cross product.

```cypher
MATCH (a:Person), (b:Movie) RETURN a, b
```

→ `Possible cartesian product between (a:Person) and (b:Movie); add a connecting pattern or use WITH.`

### `W103 UnknownFunction`

**Severity:** warning  •  **Fires when** a function call name is not in the built-in
registry. Procedures from APOC or GDS won't be recognised — this is intentional.

```cypher
MATCH (n) RETURN apoc.coll.flatten([[1, 2], [3]])
```

→ `Unknown function 'apoc.coll.flatten' — call may fail at runtime.`

### `W104 DistinctOnNonAggregate`

**Severity:** warning  •  **Fires when** `DISTINCT` is applied to an expression that
is not part of any aggregate. Usually a sign of a misunderstanding (Cypher's `DISTINCT`
operates on the entire projection list).

```cypher
MATCH (n:Person) RETURN DISTINCT n.name
```

This particular case is fine, but the warning kicks in for patterns like
`RETURN DISTINCT count(n)` where the `DISTINCT` is meaningless on an already-aggregated
expression.

### `W201 UnlabeledFullScan`

**Severity:** warning  •  **Fires when** a `MATCH (n)` has no label and no property
predicate. Such queries scan the entire database.

```cypher
MATCH (n) RETURN n LIMIT 10
```

→ `Pattern (n) has no label; this will scan all nodes in the database.`

Add a label or property predicate to make the query indexable.

### `W202 UnboundedVarLength`

**Severity:** warning  •  **Fires when** a variable-length pattern omits the upper
bound: `[*]`, `[*1..]`, `[*..]`.

```cypher
MATCH (a:Person)-[*]-(b:Person) RETURN a, b
```

→ `Unbounded variable-length pattern can blow up; add an upper bound like *1..5.`

## Working with diagnostics in code

```python
from cypher_validator import CypherValidator

result = validator.validate(query)

errors = [d for d in result.diagnostics if d.severity == "error"]
warnings = [d for d in result.diagnostics if d.severity == "warning"]

for d in errors:
    print(f"{d.code} {d.code_name}: {d.message}")
    if d.suggestion_replacement:
        print(f"  → {d.suggestion_description}")

for d in warnings:
    print(f"⚠ {d.code} {d.message}")
```

For programmatic consumption, prefer `result.to_dict()` or `result.to_json()` over
parsing the string `errors` list — the structured form is stable across versions.
