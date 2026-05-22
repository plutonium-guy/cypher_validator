# Sessions

`GraphSession` and `AsyncGraphSession` execute Cypher queries against a Neo4j-compatible
database and hydrate results into your Pydantic models. They are the **execution layer**
that pairs with the `Query` builder and `Repository`.

!!! warning "Constructor takes a database *instance*"
    `GraphSession(db, schema)` accepts a **`Neo4jDatabase` instance** (or any duck-typed
    object with `execute()`), **not** a URI / user / password triple. The same applies to
    `AsyncGraphSession` and `Repository`. See [API caveats](caveats.md).

## `GraphSession`

```python
from cypher_validator import GraphSession, Neo4jDatabase, GraphSchema

db = Neo4jDatabase("bolt://localhost:7687", "neo4j", "password")
schema = GraphSchema.from_models([Person, Movie, ActedIn])
session = GraphSession(db, schema)
```

### Constructor

```python
GraphSession(db: Any, schema: GraphSchema | None = None)
```

- `db` — any object with `execute(cypher, params) -> list[dict]`. `Neo4jDatabase` is the
  canonical choice but a `_FakeDB` mock works fine in tests.
- `schema` — optional. Required only for `apply_ddl()`. Other methods don't need it.

### Raw execution

```python
records = session.execute("MATCH (n:Person) RETURN n LIMIT 5", {})
```

`session.execute(cypher, params)` is a thin wrapper around `db.execute()`. Use this for
ad-hoc queries you've already constructed and validated.

### Query builder execution

```python
q = Query().match(Person, "p").where(Cond("p.age", ">", 30)).return_("p")
records = session.execute_query(q)
```

`execute_query(q)` calls `q.build()` and forwards the tuple to `db.execute()`.

### Typed query

```python
people = session.query(
    Person,
    var="p",
    where={"name": "Alice"},
    limit=10,
    order_by="p.age",
)
# Returns list[Person] — hydrated Pydantic instances.
```

`query()` is the typed shortcut: it builds a `MATCH (var:Label) WHERE …`, executes it,
and hydrates the records via `Person.from_records(records, var)`.

### Create / merge / delete

```python
session.create(Person(name="Bob", age=25))
session.merge(Person(name="Alice", age=31), merge_keys=["name"])
session.delete(Person, where={"name": "Bob"}, detach=True)
```

### Bulk operations

```python
session.bulk_create(Person, [
    {"name": "Carol", "age": 28},
    {"name": "Dave", "age": 33},
])

session.bulk_merge(
    Person,
    [{"name": "Eve", "age": 29}, {"name": "Frank", "age": 41}],
    merge_keys=["name"],
)
```

These delegate to [`BulkOps`](bulk.md) under the hood — single round-trip UNWIND queries.

### Relationships

```python
session.create_relationship(
    ActedIn(roles=["Trinity"]),
    src_match={"name": "Carrie-Anne Moss"},
    tgt_match={"title": "The Matrix"},
)
```

### Traversal helpers

```python
neighbors = session.neighbors(Person, match_props={"name": "Alice"})
path = session.shortest_path(
    Person, Person,
    src_props={"name": "Alice"},
    tgt_props={"name": "Bob"},
)
```

These call [`Traversal.neighbors`](traversal.md) / [`Traversal.shortest_path`](traversal.md)
and execute the result.

### `apply_ddl(include_existence=False) → list[str]`

```python
session.apply_ddl()
# Runs every CREATE CONSTRAINT / CREATE INDEX from SchemaDDL.generate_all().
# Returns the list of statements that were executed.
```

Requires the session to have been constructed with a `schema`. Use this once on
deployment / migration. `include_existence=True` enables the Enterprise-only `IS NOT NULL`
constraints.

### Context manager

```python
with GraphSession(db, schema) as session:
    session.execute(...)
# (no automatic db.close() — the session does not own the database connection)
```

`GraphSession` defines `__enter__` / `__exit__` for symmetry with the async version, but
it intentionally does **not** close the underlying database — `db` is shared and managed
by the caller.

## `AsyncGraphSession`

The async sibling. Use it inside `asyncio` apps or LLM agent frameworks.

```python
from cypher_validator import AsyncGraphSession

async with AsyncGraphSession(db, schema) as session:
    people = await session.query(Person, where={"name": "Alice"})
    await session.create(Person(name="Bob", age=25))
    await session.bulk_create(Person, [...])
```

### Constructor

```python
AsyncGraphSession(db: Any, schema: GraphSchema | None = None)
```

Same parameters as `GraphSession`. The session keeps a [`QueryHistory`](#history) for
LLM context.

### How execution dispatches

```python
async def execute(self, cypher, params): ...
```

The implementation checks whether `db.execute` is a coroutine function:

- If yes → `await db.execute(cypher, params)` directly.
- If no → `loop.run_in_executor(None, db.execute, cypher, params)` — runs the sync call
  in a thread pool, so the event loop is not blocked.

This means you can use a synchronous `Neo4jDatabase` with `AsyncGraphSession` without
porting the driver layer.

### Methods

The async API mirrors `GraphSession`:

| Async method | Equivalent sync |
|---|---|
| `await session.execute(cypher, params)` | `session.execute()` |
| `await session.execute_query(q)` | `session.execute_query()` |
| `await session.query(Person, where=..., limit=...)` | `session.query()` |
| `await session.create(instance)` | `session.create()` |
| `await session.merge(instance, merge_keys=…)` | `session.merge()` |
| `await session.bulk_create(model, items)` | `session.bulk_create()` |
| `await session.bulk_merge(model, items, merge_keys=…)` | `session.bulk_merge()` |
| `await session.neighbors(model, match_props=…)` | `session.neighbors()` |

### `__aenter__` / `__aexit__`

```python
async with AsyncGraphSession(db, schema) as session:
    ...
# On __aexit__, db.close() is called if it exists.
```

Note: unlike `GraphSession`, the async exit **does** call `db.close()` if available, on
the assumption that you're holding the session over a long-lived async scope.

### History

`AsyncGraphSession` keeps a `QueryHistory` of every executed query — including failures.
This is invaluable for LLM agents that need to know what they've already tried:

```python
print(session.history.to_context())
# ## Previous Queries
# 1. `MATCH (p:Person {name: $name}) RETURN p` → 1 results
# 2. `MATCH (p:Person)-[:KNOWS]->(f) RETURN f` → error: SyntaxError ...
```

`QueryHistory` API (defaults: `max_entries=50`):

| Method | Notes |
|---|---|
| `history.add(cypher, params, result_count, error, summary)` | Append a record. |
| `history.add_from_result(result: QueryResult)` | Pull from a `QueryResult`. |
| `history.entries` | List of `QueryHistoryEntry`. |
| `history.last` | Most recent entry, or `None`. |
| `history.clear()` | Reset. |
| `history.to_context(last_n=None)` | LLM-formatted summary. |
| `history.to_list()` | List of dicts (for serialisation). |
| `history.successful_queries()` | Filter by `error is None`. |
| `history.failed_queries()` | Filter by `error is not None`. |
| `history.find_similar(cypher)` | Substring-based lookup. |

## Picking sync vs async

| Situation | Pick |
|---|---|
| Plain script or CLI tool | `GraphSession` |
| Inside `asyncio.run(...)` / FastAPI / LangChain async agent | `AsyncGraphSession` |
| Large LLM batch ingestion with concurrent rate-limited calls | `AsyncGraphSession` + the async [`LLMNLToCypher`](../llm/async.md) |

The two share the same on-the-wire behaviour — switching is just a matter of `await`-ing
the methods.
