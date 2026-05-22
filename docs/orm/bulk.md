# Bulk operations

`BulkOps` is a static-method class that emits **`UNWIND`-batched Cypher** for high-throughput
node/relationship operations. A single `bulk_create_nodes` call sends one round-trip with the
entire batch as a `$batch` parameter — orders of magnitude faster than issuing one
`CREATE` per row.

Every method returns the canonical `(cypher, params)` tuple, so you can pass it straight
to `Neo4jDatabase.execute()`, `GraphSession.execute()`, or any other driver shim.

```python
from cypher_validator import BulkOps, NodeModel

class Person(NodeModel):
    __label__ = "Person"
    name: str
    age: int = 0
```

!!! note "All methods are `@staticmethod`"
    `BulkOps` carries no state — call methods on the class, never on an instance.

## `bulk_create_nodes(model, items, var="n") → (str, dict)`

```python
cypher, params = BulkOps.bulk_create_nodes(
    Person,
    [
        {"name": "Alice", "age": 30},
        {"name": "Bob",   "age": 25},
        {"name": "Carol", "age": 28},
    ],
)
```

Generated Cypher:

```cypher
UNWIND $batch AS item CREATE (n:Person {name: item.name, age: item.age}) RETURN n
```

`params == {"batch": [...]}` — the items are passed as a single list parameter, so the
driver only serialises one round-trip's worth of data.

The property list in the generated pattern is taken from `model.property_names()`, which
is the **declared** order. Missing keys in an item dict yield `null` for that property.

## `bulk_merge_nodes(model, items, merge_keys, var="n") → (str, dict)`

```python
cypher, params = BulkOps.bulk_merge_nodes(
    Person,
    [
        {"name": "Alice", "age": 31},
        {"name": "Dave",  "age": 33},
    ],
    merge_keys=["name"],
)
```

```cypher
UNWIND $batch AS item
MERGE (n:Person {name: item.name})
  ON CREATE SET n.age = item.age
  ON MATCH SET n.age = item.age
RETURN n
```

`merge_keys` controls the MERGE shape:

- Properties listed in `merge_keys` become part of the `MERGE` pattern.
- All other declared properties go into `ON CREATE SET` / `ON MATCH SET`.

Use this for **idempotent ingestion** — re-running the same batch produces the same
graph, no duplicates.

## `bulk_create_relationships(rel_model, items, src_key, tgt_key) → (str, dict)`

```python
cypher, params = BulkOps.bulk_create_relationships(
    ActedIn,
    [
        {"src_name": "Alice", "tgt_title": "The Matrix", "roles": ["Trinity"]},
        {"src_name": "Bob",   "tgt_title": "Inception",  "roles": ["Cobb"]},
    ],
    src_key="src_name",
    tgt_key="tgt_title",
)
```

Generated Cypher:

```cypher
UNWIND $batch AS item
MATCH (a:Person {name: item.src_name}),
      (b:Movie  {title: item.tgt_title})
CREATE (a)-[r:ACTED_IN {roles: item.roles}]->(b)
RETURN r
```

How the keys map:

- `src_key`, `tgt_key` are the **keys in each item dict** that identify the endpoints.
- The actual node property used for matching is derived by stripping `src_` / `tgt_`
  prefixes — so `src_key="src_name"` matches `a.name = item.src_name`.

!!! tip "Naming convention"
    Stick with `src_<prop>` / `tgt_<prop>` for your item dicts — it keeps the generated
    Cypher readable and self-explanatory.

## `bulk_merge_relationships(rel_model, items, src_key, tgt_key) → (str, dict)`

```python
cypher, params = BulkOps.bulk_merge_relationships(
    ActedIn,
    [
        {"src_name": "Alice", "tgt_title": "The Matrix", "roles": ["Trinity"]},
    ],
    src_key="src_name",
    tgt_key="tgt_title",
)
```

```cypher
UNWIND $batch AS item
MATCH (a:Person {name: item.src_name}),
      (b:Movie  {title: item.tgt_title})
MERGE (a)-[r:ACTED_IN]->(b)
SET r.roles = item.roles
RETURN r
```

The relationship is `MERGE`-ed (so the edge isn't duplicated), and then `SET` is used
to update relationship properties on every run. This is the right shape for idempotent
edge ingestion.

## `bulk_delete_nodes(model, match_key, values, detach=True) → (str, dict)`

```python
cypher, params = BulkOps.bulk_delete_nodes(
    Person,
    match_key="name",
    values=["Alice", "Bob", "Carol"],
    detach=True,
)
```

```cypher
MATCH (n:Person) WHERE n.name IN $values DETACH DELETE n
```

This isn't an `UNWIND` — it's a single `WHERE … IN $values` filter, which is the
fastest shape for bulk deletes. Pass `detach=False` to raise an error when a node has
relationships (the default `DETACH DELETE` clears them first).

## How big should a batch be?

In testing, batches of **500–5 000 items** per `bulk_create_nodes` call hit the sweet
spot between client memory and network round-trips. Larger batches are fine for
straightforward node creation, but `bulk_create_relationships` is bottlenecked by the
`MATCH` lookup on each endpoint — splitting into smaller batches gives the planner more
opportunities to use indexes.

If you're ingesting millions of rows, also consider:

1. Running [`SchemaDDL.uniqueness_constraints()`](ddl.md) **before** the bulk load, so
   the MERGE keys are indexed.
2. Disabling provenance / `Chunk` nodes during the bulk phase and rebuilding them
   afterwards.
3. Using the async `LLMNLToCypher.aingest_texts` with `max_concurrency=10` if your
   ingest involves LLM generation. See [Async & rate-limit](../llm/async.md).

## Composing with sessions

`GraphSession.bulk_create()`, `bulk_merge()`, and `AsyncGraphSession`'s counterparts
just wrap these `BulkOps` methods:

```python
session.bulk_create(Person, items)
# Internally:
# cypher, params = BulkOps.bulk_create_nodes(Person, items)
# return session.execute(cypher, params)
```

So you can use either layer interchangeably — `BulkOps` for direct driver use,
`GraphSession.bulk_*` for the ORM-integrated path.
