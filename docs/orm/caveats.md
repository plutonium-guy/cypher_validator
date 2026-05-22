# API caveats

A grab-bag of contracts the ORM **does** honour and the ones it deliberately
**does not** — pinned by `tests/test_orm_api_contracts.py` (21 driver-free
tests). Read this page before raising a bug.

!!! info "These are not bugs — they are the contract"
    Each item here exists because changing it would break either a current
    user or a current performance optimisation. The test file is the spec.

## `Cond` inlines literal scalars

`Cond(left, op, right)` renders the right-hand side directly into the Cypher
string for `int`, `str`, `bool`, and `None`. It does **not** generate a
parameter.

```python
from cypher_validator import Cond

Cond("p.age",     ">=", 18).render()      # "p.age >= 18"
Cond("p.name",    "=",  "Alice").render() # "p.name = 'Alice'"
Cond("p.active",  "=",  True).render()    # "p.active = true"
Cond("p.deleted", "=",  None).render()    # "p.deleted = null"
```

**Strings starting with `$`** are preserved as parameter references, not
re-quoted:

```python
Cond("p.name", "=", "$n").render()        # "p.name = $n"
```

Use this when you want the LLM-generated condition to consume a value you
supply later via `.params(n="Alice")`.

!!! tip "When to prefer inlining vs parameterising"
    Inline literals are great for **constants embedded in the query shape**
    (an `age >= 18` filter, a status flag). Use `$param` references for
    **user-supplied values** — they live in the parameters dict, get sent
    separately by the driver, and don't risk Cypher injection.

## `Query.where(condition)` takes ONE argument

The signature is `where(self, condition: Cond | CondGroup | str) -> Query`.
**No kwargs**, no auto-binding:

```python
# OK — string with explicit $param + value via .params()
q = (Query()
     .match(Person, "p")
     .where("p.age > $min_age")
     .params(min_age=30)
     .return_("p"))

# OK — Cond inlines the 30
q = (Query().match(Person, "p")
     .where(Cond("p.age", ">", 30))
     .return_("p"))

# FAILS — TypeError; .where() does not accept kwargs
Query().match(Person, "p").where("p.age > $x", x=30)   # type: ignore[call-arg]
```

Pinned by `TestWhereNoAutoParam.test_where_does_not_bind_kwargs_silently`.

## `Traversal.path_exists` returns column `connected`

The method name says `path_exists` but the Cypher returns:

```cypher
RETURN EXISTS((src)-[*1..N]-(tgt)) AS connected
```

Read the result with `record["connected"]`, not `record["path_exists"]`:

```python
cypher, params = Traversal.path_exists(Person, Person, {...}, {...})
rows = db.execute(cypher, params)
reachable = rows[0]["connected"]
```

See [Traversal — path_exists](traversal.md#path_exists).

## Sessions and Repositories take a `Neo4jDatabase`, not a URI

```python
GraphSession(db: Any, schema: GraphSchema | None = None)
AsyncGraphSession(db: Any, schema: GraphSchema | None = None)
Repository(model: Type[NodeModel], db: Any, var: str = "n")
```

`db` is anything with `.execute(cypher, params)`. A `Neo4jDatabase` works, but
so does a test double:

```python
class FakeDB:
    def execute(self, cypher, params=None):
        return []

session = GraphSession(FakeDB())   # OK
```

What does **not** work — passing connection strings directly:

```python
GraphSession("bolt://localhost:7687", "neo4j", "pw")   # TypeError
```

Pinned by `TestSessionConstructors.test_graph_session_rejects_uri_kwargs`.

!!! warning "Construct the database, then the session"
    Always: `db = Neo4jDatabase(uri, user, pw)` then `GraphSession(db, schema)`.
    This forces a single connection point you control — close it explicitly
    or wrap in `with`.

## `BulkOps.*` are `@staticmethod` returning `(cypher, params)`

They do not execute. Every method has the same shape — `(cypher_str,
params_dict)` that the caller hands to the driver:

```python
from cypher_validator import BulkOps

cypher, params = BulkOps.bulk_merge_nodes(
    Person,
    [{"name": "A", "age": 1}, {"name": "B", "age": 2}],
    merge_keys=["name"],
)
# cypher = "UNWIND $batch AS item MERGE (n:Person {name: item.name}) ..."
# params = {"batch": [{"name": "A", "age": 1}, {"name": "B", "age": 2}]}

db.execute(cypher, params)
```

Pinned by `TestBulkOpsShape.test_bulk_create_nodes_is_static` and
`test_bulk_merge_nodes_returns_cypher_params`.

Relationship bulk ops use `src_key` / `tgt_key` (the dict keys for matching
source and target identifying property values), not the underlying schema
property name:

```python
cypher, params = BulkOps.bulk_merge_relationships(
    WorksFor,
    [{"src_name": "A", "tgt_name": "C", "since": 2020}],
    src_key="src_name",
    tgt_key="tgt_name",
)
# MATCH (a:Person {name: item.src_name}), (b:Company {name: item.tgt_name})
# MERGE (a)-[r:WORKS_FOR]->(b) ...
```

## Neo4j driver returns `Node` objects, not dicts

The `neo4j` Python driver hydrates rows into `neo4j.graph.Node` and
`neo4j.graph.Relationship` instances. They are `Mapping`-like but NOT plain
`dict`. To read properties:

```python
rows = db.execute("MATCH (n:Person) RETURN n LIMIT 1")
node = rows[0]["n"]

# Works — Mapping protocol
node["name"]
dict(node).get("name")
list(node.keys())

# Does NOT work — Node is not a dict
node.get("name", "default")           # AttributeError
{**node}                              # OK actually (Mapping spread works)
```

When in doubt, materialise with `dict(node)` before passing to code that
expects a plain dict.

!!! note "Why not auto-convert?"
    Hydrating millions of records into plain dicts for every query was
    measured 3× slower than handing the `Node` straight through. The ORM's
    `NodeModel.from_records` already calls `dict(...)` internally, so when
    you go through `Repository.find_*` you never see the raw `Node`.

## `CypherFn.count(expr)` returns a plain string

Every `CypherFn.*` method returns a `str`, not a builder. There is no fluent
chain — combine with `CypherFn.as_` for aliasing:

```python
from cypher_validator import CypherFn

CypherFn.count("p")                          # "count(p)"
CypherFn.avg("p.age")                        # "avg(p.age)"
CypherFn.as_(CypherFn.count("p"), "total")   # "count(p) AS total"

# Wrong — strings don't have .as_:
CypherFn.count("p").as_("total")             # AttributeError
```

Pinned by `TestCypherFnRendering`. Use the helper in `Query.return_`:

```python
q = (Query()
     .match(Person, "p")
     .return_(CypherFn.as_(CypherFn.count("p"), "total")))
# RETURN count(p) AS total
```

## `Repository.find_by(**props)` AND-joins on equality

There is no `OR`, no `IN`, no `LIKE`. Use `Query` directly for anything more
than equality matching:

```python
repo.find_by(name="Alice", role="admin")
# MATCH (n:Person) WHERE n.name = $n_name AND n.role = $n_role RETURN n
```

For richer predicates:

```python
q = (Query().match(Person, "p")
     .where(Cond("p.age", ">=", 30) & Cond("p.role", "in", ["admin", "owner"]))
     .return_("p"))
```

## `__label__` defaults to the class name

If you omit `__label__`, Pydantic ORM uses the class name verbatim. This is
**case-sensitive** — `class person(NodeModel)` produces label `"person"`,
which won't match nodes created as `Person`. Always set `__label__` explicitly
when collaborating with code that wasn't generated through this ORM.

## Related

- The full pinned contract: `tests/test_orm_api_contracts.py`.
- [Models](models.md), [Query builder](query-builder.md), [Sessions](sessions.md),
  [Bulk ops](bulk.md), [Traversal](traversal.md) — surface-level docs that
  these caveats refine.
