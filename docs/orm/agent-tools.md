# Agent tools

`AgentTools` and `ExtendedAgentTools` build OpenAI / Anthropic function-calling
tool specs from your `GraphSchema`, then dispatch the LLM's structured tool
calls back into `(cypher, params)` tuples you can execute. The two classes are
the recommended bridge between a chat agent and a typed graph.

```python
from cypher_validator import (
    AgentTools, ExtendedAgentTools,
    GraphSchema, NodeModel, RelationshipModel, Neo4jDatabase,
)
```

## `AgentTools`

```python
AgentTools(schema: GraphSchema)
```

Base class. Produces three tool specs:

| Tool | Method | Maps to |
|---|---|---|
| `execute_cypher` | `query_tool_spec(format)` | Raw cypher + params |
| `create_node` | `create_node_tool_spec(format)` | `NodeModel.to_create_cypher` |
| `create_relationship` | `create_relationship_tool_spec(format)` | `RelationshipModel.to_create_cypher` |

### `query_tool_spec(format="openai") → dict`

A general-purpose `execute_cypher` tool. The LLM emits `{query_type, cypher,
parameters, explanation}`; the schema text is embedded in the tool description
so the model knows which labels and types exist.

### `create_node_tool_spec(format="openai") → dict`

Lets the LLM create a node by **label** + **properties** rather than raw
Cypher. The enum of allowed labels and the per-label property schema (with
required fields) are derived from your `NodeModel` subclasses.

### `create_relationship_tool_spec(format="openai") → dict`

Lets the LLM connect two nodes by relationship type + source/target match
properties. The enum of rel_types and the inline (`(:Src)-[:REL]->(:Tgt)`)
description come from your `RelationshipModel` subclasses.

### `all_tool_specs(format="openai") → list[dict]`

Returns all three specs as a list. Pass straight to the LLM SDK's `tools=`
parameter.

### `handle_tool_call(tool_name, arguments) → tuple[str, dict] | None`

The reverse direction. Given the tool name and the structured arguments the
LLM emitted, returns `(cypher, params)` ready for `db.execute(...)` — or
`None` if the tool name is not recognised.

!!! info "Dispatcher returns Cypher, not a result"
    `handle_tool_call` does **not** touch the database. It's a pure translator
    from JSON tool arguments to `(cypher, params)`. Execute it yourself —
    that gives you the option to log the query, present it to a user for
    approval, or substitute a dry-run sandbox.

### `schema_context_for_prompt() → str`

A ready-made system-prompt snippet that documents the schema and lists which
tools are available. Use this verbatim or splice into your own prompt.

## `ExtendedAgentTools`

```python
ExtendedAgentTools(schema: GraphSchema)
```

Subclass that adds five higher-level tools on top of the base three:

| Tool | Method | Maps to |
|---|---|---|
| `search_nodes` | `search_nodes_tool_spec(format)` | `Query().match().where(...).return_().order_by().limit()` |
| `find_neighbors` | `find_neighbors_tool_spec(format)` | `Traversal.neighbors` |
| `find_path` | `find_path_tool_spec(format)` | `Traversal.shortest_path` |
| `get_graph_schema` | `get_schema_tool_spec(format)` | `schema.to_prompt() / .to_markdown() / .to_json()` |
| `bulk_create_nodes` | `bulk_create_tool_spec(format)` | `BulkOps.bulk_create_nodes` |

### Behaviour

- `all_tool_specs(format)` **extends** the base list with the five extra
  tools — call this on `ExtendedAgentTools` to get all eight.
- `handle_tool_call(name, args)` first delegates to `super().handle_tool_call`.
  Only if the base returns `None` does the subclass attempt to dispatch its
  own tools. That means an `ExtendedAgentTools` instance can transparently
  handle every tool a base `AgentTools` instance would.

## Format flag — Anthropic vs OpenAI

Every spec method takes `format: str = "openai"`. The default returns the OpenAI
function-calling shape:

```python
{
    "type": "function",
    "function": {
        "name": "...",
        "description": "...",
        "parameters": {"type": "object", "properties": {...}, "required": [...]},
    },
}
```

`format="anthropic"` returns the Claude `tool_use` shape:

```python
{
    "name": "...",
    "description": "...",
    "input_schema": {"type": "object", "properties": {...}, "required": [...]},
}
```

The same `properties` / `required` blocks are reused — only the wrapper
differs.

## End-to-end agent loop

The flow is always the same: build the schema → instantiate the tools →
hand the specs to the LLM → dispatch the model's tool call → execute the
returned Cypher → reply.

=== "Anthropic"

    ```python
    import anthropic
    from cypher_validator import (
        ExtendedAgentTools, GraphSchema, Neo4jDatabase, NodeModel,
    )

    class Person(NodeModel):
        __label__ = "Person"
        name: str
        age: int = 0

    schema = GraphSchema.from_models([Person])
    tools = ExtendedAgentTools(schema)
    db = Neo4jDatabase("bolt://localhost:7687", "neo4j", "password")

    client = anthropic.Anthropic()
    msg = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=1024,
        system=tools.schema_context_for_prompt(),
        tools=tools.all_tool_specs(format="anthropic"),
        messages=[{"role": "user", "content": "Find people older than 30."}],
    )

    # Dispatch every tool_use block the model emits
    for block in msg.content:
        if block.type == "tool_use":
            result = tools.handle_tool_call(block.name, block.input)
            if result is None:
                continue
            cypher, params = result
            rows = db.execute(cypher, params)
            print(cypher, "→", len(rows), "rows")
    ```

=== "OpenAI"

    ```python
    import json
    from openai import OpenAI
    from cypher_validator import (
        ExtendedAgentTools, GraphSchema, Neo4jDatabase, NodeModel,
    )

    class Person(NodeModel):
        __label__ = "Person"
        name: str
        age: int = 0

    schema = GraphSchema.from_models([Person])
    tools = ExtendedAgentTools(schema)
    db = Neo4jDatabase("bolt://localhost:7687", "neo4j", "password")

    client = OpenAI()
    resp = client.chat.completions.create(
        model="gpt-4o",
        tools=tools.all_tool_specs(format="openai"),
        messages=[
            {"role": "system", "content": tools.schema_context_for_prompt()},
            {"role": "user",   "content": "Find people older than 30."},
        ],
    )

    for call in resp.choices[0].message.tool_calls or []:
        args = json.loads(call.function.arguments)
        result = tools.handle_tool_call(call.function.name, args)
        if result is None:
            continue
        cypher, params = result
        rows = db.execute(cypher, params)
    ```

## Dispatch table — what each tool resolves to

The mapping below is what `handle_tool_call` actually returns. Refer to it when
debugging an agent that emits an unexpected query.

| Tool name | Resolved via |
|---|---|
| `execute_cypher` | `(arguments["cypher"], arguments.get("parameters", {}))` — pass-through |
| `create_node` | Look up model by label → `m(**props).to_create_cypher()` |
| `create_relationship` | Look up rel model → `instance.to_create_cypher(src_match=, tgt_match=)` |
| `search_nodes` | `Query().match(m, "n").where(...).return_("n").order_by(...).limit(...)` |
| `find_neighbors` | `Traversal.neighbors(m, match_props=, rel_type=, direction=, limit=)` |
| `find_path` | `Traversal.shortest_path(src_m, tgt_m, src_props, tgt_props, max_depth=)` |
| `get_graph_schema` | `(schema.to_prompt() / .to_markdown() / .to_json(), {})` |
| `bulk_create_nodes` | `BulkOps.bulk_create_nodes(m, items)` |

!!! warning "Unknown tools return `None`, never raise"
    `handle_tool_call` returns `None` for anything it doesn't recognise.
    Always guard the caller — don't unpack the result without checking.

## Combining with `QueryHistory`

A natural pattern is to keep a [`QueryHistory`](sessions.md#history) on the
session and feed `history.to_context()` back into the next LLM turn, so the
model knows what's already been tried.

```python
from cypher_validator import GraphSession, ExtendedAgentTools

tools = ExtendedAgentTools(schema)
with GraphSession(db, schema) as session:
    for turn in conversation:
        # ... call LLM with tools.all_tool_specs() ...
        for tool_call in turn.tool_calls:
            result = tools.handle_tool_call(tool_call.name, tool_call.args)
            if result is None:
                continue
            cypher, params = result
            try:
                rows = session.execute(cypher, params)
                session.history.add(cypher, params, result_count=len(rows))
            except Exception as exc:
                session.history.add(cypher, params, error=str(exc))
```

## Related

- [Models](models.md) — every node and relationship model becomes a tool enum
  value.
- [Traversal](traversal.md) — `find_neighbors` / `find_path` are thin wrappers
  over `Traversal.neighbors` / `Traversal.shortest_path`.
- [LLM pipeline](../llm/pipeline.md) — for end-to-end NL → Cypher generation
  outside of structured tool calls.
- [Caveats](caveats.md) — `handle_tool_call` returns `(cypher, params)` only.
  The caller is responsible for execution.
