# Tool specs & helpers

Standalone helpers from `python/cypher_validator/llm_utils.py` for working
with LLM output and constructing tool specs. These functions are reused by
[`LLMNLToCypher`](pipeline.md), [`GraphRAGPipeline`](rag.md), and the
[`AgentTools`](../orm/agent-tools.md) family, but you can use them directly
when building your own pipeline.

## `cypher_tool_spec`

```python
cypher_tool_spec(
    schema: Schema | None = None,
    db_description: str = "",
    format: str = "anthropic",
) -> dict[str, Any]
```

Builds a tool specification for the LLM. The shape switches on `format`:

=== "Anthropic"

    ```python
    {
        "name": "execute_cypher",
        "description": "Execute a Cypher query against the Neo4j graph database...",
        "input_schema": {
            "type": "object",
            "properties": {
                "cypher": {"type": "string", "description": "..."},
                "parameters": {"type": "object", "additionalProperties": True},
            },
            "required": ["cypher"],
        },
    }
    ```

=== "OpenAI"

    ```python
    {
        "type": "function",
        "function": {
            "name": "execute_cypher",
            "description": "Execute a Cypher query against the Neo4j graph database...",
            "parameters": {
                "type": "object",
                "properties": {
                    "cypher": {"type": "string"},
                    "parameters": {"type": "object", "additionalProperties": True},
                },
                "required": ["cypher"],
            },
        },
    }
    ```

When `schema` is supplied, the inline Cypher-pattern representation
(`schema.to_cypher_context()`) is appended to the description so the LLM
knows which labels and types are available. `db_description` is a short
free-text hint (e.g. `"knowledge graph of scientific papers"`) that gets
slotted into the description in parentheses.

```python
from cypher_validator import cypher_tool_spec, Schema

schema = Schema(
    nodes={"Person": ["name", "age"]},
    relationships={"WORKS_FOR": ("Person", "Company", [])},
)
tool = cypher_tool_spec(schema, db_description="employees graph", format="openai")
```

!!! tip "Anthropic is the default"
    Unlike `AgentTools.query_tool_spec(format="openai")`, this standalone
    helper defaults to **Anthropic**. Pass `format="openai"` explicitly when
    you want the function-calling shape.

## `extract_cypher_from_text`

```python
extract_cypher_from_text(text: str) -> str
```

Lifts a Cypher query out of arbitrary LLM output. It walks five fallback
tiers in order:

| Tier | Pattern | Notes |
|---|---|---|
| 1 | ```` ```cypher\n…``` ``` / ` ```sql ` / ` ```sparql ` | Strictest — tagged fence wins immediately. |
| 2 | ```` ```<any>\n…``` ```` | Untagged fence, but only if the body contains a Cypher keyword. |
| 3 | `` `…` `` (inline backtick) | Only if the span looks like Cypher. |
| 4 | Line-anchored `MATCH` / `CREATE` / `MERGE` / `WITH` / `CALL` / `UNWIND` / `OPTIONAL` | Collects consecutive non-blank lines starting at the first match. |
| 5 | Fallback | Returns `text.strip()`. |

The Cypher-keyword check uses a `frozenset` lookup against the upper-cased
text — fast even on multi-kilobyte responses.

```python
from cypher_validator import extract_cypher_from_text

output = """
Sure! Here's the query:

```cypher
MATCH (p:Person {name: $name})-[:WORKS_FOR]->(c:Company)
RETURN p, c
```
"""
extract_cypher_from_text(output)
# 'MATCH (p:Person {name: $name})-[:WORKS_FOR]->(c:Company)\nRETURN p, c'
```

The regex patterns (`_RE_FENCED_TAGGED`, `_RE_FENCED_ANY`, `_RE_BACKTICK`,
`_RE_CYPHER_LINE`) are compiled at module load — extracting Cypher in a hot
ingestion loop is essentially free.

## `repair_cypher`

```python
repair_cypher(
    validator: CypherValidator,
    query: str,
    llm_fn: Callable[[str, list[str]], str],
    max_retries: int = 3,
) -> tuple[str, ValidationResult]
```

The standalone repair loop. The signature of `llm_fn` here is **different**
from `LLMNLToCypher`'s callable — it receives both the current query and
the list of error strings, and must return a corrected query string.

The loop:

1. Validate the current query.
2. If valid → return.
3. If `result.fixed_query is not None`, apply that auto-fix first and
   re-validate. The auto-fix is purely local (typo correction, dropping
   unknown variables, etc.) — it doesn't burn an LLM call.
4. Otherwise call `llm_fn(query, errors)` for a manual fix.
5. Loop up to `max_retries` times.

```python
from cypher_validator import CypherValidator, repair_cypher, Schema

schema = Schema(nodes={"Person": ["name"]}, relationships={})
validator = CypherValidator(schema)

def fix_with_llm(query: str, errors: list[str]) -> str:
    error_block = "\n".join(f"  - {e}" for e in errors)
    return my_llm(f"Fix this Cypher:\n{query}\n\nErrors:\n{error_block}")

cypher, result = repair_cypher(validator, "MATCH (p:Persn) RETURN p", fix_with_llm)
if result.is_valid:
    db.execute(cypher)
```

!!! note "Auto-fix may converge without ever calling the LLM"
    `result.fixed_query` is computed by the Rust validator using a
    Levenshtein-capped "did you mean?" lookup against the schema. For
    simple label/property typos the loop converges on attempt #1 with zero
    LLM cost.

## `format_records`

```python
format_records(
    records: list[dict[str, Any]],
    format: str = "markdown",
) -> str
```

Render Neo4j result records as an LLM-context-friendly string.

| Format | Output |
|---|---|
| `"markdown"` (default) | Aligned pipe-separated table. |
| `"csv"` | RFC 4180-ish CSV via `csv.DictWriter`. |
| `"json"` | Pretty-printed JSON via `json.dumps(records, indent=2, default=str)`. |
| `"text"` | One record per block: `Record N:\n  key: value`. |

Returns `""` for an empty list. Unknown formats raise `ValueError`:

```python
format_records(rows, format="yaml")
# ValueError: Unknown format 'yaml'. Use 'markdown', 'csv', 'json', or 'text'.
```

```python
records = [{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}]

format_records(records)
# | name  | age |
# |-------|-----|
# | Alice | 30  |
# | Bob   | 25  |

format_records(records, format="csv")
# name,age
# Alice,30
# Bob,25
```

The markdown table aligns columns to the longest cell — fine for tens of
rows, but if you've got thousands consider `format="json"` or slicing
`records[:50]` before formatting (the LLM context window is the bottleneck,
not the function).

## `few_shot_examples`

```python
few_shot_examples(
    generator: CypherGenerator,
    n: int = 5,
    query_type: str | None = None,
) -> list[tuple[str, str]]
```

Generates `(description, cypher)` pairs from a `CypherGenerator`. The
descriptions are derived from the query type plus the labels and rel types
the parser detects — so they're guaranteed consistent with the actual Cypher
output:

```python
from cypher_validator import CypherGenerator, Schema, few_shot_examples

schema = Schema(
    nodes={"Person": ["name", "age"], "Company": ["name"]},
    relationships={"WORKS_FOR": ("Person", "Company", [])},
)
gen = CypherGenerator(schema, seed=0)
for desc, cypher in few_shot_examples(gen, n=4):
    print(f"Q: {desc}")
    print(f"A: {cypher}\n")
```

When `query_type=None` (default), examples are spread across all
`generator.supported_types()` cyclically. When set to a specific type, **n**
examples of that type are generated. Unknown types raise `ValueError` with
the supported list:

```python
few_shot_examples(gen, n=2, query_type="bogus")
# ValueError: Unknown query_type 'bogus'. Supported: ['match_return', ...]
```

!!! tip "Stable few-shot prompts"
    Pair `CypherGenerator(schema, seed=N)` with a fixed `N` and the same
    schema and you'll get identical few-shot prompts on every run — useful
    when you want to A/B test prompt variants without LLM noise from the
    examples drifting.

## Putting it together

A minimal "ask the LLM, validate, retry, format" loop using only the
helpers from this module:

```python
from cypher_validator import (
    Schema, CypherValidator, Neo4jDatabase,
    cypher_tool_spec, extract_cypher_from_text,
    repair_cypher, format_records,
)

schema = Schema(...)
validator = CypherValidator(schema)
db = Neo4jDatabase(...)

# 1. Get cypher from the LLM
raw = my_llm(question)
cypher = extract_cypher_from_text(raw)

# 2. Validate + auto-repair
def fix_with_llm(q, errs):
    return extract_cypher_from_text(my_llm(f"fix: {q}\nerrors: {errs}"))

cypher, result = repair_cypher(validator, cypher, fix_with_llm, max_retries=3)

# 3. Execute + format
if result.is_valid:
    rows = db.execute(cypher)
    print(format_records(rows))
```

That's effectively what [`GraphRAGPipeline.query_with_context`](rag.md)
does, with an answer-synthesis step bolted on top.

## Related

- [LLM pipeline](pipeline.md) — uses every helper on this page.
- [Graph RAG](rag.md) — answer synthesis from query results.
- [Agent tools](../orm/agent-tools.md) — schema-aware versions of
  `cypher_tool_spec` plus dispatch.
- [Validator](../core/validator.md) — the `ValidationResult.fixed_query`
  contract that `repair_cypher` leans on.
