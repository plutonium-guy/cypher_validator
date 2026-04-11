"""
cypher_validator — Cypher query validation, generation, and NL-to-Cypher via GLiNER2.

Rust-accelerated core (Schema, CypherValidator, CypherGenerator, parse_query) is
provided by the compiled ``_cypher_validator`` extension.  GLiNER2 relation
extraction and Cypher conversion live in the pure-Python ``gliner2_integration``
sub-module.  LLM integration helpers live in ``llm_utils`` and ``rag``.
"""
from cypher_validator._cypher_validator import (  # noqa: F401
    Schema,
    CypherValidator,
    ValidationResult,
    ValidationDiagnostic,
    CypherGenerator,
    QueryInfo,
    parse_query,
)
from cypher_validator.gliner2_integration import (  # noqa: F401
    EntityNERExtractor,
    GLiNER2RelationExtractor,
    RelationToCypherConverter,
    NLToCypher,
    Neo4jDatabase,
)
from cypher_validator.llm_utils import (  # noqa: F401
    extract_cypher_from_text,
    format_records,
    repair_cypher,
    cypher_tool_spec,
    few_shot_examples,
)
from cypher_validator.models import (  # noqa: F401
    NodeModel,
    RelationshipModel,
    Query,
    Cond,
    CondGroup,
    Op,
    RawExpr,
    GraphSchema,
    AgentTools,
    ExtendedAgentTools,
    QueryPlan,
    QueryStep,
    QueryResult,
    Traversal,
    BulkOps,
    SchemaDDL,
    GraphSession,
    AsyncGraphSession,
    PropExpr,
    NodeRef,
    RelRef,
    QueryHistory,
    SchemaDiff,
    CypherFn,
    fn,
    PathBuilder,
    Repository,
    schema_to_pipeline_kwargs,
    node,
    relationship,
)
from cypher_validator.rag import GraphRAGPipeline  # noqa: F401
from cypher_validator.llm_pipeline import (  # noqa: F401
    LLMNLToCypher,
    ChunkResult,
    IngestionResult,
    TokenBucketRateLimiter,
)

# ---------------------------------------------------------------------------
# Schema.from_neo4j() convenience wrapper
# ---------------------------------------------------------------------------

def _schema_from_neo4j(uri, username, password, database="neo4j", sample_limit=1000):
    """Create a Schema by introspecting a live Neo4j database.

    Parameters
    ----------
    uri : str
        Bolt/neo4j URI, e.g. ``"bolt://localhost:7687"``.
    username : str
        Neo4j username.
    password : str
        Neo4j password.
    database : str
        Target database name (default: ``"neo4j"``).
    sample_limit : int
        Maximum number of nodes/relationships to sample per label/type
        when procedure-based discovery is unavailable (default: 1000).

    Returns
    -------
    Schema
        A fully populated schema discovered from the database.
    """
    db = Neo4jDatabase(uri, username, password, database=database)
    try:
        return db.introspect_schema(sample_limit=sample_limit)
    finally:
        db.close()

Schema.from_neo4j = staticmethod(_schema_from_neo4j)

__all__ = [
    # Rust core
    "Schema",
    "CypherValidator",
    "ValidationResult",
    "ValidationDiagnostic",
    "CypherGenerator",
    "QueryInfo",
    "parse_query",
    # GLiNER2 / Neo4j integration
    "EntityNERExtractor",
    "GLiNER2RelationExtractor",
    "RelationToCypherConverter",
    "NLToCypher",
    "Neo4jDatabase",
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
    # Async rate limiting
    "TokenBucketRateLimiter",
    # Pydantic ORM — models & query builder
    "NodeModel",
    "RelationshipModel",
    "Query",
    "Cond",
    "CondGroup",
    "Op",
    "RawExpr",
    "GraphSchema",
    "AgentTools",
    "QueryPlan",
    "QueryStep",
    "QueryResult",
    "Traversal",
    "BulkOps",
    "SchemaDDL",
    "GraphSession",
    "ExtendedAgentTools",
    "AsyncGraphSession",
    "PropExpr",
    "NodeRef",
    "RelRef",
    "QueryHistory",
    "SchemaDiff",
    "CypherFn",
    "fn",
    "PathBuilder",
    "Repository",
    "schema_to_pipeline_kwargs",
    "node",
    "relationship",
]
