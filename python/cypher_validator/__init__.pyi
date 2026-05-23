"""
Type stubs for the ``cypher_validator`` package.

Re-exports the Rust core and the pure-Python GLiNER2 / Neo4j integration.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple, Union, overload

# Re-export Rust core types
from cypher_validator._cypher_validator import (
    Schema as Schema,  # type: ignore[assignment]
    ValidationResult as ValidationResult,
    ValidationDiagnostic as ValidationDiagnostic,
    CypherValidator as CypherValidator,
    QueryInfo as QueryInfo,
    CypherGenerator as CypherGenerator,  # type: ignore[assignment]
    parse_query as parse_query,
)


# ---------------------------------------------------------------------------
# Batch ingestion dataclasses
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

    schema: Any
    schema_source: str
    results: list[ChunkResult] = field(default_factory=list)
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    schema_sample_texts: int = 0
    errors: list[tuple[int, str]] = field(default_factory=list)

# ---------------------------------------------------------------------------
# Schema (extended stubs for new methods)
# ---------------------------------------------------------------------------

class Schema:
    """Graph schema: node labels with their allowed property sets,
    and relationship types with their (source label, target label, property set).
    """

    def __init__(
        self,
        nodes: Dict[str, List[str]],
        relationships: Dict[str, Tuple[str, str, List[str]]],
    ) -> None: ...

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Schema":
        """Create a Schema from a plain Python dict."""
        ...

    @staticmethod
    def from_neo4j(
        uri: str,
        username: str,
        password: str,
        database: str = "neo4j",
        sample_limit: int = 1000,
    ) -> "Schema":
        """Create a Schema by introspecting a live Neo4j database.

        Convenience wrapper that creates a temporary :class:`Neo4jDatabase`,
        calls :meth:`~Neo4jDatabase.introspect_schema`, closes the connection,
        and returns the resulting :class:`Schema`.
        """
        ...

    @staticmethod
    def from_json(json_str: str) -> "Schema":
        """Deserialise a Schema from a JSON string produced by ``to_json()``."""
        ...

    def node_labels(self) -> List[str]: ...
    def rel_types(self) -> List[str]: ...
    def has_node_label(self, label: str) -> bool: ...
    def has_rel_type(self, rel_type: str) -> bool: ...
    def node_properties(self, label: str) -> List[str]: ...
    def rel_properties(self, rel_type: str) -> List[str]: ...
    def rel_endpoints(self, rel_type: str) -> Optional[Tuple[str, str]]: ...
    def to_dict(self) -> Dict[str, Any]: ...

    def to_json(self) -> str:
        """Serialise the schema to a JSON string (round-trips with ``from_json``)."""
        ...

    def merge(self, other: "Schema") -> "Schema":
        """Return a new Schema that is the union of *self* and *other*.

        Property sets for shared labels/types are merged (union).
        """
        ...

    def to_prompt(self) -> str:
        """Return a human-readable, LLM-friendly text representation of the schema.

        Suitable for injecting into an LLM system prompt so the model knows
        which labels, relationship types, and properties are available.
        """
        ...

    def to_markdown(self) -> str:
        """Return the schema formatted as a Markdown table.

        Useful for documentation, README sections, and LLM contexts that
        render Markdown.
        """
        ...

    def to_cypher_context(self) -> str:
        """Return the schema as inline Cypher node/relationship patterns.

        This mirrors Cypher query syntax (``(:Label {prop})-[:REL]->()``)
        which is the most natural format for LLMs that already know Cypher.
        """
        ...

    def __repr__(self) -> str: ...


# ---------------------------------------------------------------------------
# CypherGenerator (extended stubs)
# ---------------------------------------------------------------------------

class CypherGenerator:
    """Generates random but schema-valid Cypher queries."""

    def __init__(self, schema: Schema, seed: Optional[int] = None) -> None: ...

    def generate(self, query_type: str) -> str:
        """Generate a single random Cypher query of the given type."""
        ...

    def generate_batch(self, query_type: str, n: int) -> List[str]:
        """Generate *n* queries of the given type in a single call.

        Equivalent to calling :meth:`generate` *n* times but avoids per-call
        Python overhead.
        """
        ...

    @staticmethod
    def supported_types() -> List[str]: ...
    def __repr__(self) -> str: ...


# ---------------------------------------------------------------------------
# Neo4jDatabase
# ---------------------------------------------------------------------------

class Neo4jDatabase:
    """Thin wrapper around the Neo4j Python driver for executing Cypher queries.

    Requires the ``neo4j`` package (``pip install neo4j``).

    Can be used as a context manager::

        with Neo4jDatabase("bolt://localhost:7687", "neo4j", "password") as db:
            results = db.execute("MATCH (n:Person) RETURN n LIMIT 5")

    Pass to :class:`NLToCypher` to enable database-aware execution::

        db = Neo4jDatabase("bolt://localhost:7687", "neo4j", "password")
        pipeline = NLToCypher.from_pretrained(..., db=db)
        cypher, results = pipeline("John works for Apple.", ["works_for"],
                                   mode="create", execute=True)
    """

    def __init__(
        self,
        uri: str,
        username: str,
        password: str,
        database: str = "neo4j",
    ) -> None:
        """
        Parameters
        ----------
        uri:
            Bolt/neo4j URI, e.g. ``"bolt://localhost:7687"``.
        username:
            Neo4j username.
        password:
            Neo4j password.
        database:
            Target database name (default: ``"neo4j"``).

        Raises
        ------
        ImportError
            If the ``neo4j`` package is not installed.
        """
        ...

    def execute(
        self,
        cypher: str,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Execute a Cypher query and return results as a list of record dicts.

        Parameters
        ----------
        cypher:
            Cypher query string.
        parameters:
            Optional query parameters.

        Returns
        -------
        list[dict]
            One dict per returned record.  Empty list for queries with no
            ``RETURN`` clause (e.g. a bare ``CREATE``).
        """
        ...

    def execute_many(
        self,
        queries: List[str],
        parameters_list: Optional[List[Optional[Dict[str, Any]]]] = None,
    ) -> List[List[Dict[str, Any]]]:
        """Execute multiple Cypher queries in sequence and return all results.

        Parameters
        ----------
        queries:
            List of Cypher query strings to execute.
        parameters_list:
            Optional list of parameter dicts, one per query.

        Returns
        -------
        list[list[dict]]
            One inner list per query.
        """
        ...

    def close(self) -> None:
        """Close the underlying driver and release all connections."""
        ...

    def __enter__(self) -> "Neo4jDatabase": ...
    def __exit__(self, *args: Any) -> None: ...
    def __repr__(self) -> str: ...


# ---------------------------------------------------------------------------
# RelationToCypherConverter
# ---------------------------------------------------------------------------

class RelationToCypherConverter:
    """Convert GLiNER2 relation-extraction output to a parameterized Cypher query.

    All methods return ``(cypher_string, parameters_dict)`` so that entity
    values are never interpolated into the query string (prevents Cypher
    injection).  Pass both to :meth:`Neo4jDatabase.execute`.

    Example::

        converter = RelationToCypherConverter(schema=schema)
        cypher, params = converter.convert(results, mode="merge")
        db.execute(cypher, params)
    """

    schema: Any
    name_property: str

    def __init__(
        self,
        schema: Optional[Any] = None,
        name_property: str = "name",
    ) -> None: ...

    def to_match_query(
        self,
        relations: Dict[str, Any],
        return_clause: Optional[str] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """Build MATCH clauses for the extracted relations.

        Returns ``("", {})`` when nothing was extracted.
        """
        ...

    def to_merge_query(
        self,
        relations: Dict[str, Any],
        return_clause: Optional[str] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """Build MERGE clauses to upsert extracted entities/relationships.

        Node labels are added automatically when a schema is provided.
        Returns ``("", {})`` when nothing was extracted.
        """
        ...

    def to_create_query(
        self,
        relations: Dict[str, Any],
        return_clause: Optional[str] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """Build CREATE clauses to insert extracted entities/relationships.

        Returns ``("", {})`` when nothing was extracted.
        """
        ...

    def convert(
        self,
        relations: Dict[str, Any],
        mode: str = "match",
        **kwargs: Any,
    ) -> Tuple[str, Dict[str, Any]]:
        """Convert extracted relations to a parameterized Cypher query.

        Raises
        ------
        ValueError
            For an unrecognised *mode*.
        """
        ...

    def __repr__(self) -> str: ...


# ---------------------------------------------------------------------------
# GLiNER2RelationExtractor
# ---------------------------------------------------------------------------

class GLiNER2RelationExtractor:
    """Thin wrapper around the GLiNER2 model for zero-shot relation extraction.

    Requires the ``gliner2`` package (``pip install gliner2``).

    Example::

        extractor = GLiNER2RelationExtractor.from_pretrained("fastino/gliner2-large-v1")
        results = extractor.extract_relations(
            "John works for Apple Inc.",
            ["works_for"],
        )
        # {"relation_extraction": {"works_for": [("John", "Apple Inc.")]}}
    """

    DEFAULT_MODEL: str

    threshold: float

    def __init__(self, model: Any, threshold: float = 0.5) -> None: ...

    @classmethod
    def from_pretrained(
        cls,
        model_name: str = ...,
        threshold: float = 0.5,
    ) -> "GLiNER2RelationExtractor":
        """Load a pretrained GLiNER2 model from the HuggingFace Hub or a local path.

        Raises
        ------
        ImportError
            If the ``gliner2`` package is not installed.
        """
        ...

    def extract_relations(
        self,
        text: str,
        relation_types: List[str],
        threshold: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Extract relations from *text* using the loaded GLiNER2 model.

        All requested relation types are present in the output dict
        (with an empty list when a relation was not found).

        Returns
        -------
        dict
            ``{"relation_extraction": {"works_for": [("John", "Apple Inc.")], ...}}``
        """
        ...

    def __repr__(self) -> str: ...


# ---------------------------------------------------------------------------
# NLToCypher
# ---------------------------------------------------------------------------

class NLToCypher:
    """End-to-end pipeline: natural language text → Cypher query.

    Chains :class:`GLiNER2RelationExtractor` and :class:`RelationToCypherConverter`.
    Optionally executes the generated query against a Neo4j database when a
    :class:`Neo4jDatabase` is provided and ``execute=True`` is passed.

    Example — generation only::

        pipeline = NLToCypher.from_pretrained("fastino/gliner2-large-v1", schema=schema)
        cypher = pipeline("John works for Apple Inc.", ["works_for"], mode="create")

    Example — db-aware execution::

        db = Neo4jDatabase("bolt://localhost:7687", "neo4j", "password")
        pipeline = NLToCypher.from_pretrained(..., db=db)
        cypher, results = pipeline(
            "John works for Apple Inc.",
            ["works_for"],
            mode="create",
            execute=True,
        )

    Example — credentials from environment variables::

        # export NEO4J_URI=bolt://localhost:7687
        # export NEO4J_PASSWORD=secret
        pipeline = NLToCypher.from_env("fastino/gliner2-large-v1", schema=schema)
        cypher, results = pipeline("...", ["works_for"], mode="create", execute=True)
    """

    extractor: GLiNER2RelationExtractor
    converter: RelationToCypherConverter
    db: Optional[Neo4jDatabase]

    def __init__(
        self,
        extractor: GLiNER2RelationExtractor,
        schema: Optional[Any] = None,
        name_property: str = "name",
        db: Optional[Neo4jDatabase] = None,
    ) -> None: ...

    @classmethod
    def from_pretrained(
        cls,
        model_name: str = ...,
        schema: Optional[Any] = None,
        threshold: float = 0.5,
        name_property: str = "name",
        db: Optional[Neo4jDatabase] = None,
    ) -> "NLToCypher":
        """Create a pipeline by loading a pretrained GLiNER2 model.

        Raises
        ------
        ImportError
            If the ``gliner2`` package is not installed.
        """
        ...

    @classmethod
    def from_env(
        cls,
        model_name: str = ...,
        schema: Optional[Any] = None,
        threshold: float = 0.5,
        name_property: str = "name",
        database: str = "neo4j",
    ) -> "NLToCypher":
        """Create a pipeline reading Neo4j credentials from environment variables.

        Reads ``NEO4J_URI``, ``NEO4J_USERNAME`` (default ``"neo4j"``), and
        ``NEO4J_PASSWORD`` from the process environment.

        Raises
        ------
        KeyError
            If ``NEO4J_URI`` or ``NEO4J_PASSWORD`` are not set.
        ImportError
            If the ``gliner2`` or ``neo4j`` packages are not installed.
        """
        ...

    # execute=False → str
    @overload
    def __call__(
        self,
        text: str,
        relation_types: List[str],
        mode: str = ...,
        threshold: Optional[float] = ...,
        execute: Literal[False] = ...,
        **kwargs: Any,
    ) -> str: ...

    # execute=True → (str, list[dict])
    @overload
    def __call__(
        self,
        text: str,
        relation_types: List[str],
        mode: str = ...,
        threshold: Optional[float] = ...,
        *,
        execute: Literal[True],
        **kwargs: Any,
    ) -> Tuple[str, List[Dict[str, Any]]]: ...

    def __call__(
        self,
        text: str,
        relation_types: List[str],
        mode: str = "match",
        threshold: Optional[float] = None,
        execute: bool = False,
        **kwargs: Any,
    ) -> Union[str, Tuple[str, List[Dict[str, Any]]]]:
        """Extract relations from *text* and return a Cypher query.

        Parameters
        ----------
        text:
            Input sentence or passage.
        relation_types:
            Relation labels to extract.
        mode:
            ``"match"``, ``"merge"``, or ``"create"``.
        threshold:
            Override extractor confidence threshold.
        execute:
            When ``True``, execute the query against the database and return
            ``(cypher, results)``.  Requires ``db`` to be set.
        **kwargs:
            Forwarded to the Cypher converter (e.g. ``return_clause="RETURN *"``).

        Returns
        -------
        str
            Cypher query when ``execute=False`` (default).
        tuple[str, list[dict]]
            ``(cypher, db_results)`` when ``execute=True``.

        Raises
        ------
        RuntimeError
            When ``execute=True`` but no ``db`` was provided.
        """
        ...

    # execute=False → (dict, str)
    @overload
    def extract_and_convert(
        self,
        text: str,
        relation_types: List[str],
        mode: str = ...,
        threshold: Optional[float] = ...,
        execute: Literal[False] = ...,
        **kwargs: Any,
    ) -> Tuple[Dict[str, Any], str]: ...

    # execute=True → (dict, str, list[dict])
    @overload
    def extract_and_convert(
        self,
        text: str,
        relation_types: List[str],
        mode: str = ...,
        threshold: Optional[float] = ...,
        *,
        execute: Literal[True],
        **kwargs: Any,
    ) -> Tuple[Dict[str, Any], str, List[Dict[str, Any]]]: ...

    def extract_and_convert(
        self,
        text: str,
        relation_types: List[str],
        mode: str = "match",
        threshold: Optional[float] = None,
        execute: bool = False,
        **kwargs: Any,
    ) -> Union[Tuple[Dict[str, Any], str], Tuple[Dict[str, Any], str, List[Dict[str, Any]]]]:
        """Extract relations and return the raw dict and the Cypher string.

        Returns
        -------
        tuple[dict, str]
            ``(relations_dict, cypher_query)`` when ``execute=False``.
        tuple[dict, str, list[dict]]
            ``(relations_dict, cypher_query, db_results)`` when ``execute=True``.

        Raises
        ------
        RuntimeError
            When ``execute=True`` but no ``db`` was provided.
        """
        ...

    def __repr__(self) -> str: ...


# ---------------------------------------------------------------------------
# LLM utility functions
# ---------------------------------------------------------------------------

def extract_cypher_from_text(text: str) -> str:
    """Extract a Cypher query from LLM-generated text.

    Handles fenced code blocks (````cypher``, ````sql``, or plain ` ``` `),
    inline backtick spans, and line-anchored Cypher as fallback.

    Parameters
    ----------
    text:
        Raw LLM output.

    Returns
    -------
    str
        Extracted Cypher string (stripped), or the original text when no
        recognisable pattern is found.
    """
    ...


def format_records(
    records: List[Dict[str, Any]],
    format: str = "markdown",
) -> str:
    """Format Neo4j result records as a string for LLM context.

    Parameters
    ----------
    records:
        Records as returned by :meth:`Neo4jDatabase.execute`.
    format:
        One of ``"markdown"`` (default), ``"csv"``, ``"json"``, ``"text"``.

    Returns
    -------
    str
        Formatted string, or ``""`` when *records* is empty.

    Raises
    ------
    ValueError
        For an unrecognised *format*.
    """
    ...


def repair_cypher(
    validator: CypherValidator,
    query: str,
    llm_fn: Any,
    max_retries: int = 3,
) -> Tuple[str, ValidationResult]:
    """Validate a Cypher query and use an LLM to repair it when invalid.

    Parameters
    ----------
    validator:
        :class:`CypherValidator` instance.
    query:
        Initial query string (possibly invalid).
    llm_fn:
        Callable ``(query: str, errors: list[str]) -> str`` that returns
        a repaired query.
    max_retries:
        Maximum number of repair attempts.

    Returns
    -------
    tuple[str, ValidationResult]
        ``(final_query, final_result)`` after at most *max_retries* iterations.
    """
    ...


def cypher_tool_spec(
    schema: Optional[Schema] = None,
    db_description: str = "",
    format: str = "anthropic",
) -> Dict[str, Any]:
    """Build a tool/function-call specification for Cypher execution.

    Parameters
    ----------
    schema:
        Optional schema embedded in the tool description.
    db_description:
        Short description of the database.
    format:
        ``"anthropic"`` (default) or ``"openai"``.

    Returns
    -------
    dict
        Tool specification dict ready for the chosen LLM API.
    """
    ...


def few_shot_examples(
    generator: CypherGenerator,
    n: int = 5,
    query_type: Optional[str] = None,
) -> List[Tuple[str, str]]:
    """Generate ``(natural_language_description, cypher)`` pairs.

    Parameters
    ----------
    generator:
        :class:`CypherGenerator` instance.
    n:
        Number of examples to produce.
    query_type:
        Restrict to this query type.  ``None`` spreads across all types.

    Returns
    -------
    list[tuple[str, str]]
        ``[(description, cypher), ...]``
    """
    ...


# ---------------------------------------------------------------------------
# Graph RAG pipeline
# ---------------------------------------------------------------------------

class GraphRAGPipeline:
    """End-to-end Graph RAG pipeline: NL question → Cypher → execute → answer.

    Parameters
    ----------
    schema:
        Graph schema used for context injection and validation.
    db:
        :class:`Neo4jDatabase` connection.
    llm_fn:
        Callable ``(prompt: str) -> str`` wrapping your chosen LLM.
    max_repair_retries:
        Maximum LLM repair attempts for invalid queries (default: 2).
    result_format:
        Format for query results injected into the answer prompt.
    cypher_system_prompt:
        Override the default Cypher-generation system prompt.
    answer_system_prompt:
        Override the default answer-synthesis system prompt.

    Examples
    --------
    ::

        pipeline = GraphRAGPipeline(schema=schema, db=db, llm_fn=my_llm)
        answer = pipeline.query("Who works for Acme Corp?")

        ctx = pipeline.query_with_context("Who works for Acme Corp?")
        print(ctx["cypher"], ctx["answer"])
    """

    schema: Any
    db: Any
    llm_fn: Any
    max_repair_retries: int
    result_format: str

    def __init__(
        self,
        schema: Any,
        db: Any,
        llm_fn: Any,
        *,
        max_repair_retries: int = 2,
        result_format: str = "markdown",
        cypher_system_prompt: Optional[str] = None,
        answer_system_prompt: Optional[str] = None,
    ) -> None: ...

    def query(self, question: str) -> str:
        """Run the full pipeline and return a natural language answer."""
        ...

    def query_with_context(self, question: str) -> Dict[str, Any]:
        """Run the pipeline and return all intermediate artefacts.

        Returns a dict with keys: ``question``, ``cypher``, ``is_valid``,
        ``validation_errors``, ``repair_attempts``, ``records``,
        ``formatted_results``, ``answer``, ``execution_error``.
        """
        ...

    def __repr__(self) -> str: ...


# ---------------------------------------------------------------------------
# LLMNLToCypher
# ---------------------------------------------------------------------------

class LLMNLToCypher:
    """LLM-based natural language to Cypher pipeline.

    Unlike :class:`NLToCypher` (GLiNER2-based), this sends text directly to
    an LLM to produce Cypher.  Supports any OpenAI-compatible backend or a
    raw ``llm_fn`` callable.
    """

    schema: Any
    db: Any
    max_repair_retries: int
    temperature: float

    def __init__(
        self,
        *,
        llm_fn: Optional[Callable[[str], str]] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        schema: Any = None,
        db: Optional[Neo4jDatabase] = None,
        max_repair_retries: int = 2,
        temperature: float = 0.0,
        system_prompt: Optional[str] = None,
    ) -> None: ...

    @classmethod
    def from_openai(
        cls,
        model: str = "gpt-4o",
        *,
        api_key: Optional[str] = None,
        schema: Any = None,
        db: Optional[Neo4jDatabase] = None,
        max_repair_retries: int = 2,
        temperature: float = 0.0,
        system_prompt: Optional[str] = None,
    ) -> "LLMNLToCypher": ...

    @classmethod
    def from_deepseek(
        cls,
        model: str = "deepseek-chat",
        *,
        api_key: Optional[str] = None,
        base_url: str = "https://api.deepseek.com",
        schema: Any = None,
        db: Optional[Neo4jDatabase] = None,
        max_repair_retries: int = 2,
        temperature: float = 0.0,
        system_prompt: Optional[str] = None,
    ) -> "LLMNLToCypher": ...

    @classmethod
    def from_anthropic(
        cls,
        model: str = "claude-sonnet-4-20250514",
        *,
        api_key: Optional[str] = None,
        schema: Any = None,
        db: Optional[Neo4jDatabase] = None,
        max_repair_retries: int = 2,
        temperature: float = 0.0,
        system_prompt: Optional[str] = None,
    ) -> "LLMNLToCypher": ...

    @classmethod
    def from_langchain(
        cls,
        chat_model: Any,
        *,
        schema: Any = None,
        db: Optional[Neo4jDatabase] = None,
        max_repair_retries: int = 2,
        system_prompt: Optional[str] = None,
    ) -> "LLMNLToCypher":
        """Create a pipeline from a LangChain ``BaseChatModel``.

        Accepts any LangChain chat model (``ChatOpenAI``,
        ``ChatAnthropic``, ``ChatOllama``, etc.).  Temperature and
        other params should be configured on the model instance.

        Requires the ``langchain-core`` package.
        """
        ...

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
    ) -> "LLMNLToCypher": ...

    def close(self) -> None:
        """Close the DB connection if this instance owns it."""
        ...

    def __enter__(self) -> "LLMNLToCypher": ...
    def __exit__(self, *args: Any) -> None: ...

    def reset_discovered_schema(self) -> None:
        """Clear the cached DB-discovered / LLM-inferred schema."""
        ...

    # execute=False → str
    @overload
    def __call__(
        self,
        text: str,
        mode: str = ...,
        execute: Literal[False] = ...,
    ) -> str: ...

    # execute=True → (str, list[dict])
    @overload
    def __call__(
        self,
        text: str,
        mode: str = ...,
        *,
        execute: Literal[True],
    ) -> Tuple[str, List[Dict[str, Any]]]: ...

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
            Natural language passage.
        mode:
            ``"create"``, ``"merge"``, or ``"match"``.
        execute:
            Execute the query and return ``(cypher, records)``.

        Returns
        -------
        str
            Cypher query when ``execute=False``.
        tuple[str, list[dict]]
            ``(cypher, records)`` when ``execute=True``.
        """
        ...

    def ingest_with_context(
        self,
        text: str,
        mode: str = "create",
        execute: bool = False,
    ) -> Dict[str, Any]:
        """Generate Cypher and return all intermediate artefacts.

        Returns a dict with keys: ``schema_source``, ``inferred_schema``,
        ``cypher``, ``is_valid``, ``validation_errors``,
        ``repair_attempts``, ``records``, ``execution_error``.
        """
        ...

    @staticmethod
    def _chunk_text(
        text: str,
        chunk_size: int = 2000,
        chunk_overlap: int = 200,
    ) -> List[str]:
        """Split text into chunks respecting sentence boundaries."""
        ...

    @staticmethod
    def _build_provenance_cypher(
        domain_cypher: str,
        chunk_id: str,
        source_id: str,
        text_preview: str,
    ) -> Tuple[str, Dict[str, Any]]:
        """Build deterministic provenance Cypher from parsed domain labels."""
        ...

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
        """Batch-ingest texts into a knowledge graph."""
        ...

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
        """Chunk a document and ingest all chunks."""
        ...

    def __repr__(self) -> str: ...


# ---------------------------------------------------------------------------
# Vector support
# ---------------------------------------------------------------------------

@dataclass
class VectorProperty:
    """Declares a vector index on a NodeModel property."""
    dimensions: int
    similarity: str = "cosine"


# ---------------------------------------------------------------------------
# Embedding adapters
# ---------------------------------------------------------------------------

class EmbeddingFn:
    def __call__(self, text: str) -> List[float]: ...

class BatchEmbeddingFn:
    def __call__(self, text: str) -> List[float]: ...
    def batch(self, texts: List[str]) -> List[List[float]]: ...

class OpenAIEmbeddings:
    def __init__(self, model: str = "text-embedding-3-small", api_key: Optional[str] = None) -> None: ...
    def __call__(self, text: str) -> List[float]: ...
    def batch(self, texts: List[str]) -> List[List[float]]: ...

class SentenceTransformerEmbeddings:
    def __init__(self, model: str = "all-MiniLM-L6-v2") -> None: ...
    def __call__(self, text: str) -> List[float]: ...
    def batch(self, texts: List[str]) -> List[List[float]]: ...

class CohereEmbeddings:
    def __init__(self, model: str = "embed-english-v3.0", api_key: Optional[str] = None) -> None: ...
    def __call__(self, text: str) -> List[float]: ...
    def batch(self, texts: List[str]) -> List[List[float]]: ...


__all__ = [
    "Schema",
    "CypherValidator",
    "ValidationResult",
    "ValidationDiagnostic",
    "CypherGenerator",
    "QueryInfo",
    "parse_query",
    "Neo4jDatabase",
    "GLiNER2RelationExtractor",
    "RelationToCypherConverter",
    "NLToCypher",
    # LLM utilities
    "extract_cypher_from_text",
    "format_records",
    "repair_cypher",
    "cypher_tool_spec",
    "few_shot_examples",
    # RAG pipeline
    "GraphRAGPipeline",
    # LLM NL-to-Cypher pipeline
    "LLMNLToCypher",
    # Batch ingestion
    "ChunkResult",
    "IngestionResult",
    # Vector support
    "VectorProperty",
    # Embedding adapters
    "EmbeddingFn",
    "BatchEmbeddingFn",
    "OpenAIEmbeddings",
    "SentenceTransformerEmbeddings",
    "CohereEmbeddings",
]
