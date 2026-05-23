"""Pydantic-based Cypher ORM: declarative graph schema, query builder, and AI agent tools.

Define your graph schema as Python classes, build type-safe parameterized Cypher
queries with a fluent API, and get AI-agent-friendly tool specs for function calling.

Example::

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

    # Query builder
    q = (Query()
         .match(Person, "p")
         .where(Cond("p.name", "=", "$name"))
         .return_("p"))
    print(q.build())
    # MATCH (p:Person) WHERE p.name = $name RETURN p

    # Schema bridge
    schema = GraphSchema.from_models([Person, Movie, ActedIn])
    validator = CypherValidator(schema.to_cypher_schema())
"""

# Re-export everything for backwards compatibility.
# All existing `from cypher_validator.models import X` imports continue to work.

from cypher_validator.models.orm import (  # noqa: F401
    _NODE_REGISTRY,
    _REL_REGISTRY,
    _NodeMeta,
    NodeModel,
    _RelMeta,
    _to_upper_snake,
    RelationshipModel,
    _python_type_to_json_type,
    node,
    relationship,
)

from cypher_validator.models.query import (  # noqa: F401
    Op,
    Cond,
    CondGroup,
    RawExpr,
    Query,
    QueryStep,
    QueryPlan,
    QueryResult,
    PropExpr,
    NodeRef,
    RelRef,
    _orig_match,
    _orig_return,
    _match_with_ref,
    _return_with_ref,
    QueryHistoryEntry,
    QueryHistory,
    CypherFn,
    fn,
    PathBuilder,
)

from cypher_validator.models.schema import (  # noqa: F401
    GraphSchema,
    SchemaDDL,
    SchemaDiff,
    schema_to_pipeline_kwargs,
)

from cypher_validator.models.session import (  # noqa: F401
    _VALID_DIRECTIONS,
    _validate_direction,
    Traversal,
    BulkOps,
    GraphSession,
    AsyncGraphSession,
    Repository,
)

from cypher_validator.models.agents import (  # noqa: F401
    AgentTools,
    ExtendedAgentTools,
)

__all__ = [
    # orm
    "_NODE_REGISTRY",
    "_REL_REGISTRY",
    "_NodeMeta",
    "NodeModel",
    "_RelMeta",
    "_to_upper_snake",
    "RelationshipModel",
    "_python_type_to_json_type",
    "node",
    "relationship",
    # query
    "Op",
    "Cond",
    "CondGroup",
    "RawExpr",
    "Query",
    "QueryStep",
    "QueryPlan",
    "QueryResult",
    "PropExpr",
    "NodeRef",
    "RelRef",
    "_orig_match",
    "_orig_return",
    "_match_with_ref",
    "_return_with_ref",
    "QueryHistoryEntry",
    "QueryHistory",
    "CypherFn",
    "fn",
    "PathBuilder",
    # schema
    "GraphSchema",
    "SchemaDDL",
    "SchemaDiff",
    "schema_to_pipeline_kwargs",
    # session
    "_VALID_DIRECTIONS",
    "_validate_direction",
    "Traversal",
    "BulkOps",
    "GraphSession",
    "AsyncGraphSession",
    "Repository",
    # agents
    "AgentTools",
    "ExtendedAgentTools",
]
