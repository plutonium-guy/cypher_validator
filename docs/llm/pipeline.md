# LLM NL → Cypher pipeline

`LLMNLToCypher` is the production-grade natural-language → Cypher pipeline.
Unlike [GLiNER2 `NLToCypher`](../ner/gliner2.md) (which uses a zero-shot
relation extractor), this class delegates everything to an LLM, then runs the
output through the Rust validator with an automatic repair loop.

Source: `python/cypher_validator/llm_pipeline.py` (`class LLMNLToCypher` at
line 249).

## What it does

1. **Resolves a schema** — user-supplied > DB introspection > LLM-inferred.
2. **Builds a system + user prompt** appropriate for the resolved schema
   state (Mode A "schema known" or Mode B "schema unknown").
3. **Calls the LLM** synchronously or asynchronously.
4. **Extracts the Cypher** via `extract_cypher_from_text` (see
   [Tool specs & helpers](tools.md)).
5. **Validates + repairs** in a loop — first by applying the validator's
   `fixed_query` auto-fix, then by asking the LLM to repair.
6. Optionally **executes** the query against `self.db` and returns records.
7. For batch ingestion, **stabilises the schema** from a sample, then
   processes the remaining texts under the stabilised schema, optionally
   writing `Chunk` + `MENTIONED_IN` provenance edges.

## Constructor

```python
LLMNLToCypher(
    *,
    llm_fn: Callable[[str], str] | None = None,
    async_llm_fn: Callable[[str], Awaitable[str]] | None = None,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    schema: Any = None,
    db: Any = None,
    max_repair_retries: int = 2,
    temperature: float = 0.0,
    system_prompt: str | None = None,
    tpm_limit: int | None = None,
    max_concurrency: int = 5,
)
```

| Parameter | Purpose |
|---|---|
| `llm_fn` | Sync callable `(prompt) -> str`. Wins over `model`. |
| `async_llm_fn` | Async callable `(prompt) -> Awaitable[str]`. Optional — falls back to wrapping sync via `asyncio.to_thread`. |
| `model` | OpenAI-compatible model id; combined with `base_url` / `api_key`. |
| `base_url` | API base URL — DeepSeek, Groq, vLLM, Ollama, … |
| `api_key` | Provider key. Falls back to env vars used by the underlying SDK. |
| `schema` | A `cypher_validator.Schema` (or `GraphSchema.to_cypher_schema()`). When `None`, the pipeline tries DB introspection then LLM inference. |
| `db` | A `Neo4jDatabase` (or anything with `.execute(cypher, params)` and `.introspect_schema()`). |
| `max_repair_retries` | Max LLM repair iterations after validation failure. Default `2`. |
| `temperature` | Forwarded to SDK adapters; ignored when `llm_fn` is set. |
| `system_prompt` | Full override of the default schema-aware system prompt. |
| `tpm_limit` | Builds a `TokenBucketRateLimiter` internally. See [Async & rate-limit](async.md). |
| `max_concurrency` | Default for `aingest_texts` Phase 2 — gated by an `asyncio.Semaphore`. |

!!! note "Pick exactly one LLM source"
    Provide `llm_fn` **or** `model`, not both. The constructor raises
    `ValueError("Provide either 'llm_fn' or 'model'.")` if neither is
    supplied.

## Factory class methods

```python
LLMNLToCypher.from_openai(model="gpt-4o", *, api_key=None, schema=None,
                          db=None, max_repair_retries=2,
                          temperature=0.0, system_prompt=None)

LLMNLToCypher.from_deepseek(model="deepseek-chat", *, api_key=None,
                            base_url="https://api.deepseek.com", schema=None,
                            db=None, max_repair_retries=2,
                            temperature=0.0, system_prompt=None)

LLMNLToCypher.from_anthropic(model="claude-sonnet-4-20250514", *,
                             api_key=None, schema=None, db=None,
                             max_repair_retries=2, temperature=0.0,
                             system_prompt=None)

LLMNLToCypher.from_langchain(chat_model, *, schema=None, db=None,
                             max_repair_retries=2, system_prompt=None)

LLMNLToCypher.from_env(model=None, *, schema=None, database="neo4j",
                       max_repair_retries=2, temperature=0.0,
                       system_prompt=None)
```

`from_env` reads (in priority order) `ANTHROPIC_API_KEY` → `DEEPSEEK_API_KEY` →
`OPENAI_API_KEY`, and if `NEO4J_URI` + `NEO4J_PASSWORD` are present it
constructs a `Neo4jDatabase` (the pipeline marks itself the owner so `close()`
will tear it down later).

=== "OpenAI"

    ```python
    pipe = LLMNLToCypher.from_openai("gpt-4o", schema=my_schema, db=db)
    cypher = pipe("Alice acted in The Matrix.", mode="merge")
    ```

=== "Anthropic"

    ```python
    pipe = LLMNLToCypher.from_anthropic("claude-opus-4-7", schema=my_schema, db=db)
    cypher = pipe("Alice acted in The Matrix.", mode="merge")
    ```

=== "DeepSeek"

    ```python
    pipe = LLMNLToCypher.from_deepseek(schema=my_schema, db=db)
    ```

=== "LangChain"

    ```python
    from langchain_openai import ChatOpenAI

    chat = ChatOpenAI(model="gpt-4o", temperature=0)
    pipe = LLMNLToCypher.from_langchain(chat, schema=my_schema, db=db)
    ```

=== "Env"

    ```python
    pipe = LLMNLToCypher.from_env()    # picks Anthropic > DeepSeek > OpenAI
    ```

## Public sync API

### `__call__(text, mode="create", execute=False)`

The convenience entrypoint. Internally delegates to `ingest_with_context` and
returns:

- `cypher: str` when `execute=False`
- `(cypher, records)` when `execute=True`

```python
cypher = pipe("Alice acted in The Matrix.", mode="merge")
cypher, rows = pipe("List all actors over 60.", mode="match", execute=True)
```

Valid `mode` values: `"create"`, `"merge"`, `"match"`.

### `ingest_with_context(text, mode="create", execute=False) → dict`

Full audit trail of a single conversion. Returns:

| Key | Type | Meaning |
|---|---|---|
| `schema_source` | `"user" \| "db" \| "inferred"` | Where the schema came from. |
| `inferred_schema` | `dict \| None` | The JSON schema the LLM proposed (Mode B only). |
| `cypher` | `str` | Final, possibly repaired query. |
| `is_valid` | `bool` | Did the validator accept it after repair? |
| `validation_errors` | `list[str]` | Errors from the last validation attempt. |
| `repair_attempts` | `int` | How many repair iterations ran. |
| `records` | `list[dict]` | Driver output when `execute=True`. |
| `execution_error` | `str \| None` | Set when execution raised. |

### `ingest_texts(texts, *, source_ids=None, execute=False, schema_sample_size=3, provenance=True, on_error="skip", progress_fn=None) → IngestionResult`

Two-phase batch ingestion.

**Phase 1 — schema stabilisation.** When no schema is supplied and no DB
introspection succeeded, the pipeline runs `schema_sample_size` texts
serially in Mode B (JSON-fenced schema + Cypher). The inferred schemas are
**merged** into a single `Schema` instance cached on the pipeline.

**Phase 2 — bulk MERGE.** The remaining texts are ingested under the now-stable
schema using the `_SYSTEM_PROMPT_INGEST` template (always MERGE, never CREATE,
to avoid duplicates).

Each chunk yields a `ChunkResult` with:

```python
@dataclass
class ChunkResult:
    index: int
    source_id: str
    text_preview: str           # first 80 chars
    cypher: str
    provenance_cypher: str
    is_valid: bool
    validation_errors: list[str]
    repair_attempts: int
    executed: bool
    execution_error: str | None
    records: list[dict]
```

And the overall return value:

```python
@dataclass
class IngestionResult:
    schema: Any
    schema_source: str          # "user" | "db" | "inferred"
    results: list[ChunkResult]
    total: int
    succeeded: int
    failed: int
    schema_sample_texts: int    # how many texts were used by Phase 1
    errors: list[tuple[int, str]]
```

`on_error` accepts `"skip"` (default — recorded and continue) or `"raise"`
(stop immediately).

### `ingest_document(text, *, source_id="doc", chunk_size=2000, chunk_overlap=200, execute=False, schema_sample_size=3, provenance=True, on_error="skip", progress_fn=None) → IngestionResult`

Convenience wrapper. Splits `text` on sentence boundaries via
`_RE_SENTENCE_BOUNDARY` into chunks of `chunk_size` chars (with `chunk_overlap`
chars of trailing sentence rewind), names them `{source_id}_chunk_{i}`, and
delegates to `ingest_texts`.

## Provenance edges

When `provenance=True`, every chunk also emits:

```cypher
MERGE (chunk:Chunk {chunk_id: $chunk_id})
ON CREATE SET chunk.source_id = $source_id,
              chunk.text_preview = $text_preview,
              chunk.ingested_at = datetime()
WITH chunk
MATCH (n)
WHERE any(label IN labels(n) WHERE label IN $domain_labels)
AND n.name IS NOT NULL
MERGE (n)-[:MENTIONED_IN]->(chunk)
```

The `domain_labels` list is computed deterministically from the **just-emitted
domain Cypher** by running it through `parse_query()` and reading
`info.labels_used` (excluding `Chunk` itself). That means provenance always
matches what the domain MERGE actually wrote — no race, no duplication.

!!! tip "Provenance unlocks Graph RAG"
    The `Chunk` nodes and `:MENTIONED_IN` edges let you answer questions like
    "show me the source text that supports this entity" — point a
    [`GraphRAGPipeline`](rag.md) at the same database and you get
    answer-with-citations for free.

## Validation + repair loop

`_validate_and_repair` (sync) and `_avalidate_and_repair` (async) share the
same logic:

1. `validator.validate(cypher)` → `ValidationResult`.
2. If valid → return.
3. If `result.fixed_query is not None` — apply the auto-fix and re-validate.
   This handles the cheap cases (label typos, missing parentheses) without
   touching the LLM.
4. Otherwise build a repair prompt that includes the schema + errors and
   ask the LLM. Extract Cypher → re-validate.
5. Loop up to `max_repair_retries` times.

`repair_attempts` counts only the LLM round-trips, not the auto-fix steps.

## Schema sources

`_resolve_schema()` walks these sources in order:

1. `self.schema` (user-supplied).
2. `self._discovered_schema` cache (populated by previous DB introspection or
   LLM inference).
3. `self.db.introspect_schema()` — only cached if `node_labels()` is non-empty.
4. **LLM-inferred** via the Mode B prompt: the LLM emits a fenced ` ```json `
   block followed by a fenced ` ```cypher ` block. `_parse_inferred_schema`
   splits them; `_merge_inferred_schema` updates the cached schema.

The Mode B prompt template lives in `_SYSTEM_PROMPT_SCHEMA_UNKNOWN` and is
strict about output format — labels must be PascalCase, rel types
UPPER_SNAKE_CASE, every entity must have a `name` property.

## Async siblings

Every public sync entry point has an async counterpart with the same arguments:

| Sync | Async |
|---|---|
| `__call__` | `acall` |
| `ingest_with_context` | `aingest_with_context` |
| `ingest_texts` | `aingest_texts` |
| `ingest_document` | `aingest_document` |
| `_validate_and_repair` | `_avalidate_and_repair` |

Internal helpers:

- `_get_async_llm_fn()` returns `self._async_llm_fn` if set, else wraps
  `self._llm_fn` via `asyncio.to_thread(sync_fn, prompt)`.
- `_async_llm_call(prompt)` calls the async fn, applying
  `TokenBucketRateLimiter.acquire(estimate_tokens(prompt))` first when a
  rate limiter is configured.

Use the async path for parallel ingestion — `aingest_texts` runs Phase 1
serially (schema must stabilise before Phase 2 can branch) then drives Phase 2
through an `asyncio.Semaphore(max_concurrency)`.

See [Async & rate-limit](async.md) for the full story.

## Closing the pipeline

```python
with LLMNLToCypher.from_env() as pipe:
    cypher = pipe("Alice acted in The Matrix.", mode="merge")
# DB connection (if owned) is closed here.

# Async variant
async with LLMNLToCypher.from_env() as pipe:
    cypher = await pipe.acall("Alice acted in The Matrix.", mode="merge")
```

The pipeline marks itself the owner of the `db` only when `from_env`
constructs it. User-supplied `db` is never closed.

## Related

- [Async & rate-limit](async.md) — `TokenBucketRateLimiter` + concurrency.
- [Graph RAG](rag.md) — the question-answering counterpart that reuses the
  validate-and-repair plumbing.
- [Tool specs & helpers](tools.md) — `extract_cypher_from_text`,
  `repair_cypher`, `format_records`, `few_shot_examples`.
- [API caveats](../orm/caveats.md) — gotchas about the records the pipeline
  returns.
