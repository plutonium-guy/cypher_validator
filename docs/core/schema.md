# Schema

The `Schema` class is the **single source of truth** about your graph's structure. It is consumed by:

- [`CypherValidator`](validator.md) — for semantic validation.
- [`CypherGenerator`](generator.md) — for synthesising example queries.
- [`LLMNLToCypher`](../llm/pipeline.md) — as the prompt context for an LLM.
- [`GraphRAGPipeline`](../llm/rag.md) — for retrieval-augmented generation.

It is implemented in **Rust** and exposed to Python through PyO3, so look-ups against
the schema (label existence, property existence, endpoint lookups) are O(1) hash-set
operations rather than linear scans.

## Constructing a schema

`Schema(nodes, relationships)` takes two dicts:

```python
from cypher_validator import Schema

schema = Schema(
    nodes={
        "Person":  ["name", "age", "email"],
        "Company": ["name", "founded"],
        "City":    ["name", "country"],
    },
    relationships={
        # rel_type: (src_label, tgt_label, [props])
        "WORKS_FOR": ("Person",  "Company", ["since", "role"]),
        "LIVES_IN":  ("Person",  "City",    []),
    },
)
```

!!! note "Underlying storage"
    Internally, property lists become `HashSet<String>` and relationship endpoints become
    a `(src, tgt, HashSet<String>)` tuple. The property lookup is therefore O(1) regardless
    of how many properties a node label has.

## Existence checks

```python
schema.has_node_label("Person")          # True
schema.has_node_label("Persn")           # False
schema.has_rel_type("WORKS_FOR")         # True
schema.node_has_property("Person", "name")   # True
schema.rel_has_property("WORKS_FOR", "since")  # True
```

| Method | Returns | Use case |
|---|---|---|
| `has_node_label(label)` | `bool` | Cheap label existence check |
| `has_rel_type(rel_type)` | `bool` | Cheap rel-type existence check |
| `node_has_property(label, prop)` | `bool` | Property check on a single node label |
| `rel_has_property(rel_type, prop)` | `bool` | Property check on a single rel type |

## Enumeration

All enumeration methods return **sorted** lists for deterministic output (useful in
snapshot tests and prompt construction):

```python
schema.node_labels()                     # ["City", "Company", "Person"]
schema.rel_types()                       # ["LIVES_IN", "WORKS_FOR"]
schema.node_properties("Person")         # ["age", "email", "name"]
schema.rel_properties("WORKS_FOR")       # ["role", "since"]
schema.rel_endpoints("WORKS_FOR")        # ("Person", "Company")
```

## Serialisation

### `to_dict()` / `from_dict()`

```python
d = schema.to_dict()
# {
#   "nodes": {"Person": ["age", "email", "name"], ...},
#   "relationships": {"WORKS_FOR": ("Person", "Company", ["role", "since"]), ...}
# }
schema2 = Schema.from_dict(d)
```

The dict form is identical to what the `Schema(nodes, relationships)` constructor expects
(except that relationship triples can be either tuples or lists).

### `to_json()` / `from_json()`

```python
js = schema.to_json()
schema2 = Schema.from_json(js)
assert schema.to_dict() == schema2.to_dict()
```

`to_json()` produces a compact representation that survives a round-trip — handy for caching
or sending over the wire.

## Merging schemas

`Schema.merge(other)` returns a **new** schema that is the union of the two:

```python
s1 = Schema({"Person": ["name"]}, {"KNOWS": ("Person", "Person", [])})
s2 = Schema({"Movie": ["title"]}, {"ACTED_IN": ("Person", "Movie", ["role"])})
merged = s1.merge(s2)

merged.node_labels()    # ["Movie", "Person"]
merged.rel_types()      # ["ACTED_IN", "KNOWS"]
```

When a label appears in both schemas, **property sets are unioned**. When a rel type appears
in both, the *other* schema's endpoint labels take precedence (but properties union).

This is what powers the LLM pipeline's *Mode B* — each LLM-inferred mini-schema is merged
into the running discovered schema, so the system stabilises as documents are ingested.

## LLM-friendly formats

| Method | Output style | Best for |
|---|---|---|
| `to_prompt()` | Plain text with column alignment | Code-davinci / older models |
| `to_markdown()` | Markdown tables | Models that render Markdown (Claude, GPT-4) |
| `to_cypher_context()` | Inline Cypher patterns | Cypher-aware models (most accurate) |

### `to_prompt()` example

```text
Graph Schema
============

Nodes
-----
  :City                       country, name
  :Company                    founded, name
  :Person                     age, email, name

Relationships
-------------
  :LIVES_IN                   (Person)-->(City)
  :WORKS_FOR                  (Person)-->(Company)   role, since
```

### `to_markdown()` example

```markdown
### Nodes

| Label | Properties |
|---|---|
| :Person | age, email, name |
| :Company | founded, name |

### Relationships

| Type | Source → Target | Properties |
|---|---|---|
| :WORKS_FOR | :Person → :Company | role, since |
```

### `to_cypher_context()` example

```cypher
// Node labels and their properties
(:City {country, name})
(:Company {founded, name})
(:Person {age, email, name})

// Relationship types
(:Person)-[:LIVES_IN]->(:City)
(:Person)-[:WORKS_FOR {role, since}]->(:Company)
```

!!! tip "Picking a format"
    `to_cypher_context()` is the default used by [`LLMNLToCypher`](../llm/pipeline.md) and
    [`GraphRAGPipeline`](../llm/rag.md) because Cypher-fluent LLMs produce noticeably better
    queries when the schema mirrors the syntax they need to write.

## Discovering a schema from a live Neo4j

The convenience helper `Schema.from_neo4j(uri, user, password)` connects to a running
Neo4j instance and introspects its schema in one call:

```python
from cypher_validator import Schema

schema = Schema.from_neo4j(
    "bolt://localhost:7687",
    "neo4j",
    "password",
    database="neo4j",
    sample_limit=1000,
)
print(schema.to_prompt())
```

It tries the built-in `db.schema.nodeTypeProperties()` / `db.schema.relTypeProperties()`
procedures first (Neo4j 4.3+), then falls back to sampling existing nodes and
relationships. Endpoint labels are always discovered via a `MATCH (a)-[r]->(b)` sample.

For driver-less use, you can call `Neo4jDatabase.introspect_schema()` directly — see
[Neo4jDatabase](../ner/gliner2.md#neo4jdatabase).

## Bridging from Pydantic models

If you prefer to define your schema declaratively with Pydantic, use
[`GraphSchema`](../orm/index.md) and convert:

```python
from cypher_validator import GraphSchema, NodeModel, RelationshipModel, CypherValidator

class Person(NodeModel):
    __label__ = "Person"
    name: str
    age: int = 0

class Movie(NodeModel):
    __label__ = "Movie"
    title: str

class ActedIn(RelationshipModel):
    __source__ = Person
    __target__ = Movie
    __rel_type__ = "ACTED_IN"
    roles: list[str] = []

graph_schema = GraphSchema.from_models([Person, Movie, ActedIn])
rust_schema = graph_schema.to_cypher_schema()   # → cypher_validator.Schema
validator = CypherValidator(rust_schema)
```

See [ORM overview](../orm/index.md) for the full Pydantic-side API.
