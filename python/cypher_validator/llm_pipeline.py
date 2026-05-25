"""
LLM-based natural language to Cypher pipeline.

Unlike :class:`~cypher_validator.NLToCypher` (which uses GLiNER2 for
relation extraction), this module sends the text directly to an LLM and
asks it to produce Cypher.  The LLM backend is swappable — any
OpenAI-compatible API (OpenAI, DeepSeek, Groq, …) works out of the box
via the ``openai`` SDK, or you can supply a raw ``llm_fn`` callable.

Schema can be:
- Provided explicitly (a :class:`~cypher_validator.Schema` instance)
- Auto-discovered from a live Neo4j database
- Inferred by the LLM from the input text (when neither is available)

Usage
-----
::

    from cypher_validator import LLMNLToCypher, Schema

    schema = Schema(
        nodes={"Person": ["name"], "Company": ["name"]},
        relationships={"WORKS_FOR": ("Person", "Company", [])},
    )

    # Option 1: OpenAI-compatible provider
    pipeline = LLMNLToCypher(model="deepseek-chat",
                              base_url="https://api.deepseek.com",
                              api_key="sk-...", schema=schema)

    # Option 2: raw callable
    pipeline = LLMNLToCypher(llm_fn=my_fn, schema=schema)

    cypher = pipeline("John works for Apple and lives in SF.", mode="create")
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    Optional,
    Tuple,
    Union,
)

from cypher_validator.llm_utils import extract_cypher_from_text


# Precompiled patterns — these run on every LLM response during ingestion.
_RE_JSON_BLOCK = re.compile(r"```json\s*\n(.*?)```", re.DOTALL)
_RE_CYPHER_BLOCK = re.compile(r"```cypher\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
_RE_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")


# ---------------------------------------------------------------------------
# Dataclasses for batch ingestion
# ---------------------------------------------------------------------------

@dataclass
class ChunkResult:
    """Result of ingesting a single text chunk."""

    index: int
    source_id: str
    text_preview: str
    cypher: str
    provenance_cypher: str
    is_valid: bool
    validation_errors: list[str] = field(default_factory=list)
    repair_attempts: int = 0
    executed: bool = False
    execution_error: str | None = None
    records: list[dict] = field(default_factory=list)


@dataclass
class IngestionResult:
    """Aggregate result of a batch ingestion run."""

    schema: Any  # Schema
    schema_source: str  # "user" | "db" | "inferred"
    results: list[ChunkResult] = field(default_factory=list)
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    schema_sample_texts: int = 0
    errors: list[tuple[int, str]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Token-bucket rate limiter for TPM quotas
# ---------------------------------------------------------------------------

class TokenBucketRateLimiter:
    """Async token-bucket rate limiter for LLM tokens-per-minute quotas.

    Parameters
    ----------
    tpm : int
        Maximum tokens per minute.
    """

    def __init__(self, tpm: int) -> None:
        self.tpm = tpm
        self._tokens = float(tpm)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: int) -> None:
        """Wait until *tokens* are available, then consume them."""
        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                # Calculate wait time for enough tokens to refill
                deficit = tokens - self._tokens
                wait = deficit / (self.tpm / 60.0)
            await asyncio.sleep(wait)

    def _refill(self) -> None:
        """Refill tokens based on elapsed time (called under lock)."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(
            float(self.tpm),
            self._tokens + elapsed * (self.tpm / 60.0),
        )
        self._last_refill = now

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Rough char-to-token estimate (1 token ≈ 4 chars)."""
        return max(1, len(text) // 4)


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_SCHEMA_KNOWN = """\
You are a Neo4j Cypher expert.
Generate a single Cypher query that faithfully represents the information in the user's text.

Schema:
{schema_context}

Rules:
- Return ONLY the Cypher query inside a ```cypher code fence.
- Use only the labels and relationship types defined in the schema above.
- Use parameterised values ($param) for user-supplied literals when appropriate.
- For CREATE/MERGE mode: create nodes and relationships that capture the entities and relations in the text.
- For MATCH mode: write a query that would retrieve the information described.
"""

_SYSTEM_PROMPT_SCHEMA_UNKNOWN = """\
You are a Neo4j Cypher expert and knowledge-graph designer.
The user will provide a natural language passage. You must:

1. Infer a graph schema (node labels with properties, relationship types with source/target labels and properties) that best represents the information.
2. Generate a Cypher query using that schema.

Return your response in EXACTLY this format — a JSON block followed by a Cypher block:

```json
{{
  "inferred_schema": {{
    "nodes": {{
      "Label": ["prop1", "prop2"]
    }},
    "relationships": {{
      "REL_TYPE": ["SourceLabel", "TargetLabel", ["prop1"]]
    }}
  }}
}}
```

```cypher
CREATE ...
```

Rules:
- Use PascalCase for labels, UPPER_SNAKE_CASE for relationship types.
- Include a "name" property on every entity node.
- Keep the schema minimal — only what the text requires.
"""

_REPAIR_PROMPT_WITH_SCHEMA = """\
The Cypher query below has validation errors. \
Fix it and return ONLY the corrected query inside a ```cypher code fence.

Schema:
{schema_context}

Query:
```cypher
{cypher}
```

Errors:
{error_list}
"""

_SYSTEM_PROMPT_INGEST = """\
You are a Neo4j Cypher expert.
Generate a Cypher query using MERGE to upsert entities and relationships from the user's text.

Schema:
{schema_context}

Rules:
- Return ONLY the Cypher query inside a ```cypher code fence.
- Use MERGE for every node and relationship to avoid duplicates.
- MERGE nodes on their primary identifying property (usually "name").
- Use ON CREATE SET / ON MATCH SET to update properties as needed.
- Use only the labels and relationship types from the schema above.
- Extract ALL entities and relationships from the text.
"""


# ---------------------------------------------------------------------------
# LLMNLToCypher
# ---------------------------------------------------------------------------

class LLMNLToCypher:
    """LLM-based natural language to Cypher pipeline.

    Parameters
    ----------
    llm_fn:
        A callable ``(prompt: str) -> str``.  If provided, ``model``,
        ``base_url``, and ``api_key`` are ignored.  Note that
        ``temperature`` has no effect when using a raw *llm_fn* — you
        must configure temperature inside the callable itself.
    model:
        Model identifier (e.g. ``"deepseek-chat"``, ``"gpt-4o"``).
        Used with the ``openai`` SDK.
    base_url:
        API base URL for OpenAI-compatible providers.  Defaults to
        ``None`` (the OpenAI default).
    api_key:
        API key.  If ``None``, the ``openai`` SDK reads from
        ``OPENAI_API_KEY`` environment variable.
    schema:
        Optional :class:`~cypher_validator.Schema`.  When provided,
        the LLM is constrained to use these labels/types.
    db:
        Optional :class:`~cypher_validator.Neo4jDatabase`.  Used for
        schema auto-discovery and optional query execution.
    max_repair_retries:
        Maximum number of validate-and-repair iterations (default: 2).
    temperature:
        LLM temperature (default: 0.0 for deterministic output).
        Only applies to SDK-backed adapters (``model`` param), not
        to a raw ``llm_fn``.
    system_prompt:
        Override the default system prompt entirely.
    """

    def __init__(
        self,
        *,
        llm_fn: Optional[Callable[[str], str]] = None,
        async_llm_fn: Optional[Callable[[str], Awaitable[str]]] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        schema: Any = None,
        db: Any = None,
        max_repair_retries: int = 2,
        temperature: float = 0.0,
        system_prompt: Optional[str] = None,
        tpm_limit: Optional[int] = None,
        max_concurrency: int = 5,
    ) -> None:
        if llm_fn is None and model is None:
            raise ValueError("Provide either 'llm_fn' or 'model'.")

        if llm_fn is not None:
            self._llm_fn = llm_fn
        else:
            self._llm_fn = _build_openai_fn(
                model=model,  # type: ignore[arg-type]
                base_url=base_url,
                api_key=api_key,
                temperature=temperature,
            )

        self.schema = schema
        self.db = db
        self.max_repair_retries = max_repair_retries
        self.temperature = temperature
        self._system_prompt_override = system_prompt
        self._owns_db = False

        # Async support
        self._async_llm_fn = async_llm_fn
        self._rate_limiter = (
            TokenBucketRateLimiter(tpm_limit) if tpm_limit else None
        )
        self._max_concurrency = max_concurrency

        # Cache for DB-discovered or LLM-inferred schema
        self._discovered_schema: Any = None

    # ------------------------------------------------------------------
    # Factory class methods
    # ------------------------------------------------------------------

    @classmethod
    def from_openai(
        cls,
        model: str = "gpt-4o",
        *,
        api_key: Optional[str] = None,
        schema: Any = None,
        db: Any = None,
        max_repair_retries: int = 2,
        temperature: float = 0.0,
        system_prompt: Optional[str] = None,
    ) -> "LLMNLToCypher":
        """Create a pipeline using an OpenAI model."""
        return cls(
            model=model,
            api_key=api_key,
            schema=schema,
            db=db,
            max_repair_retries=max_repair_retries,
            temperature=temperature,
            system_prompt=system_prompt,
        )

    @classmethod
    def from_deepseek(
        cls,
        model: str = "deepseek-chat",
        *,
        api_key: Optional[str] = None,
        base_url: str = "https://api.deepseek.com",
        schema: Any = None,
        db: Any = None,
        max_repair_retries: int = 2,
        temperature: float = 0.0,
        system_prompt: Optional[str] = None,
    ) -> "LLMNLToCypher":
        """Create a pipeline using a DeepSeek model."""
        return cls(
            model=model,
            base_url=base_url,
            api_key=api_key,
            schema=schema,
            db=db,
            max_repair_retries=max_repair_retries,
            temperature=temperature,
            system_prompt=system_prompt,
        )

    @classmethod
    def from_anthropic(
        cls,
        model: str = "claude-sonnet-4-20250514",
        *,
        api_key: Optional[str] = None,
        schema: Any = None,
        db: Any = None,
        max_repair_retries: int = 2,
        temperature: float = 0.0,
        system_prompt: Optional[str] = None,
    ) -> "LLMNLToCypher":
        """Create a pipeline using an Anthropic Claude model.

        Requires the ``anthropic`` package.
        """
        fn = _build_anthropic_fn(
            model=model,
            api_key=api_key,
            temperature=temperature,
        )
        return cls(
            llm_fn=fn,
            schema=schema,
            db=db,
            max_repair_retries=max_repair_retries,
            temperature=temperature,
            system_prompt=system_prompt,
        )

    @classmethod
    def from_langchain(
        cls,
        chat_model: Any,
        *,
        schema: Any = None,
        db: Any = None,
        max_repair_retries: int = 2,
        system_prompt: Optional[str] = None,
    ) -> "LLMNLToCypher":
        """Create a pipeline from a LangChain ``BaseChatModel``.

        This accepts any LangChain chat model (``ChatOpenAI``,
        ``ChatAnthropic``, ``ChatOllama``, etc.) and wraps it as the
        LLM backend.  Temperature and other model params should be
        configured on the *chat_model* instance itself.

        Requires the ``langchain-core`` package.

        Parameters
        ----------
        chat_model:
            A LangChain ``BaseChatModel`` instance.  Must support
            ``.invoke()`` with a list of messages.

        Examples
        --------
        ::

            from langchain_openai import ChatOpenAI
            from cypher_validator import LLMNLToCypher, Schema

            llm = ChatOpenAI(model="gpt-4o", temperature=0)
            pipe = LLMNLToCypher.from_langchain(llm, schema=schema)
            cypher = pipe("John works for Apple.", mode="create")
        """
        fn = _build_langchain_fn(chat_model)
        return cls(
            llm_fn=fn,
            schema=schema,
            db=db,
            max_repair_retries=max_repair_retries,
            system_prompt=system_prompt,
        )

    @classmethod
    def from_env(
        cls,
        model: Optional[str] = None,
        *,
        schema: Any = None,
        database: str = "neo4j",
        max_repair_retries: int = 2,
        temperature: float = 0.0,
        system_prompt: Optional[str] = None,
    ) -> "LLMNLToCypher":
        """Create a pipeline from environment variables.

        Reads:
        - ``ANTHROPIC_API_KEY``, ``DEEPSEEK_API_KEY``, or
          ``OPENAI_API_KEY`` for the LLM (checked in that order)
        - ``NEO4J_URI``, ``NEO4J_USERNAME`` (default ``"neo4j"``),
          ``NEO4J_PASSWORD`` for the database (optional)

        Parameters
        ----------
        model:
            Model identifier.  When ``None``, defaults to
            ``"claude-sonnet-4-20250514"`` / ``"deepseek-chat"`` /
            ``"gpt-4o"`` depending on which API key is found.
        """
        # Resolve LLM credentials
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
        deepseek_key = os.environ.get("DEEPSEEK_API_KEY")
        openai_key = os.environ.get("OPENAI_API_KEY")

        llm_fn: Optional[Callable[[str], str]] = None
        resolved_model: Optional[str] = None
        base_url: Optional[str] = None
        api_key: Optional[str] = None

        if anthropic_key:
            fn = _build_anthropic_fn(
                model=model or "claude-sonnet-4-20250514",
                api_key=anthropic_key,
                temperature=temperature,
            )
            llm_fn = fn
        elif deepseek_key:
            resolved_model = model or "deepseek-chat"
            base_url = "https://api.deepseek.com"
            api_key = deepseek_key
        elif openai_key:
            resolved_model = model or "gpt-4o"
            api_key = openai_key
        else:
            raise KeyError(
                "Set ANTHROPIC_API_KEY, DEEPSEEK_API_KEY, or "
                "OPENAI_API_KEY in the environment."
            )

        # Optionally connect to Neo4j
        db = None
        neo4j_uri = os.environ.get("NEO4J_URI")
        neo4j_password = os.environ.get("NEO4J_PASSWORD")
        if neo4j_uri and neo4j_password:
            from cypher_validator import Neo4jDatabase

            neo4j_user = os.environ.get("NEO4J_USERNAME", "neo4j")
            db = Neo4jDatabase(
                neo4j_uri, neo4j_user, neo4j_password, database=database
            )

        if llm_fn is not None:
            inst = cls(
                llm_fn=llm_fn,
                schema=schema,
                db=db,
                max_repair_retries=max_repair_retries,
                temperature=temperature,
                system_prompt=system_prompt,
            )
        else:
            inst = cls(
                model=resolved_model,
                base_url=base_url,
                api_key=api_key,
                schema=schema,
                db=db,
                max_repair_retries=max_repair_retries,
                temperature=temperature,
                system_prompt=system_prompt,
            )

        if db is not None:
            inst._owns_db = True
        return inst

    # ------------------------------------------------------------------
    # Context manager (closes DB connections created by from_env)
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the DB connection if this instance owns it.

        Only connections created internally (e.g. by :meth:`from_env`)
        are closed.  User-supplied ``db`` instances are left open.
        """
        if self._owns_db and self.db is not None:
            try:
                self.db.close()
            except Exception:  # noqa: BLE001
                pass

    def __enter__(self) -> "LLMNLToCypher":
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()

    async def __aenter__(self) -> "LLMNLToCypher":
        return self

    async def __aexit__(self, *_args: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Schema resolution
    # ------------------------------------------------------------------

    def _resolve_schema(self) -> Any:
        """Return the best available schema (user > DB > cached inferred)."""
        if self.schema is not None:
            return self.schema

        if self._discovered_schema is not None:
            return self._discovered_schema

        # Try DB introspection
        if self.db is not None:
            try:
                discovered = self.db.introspect_schema()
                # Only cache if non-empty
                if discovered.node_labels():
                    self._discovered_schema = discovered
                    return discovered
            except Exception:  # noqa: BLE001
                pass

        return None

    def reset_discovered_schema(self) -> None:
        """Clear the cached DB-discovered / LLM-inferred schema.

        After calling this, the next invocation will re-discover the
        schema from the DB or ask the LLM to infer it again.
        """
        self._discovered_schema = None

    # ------------------------------------------------------------------
    # Prompt building
    # ------------------------------------------------------------------

    def _build_prompt(self, text: str, mode: str) -> Tuple[str, str]:
        """Build system and user messages for the LLM.

        Returns ``(system_message, user_message)``.
        """
        schema = self._resolve_schema()

        if self._system_prompt_override:
            system = self._system_prompt_override
        elif schema is not None:
            system = _SYSTEM_PROMPT_SCHEMA_KNOWN.format(
                schema_context=schema.to_cypher_context()
            )
        else:
            system = _SYSTEM_PROMPT_SCHEMA_UNKNOWN

        mode_instruction = {
            "create": "Generate a CREATE query to insert the entities and relationships.",
            "merge": "Generate a MERGE query to upsert the entities and relationships.",
            "match": "Generate a MATCH query to retrieve the described information.",
        }.get(mode, f"Generate a {mode.upper()} Cypher query.")

        user_msg = f"{mode_instruction}\n\nText: {text}"
        return system, user_msg

    # ------------------------------------------------------------------
    # Schema inference from LLM response
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_inferred_schema(
        response: str,
    ) -> Tuple[Optional[Dict[str, Any]], str]:
        """Extract inferred schema JSON and Cypher from a Mode B response.

        Returns ``(schema_dict_or_None, cypher_string)``.
        """
        schema_dict: Optional[Dict[str, Any]] = None

        # Try to find JSON block
        json_match = _RE_JSON_BLOCK.search(response)
        if json_match:
            try:
                parsed = json.loads(json_match.group(1))
                if "inferred_schema" in parsed:
                    schema_dict = parsed["inferred_schema"]
                else:
                    schema_dict = parsed
            except (json.JSONDecodeError, KeyError):
                pass

        # Extract the cypher block specifically — extract_cypher_from_text
        # can be confused by multiple fenced blocks, so look for the
        # ```cypher block explicitly first.
        cypher_match = _RE_CYPHER_BLOCK.search(response)
        if cypher_match:
            cypher = cypher_match.group(1).strip()
        else:
            # Fallback: strip out any json block and then extract
            stripped = response
            if json_match:
                stripped = response[:json_match.start()] + response[json_match.end():]
            cypher = extract_cypher_from_text(stripped)

        return schema_dict, cypher

    @staticmethod
    def _schema_dict_to_schema(d: Dict[str, Any]) -> Any:
        """Convert an inferred schema dict to a Schema object."""
        from cypher_validator import Schema

        nodes = {}
        relationships = {}

        raw_nodes = d.get("nodes", {})
        for label, props in raw_nodes.items():
            if isinstance(props, list):
                nodes[label] = props
            else:
                nodes[label] = []

        raw_rels = d.get("relationships", {})
        for rel_type, spec in raw_rels.items():
            if isinstance(spec, (list, tuple)) and len(spec) >= 2:
                src = str(spec[0])
                tgt = str(spec[1])
                props = list(spec[2]) if len(spec) > 2 and isinstance(spec[2], (list, tuple)) else []
                relationships[rel_type] = (src, tgt, props)
            else:
                # Fallback: no endpoint info
                relationships[rel_type] = ("_Unknown", "_Unknown", [])

        return Schema(nodes=nodes, relationships=relationships)

    def _merge_inferred_schema(self, schema_dict: Dict[str, Any]) -> None:
        """Merge an LLM-inferred schema into the cached discovered schema."""
        new_schema = self._schema_dict_to_schema(schema_dict)
        if self._discovered_schema is not None:
            self._discovered_schema = self._discovered_schema.merge(new_schema)
        else:
            self._discovered_schema = new_schema

    # ------------------------------------------------------------------
    # Validation + repair
    # ------------------------------------------------------------------

    def _validate_and_repair(
        self, cypher: str, schema: Any
    ) -> Tuple[str, bool, List[str], int]:
        """Validate and optionally repair the Cypher query.

        Returns ``(final_cypher, is_valid, errors, repair_attempts)``.
        """
        from cypher_validator import CypherValidator

        if schema is None:
            # No schema available — skip semantic validation entirely.
            # We still do a syntax-level parse check.
            from cypher_validator import parse_query
            info = parse_query(cypher)
            return cypher, info.is_valid, list(info.errors), 0

        validator = CypherValidator(schema)
        result = validator.validate(cypher)
        repair_attempts = 0

        schema_context = schema.to_cypher_context()

        while not result.is_valid and repair_attempts < self.max_repair_retries:
            # Try auto-fix first
            if result.fixed_query is not None:
                cypher = result.fixed_query
                result = validator.validate(cypher)
                if result.is_valid:
                    break

            error_list = "\n".join(f"  - {e}" for e in result.errors)
            repair_prompt = _REPAIR_PROMPT_WITH_SCHEMA.format(
                schema_context=schema_context,
                cypher=cypher,
                error_list=error_list,
            )
            raw = self._llm_fn(repair_prompt)
            cypher = extract_cypher_from_text(raw)
            result = validator.validate(cypher)
            repair_attempts += 1

        return cypher, result.is_valid, list(result.errors), repair_attempts

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def __call__(
        self,
        text: str,
        mode: str = "create",
        execute: bool = False,
    ) -> Union[str, Tuple[str, List[Dict[str, Any]]]]:
        """Generate Cypher from natural language text.

        Parameters
        ----------
        text:
            Natural language passage describing entities/relationships.
        mode:
            ``"create"``, ``"merge"``, or ``"match"``.
        execute:
            When ``True``, execute the query and return
            ``(cypher, records)``.  Requires ``db`` to be set.

        Returns
        -------
        str
            Cypher query when ``execute=False``.
        tuple[str, list[dict]]
            ``(cypher, records)`` when ``execute=True``.
        """
        ctx = self.ingest_with_context(text, mode=mode, execute=execute)
        if execute:
            return ctx["cypher"], ctx["records"]
        return ctx["cypher"]

    def ingest_with_context(
        self,
        text: str,
        mode: str = "create",
        execute: bool = False,
    ) -> Dict[str, Any]:
        """Generate Cypher and return all intermediate artefacts.

        Returns
        -------
        dict
            Keys: ``schema_source``, ``inferred_schema``, ``cypher``,
            ``is_valid``, ``validation_errors``, ``repair_attempts``,
            ``records``, ``execution_error``.
        """
        schema = self._resolve_schema()
        schema_source = (
            "user" if self.schema is not None
            else "db" if schema is not None
            else "inferred"
        )

        # Build prompt and call LLM
        system_msg, user_msg = self._build_prompt(text, mode)
        prompt = f"{system_msg}\n\n{user_msg}"
        raw_response = self._llm_fn(prompt)

        # Parse response
        inferred_schema: Optional[Dict[str, Any]] = None
        if schema is None:
            # Mode B: expect JSON schema + Cypher
            inferred_schema, cypher = self._parse_inferred_schema(raw_response)
            if inferred_schema:
                self._merge_inferred_schema(inferred_schema)
                schema = self._discovered_schema
        else:
            cypher = extract_cypher_from_text(raw_response)

        # Validate + repair
        cypher, is_valid, errors, repair_attempts = self._validate_and_repair(
            cypher, schema
        )

        # Execute if requested
        records: List[Dict[str, Any]] = []
        execution_error: Optional[str] = None
        if execute:
            if self.db is None:
                raise RuntimeError(
                    "Cannot execute: no 'db' was provided to LLMNLToCypher."
                )
            try:
                records = self.db.execute(cypher)
            except Exception as exc:  # noqa: BLE001
                execution_error = str(exc)

        return {
            "schema_source": schema_source,
            "inferred_schema": inferred_schema,
            "cypher": cypher,
            "is_valid": is_valid,
            "validation_errors": errors,
            "repair_attempts": repair_attempts,
            "records": records,
            "execution_error": execution_error,
        }

    # ------------------------------------------------------------------
    # Batch ingestion
    # ------------------------------------------------------------------

    @staticmethod
    def _chunk_text(
        text: str,
        chunk_size: int = 2000,
        chunk_overlap: int = 200,
    ) -> List[str]:
        """Split *text* into chunks respecting sentence boundaries.

        1. Split on sentence-ending punctuation followed by whitespace.
        2. Greedily accumulate sentences until *chunk_size* is exceeded.
        3. Start the next chunk rewinding *chunk_overlap* chars of sentences.
        4. A single sentence longer than *chunk_size* becomes its own chunk.
        """
        sentences = _RE_SENTENCE_BOUNDARY.split(text.strip())
        if not sentences or (len(sentences) == 1 and not sentences[0]):
            return [text.strip()] if text.strip() else []

        chunks: List[str] = []
        current_sentences: List[str] = []
        current_len = 0

        for sentence in sentences:
            sentence_len = len(sentence)
            # Would adding this sentence exceed chunk_size?
            added_len = sentence_len + (1 if current_sentences else 0)
            if current_sentences and current_len + added_len > chunk_size:
                # Flush current chunk
                chunks.append(" ".join(current_sentences))
                # Rewind for overlap
                overlap_sentences: List[str] = []
                overlap_len = 0
                for s in reversed(current_sentences):
                    if overlap_len + len(s) + (1 if overlap_sentences else 0) > chunk_overlap:
                        break
                    overlap_sentences.insert(0, s)
                    overlap_len += len(s) + (1 if len(overlap_sentences) > 1 else 0)
                current_sentences = overlap_sentences
                current_len = sum(len(s) for s in current_sentences) + max(0, len(current_sentences) - 1)

            current_sentences.append(sentence)
            current_len += sentence_len + (1 if len(current_sentences) > 1 else 0)

        if current_sentences:
            chunks.append(" ".join(current_sentences))

        return chunks

    @staticmethod
    def _build_provenance_cypher(
        domain_cypher: str,
        chunk_id: str,
        source_id: str,
        text_preview: str,
    ) -> Tuple[str, Dict[str, Any]]:
        """Build deterministic provenance Cypher from parsed domain labels.

        Uses ``parse_query()`` to extract node labels from *domain_cypher*,
        then produces a MERGE for a ``Chunk`` node and ``MENTIONED_IN``
        relationships linking domain nodes to the chunk.

        Returns ``(cypher_str, params_dict)``.
        """
        from cypher_validator import parse_query

        info = parse_query(domain_cypher)
        domain_labels = [lbl for lbl in info.labels_used if lbl != "Chunk"]

        params = {
            "chunk_id": chunk_id,
            "source_id": source_id,
            "text_preview": text_preview,
            "domain_labels": domain_labels,
        }

        cypher = (
            "MERGE (chunk:Chunk {chunk_id: $chunk_id})\n"
            "ON CREATE SET chunk.source_id = $source_id,\n"
            "              chunk.text_preview = $text_preview,\n"
            "              chunk.ingested_at = datetime()\n"
            "WITH chunk\n"
            "MATCH (n)\n"
            "WHERE any(label IN labels(n) WHERE label IN $domain_labels)\n"
            "AND n.name IS NOT NULL\n"
            "MERGE (n)-[:MENTIONED_IN]->(chunk)"
        )

        return cypher, params

    def _finish_chunk(
        self,
        index: int,
        source_id: str,
        text: str,
        cypher: str,
        is_valid: bool,
        validation_errors: List[str],
        repair_attempts: int,
        *,
        provenance: bool,
        execute: bool,
        on_error: str,
    ) -> ChunkResult:
        """Build provenance, optionally execute, and return a ChunkResult.

        Shared by Phase 1 and Phase 2 of :meth:`ingest_texts`.
        """
        text_preview = text[:80]

        # Provenance
        prov_cypher = ""
        prov_params: Optional[Dict[str, Any]] = None
        if provenance:
            chunk_id = f"{source_id}_chunk_0"
            prov_cypher, prov_params = self._build_provenance_cypher(
                cypher, chunk_id, source_id, text_preview,
            )

        # Execute
        executed = False
        execution_error: Optional[str] = None
        records: List[Dict[str, Any]] = []
        if execute:
            if self.db is None:
                raise RuntimeError(
                    "Cannot execute: no 'db' was provided."
                )
            try:
                records = self.db.execute(cypher)
                if prov_params is not None:
                    self.db.execute(prov_cypher, prov_params)
                executed = True
            except Exception as exc:
                execution_error = str(exc)
                if on_error == "raise":
                    raise

        return ChunkResult(
            index=index,
            source_id=source_id,
            text_preview=text_preview,
            cypher=cypher,
            provenance_cypher=prov_cypher,
            is_valid=is_valid,
            validation_errors=validation_errors,
            repair_attempts=repair_attempts,
            executed=executed,
            execution_error=execution_error,
            records=records,
        )

    def ingest_texts(
        self,
        texts: List[str],
        *,
        source_ids: Optional[List[str]] = None,
        execute: bool = False,
        schema_sample_size: int = 3,
        provenance: bool = True,
        on_error: str = "skip",
        progress_fn: Optional[Callable[[int, int], None]] = None,
    ) -> IngestionResult:
        """Batch-ingest texts into a knowledge graph.

        Parameters
        ----------
        texts:
            List of natural language passages.
        source_ids:
            Optional per-text identifiers.  Defaults to ``"text_0"``, etc.
        execute:
            Execute generated Cypher against ``self.db``.
        schema_sample_size:
            Number of texts to use for schema inference when no schema is
            available (Phase 1).
        provenance:
            Generate deterministic ``Chunk`` / ``MENTIONED_IN`` Cypher.
        on_error:
            ``"skip"`` (default) or ``"raise"``.
        progress_fn:
            Optional callback ``(current_index, total)`` called after each text.

        Returns
        -------
        IngestionResult
        """
        if on_error not in ("skip", "raise"):
            raise ValueError(
                f"on_error must be 'skip' or 'raise', got {on_error!r}"
            )

        if not texts:
            schema = self._resolve_schema()
            schema_source = (
                "user" if self.schema is not None
                else "db" if schema is not None
                else "inferred"
            )
            return IngestionResult(
                schema=schema,
                schema_source=schema_source,
            )

        if source_ids is None:
            source_ids = [f"text_{i}" for i in range(len(texts))]
        if len(source_ids) != len(texts):
            raise ValueError(
                f"source_ids length ({len(source_ids)}) != texts length ({len(texts)})"
            )

        total = len(texts)
        results: List[ChunkResult] = []
        errors: List[Tuple[int, str]] = []

        # Determine initial schema state
        schema = self._resolve_schema()
        schema_source = (
            "user" if self.schema is not None
            else "db" if schema is not None
            else "inferred"
        )

        # Phase 1: Schema stabilization (only when no schema available)
        phase1_count = 0
        if schema is None:
            sample_count = min(schema_sample_size, total)
            for i in range(sample_count):
                phase1_count += 1
                try:
                    ctx = self.ingest_with_context(
                        texts[i], mode="create", execute=False
                    )
                    result = self._finish_chunk(
                        i, source_ids[i], texts[i],
                        ctx["cypher"], ctx["is_valid"],
                        ctx["validation_errors"], ctx["repair_attempts"],
                        provenance=provenance, execute=execute,
                        on_error=on_error,
                    )
                    results.append(result)
                except Exception as exc:
                    if on_error == "raise":
                        raise
                    errors.append((i, str(exc)))
                    results.append(ChunkResult(
                        index=i,
                        source_id=source_ids[i],
                        text_preview=texts[i][:80],
                        cypher="",
                        provenance_cypher="",
                        is_valid=False,
                        validation_errors=[str(exc)],
                    ))

                if progress_fn is not None:
                    progress_fn(i + 1, total)

            # After Phase 1, we should have a discovered schema
            schema = self._resolve_schema()

        # Phase 2: Ingest remaining texts with stable schema
        for i in range(phase1_count, total):
            try:
                # Build MERGE prompt with stable schema
                if schema is not None:
                    system_msg = _SYSTEM_PROMPT_INGEST.format(
                        schema_context=schema.to_cypher_context()
                    )
                else:
                    system_msg = _SYSTEM_PROMPT_SCHEMA_UNKNOWN

                user_msg = (
                    "Generate a MERGE query to upsert the entities "
                    "and relationships.\n\nText: " + texts[i]
                )
                prompt = f"{system_msg}\n\n{user_msg}"
                raw_response = self._llm_fn(prompt)
                cypher = extract_cypher_from_text(raw_response)

                # Validate + repair
                cypher, is_valid, validation_errors, repair_attempts = (
                    self._validate_and_repair(cypher, schema)
                )

                result = self._finish_chunk(
                    i, source_ids[i], texts[i],
                    cypher, is_valid, validation_errors, repair_attempts,
                    provenance=provenance, execute=execute,
                    on_error=on_error,
                )
                results.append(result)
            except Exception as exc:
                if on_error == "raise":
                    raise
                errors.append((i, str(exc)))
                results.append(ChunkResult(
                    index=i,
                    source_id=source_ids[i],
                    text_preview=texts[i][:80],
                    cypher="",
                    provenance_cypher="",
                    is_valid=False,
                    validation_errors=[str(exc)],
                ))

            if progress_fn is not None:
                progress_fn(i + 1, total)

        succeeded = sum(1 for r in results if r.is_valid)
        failed = sum(1 for r in results if not r.is_valid)

        return IngestionResult(
            schema=self._resolve_schema(),
            schema_source=schema_source,
            results=results,
            total=total,
            succeeded=succeeded,
            failed=failed,
            schema_sample_texts=phase1_count,
            errors=errors,
        )

    def ingest_document(
        self,
        text: str,
        *,
        source_id: str = "doc",
        chunk_size: int = 2000,
        chunk_overlap: int = 200,
        execute: bool = False,
        schema_sample_size: int = 3,
        provenance: bool = True,
        on_error: str = "skip",
        progress_fn: Optional[Callable[[int, int], None]] = None,
    ) -> IngestionResult:
        """Chunk a document and ingest all chunks.

        Convenience wrapper: splits *text* into chunks via
        :meth:`_chunk_text`, generates ``source_ids`` as
        ``"{source_id}_chunk_{i}"``, and delegates to :meth:`ingest_texts`.
        """
        chunks = self._chunk_text(text, chunk_size, chunk_overlap)
        chunk_source_ids = [f"{source_id}_chunk_{i}" for i in range(len(chunks))]
        return self.ingest_texts(
            chunks,
            source_ids=chunk_source_ids,
            execute=execute,
            schema_sample_size=schema_sample_size,
            provenance=provenance,
            on_error=on_error,
            progress_fn=progress_fn,
        )

    def __repr__(self) -> str:
        schema_info = "schema" if self.schema else "no schema"
        db_info = "db" if self.db else "no db"
        return f"LLMNLToCypher({schema_info}, {db_info})"

    # ------------------------------------------------------------------
    # Async helpers
    # ------------------------------------------------------------------

    def _get_async_llm_fn(self) -> Callable[[str], Awaitable[str]]:
        """Return the async LLM callable.

        Uses ``self._async_llm_fn`` if set, otherwise wraps the sync
        ``self._llm_fn`` via ``asyncio.to_thread``.
        """
        if self._async_llm_fn is not None:
            return self._async_llm_fn

        sync_fn = self._llm_fn

        async def _wrapped(prompt: str) -> str:
            return await asyncio.to_thread(sync_fn, prompt)

        return _wrapped

    async def _async_llm_call(self, prompt: str) -> str:
        """Call the async LLM, applying rate limiting if configured."""
        if self._rate_limiter is not None:
            tokens = TokenBucketRateLimiter.estimate_tokens(prompt)
            await self._rate_limiter.acquire(tokens)
        fn = self._get_async_llm_fn()
        return await fn(prompt)

    # ------------------------------------------------------------------
    # Async validation + repair
    # ------------------------------------------------------------------

    async def _avalidate_and_repair(
        self, cypher: str, schema: Any
    ) -> Tuple[str, bool, List[str], int]:
        """Async version of :meth:`_validate_and_repair`."""
        from cypher_validator import CypherValidator

        if schema is None:
            from cypher_validator import parse_query
            info = parse_query(cypher)
            return cypher, info.is_valid, list(info.errors), 0

        validator = CypherValidator(schema)
        result = validator.validate(cypher)
        repair_attempts = 0

        schema_context = schema.to_cypher_context()

        while not result.is_valid and repair_attempts < self.max_repair_retries:
            if result.fixed_query is not None:
                cypher = result.fixed_query
                result = validator.validate(cypher)
                if result.is_valid:
                    break

            error_list = "\n".join(f"  - {e}" for e in result.errors)
            repair_prompt = _REPAIR_PROMPT_WITH_SCHEMA.format(
                schema_context=schema_context,
                cypher=cypher,
                error_list=error_list,
            )
            raw = await self._async_llm_call(repair_prompt)
            cypher = extract_cypher_from_text(raw)
            result = validator.validate(cypher)
            repair_attempts += 1

        return cypher, result.is_valid, list(result.errors), repair_attempts

    # ------------------------------------------------------------------
    # Async public API
    # ------------------------------------------------------------------

    async def acall(
        self,
        text: str,
        mode: str = "create",
        execute: bool = False,
    ) -> Union[str, Tuple[str, List[Dict[str, Any]]]]:
        """Async version of :meth:`__call__`."""
        ctx = await self.aingest_with_context(text, mode=mode, execute=execute)
        if execute:
            return ctx["cypher"], ctx["records"]
        return ctx["cypher"]

    async def aingest_with_context(
        self,
        text: str,
        mode: str = "create",
        execute: bool = False,
    ) -> Dict[str, Any]:
        """Async version of :meth:`ingest_with_context`."""
        schema = self._resolve_schema()
        schema_source = (
            "user" if self.schema is not None
            else "db" if schema is not None
            else "inferred"
        )

        system_msg, user_msg = self._build_prompt(text, mode)
        prompt = f"{system_msg}\n\n{user_msg}"
        raw_response = await self._async_llm_call(prompt)

        inferred_schema: Optional[Dict[str, Any]] = None
        if schema is None:
            inferred_schema, cypher = self._parse_inferred_schema(raw_response)
            if inferred_schema:
                self._merge_inferred_schema(inferred_schema)
                schema = self._discovered_schema
        else:
            cypher = extract_cypher_from_text(raw_response)

        cypher, is_valid, errors, repair_attempts = (
            await self._avalidate_and_repair(cypher, schema)
        )

        records: List[Dict[str, Any]] = []
        execution_error: Optional[str] = None
        if execute:
            if self.db is None:
                raise RuntimeError(
                    "Cannot execute: no 'db' was provided to LLMNLToCypher."
                )
            try:
                records = self.db.execute(cypher)
            except Exception as exc:  # noqa: BLE001
                execution_error = str(exc)

        return {
            "schema_source": schema_source,
            "inferred_schema": inferred_schema,
            "cypher": cypher,
            "is_valid": is_valid,
            "validation_errors": errors,
            "repair_attempts": repair_attempts,
            "records": records,
            "execution_error": execution_error,
        }

    async def aingest_texts(
        self,
        texts: List[str],
        *,
        source_ids: Optional[List[str]] = None,
        execute: bool = False,
        schema_sample_size: int = 3,
        provenance: bool = True,
        on_error: str = "skip",
        progress_fn: Optional[Callable[[int, int], None]] = None,
        max_concurrency: Optional[int] = None,
    ) -> IngestionResult:
        """Async version of :meth:`ingest_texts` with parallel Phase 2.

        Phase 1 (schema inference) runs sequentially.
        Phase 2 runs up to *max_concurrency* LLM calls concurrently.
        """
        if on_error not in ("skip", "raise"):
            raise ValueError(
                f"on_error must be 'skip' or 'raise', got {on_error!r}"
            )

        if not texts:
            schema = self._resolve_schema()
            schema_source = (
                "user" if self.schema is not None
                else "db" if schema is not None
                else "inferred"
            )
            return IngestionResult(
                schema=schema,
                schema_source=schema_source,
            )

        if source_ids is None:
            source_ids = [f"text_{i}" for i in range(len(texts))]
        if len(source_ids) != len(texts):
            raise ValueError(
                f"source_ids length ({len(source_ids)}) != texts length ({len(texts)})"
            )

        concurrency = max_concurrency or self._max_concurrency
        total = len(texts)
        results: List[Optional[ChunkResult]] = [None] * total
        errors: List[Tuple[int, str]] = []

        schema = self._resolve_schema()
        schema_source = (
            "user" if self.schema is not None
            else "db" if schema is not None
            else "inferred"
        )

        # Phase 1: sequential schema stabilization
        phase1_count = 0
        if schema is None:
            sample_count = min(schema_sample_size, total)
            for i in range(sample_count):
                phase1_count += 1
                try:
                    ctx = await self.aingest_with_context(
                        texts[i], mode="create", execute=False
                    )
                    result = self._finish_chunk(
                        i, source_ids[i], texts[i],
                        ctx["cypher"], ctx["is_valid"],
                        ctx["validation_errors"], ctx["repair_attempts"],
                        provenance=provenance, execute=execute,
                        on_error=on_error,
                    )
                    results[i] = result
                except Exception as exc:
                    if on_error == "raise":
                        raise
                    errors.append((i, str(exc)))
                    results[i] = ChunkResult(
                        index=i,
                        source_id=source_ids[i],
                        text_preview=texts[i][:80],
                        cypher="",
                        provenance_cypher="",
                        is_valid=False,
                        validation_errors=[str(exc)],
                    )

                if progress_fn is not None:
                    progress_fn(i + 1, total)

            schema = self._resolve_schema()

        # Phase 2: parallel ingestion with semaphore
        sem = asyncio.Semaphore(concurrency)

        async def _process_text(i: int) -> None:
            async with sem:
                try:
                    if schema is not None:
                        system_msg = _SYSTEM_PROMPT_INGEST.format(
                            schema_context=schema.to_cypher_context()
                        )
                    else:
                        system_msg = _SYSTEM_PROMPT_SCHEMA_UNKNOWN

                    user_msg = (
                        "Generate a MERGE query to upsert the entities "
                        "and relationships.\n\nText: " + texts[i]
                    )
                    prompt = f"{system_msg}\n\n{user_msg}"
                    raw_response = await self._async_llm_call(prompt)
                    cypher = extract_cypher_from_text(raw_response)

                    cypher, is_valid, validation_errors, repair_attempts = (
                        await self._avalidate_and_repair(cypher, schema)
                    )

                    result = self._finish_chunk(
                        i, source_ids[i], texts[i],
                        cypher, is_valid, validation_errors, repair_attempts,
                        provenance=provenance, execute=execute,
                        on_error=on_error,
                    )
                    results[i] = result
                except Exception as exc:
                    if on_error == "raise":
                        raise
                    errors.append((i, str(exc)))
                    results[i] = ChunkResult(
                        index=i,
                        source_id=source_ids[i],
                        text_preview=texts[i][:80],
                        cypher="",
                        provenance_cypher="",
                        is_valid=False,
                        validation_errors=[str(exc)],
                    )

                if progress_fn is not None:
                    progress_fn(i + 1, total)

        phase2_indices = list(range(phase1_count, total))
        await asyncio.gather(*[_process_text(i) for i in phase2_indices])

        final_results = [r for r in results if r is not None]
        succeeded = sum(1 for r in final_results if r.is_valid)
        failed = sum(1 for r in final_results if not r.is_valid)

        return IngestionResult(
            schema=self._resolve_schema(),
            schema_source=schema_source,
            results=final_results,
            total=total,
            succeeded=succeeded,
            failed=failed,
            schema_sample_texts=phase1_count,
            errors=errors,
        )

    async def aingest_document(
        self,
        text: str,
        *,
        source_id: str = "doc",
        chunk_size: int = 2000,
        chunk_overlap: int = 200,
        execute: bool = False,
        schema_sample_size: int = 3,
        provenance: bool = True,
        on_error: str = "skip",
        progress_fn: Optional[Callable[[int, int], None]] = None,
        max_concurrency: Optional[int] = None,
    ) -> IngestionResult:
        """Async version of :meth:`ingest_document`."""
        chunks = self._chunk_text(text, chunk_size, chunk_overlap)
        chunk_source_ids = [f"{source_id}_chunk_{i}" for i in range(len(chunks))]
        return await self.aingest_texts(
            chunks,
            source_ids=chunk_source_ids,
            execute=execute,
            schema_sample_size=schema_sample_size,
            provenance=provenance,
            on_error=on_error,
            progress_fn=progress_fn,
            max_concurrency=max_concurrency,
        )


# ---------------------------------------------------------------------------
# OpenAI SDK adapter (#1 — proper system/user message separation)
# ---------------------------------------------------------------------------

def _build_openai_fn(
    model: str,
    base_url: Optional[str],
    api_key: Optional[str],
    temperature: float,
) -> Callable[[str], str]:
    """Build a ``(prompt) -> str`` callable backed by the OpenAI SDK.

    The prompt is split on the first double-newline into a ``system``
    message and a ``user`` message.  If no split point is found, the
    entire prompt is sent as a ``user`` message.
    """
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise ImportError(
            "The 'openai' package is required for LLMNLToCypher with "
            "model-based backends.  Install it with: pip install openai"
        ) from exc

    kwargs: Dict[str, Any] = {}
    if base_url is not None:
        kwargs["base_url"] = base_url
    if api_key is not None:
        kwargs["api_key"] = api_key

    client = OpenAI(**kwargs)

    def call_llm(prompt: str) -> str:
        messages = _split_prompt_to_messages(prompt)
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
        )
        return response.choices[0].message.content or ""

    return call_llm


# ---------------------------------------------------------------------------
# Anthropic SDK adapter (#4 — from_anthropic factory)
# ---------------------------------------------------------------------------

def _build_anthropic_fn(
    model: str,
    api_key: Optional[str],
    temperature: float,
) -> Callable[[str], str]:
    """Build a ``(prompt) -> str`` callable backed by the Anthropic SDK."""
    try:
        import anthropic
    except ImportError as exc:
        raise ImportError(
            "The 'anthropic' package is required for "
            "LLMNLToCypher.from_anthropic().  "
            "Install it with: pip install anthropic"
        ) from exc

    kwargs: Dict[str, Any] = {}
    if api_key is not None:
        kwargs["api_key"] = api_key

    client = anthropic.Anthropic(**kwargs)

    def call_llm(prompt: str) -> str:
        messages = _split_prompt_to_messages(prompt)
        # Separate system from user messages for Anthropic API
        system_text = ""
        user_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_text = msg["content"]
            else:
                user_messages.append(msg)
        if not user_messages:
            user_messages = [{"role": "user", "content": prompt}]

        create_kwargs: Dict[str, Any] = {
            "model": model,
            "max_tokens": 4096,
            "messages": user_messages,
        }
        if system_text:
            create_kwargs["system"] = system_text
        if temperature > 0:
            create_kwargs["temperature"] = temperature

        response = client.messages.create(**create_kwargs)
        return response.content[0].text

    return call_llm


# ---------------------------------------------------------------------------
# Shared prompt-splitting helper
# ---------------------------------------------------------------------------

def _split_prompt_to_messages(
    prompt: str,
) -> List[Dict[str, str]]:
    """Split a combined prompt into system + user messages.

    Looks for a double-newline boundary.  Everything before the *last*
    double-newline paragraph that starts with a mode instruction
    (``Generate a …`` / ``Text: …``) is treated as the system message.
    """
    # Find the split point: the last occurrence of a mode instruction line
    # preceded by a blank line.
    split_idx = None
    for marker in ("\n\nGenerate a ", "\n\nText: "):
        idx = prompt.rfind(marker)
        if idx != -1 and (split_idx is None or idx < split_idx):
            split_idx = idx

    if split_idx is not None and split_idx > 0:
        system = prompt[:split_idx].strip()
        user = prompt[split_idx:].strip()
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    return [{"role": "user", "content": prompt}]


# ---------------------------------------------------------------------------
# LangChain adapter
# ---------------------------------------------------------------------------

def _build_langchain_fn(chat_model: Any) -> Callable[[str], str]:
    """Build a ``(prompt) -> str`` callable from a LangChain ``BaseChatModel``.

    Uses ``SystemMessage`` / ``HumanMessage`` for proper role separation.
    """
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
    except ImportError as exc:
        raise ImportError(
            "The 'langchain-core' package is required for "
            "LLMNLToCypher.from_langchain().  "
            "Install it with: pip install langchain-core"
        ) from exc

    def call_llm(prompt: str) -> str:
        parts = _split_prompt_to_messages(prompt)
        messages = []
        for part in parts:
            if part["role"] == "system":
                messages.append(SystemMessage(content=part["content"]))
            else:
                messages.append(HumanMessage(content=part["content"]))
        result = chat_model.invoke(messages)
        # LangChain returns an AIMessage; .content is the text.
        return result.content if hasattr(result, "content") else str(result)

    return call_llm
