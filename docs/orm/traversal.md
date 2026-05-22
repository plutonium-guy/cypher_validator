# Traversal

`Traversal` is a collection of `@staticmethod`s that build common graph-pattern
queries from your Pydantic models. Each method returns a `(cypher, params)` tuple
that the caller passes to `db.execute(...)` (or any `GraphSession`).

```python
from cypher_validator import Traversal, Neo4jDatabase, NodeModel

class Person(NodeModel):
    __label__ = "Person"
    name: str
    age: int = 0

db = Neo4jDatabase("bolt://localhost:7687", "neo4j", "password")
cypher, params = Traversal.neighbors(Person, match_props={"name": "Alice"}, limit=10)
records = db.execute(cypher, params)
```

!!! note "Stateless by design"
    `Traversal` never opens a connection or executes anything. It's pure
    Cypher generation — you can inspect, log, or rewrite the query before
    sending it to the driver. This is what makes the patterns LLM-safe.

## `neighbors`

```python
Traversal.neighbors(
    model: Type[NodeModel],
    var: str = "n",
    match_props: dict[str, Any] | None = None,
    rel_type: str | Type[RelationshipModel] | None = None,
    direction: str = "both",   # "in" | "out" | "both"
    limit: int | None = None,
) -> tuple[str, dict[str, Any]]
```

Find nodes connected to a matched source. Returns `(source, relationship, neighbor)`
triples — column names are exactly `var`, `r`, `neighbor`.

```python
cypher, params = Traversal.neighbors(
    Person,
    "p",
    match_props={"name": "Alice"},
    rel_type="KNOWS",
    direction="out",
    limit=25,
)
# MATCH (p:Person)-[r:KNOWS]->(neighbor) WHERE p.name = $p_name RETURN p, r, neighbor LIMIT 25
```

`rel_type` accepts a `RelationshipModel` subclass too — it calls `.rel_type()` on
the class to get the string label.

!!! tip "Direction is a string, not an enum"
    Use `"in"`, `"out"`, or `"both"`. Anything else raises `ValueError` via the
    internal `_validate_direction` guard — so a typo fails loudly at call time,
    not somewhere deep in the database driver.

## `shortest_path`

```python
Traversal.shortest_path(
    src_model: Type[NodeModel],
    tgt_model: Type[NodeModel],
    src_props: dict[str, Any],
    tgt_props: dict[str, Any],
    rel_type: str | None = None,
    max_depth: int | None = None,
) -> tuple[str, dict[str, Any]]
```

Find the shortest path between two endpoints via Neo4j's built-in
`shortestPath()` function. Returns one row with columns `path` and `distance`
(where `distance = length(path)`).

```python
cypher, params = Traversal.shortest_path(
    Person, Person,
    {"name": "Alice"},
    {"name": "Bob"},
    rel_type="KNOWS",
    max_depth=6,
)
# MATCH (src:Person), (tgt:Person),
#       path = shortestPath((src)-[:KNOWS*..6]-(tgt))
# WHERE src.name = $src_name AND tgt.name = $tgt_name
# RETURN path, length(path) AS distance
```

`max_depth=None` produces `[*]` (unbounded — Neo4j caps this at 15 by default
for safety, but cluster configurations vary).

## `subgraph`

```python
Traversal.subgraph(
    model: Type[NodeModel],
    match_props: dict[str, Any],
    depth: int = 2,
    var: str = "n",
) -> tuple[str, dict[str, Any]]
```

Extract every path within `depth` hops of a seed node:

```python
cypher, params = Traversal.subgraph(
    Person,
    {"name": "Alice"},
    depth=3,
)
# MATCH path = (n:Person)-[*1..3]-(connected) WHERE n.name = $n_name RETURN path
```

The result is a list of `path` rows. Each path can be unwound by the driver into
nodes and relationships (`neo4j.graph.Path` has `.nodes`, `.relationships`).

!!! warning "Result size blows up with depth"
    `subgraph` doesn't have a `LIMIT`. At `depth=4+` on a dense graph the result
    set can be millions of paths. Either keep `depth <= 2`, add your own filter
    via `RETURN path LIMIT n`, or use [`Traversal.degree`](#degree) first to
    judge fan-out.

## `degree`

```python
Traversal.degree(
    model: Type[NodeModel],
    var: str = "n",
    match_props: dict[str, Any] | None = None,
    rel_type: str | None = None,
    direction: str = "both",
) -> tuple[str, dict[str, Any]]
```

Count the relationships hanging off a node. Returns columns `n` and `degree`:

```python
cypher, params = Traversal.degree(
    Person,
    "p",
    match_props={"name": "Alice"},
    rel_type="KNOWS",
    direction="out",
)
# MATCH (p:Person) WHERE p.name = $p_name
# RETURN p, size([(p)-[r:KNOWS]->() | 1]) AS degree
```

The pattern comprehension `[(...) | 1]` plus `size(...)` is faster than
`count { ... }` on most Neo4j 5.x versions because it avoids an inner subquery
plan.

## `common_neighbors`

```python
Traversal.common_neighbors(
    model_a: Type[NodeModel],
    model_b: Type[NodeModel],
    props_a: dict[str, Any],
    props_b: dict[str, Any],
    rel_type: str | None = None,
) -> tuple[str, dict[str, Any]]
```

Nodes connected to both `a` and `b`:

```python
cypher, params = Traversal.common_neighbors(
    Person, Person,
    {"name": "Alice"},
    {"name": "Bob"},
    rel_type="KNOWS",
)
# MATCH (a:Person)-[:KNOWS]-(common)-[:KNOWS]-(b:Person)
# WHERE a.name = $a_name AND b.name = $b_name
# RETURN DISTINCT common
```

Column: `common`. The `DISTINCT` prevents duplicate rows when there are
multiple paths through the same shared node.

## `path_exists`

```python
Traversal.path_exists(
    src_model: Type[NodeModel],
    tgt_model: Type[NodeModel],
    src_props: dict[str, Any],
    tgt_props: dict[str, Any],
    max_depth: int = 5,
) -> tuple[str, dict[str, Any]]
```

Boolean reachability check.

!!! warning "Column name is `connected`, NOT `path_exists`"
    The Cypher this emits ends in `RETURN EXISTS(...) AS connected`. Many
    callers assume the column name matches the method name — but it does not.
    Pin this in your test code:

    ```python
    cypher, _ = Traversal.path_exists(Person, Person, {...}, {...})
    assert "AS connected" in cypher    # pinned in test_orm_api_contracts.py
    ```

    To consume the result:

    ```python
    rows = db.execute(cypher, params)
    if rows and rows[0]["connected"]:
        ...
    ```

```python
cypher, params = Traversal.path_exists(
    Person, Person,
    {"name": "Alice"},
    {"name": "Bob"},
    max_depth=4,
)
# MATCH (src:Person), (tgt:Person)
# WHERE src.name = $src_name AND tgt.name = $tgt_name
# RETURN EXISTS((src)-[*1..4]-(tgt)) AS connected
```

## Executing a Traversal

`Traversal` returns Cypher and params. You execute them — usually via
`Neo4jDatabase.execute` or a `GraphSession`:

=== "Direct driver"

    ```python
    from cypher_validator import Neo4jDatabase, Traversal, NodeModel

    class Person(NodeModel):
        __label__ = "Person"
        name: str

    db = Neo4jDatabase("bolt://localhost:7687", "neo4j", "password")
    cypher, params = Traversal.shortest_path(
        Person, Person,
        {"name": "Alice"}, {"name": "Bob"},
        rel_type="KNOWS",
    )
    for row in db.execute(cypher, params):
        print(row["distance"])
    ```

=== "GraphSession"

    ```python
    from cypher_validator import GraphSession, Traversal

    with GraphSession(db) as session:
        cypher, params = Traversal.neighbors(
            Person, match_props={"name": "Alice"}, limit=10,
        )
        rows = session.execute(cypher, params)
    ```

=== "Inside an agent loop"

    ```python
    from cypher_validator import ExtendedAgentTools

    # ExtendedAgentTools.handle_tool_call("find_neighbors", {...})
    # internally delegates to Traversal.neighbors and returns (cypher, params).
    tools = ExtendedAgentTools(schema)
    cypher, params = tools.handle_tool_call("find_path", {
        "source_label": "Person",
        "source_properties": {"name": "Alice"},
        "target_label": "Person",
        "target_properties": {"name": "Bob"},
        "max_depth": 5,
    })
    rows = db.execute(cypher, params)
    ```

## Related

- [Agent tools](agent-tools.md) — `ExtendedAgentTools` dispatches `find_neighbors`,
  `find_path`, etc. through `Traversal`.
- [Bulk ops](bulk.md) — same `(cypher, params)` shape, batch variants.
- [API caveats](caveats.md) — the `connected` vs `path_exists` column gotcha is
  pinned in tests.
