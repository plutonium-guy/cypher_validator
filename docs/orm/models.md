# Models

`NodeModel` and `RelationshipModel` are the two Pydantic base classes that define your graph
schema. They auto-register on subclass creation, so [`GraphSchema.from_registry()`](#graphschema)
discovers every model in your project without you having to enumerate them.

Both classes inherit from `pydantic.BaseModel` with `populate_by_name=True` and `extra="allow"`.

## `NodeModel`

```python
from cypher_validator import NodeModel

class Person(NodeModel):
    __label__ = "Person"
    __description__ = "A human in the graph"
    __constraints__ = []
    __indexes__ = []

    name: str
    age: int = 0
    email: str | None = None
```

### Class-level attributes

| Attribute | Type | Default | Purpose |
|---|---|---|---|
| `__label__` | `str` | class name | Primary Cypher label. |
| `__labels__` | `list[str]` | `[]` | Multi-label support — e.g. `["Person", "Employee"]`. |
| `__description__` | `str` | `""` | Human / LLM description. Surfaces in `to_schema_description()`. |
| `__constraints__` | `list[str]` | `[]` | Custom Cypher DDL — picked up by [`SchemaDDL.custom_constraints`](ddl.md). |
| `__indexes__` | `list[str]` | `[]` | Custom Cypher DDL — picked up by [`SchemaDDL.custom_indexes`](ddl.md). |

### Class methods

| Method | Returns | Notes |
|---|---|---|
| `label()` | `str` | Primary label (first of `__labels__` if set). |
| `labels()` | `list[str]` | All labels for multi-label nodes. |
| `labels_cypher()` | `str` | Formatted for Cypher: `":Person:Employee"`. |
| `property_names()` | `list[str]` | Order of declaration. |
| `property_types()` | `dict[str, str]` | `{"age": "int", "name": "str", …}` |
| `required_properties()` | `list[str]` | Fields without a default. |
| `optional_properties()` | `list[str]` | Fields with a default. |
| `from_record(record, key=None)` | `NodeModel` | Hydrate from a Neo4j record dict. Handles raw dicts and `neo4j.graph.Node`. |
| `from_records(records, key=None)` | `list[NodeModel]` | Vectorised hydration. |
| `match_cypher(var="n", where=None)` | `(str, dict)` | `MATCH (n:Label) [WHERE …] RETURN n` |
| `to_schema_description()` | `str` | LLM-readable description block. |

### Instance methods

| Method | Returns | Notes |
|---|---|---|
| `to_property_map()` | `dict[str, Any]` | Drops `None`s. Suitable for Cypher `$params`. |
| `to_create_cypher(var="n")` | `(str, dict)` | `CREATE (n:Label {props}) RETURN n`. |
| `to_merge_cypher(var="n", merge_keys=None)` | `(str, dict)` | `MERGE (n:Label {keys}) ON CREATE/MATCH SET … RETURN n`. |

```python
alice = Person(name="Alice", age=30)

cypher, params = alice.to_create_cypher("p")
# CREATE (p:Person {name: $p_name, age: $p_age}) RETURN p
# params = {"p_name": "Alice", "p_age": 30}

cypher, params = alice.to_merge_cypher(merge_keys=["name"])
# MERGE (n:Person {name: $n_name})
#   ON CREATE SET n.age = $n_age
#   ON MATCH SET n.age = $n_age
# RETURN n
```

!!! warning "Merge-key validation"
    `to_merge_cypher()` raises `ValueError` if any `merge_key` is not a declared property
    of the model. This protects against silent typos like `merge_keys=["nme"]`.

### Auto-registry

When a `NodeModel` subclass is defined, its metaclass adds it to the global
`_NODE_REGISTRY` keyed by `label()`. This powers:

- `GraphSchema.from_registry()` — discover all models without listing them.
- Dynamic schemas built via the `node()` / `relationship()` factories.

```python
class Movie(NodeModel):
    __label__ = "Movie"
    title: str

# Movie is now in _NODE_REGISTRY["Movie"].

from cypher_validator import GraphSchema
schema = GraphSchema.from_registry()
assert any(m.label() == "Movie" for m in schema.node_models)
```

## `RelationshipModel`

```python
from cypher_validator import RelationshipModel

class ActedIn(RelationshipModel):
    __source__ = Person
    __target__ = Movie
    __rel_type__ = "ACTED_IN"
    __description__ = "Person performed in Movie"

    roles: list[str] = []
    year: int | None = None
```

### Class-level attributes

| Attribute | Type | Default | Purpose |
|---|---|---|---|
| `__source__` | `Type[NodeModel]` | required | Source node class. |
| `__target__` | `Type[NodeModel]` | required | Target node class. |
| `__rel_type__` | `str` | `_to_upper_snake(class_name)` | Cypher rel-type string. |
| `__description__` | `str` | `""` | Human / LLM description. |
| `__constraints__` | `list[str]` | `[]` | Custom DDL. |

If you omit `__rel_type__`, the class name is converted from `CamelCase` to
`UPPER_SNAKE_CASE` automatically (e.g. `ActedIn` → `ACTED_IN`).

### Class methods

| Method | Returns | Notes |
|---|---|---|
| `rel_type()` | `str` | Computed Cypher rel-type. |
| `source_label()` | `str` | `__source__.label()`. |
| `target_label()` | `str` | `__target__.label()`. |
| `property_names()` | `list[str]` |  |
| `property_types()` | `dict[str, str]` |  |
| `required_properties()` | `list[str]` |  |
| `from_record(record, key=None)` | `RelationshipModel` | Hydrate from a Neo4j record. |
| `to_schema_description()` | `str` | Block describing pattern + properties. |

### Instance methods

`to_property_map() → dict` is identical to `NodeModel`.

`to_create_cypher(src_var="a", tgt_var="b", rel_var="r", src_match=None, tgt_match=None)`
generates a full `MATCH src, tgt CREATE (src)-[:R {props}]->(tgt) RETURN r`:

```python
rel = ActedIn(roles=["Trinity"])
cypher, params = rel.to_create_cypher(
    src_match={"name": "Carrie-Anne Moss"},
    tgt_match={"title": "The Matrix"},
)
# MATCH (a:Person), (b:Movie)
#   WHERE a.name = $a_name AND b.title = $b_title
# CREATE (a)-[r:ACTED_IN {roles: $r_roles}]->(b)
# RETURN r
```

`src_match` / `tgt_match` are property predicates used to locate the endpoints — the
keys become `WHERE` filters bound through `$src_*` / `$tgt_*` params.

## `GraphSchema`

`GraphSchema` is the bridge between Pydantic models and the Rust validator. It collects
node/relationship models and offers conversions:

```python
from cypher_validator import GraphSchema

# Option 1: explicit list
schema = GraphSchema.from_models([Person, Movie, ActedIn])

# Option 2: discover everything declared so far
schema = GraphSchema.from_registry()

# Option 3: introspect a running Neo4j and synthesise models
from cypher_validator import Neo4jDatabase
db = Neo4jDatabase("bolt://localhost:7687", "neo4j", "password")
schema = GraphSchema.from_neo4j_db(db, sample_limit=1000)
```

### Methods

| Method | Returns | Use case |
|---|---|---|
| `to_dict()` | `dict` | Matches `Schema.from_dict()` shape. |
| `to_json()` | `str` | Pretty-printed JSON. |
| `to_cypher_schema()` | `cypher_validator.Schema` | Feed into `CypherValidator`. |
| `to_prompt()` | `str` | LLM-readable prose schema block. |
| `to_markdown()` | `str` | Markdown table format. |
| `merge(other)` | `GraphSchema` | Union of two schemas (no duplicate registration). |
| `get_constraints()` | `list[str]` | All `__constraints__` from every model. |
| `get_indexes()` | `list[str]` | All `__indexes__` from every node model. |
| `from_dict(d)` | `GraphSchema` | Reverse of `to_dict()`. Dynamically creates models. |
| `from_neo4j_db(db, sample_limit=1000)` | `GraphSchema` | Introspect from a live DB. |

```python
schema.to_dict()
# {
#   "nodes": {"Person": ["name", "age"], "Movie": ["title", "year"]},
#   "relationships": {"ACTED_IN": ("Person", "Movie", ["roles", "year"])},
# }
```

## Dynamic model factories

When you don't know the schema at type-checking time (e.g. an agent connecting to an
unfamiliar database), `node()` and `relationship()` build models on the fly:

```python
from cypher_validator.models import node, relationship

Tag = node("Tag", name=(str, ...), count=(int, 0))
# Required `name`, optional `count` with default 0.

TaggedWith = relationship("TAGGED_WITH", Person, Tag, weight=(float, 1.0))
```

Field definitions follow Pydantic's `(type, default)` tuple convention. A bare type
means required with no default.

`GraphSchema.from_dict()` uses these factories internally:

```python
schema = GraphSchema.from_dict({
    "nodes": {"Person": ["name", "age"]},
    "relationships": {"KNOWS": ["Person", "Person", ["since"]]},
})
# Person and Knows classes are now in the registry.
```
