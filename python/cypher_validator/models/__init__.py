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
    "VectorProperty",
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

_SUBMODULE_MAP = {
    "_NODE_REGISTRY": "cypher_validator.models.orm",
    "_REL_REGISTRY": "cypher_validator.models.orm",
    "_NodeMeta": "cypher_validator.models.orm",
    "NodeModel": "cypher_validator.models.orm",
    "_RelMeta": "cypher_validator.models.orm",
    "_to_upper_snake": "cypher_validator.models.orm",
    "RelationshipModel": "cypher_validator.models.orm",
    "_python_type_to_json_type": "cypher_validator.models.orm",
    "node": "cypher_validator.models.orm",
    "relationship": "cypher_validator.models.orm",
    "VectorProperty": "cypher_validator.models.orm",
    "Op": "cypher_validator.models.query",
    "Cond": "cypher_validator.models.query",
    "CondGroup": "cypher_validator.models.query",
    "RawExpr": "cypher_validator.models.query",
    "Query": "cypher_validator.models.query",
    "QueryStep": "cypher_validator.models.query",
    "QueryPlan": "cypher_validator.models.query",
    "QueryResult": "cypher_validator.models.query",
    "PropExpr": "cypher_validator.models.query",
    "NodeRef": "cypher_validator.models.query",
    "RelRef": "cypher_validator.models.query",
    "_orig_match": "cypher_validator.models.query",
    "_orig_return": "cypher_validator.models.query",
    "_match_with_ref": "cypher_validator.models.query",
    "_return_with_ref": "cypher_validator.models.query",
    "QueryHistoryEntry": "cypher_validator.models.query",
    "QueryHistory": "cypher_validator.models.query",
    "CypherFn": "cypher_validator.models.query",
    "fn": "cypher_validator.models.query",
    "PathBuilder": "cypher_validator.models.query",
    "GraphSchema": "cypher_validator.models.schema",
    "SchemaDDL": "cypher_validator.models.schema",
    "SchemaDiff": "cypher_validator.models.schema",
    "schema_to_pipeline_kwargs": "cypher_validator.models.schema",
    "_VALID_DIRECTIONS": "cypher_validator.models.session",
    "_validate_direction": "cypher_validator.models.session",
    "Traversal": "cypher_validator.models.session",
    "BulkOps": "cypher_validator.models.session",
    "GraphSession": "cypher_validator.models.session",
    "AsyncGraphSession": "cypher_validator.models.session",
    "Repository": "cypher_validator.models.session",
    "AgentTools": "cypher_validator.models.agents",
    "ExtendedAgentTools": "cypher_validator.models.agents",
}


def __getattr__(name: str):
    if name in _SUBMODULE_MAP:
        import importlib
        mod = importlib.import_module(_SUBMODULE_MAP[name])
        val = getattr(mod, name)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
