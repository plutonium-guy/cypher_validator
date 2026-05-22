# Pydantic ORM — overview

`cypher_validator` ships a **Pydantic-based graph ORM** that lets you declare your schema as
Python classes and then build, validate, and execute Cypher queries against Neo4j
type-safely. The ORM layer is **pure Python** — it sits on top of the Rust validator and
generator, not under them.

The design goals:

1. **Familiar** — looks like SQLAlchemy / Django ORM if you squint.
2. **Schema-driven** — your declared models *are* the schema, and they feed straight into
   the Rust `CypherValidator`.
3. **Parameterised by default** — every value path emits `$param` placeholders.
4. **Agent-friendly** — every query exposes `(cypher, params)` so an LLM can inspect or
   modify it before execution.

## How the pieces fit together

```text
                        Pydantic NodeModel / RelationshipModel
                                    │
                                    ▼
                ┌───────────────────────────────────────────┐
                │              GraphSchema                  │
                │  (collects models, computes shape)        │
                └───────────────────────────────────────────┘
                       │                          │
            to_dict()  │                          │  to_cypher_schema()
                       ▼                          ▼
              ┌─────────────────┐         ┌─────────────────┐
              │ AgentTools spec │         │  Rust  Schema   │
              │ (OpenAI / Anth) │         │ (HashSet props) │
              └─────────────────┘         └─────────────────┘
                                                    │
                                                    ▼
                                          ┌─────────────────┐
                                          │ CypherValidator │  ← validates every
                                          │   (Rust core)   │     generated query
                                          └─────────────────┘
                                                    │
   ┌──────────────────────────────┬────────────────┴──────────────────────────────┐
   ▼                              ▼                                               ▼
┌──────────────┐         ┌─────────────────┐                          ┌────────────────────┐
│   Query      │         │   Repository    │                          │   GraphSession     │
│ (builder)    │         │ (CRUD per model)│                          │ (execute, hydrate) │
└──────────────┘         └─────────────────┘                          └────────────────────┘
   │  build()                                                                     │
   ▼                                                                              ▼
(cypher, params)  →  db.execute  →  records  →  Model.from_records(...)  →  Pydantic instances
```

## Component cheat-sheet

| Component | Purpose |
|---|---|
| [`NodeModel`](models.md#nodemodel) | Base class for node types. Subclass and add fields. |
| [`RelationshipModel`](models.md#relationshipmodel) | Base class for relationships. Set `__source__`, `__target__`, `__rel_type__`. |
| [`Query`](query-builder.md) | Fluent Cypher builder — `.match().where().return_().build()`. |
| [`Cond`](query-builder.md#conditions) | Single condition `Cond(left, op, right)`. Inlines scalar literals. |
| [`CondGroup`](query-builder.md#conditions) | Group of conditions joined by AND / OR. |
| [`RawExpr`](query-builder.md#rawexpr) | Escape hatch — inject raw Cypher text. |
| [`GraphSchema`](models.md#graphschema) | Bridge from Pydantic models to the Rust `Schema`. |
| [`AgentTools`](agent-tools.md) | OpenAI / Anthropic function-call tool specs for an LLM agent. |
| [`ExtendedAgentTools`](agent-tools.md#extended) | Adds `search_nodes`, `find_neighbors`, `find_path`, etc. |
| [`QueryPlan`](query-builder.md#queryplan) | Multi-step plan with dependencies; topologically sorted into waves. |
| [`QueryStep`](query-builder.md#queryplan) | One step in a `QueryPlan`. |
| [`QueryResult`](query-builder.md#queryresult) | Structured wrapper around execution output. |
| [`Traversal`](traversal.md) | Pre-built patterns: `neighbors`, `shortest_path`, `degree`, `path_exists`, … |
| [`BulkOps`](bulk.md) | UNWIND-based bulk create / merge / delete. |
| [`SchemaDDL`](ddl.md) | Auto-generate CREATE CONSTRAINT / CREATE INDEX. |
| [`GraphSession`](sessions.md#graphsession) | Sync session over a `Neo4jDatabase`. Hydrates results into models. |
| [`AsyncGraphSession`](sessions.md#asyncgraphsession) | Async sibling — `async with`, `await session.query(...)`. |
| [`PropExpr`](query-builder.md#propexpr) | Typed property reference: `p.name == "Alice"` → `Cond`. |
| [`NodeRef`](query-builder.md#noderef) | Typed variable reference for nodes. |
| [`RelRef`](query-builder.md#relref) | Typed variable reference for relationships. |
| [`QueryHistory`](sessions.md#history) | LRU history for agent conversation context. |
| [`SchemaDiff`](ddl.md#schemadiff) | Compare two schemas; emit migration DDL. |
| [`CypherFn`](query-builder.md#cypherfn) / `fn` | Type-safe wrappers for built-in functions (`count`, `avg`, `coalesce`, …). |
| [`PathBuilder`](query-builder.md#pathbuilder) | Multi-hop path construction: `PathBuilder(Person).rel(ActedIn).to(Movie)`. |
| [`Repository`](repository.md) | Typed CRUD over a single model. |
| [`schema_to_pipeline_kwargs`](#integration-with-the-llm-pipeline) | Hand off a `GraphSchema` to `LLMNLToCypher`. |

## A complete example

```python
from cypher_validator import (
    NodeModel, RelationshipModel,
    Query, Cond, GraphSchema,
    CypherValidator, GraphSession, Neo4jDatabase,
    Repository,
)

# 1) Declare schema as Python classes
class Person(NodeModel):
    __label__ = "Person"
    name: str
    age: int = 0

class Movie(NodeModel):
    __label__ = "Movie"
    title: str
    year: int

class ActedIn(RelationshipModel):
    __source__ = Person
    __target__ = Movie
    __rel_type__ = "ACTED_IN"
    roles: list[str] = []

# 2) Bridge to the Rust validator
schema = GraphSchema.from_models([Person, Movie, ActedIn])
validator = CypherValidator(schema.to_cypher_schema())

# 3) Build a query
q = (Query()
     .match(Person, "p")
     .where(Cond("p.age", ">=", 18))    # → p.age >= 18   (literal inlined)
     .return_("p.name AS name", "p.age AS age"))
cypher, params = q.build()
result = q.validate(schema)             # validates against the Rust validator
assert result.is_valid

# 4) Execute via a GraphSession
db = Neo4jDatabase("bolt://localhost:7687", "neo4j", "password")
with GraphSession(db, schema) as session:
    rows = session.execute(cypher, params)

# 5) Or use a per-model Repository for CRUD
repo = Repository(Person, db)
alice = repo.find_one(name="Alice")
all_people = repo.find_all(limit=100)
```

## Integration with the LLM pipeline

`schema_to_pipeline_kwargs(graph_schema)` converts a `GraphSchema` into the kwargs
`LLMNLToCypher` expects:

```python
from cypher_validator import LLMNLToCypher, schema_to_pipeline_kwargs

pipe = LLMNLToCypher.from_openai(
    model="gpt-4o",
    api_key="...",
    **schema_to_pipeline_kwargs(graph_schema),
)
cypher = pipe("List actors over 60 who appeared in films from the 90s.", mode="match")
```

This is the recommended way to share a single source-of-truth schema between your
Pydantic models, the validator, and the LLM pipeline.

## Where to go from here

- Define your schema → [Models](models.md)
- Build queries → [Query builder](query-builder.md)
- Per-model CRUD → [Repository](repository.md)
- Execute against Neo4j → [Sessions](sessions.md)
- Batch operations → [Bulk ops](bulk.md)
- Graph patterns → [Traversal](traversal.md)
- Constraints & indexes → [DDL & migrations](ddl.md)
- Build an LLM agent → [Agent tools](agent-tools.md)
- Gotchas → [API caveats](caveats.md)
