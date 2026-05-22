# Graph RAG

`GraphRAGPipeline` chains Cypher generation, validation, execution, and
answer synthesis into a single `pipeline.query(question)` call. It's the
natural-language → answer counterpart to [`LLMNLToCypher`](pipeline.md), which
focuses on natural-language → Cypher.

Source: `python/cypher_validator/rag.py`.

## What's in the chain

```text
question
   │
   ▼
1. Cypher generation        ← llm_fn(cypher_system + question)
   │
   ▼
2. extract_cypher_from_text
   │
   ▼
3. validate + repair loop   ← max_repair_retries
   │
   ▼
4. db.execute(cypher)
   │
   ▼
5. format_records           ← markdown / csv / json / text
   │
   ▼
6. answer synthesis         ← llm_fn(answer_system + question + results)
   │
   ▼
answer
```

Steps 1 and 6 are LLM round-trips; step 4 is the only database touch.

## Constructor

```python
GraphRAGPipeline(
    schema,
    db,
    llm_fn: Callable[[str], str],
    *,
    max_repair_retries: int = 2,
    result_format: str = "markdown",
    cypher_system_prompt: str | None = None,
    answer_system_prompt: str | None = None,
)
```

| Parameter | Purpose |
|---|---|
| `schema` | A `cypher_validator.Schema`. Used for validation and is embedded in the default Cypher-generation system prompt via `schema.to_cypher_context()`. |
| `db` | `Neo4jDatabase` (or any duck-typed `.execute(cypher) -> list[dict]`). |
| `llm_fn` | Callable `(prompt: str) -> str` — called **twice** per `query`. |
| `max_repair_retries` | LLM repair iterations. Default `2`. |
| `result_format` | Forwarded to [`format_records`](tools.md#format_records) — `"markdown"` (default), `"csv"`, `"json"`, or `"text"`. |
| `cypher_system_prompt` | Override the default Cypher-generation system prompt (schema is **not** appended automatically when overridden). |
| `answer_system_prompt` | Override the default answer-synthesis system prompt. |

Internally the pipeline constructs a `CypherValidator(schema)` once and reuses
it for every `query`.

## Public API

### `query(question: str) → str`

The convenience method. Returns just the final natural-language answer.

```python
from cypher_validator import GraphRAGPipeline, Neo4jDatabase, Schema

def call_llm(prompt: str) -> str:
    # Wrap your provider here — Anthropic / OpenAI / Gemini / Ollama …
    ...

schema = Schema(
    nodes={"Person": ["name"], "Company": ["name"]},
    relationships={"WORKS_FOR": ("Person", "Company", [])},
)
db = Neo4jDatabase("bolt://localhost:7687", "neo4j", "password")

pipeline = GraphRAGPipeline(schema, db, call_llm)
print(pipeline.query("Who works for Acme Corp?"))
```

### `query_with_context(question: str) → dict`

The full audit trail. Returns every intermediate artefact so you can log,
debug, or hand-off to a UI:

| Key | Type | Meaning |
|---|---|---|
| `question` | `str` | Verbatim input. |
| `cypher` | `str` | Final Cypher (post-repair). |
| `is_valid` | `bool` | Did the validator accept the final Cypher? |
| `validation_errors` | `list[str]` | Errors from the last validation attempt. |
| `repair_attempts` | `int` | LLM repair iterations actually run (0 = first try worked). |
| `records` | `list[dict]` | Raw driver output. Empty on execution error. |
| `formatted_results` | `str` | `records` rendered via `format_records(..., result_format)`. |
| `answer` | `str` | LLM-synthesised final answer. |
| `execution_error` | `str \| None` | Set when the driver raised. |

```python
ctx = pipeline.query_with_context("Who works for Acme Corp?")
print(ctx["cypher"])               # the actual Cypher used
print(ctx["formatted_results"])    # markdown table the LLM saw
print(ctx["answer"])               # final user-facing answer
```

## Default Cypher system prompt

The default prompt (auto-built when `cypher_system_prompt is None`) is:

```text
You are a Neo4j Cypher expert. Generate a single Cypher query that answers
the user's question.

Schema:
<schema.to_cypher_context()>

Rules:
- Return ONLY the Cypher query inside a ```cypher code fence, with no other text.
- Use only the labels and relationship types defined in the schema above.
- Prefer parameterised values ($name, $year, ...) for user-supplied data.
- Always include a RETURN clause.
- Use LIMIT when the result could be very large.
```

Override only when you want different rules (e.g. force a single-record
RETURN, or disallow `OPTIONAL MATCH`). When you override, the schema is **not**
automatically appended — splice it in yourself if you need it.

## Default answer system prompt

```text
You are a helpful assistant. Answer the user's question concisely based on
the provided graph database query results. If the results are empty, say so
clearly.
```

The actual prompt sent for answer synthesis adds:

```text
<answer_system_prompt>

Question: <question>

Graph database results:
<formatted_results, or "No results found.", or "Query execution failed: ...">

Answer:
```

## Validation + repair

Same approach as `LLMNLToCypher` but inlined:

1. `extract_cypher_from_text(raw_response)` lifts the Cypher out of the
   fenced block.
2. `self._validator.validate(cypher)` checks it.
3. If invalid, the pipeline builds a repair prompt embedding the original
   system prompt, the faulty query, and the error list, then re-extracts.
4. Loop up to `max_repair_retries` times.

The validator's auto-fix path (`result.fixed_query`) is **not** used by
`GraphRAGPipeline` directly — every repair iteration goes through the LLM.
If you want the auto-fix shortcut, use
[`repair_cypher`](tools.md#repair_cypher) explicitly, or switch to
[`LLMNLToCypher`](pipeline.md).

## Full example with a mock LLM

The pattern below uses a stub `llm_fn` so the test is reproducible — replace
with your real provider in production.

```python
from cypher_validator import (
    GraphRAGPipeline, Schema, Neo4jDatabase,
)

schema = Schema(
    nodes={"Person": ["name", "age"], "Company": ["name"]},
    relationships={"WORKS_FOR": ("Person", "Company", [])},
)
db = Neo4jDatabase("bolt://localhost:7687", "neo4j", "password")

CYPHER_RESP = """```cypher
MATCH (p:Person)-[:WORKS_FOR]->(c:Company {name: $company})
RETURN p.name AS name, p.age AS age
```"""

ANSWER_RESP = "Alice (30) and Bob (25) work for Acme Corp."

def fake_llm(prompt: str) -> str:
    # First call: cypher generation; second call: answer synthesis
    return CYPHER_RESP if "Schema:" in prompt else ANSWER_RESP

pipeline = GraphRAGPipeline(schema, db, fake_llm)
ctx = pipeline.query_with_context("Who works for Acme Corp?")
print(ctx["cypher"])
# MATCH (p:Person)-[:WORKS_FOR]->(c:Company {name: $company})
# RETURN p.name AS name, p.age AS age

print(ctx["formatted_results"])
# | name  | age |
# |-------|-----|
# | Alice |  30 |
# | Bob   |  25 |

print(ctx["answer"])
# Alice (30) and Bob (25) work for Acme Corp.
```

!!! warning "Parameter injection is your job"
    The default prompt tells the LLM to *prefer parameterised values* — but
    nothing in `query()` actually supplies parameter dictionaries to
    `db.execute`. If your generated Cypher contains `$param` placeholders
    without bound values, the driver will refuse to run it. Either accept
    that the LLM will inline literals when the schema rules allow, or
    extend the pipeline (subclass + override `query_with_context`) to
    capture extracted parameters before `db.execute`.

## When to use this vs `LLMNLToCypher`

| Need | Use |
|---|---|
| Single shot: question → answer | `GraphRAGPipeline` |
| Ingest documents into the graph | `LLMNLToCypher.ingest_texts` |
| Agent / tool-call flow | [`AgentTools`](../orm/agent-tools.md) |
| Just want Cypher, no answer | `LLMNLToCypher.__call__` |
| Async / rate-limited workloads | `LLMNLToCypher.aingest_texts` |

## Related

- [LLM pipeline](pipeline.md) — `LLMNLToCypher` shares the validate + repair
  plumbing.
- [Tool specs & helpers](tools.md) — `extract_cypher_from_text`,
  `format_records`, `repair_cypher`.
- [GLiNER2 integration](../ner/gliner2.md) — non-LLM relation extraction for
  when you don't want to pay per token.
