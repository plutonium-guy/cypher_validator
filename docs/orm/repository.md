# Repository

`Repository` is a thin, typed CRUD wrapper over a single `NodeModel`. If you want
"give me all the Persons whose name starts with 'A' and there are at most 50", a
`Repository(Person, db)` is the shortest path.

```python
from cypher_validator import Repository, Neo4jDatabase, NodeModel

class Person(NodeModel):
    __label__ = "Person"
    name: str
    age: int = 0

db = Neo4jDatabase("bolt://localhost:7687", "neo4j", "password")
repo = Repository(Person, db)
```

## Constructor

```python
Repository(model: Type[NodeModel], db, var: str = "n")
```

| Parameter | Type | Default | Notes |
|---|---|---|---|
| `model` | `Type[NodeModel]` | required | The class this repo operates on. |
| `db` | duck-typed | required | Anything with `.execute(cypher, params)`. `Neo4jDatabase` works. |
| `var` | `str` | `"n"` | Cypher variable name used in generated queries. |

!!! note "Driver-agnostic"
    `Repository` calls `db.execute(cypher, params)` only. It doesn't care if you pass a
    `Neo4jDatabase`, a `GraphSession`, or your own thin adapter — as long as `.execute()`
    returns a list of record dicts.

## Read methods

### `find_all(limit=None, order_by=None, skip=None) → list[Model]`

```python
people = repo.find_all(limit=100, order_by="age DESC", skip=20)
# MATCH (n:Person) RETURN n ORDER BY n.age DESC SKIP 20 LIMIT 100
```

`order_by` accepts a property name optionally followed by `ASC` / `DESC`. The base
property name is **validated** against the model's declared fields — a typo raises
`ValueError` before any SQL/Cypher is sent.

Returns hydrated `Person` instances, not raw dicts.

### `find_by(**props, limit=None) → list[Model]`

```python
matches = repo.find_by(name="Alice")                  # all matches
admins = repo.find_by(role="admin", limit=10)
```

Each kwarg becomes a `WHERE n.k = $n_k` clause. Multiple kwargs are AND-ed.

### `find_one(**props) → Model | None`

```python
alice = repo.find_one(name="Alice")
if alice is None:
    print("not found")
```

Equivalent to `find_by(limit=1, **props)[0]` with `None` for the empty case.

### `exists(**props) → bool`

```python
if repo.exists(name="Alice"):
    print("Alice is in the database")
```

Generates `RETURN count(n) > 0 AS exists` so it doesn't pay the full match.

### `count(**props=None) → int`

```python
total = repo.count()
adults = repo.count(role="admin")
```

When no kwargs are given, counts all nodes of this type.

## Write methods

### `create(instance) → list[dict]`

```python
records = repo.create(Person(name="Bob", age=25))
# CREATE (n:Person {name: $n_name, age: $n_age}) RETURN n
```

Delegates to `instance.to_create_cypher(self.var)`.

### `create_many(items: list[dict]) → list[dict]`

```python
records = repo.create_many([
    {"name": "Carol", "age": 28},
    {"name": "Dave", "age": 33},
])
# UNWIND $batch AS item CREATE (n:Person {name: item.name, age: item.age}) RETURN n
```

Uses [`BulkOps.bulk_create_nodes`](bulk.md). One round-trip for the whole batch.

!!! tip "Item dicts, not instances"
    `create_many` takes raw dicts to avoid the per-row Pydantic validation cost. If you
    want validation, call `Person(**item).to_property_map()` before passing in.

### `merge(instance, merge_keys=None) → list[dict]`

```python
records = repo.merge(Person(name="Alice", age=31), merge_keys=["name"])
# MERGE (n:Person {name: $n_name})
#   ON CREATE SET n.age = $n_age
#   ON MATCH SET n.age = $n_age
# RETURN n
```

Falls back to `instance.required_properties()` (and then to the first property) if
`merge_keys` is omitted.

### `merge_many(items, merge_keys) → list[dict]`

```python
records = repo.merge_many(
    [{"name": "Eve", "age": 29}, {"name": "Frank", "age": 41}],
    merge_keys=["name"],
)
# UNWIND $batch AS item
# MERGE (n:Person {name: item.name})
#   ON CREATE SET n.age = item.age
#   ON MATCH SET n.age = item.age
# RETURN n
```

### `update(match_props, set_props) → list[dict]`

```python
records = repo.update(
    {"name": "Alice"},                # WHERE n.name = $match_name
    {"age": 31, "email": "a@a.com"},  # SET n.age = $set_age, n.email = $set_email
)
```

`match_props` and `set_props` are passed as two distinct dicts so you can update a
property and use it as a match key simultaneously.

### `delete(detach=True, **props) → list[dict]`

```python
repo.delete(name="Alice")                  # DETACH DELETE
repo.delete(name="Alice", detach=False)    # raise on relationships
```

Without `**props` it would delete nothing — use `delete_all` for "all of them".

### `delete_all(detach=True) → list[dict]`

```python
repo.delete_all()                          # MATCH (n:Person) DETACH DELETE n
```

Use with extreme care. This wipes every node of the type.

## `query() → Query`

When the convenience methods aren't enough, drop down to the full builder pre-seeded
with `MATCH (n:Label)`:

```python
q = (repo.query()
      .where(Cond("n.age", ">", 30))
      .return_("n.name")
      .order_by("n.name")
      .limit(50))

cypher, params = q.build()
records = db.execute(cypher, params)
```

This is also how you write joins / traversals — the repo is just a starting point.

## Picking between Repository, GraphSession, and Query

| Use | Pick |
|---|---|
| Simple CRUD over one node type | **Repository** |
| Many types, transactions, async | [`GraphSession`](sessions.md) / [`AsyncGraphSession`](sessions.md#asyncgraphsession) |
| Complex queries, validation upfront | **Query.build() → session.execute()** |
| Mass insertion / migration | [`BulkOps`](bulk.md) directly |
| Pre-built traversals (paths, neighbours) | [`Traversal`](traversal.md) |
