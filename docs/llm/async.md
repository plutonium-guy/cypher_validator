# Async & rate-limit

`LLMNLToCypher` ships first-class async support and a built-in
tokens-per-minute (TPM) rate limiter — the two combine to let you ingest
thousands of texts in parallel without tripping provider quotas.

Source: `python/cypher_validator/llm_pipeline.py` — `class TokenBucketRateLimiter`
at line 104.

## `TokenBucketRateLimiter`

```python
TokenBucketRateLimiter(tpm: int)
```

A leaky-bucket rate limiter sized in tokens-per-minute. Methods:

| Method | Signature | Notes |
|---|---|---|
| `acquire` | `async def acquire(tokens: int) -> None` | Blocks until *tokens* are available, then consumes them. |
| `_refill` | `def _refill() -> None` | Internal — adds `elapsed_seconds * (tpm / 60)` tokens, capped at `tpm`. Called under the lock. |
| `estimate_tokens` | `@staticmethod estimate_tokens(text: str) -> int` | Char-to-token heuristic: `max(1, len(text) // 4)`. |

```python
import asyncio
from cypher_validator.llm_pipeline import TokenBucketRateLimiter

async def main():
    limiter = TokenBucketRateLimiter(tpm=60_000)
    for chunk in chunks:
        await limiter.acquire(TokenBucketRateLimiter.estimate_tokens(chunk))
        ...  # call the LLM

asyncio.run(main())
```

### How it works

`acquire` loops:

1. Take the lock, call `_refill()` to top up the bucket based on elapsed
   monotonic time.
2. If `_tokens >= requested`, deduct and return.
3. Otherwise compute the wait time as `(deficit) / (tpm / 60.0)`, drop the
   lock, `await asyncio.sleep(wait)`, retry.

The lock is held only during refill + check + deduct — never during sleep —
so many coroutines can wait concurrently without serialising on the lock.

!!! warning "char/4 is a heuristic, not a token count"
    `estimate_tokens` is intentionally cheap. Real tokenisation costs (BPE,
    SentencePiece) vary 2-3× per provider. If you're hitting quota walls,
    over-provision your `tpm` budget by ~50% or call your provider's
    tokenizer directly and pass the exact count to `acquire`.

## Wiring a rate limiter into `LLMNLToCypher`

Two paths:

=== "tpm_limit at construction"

    ```python
    pipe = LLMNLToCypher.from_openai(
        "gpt-4o",
        api_key="sk-...",
        schema=schema,
        db=db,
    )
    # Equivalent to internally setting:
    #   self._rate_limiter = TokenBucketRateLimiter(60_000)

    # Or set tpm_limit directly via __init__:
    pipe = LLMNLToCypher(
        model="gpt-4o",
        api_key="sk-...",
        schema=schema,
        tpm_limit=60_000,        # builds a TokenBucketRateLimiter internally
        max_concurrency=10,
    )
    ```

=== "Manual limiter"

    ```python
    from cypher_validator.llm_pipeline import TokenBucketRateLimiter

    limiter = TokenBucketRateLimiter(tpm=60_000)

    pipe = LLMNLToCypher(
        model="gpt-4o",
        api_key="sk-...",
        schema=schema,
    )
    pipe._rate_limiter = limiter   # share across multiple pipelines
    ```

Whenever `_async_llm_call(prompt)` runs:

```python
if self._rate_limiter is not None:
    tokens = TokenBucketRateLimiter.estimate_tokens(prompt)
    await self._rate_limiter.acquire(tokens)
fn = self._get_async_llm_fn()
return await fn(prompt)
```

That means **every** async entry point — `acall`, `aingest_with_context`,
`aingest_texts`, `aingest_document`, and the async repair loop — is rate-limited
automatically.

## `_get_async_llm_fn`

```python
def _get_async_llm_fn(self) -> Callable[[str], Awaitable[str]]:
    if self._async_llm_fn is not None:
        return self._async_llm_fn

    sync_fn = self._llm_fn
    async def _wrapped(prompt: str) -> str:
        return await asyncio.to_thread(sync_fn, prompt)
    return _wrapped
```

If you supply `async_llm_fn` at construction (e.g. an `httpx.AsyncClient`-based
caller), it's used directly. Otherwise the pipeline wraps the sync `llm_fn`
through `asyncio.to_thread` — this lets you ship an async ingestion job even
when your LLM client is sync.

!!! tip "Prefer a real async client when you can"
    `asyncio.to_thread` is fine for moderate parallelism (~10s of concurrent
    requests), but each call still holds a thread from the default executor.
    For high-throughput ingestion supply a true async client and pass it
    via `async_llm_fn=`.

## Parallel ingestion with `asyncio.gather`

The simplest async use case: convert many texts in parallel.

```python
import asyncio
from cypher_validator import LLMNLToCypher, GraphSchema

schema = GraphSchema.from_models([...])
pipe = LLMNLToCypher(
    model="gpt-4o",
    api_key="sk-...",
    schema=schema.to_cypher_schema(),
    tpm_limit=60_000,
)

texts = [
    "Alice acted in The Matrix.",
    "Bob directed Inception.",
    # ... many more ...
]

async def run():
    results = await asyncio.gather(*[pipe.acall(t, mode="merge") for t in texts])
    return results

cyphers = asyncio.run(run())
```

The rate limiter coordinates across every concurrent `acall`. If 100 calls
arrive at once and they each estimate 2 000 tokens, the limiter will release
them in waves of `tpm / 2 000` per minute.

## Bulk ingestion — `aingest_texts`

For the full schema-stabilisation + provenance flow, use `aingest_texts`.
Phase 1 runs serially; Phase 2 fans out under `asyncio.Semaphore(max_concurrency)`:

```python
async def ingest():
    async with LLMNLToCypher.from_anthropic(schema=schema, db=db) as pipe:
        pipe._rate_limiter = TokenBucketRateLimiter(tpm=200_000)
        result = await pipe.aingest_texts(
            texts,
            execute=True,
            schema_sample_size=3,
            provenance=True,
            on_error="skip",
            progress_fn=lambda i, n: print(f"{i}/{n}"),
            max_concurrency=20,
        )
    return result

result = asyncio.run(ingest())
print(f"{result.succeeded}/{result.total} OK; schema source: {result.schema_source}")
```

`max_concurrency` defaults to whatever you set on the constructor
(`5` by default).

## Putting it all together

A complete script that ingests a directory of `.txt` files with TPM caps:

```python
import asyncio, glob
from cypher_validator import (
    LLMNLToCypher, GraphSchema, Neo4jDatabase,
    NodeModel, RelationshipModel,
)
from cypher_validator.llm_pipeline import TokenBucketRateLimiter

class Person(NodeModel):
    __label__ = "Person"
    name: str

class Company(NodeModel):
    __label__ = "Company"
    name: str

class WorksFor(RelationshipModel):
    __source__ = Person
    __target__ = Company
    __rel_type__ = "WORKS_FOR"

schema = GraphSchema.from_models([Person, Company, WorksFor]).to_cypher_schema()
db = Neo4jDatabase("bolt://localhost:7687", "neo4j", "password")

async def main():
    texts = [open(p).read() for p in glob.glob("docs/*.txt")]
    async with LLMNLToCypher.from_anthropic(schema=schema, db=db) as pipe:
        pipe._rate_limiter = TokenBucketRateLimiter(tpm=200_000)
        result = await pipe.aingest_texts(
            texts,
            execute=True,
            provenance=True,
            max_concurrency=10,
            progress_fn=lambda i, n: print(f"\r{i}/{n}", end=""),
        )
    print()
    print(f"OK: {result.succeeded}/{result.total}")
    print(f"Failed: {len(result.errors)}")

asyncio.run(main())
```

## Cheat-sheet: which methods are async-aware

| Sync | Async | Rate-limited? |
|---|---|---|
| `__call__` | `acall` | Yes (via `_async_llm_call`) |
| `ingest_with_context` | `aingest_with_context` | Yes |
| `ingest_texts` | `aingest_texts` | Yes |
| `ingest_document` | `aingest_document` | Yes |
| `_validate_and_repair` | `_avalidate_and_repair` | Yes (repair prompts also go through `_async_llm_call`) |

Sync methods do not consult the rate limiter — if you need quotas, switch
to the async path.

## Related

- [LLM pipeline](pipeline.md) — full `LLMNLToCypher` reference.
- [Graph RAG](rag.md) — `GraphRAGPipeline` (sync only — wrap manually if you
  need async).
- [API caveats](../orm/caveats.md) — Pydantic ORM gotchas you'll hit during
  ingestion.
