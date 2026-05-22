"""Live Neo4j integration tests for the Pydantic ORM layer.

Gated by NEO4J_URI environment variable. Skipped when not set so the
default `pytest` invocation stays driver-free.

Spin up a Neo4j container locally:

    docker run -d --name neo4j-cv -p 7687:7687 \
        -e NEO4J_AUTH=neo4j/testtest12 neo4j:5.26-community
    NEO4J_URI=bolt://localhost:7687 \
        NEO4J_USERNAME=neo4j NEO4J_PASSWORD=testtest12 \
        pytest tests/test_orm_neo4j.py -v
"""
from __future__ import annotations

import os
from typing import Any

import pytest

from cypher_validator import (
    AsyncGraphSession,
    BulkOps,
    CypherFn,
    CypherValidator,
    ExtendedAgentTools,
    GraphSchema,
    GraphSession,
    Neo4jDatabase,
    NodeModel,
    Query,
    QueryHistory,
    RelationshipModel,
    Repository,
    Schema,
    SchemaDDL,
    SchemaDiff,
    Traversal,
)


# Skip the whole module when no live DB is configured.
NEO4J_URI = os.environ.get("NEO4J_URI")
NEO4J_USER = os.environ.get("NEO4J_USERNAME", "neo4j")
NEO4J_PASS = os.environ.get("NEO4J_PASSWORD", "testtest12")

pytestmark = pytest.mark.skipif(
    not NEO4J_URI,
    reason="NEO4J_URI not set; live Neo4j integration tests skipped.",
)


# ---------------------------------------------------------------------------
# Domain models — distinct labels to avoid registry collisions
# ---------------------------------------------------------------------------

class Person(NodeModel):
    __label__ = "OrmTestPerson"
    name: str
    age: int = 0
    email: str = ""


class Company(NodeModel):
    __label__ = "OrmTestCompany"
    name: str
    founded: int = 0


class City(NodeModel):
    __label__ = "OrmTestCity"
    name: str
    country: str = ""


class WorksFor(RelationshipModel):
    __source__ = Person
    __target__ = Company
    __rel_type__ = "ORM_WORKS_FOR"
    since: int = 0


class LivesIn(RelationshipModel):
    __source__ = Person
    __target__ = City
    __rel_type__ = "ORM_LIVES_IN"


class Knows(RelationshipModel):
    __source__ = Person
    __target__ = Person
    __rel_type__ = "ORM_KNOWS"
    since: int = 0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def schema() -> GraphSchema:
    return GraphSchema.from_models(
        [Person, Company, City, WorksFor, LivesIn, Knows]
    )


@pytest.fixture(scope="module")
def db() -> Neo4jDatabase:
    inst = Neo4jDatabase(NEO4J_URI, NEO4J_USER, NEO4J_PASS)
    yield inst
    # Best-effort cleanup at module teardown.
    try:
        inst.execute(
            "MATCH (n) WHERE any(l IN labels(n) "
            "WHERE l STARTS WITH 'OrmTest') "
            "DETACH DELETE n"
        )
    finally:
        inst.close()


@pytest.fixture(autouse=True)
def _clean_ns(db: Neo4jDatabase):
    """Wipe only this module's labels between tests."""
    db.execute(
        "MATCH (n) WHERE any(l IN labels(n) WHERE l STARTS WITH 'OrmTest') "
        "DETACH DELETE n"
    )


def _seed_graph(gs: GraphSession) -> None:
    """Insert 4 people / 2 companies / 2 cities + WORKS_FOR, LIVES_IN, KNOWS."""
    cypher, params = BulkOps.bulk_merge_nodes(
        Person,
        [
            {"name": "Alice", "age": 31, "email": ""},
            {"name": "Bob", "age": 28, "email": ""},
            {"name": "Carol", "age": 45, "email": ""},
            {"name": "Dan", "age": 22, "email": ""},
        ],
        merge_keys=["name"],
    )
    gs.execute(cypher, params)
    cypher, params = BulkOps.bulk_merge_nodes(
        Company,
        [{"name": "Acme", "founded": 1990}, {"name": "Globex", "founded": 2001}],
        merge_keys=["name"],
    )
    gs.execute(cypher, params)
    cypher, params = BulkOps.bulk_merge_nodes(
        City,
        [{"name": "Paris", "country": "FR"}, {"name": "Tokyo", "country": "JP"}],
        merge_keys=["name"],
    )
    gs.execute(cypher, params)
    cypher, params = BulkOps.bulk_merge_relationships(
        WorksFor,
        [
            {"src_name": "Alice", "tgt_name": "Acme", "since": 2020},
            {"src_name": "Bob", "tgt_name": "Acme", "since": 2018},
            {"src_name": "Carol", "tgt_name": "Globex", "since": 2010},
            {"src_name": "Dan", "tgt_name": "Globex", "since": 2024},
        ],
        src_key="src_name",
        tgt_key="tgt_name",
    )
    gs.execute(cypher, params)
    cypher, params = BulkOps.bulk_merge_relationships(
        LivesIn,
        [
            {"src_name": "Alice", "tgt_name": "Paris"},
            {"src_name": "Bob", "tgt_name": "Paris"},
            {"src_name": "Carol", "tgt_name": "Tokyo"},
            {"src_name": "Dan", "tgt_name": "Tokyo"},
        ],
        src_key="src_name",
        tgt_key="tgt_name",
    )
    gs.execute(cypher, params)
    cypher, params = BulkOps.bulk_merge_relationships(
        Knows,
        [
            {"src_name": "Alice", "tgt_name": "Bob", "since": 2015},
            {"src_name": "Bob", "tgt_name": "Carol", "since": 2017},
            {"src_name": "Carol", "tgt_name": "Dan", "since": 2020},
        ],
        src_key="src_name",
        tgt_key="tgt_name",
    )
    gs.execute(cypher, params)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSchemaBridge:
    def test_graph_schema_to_rust_schema(self, schema: GraphSchema):
        rust = schema.to_cypher_schema()
        assert isinstance(rust, Schema)
        assert "OrmTestPerson" in rust.node_labels()
        assert "ORM_WORKS_FOR" in rust.rel_types()
        src, tgt = rust.rel_endpoints("ORM_WORKS_FOR")
        assert src == "OrmTestPerson"
        assert tgt == "OrmTestCompany"

    def test_validator_uses_orm_schema(self, schema: GraphSchema):
        v = CypherValidator(schema.to_cypher_schema())
        assert v.validate(
            "MATCH (p:OrmTestPerson)-[:ORM_WORKS_FOR]->(c:OrmTestCompany) RETURN p"
        ).is_valid
        bad = v.validate(
            "MATCH (p:OrmTestPersn)-[:ORM_WORK_FOR]->(c:OrmTestCompny) RETURN p"
        )
        assert not bad.is_valid
        assert bad.fixed_query and "OrmTestPerson" in bad.fixed_query


class TestQueryBuilderRoundTrip:
    def test_match_where_return_executes(self, db: Neo4jDatabase, schema: GraphSchema):
        gs = GraphSession(db, schema)
        _seed_graph(gs)
        q = (
            Query()
            .match(Person, "p")
            .where("p.age > $min_age")
            .params(min_age=30)
            .return_("p.name AS name", "p.age AS age")
            .order_by("p.age DESC")
        )
        cypher, params = q.build()
        rows = gs.execute(cypher, params)
        names = [r["name"] for r in rows]
        # Alice (31), Carol (45) — order DESC
        assert names == ["Carol", "Alice"]

    def test_match_path_typed(self, db: Neo4jDatabase, schema: GraphSchema):
        gs = GraphSession(db, schema)
        _seed_graph(gs)
        q = (
            Query()
            .match_path(
                (Person, "p", None),
                (WorksFor, "r", None),
                (Company, "c", None),
            )
            .where("p.name = $n")
            .params(n="Alice")
            .return_("c.name AS company", "r.since AS since")
        )
        cypher, params = q.build()
        rows = gs.execute(cypher, params)
        assert rows and rows[0]["company"] == "Acme" and rows[0]["since"] == 2020


class TestRepositoryCRUD:
    def test_create_count_find(self, db: Neo4jDatabase):
        repo = Repository(Person, db)
        repo.create(Person(name="Alice", age=31))
        repo.create_many([
            {"name": "Bob", "age": 28, "email": ""},
            {"name": "Carol", "age": 45, "email": ""},
        ])
        assert repo.count() == 3
        assert len(repo.find_by(name="Alice")) == 1
        assert repo.find_one(name="Alice").age == 31

    def test_exists_returns_bool(self, db: Neo4jDatabase):
        repo = Repository(Person, db)
        repo.create(Person(name="Alice", age=31))
        assert repo.exists(name="Alice") is True
        assert repo.exists(name="NoSuchUser") is False

    def test_update_changes_value(self, db: Neo4jDatabase):
        repo = Repository(Person, db)
        repo.create(Person(name="Alice", age=31))
        repo.update({"name": "Alice"}, {"age": 32, "email": "a@y.com"})
        assert repo.find_one(name="Alice").age == 32

    def test_merge_many_upserts(self, db: Neo4jDatabase):
        repo = Repository(Person, db)
        repo.create(Person(name="Alice", age=31))
        repo.merge_many(
            [
                {"name": "Alice", "age": 33, "email": ""},
                {"name": "Dan", "age": 22, "email": ""},
            ],
            merge_keys=["name"],
        )
        assert repo.find_one(name="Alice").age == 33
        assert repo.exists(name="Dan")

    def test_delete_and_delete_all(self, db: Neo4jDatabase):
        repo = Repository(Person, db)
        repo.create_many([
            {"name": "A", "age": 1, "email": ""},
            {"name": "B", "age": 2, "email": ""},
        ])
        repo.delete(name="A")
        assert not repo.exists(name="A")
        repo.delete_all()
        assert repo.count() == 0

    def test_find_all_with_order_by(self, db: Neo4jDatabase):
        repo = Repository(Person, db)
        repo.create_many([
            {"name": "A", "age": 10, "email": ""},
            {"name": "B", "age": 5, "email": ""},
            {"name": "C", "age": 15, "email": ""},
        ])
        result = repo.find_all(order_by="age DESC")
        assert [p.age for p in result] == [15, 10, 5]


class TestBulkOpsLive:
    def test_bulk_merge_nodes_persists(self, db: Neo4jDatabase, schema: GraphSchema):
        gs = GraphSession(db, schema)
        cypher, params = BulkOps.bulk_merge_nodes(
            Person,
            [
                {"name": "Alice", "age": 31, "email": ""},
                {"name": "Bob", "age": 28, "email": ""},
            ],
            merge_keys=["name"],
        )
        gs.execute(cypher, params)
        rows = gs.execute("MATCH (p:OrmTestPerson) RETURN count(p) AS c")
        assert rows[0]["c"] == 2

    def test_bulk_merge_relationships_persists(self, db: Neo4jDatabase, schema: GraphSchema):
        gs = GraphSession(db, schema)
        _seed_graph(gs)
        rows = gs.execute("MATCH ()-[r:ORM_WORKS_FOR]->() RETURN count(r) AS c")
        assert rows[0]["c"] == 4


class TestTraversalLive:
    def test_neighbors(self, db: Neo4jDatabase, schema: GraphSchema):
        gs = GraphSession(db, schema)
        _seed_graph(gs)
        cypher, params = Traversal.neighbors(Person, "p", {"name": "Alice"})
        rows = gs.execute(cypher, params)
        names = {dict(r["neighbor"]).get("name") for r in rows if r.get("neighbor") is not None}
        assert {"Bob", "Acme", "Paris"} <= names

    def test_shortest_path_returns_distance(self, db: Neo4jDatabase, schema: GraphSchema):
        gs = GraphSession(db, schema)
        _seed_graph(gs)
        cypher, params = Traversal.shortest_path(
            Person, Person, {"name": "Alice"}, {"name": "Dan"}
        )
        rows = gs.execute(cypher, params)
        assert rows and rows[0]["distance"] >= 1

    def test_degree(self, db: Neo4jDatabase, schema: GraphSchema):
        gs = GraphSession(db, schema)
        _seed_graph(gs)
        cypher, params = Traversal.degree(Person, "p", {"name": "Alice"})
        rows = gs.execute(cypher, params)
        assert rows and rows[0]["degree"] >= 3

    def test_path_exists_returns_connected(self, db: Neo4jDatabase, schema: GraphSchema):
        gs = GraphSession(db, schema)
        _seed_graph(gs)
        cypher, params = Traversal.path_exists(
            Person, Person, {"name": "Alice"}, {"name": "Dan"}, max_depth=5
        )
        rows = gs.execute(cypher, params)
        # NOTE: column name is `connected`, NOT `path_exists`.
        assert rows and rows[0]["connected"] is True


class TestSchemaDDLDiffLive:
    def test_schema_ddl_generates_list(self, schema: GraphSchema):
        stmts = SchemaDDL(schema).generate_all()
        assert isinstance(stmts, list)

    def test_schema_diff_detects_added_labels(self):
        v1 = GraphSchema.from_models([Person, Company, WorksFor])

        class _Ext(NodeModel):
            __label__ = "OrmTestExt"
            name: str

        v2 = GraphSchema.from_models([Person, Company, _Ext, WorksFor])
        diff = SchemaDiff(v1, v2)
        assert "OrmTestExt" in diff.added_labels
        assert isinstance(diff.migration_ddl(), list)


class TestAgentToolsLive:
    def test_extended_tool_specs(self, schema: GraphSchema):
        names = {s["name"] for s in ExtendedAgentTools(schema).all_tool_specs(format="anthropic")}
        assert {"search_nodes", "find_neighbors", "find_path",
                "get_graph_schema", "bulk_create_nodes"} <= names

    def test_search_nodes_dispatch(self, db: Neo4jDatabase, schema: GraphSchema):
        gs = GraphSession(db, schema)
        gs.execute(
            "CREATE (:OrmTestPerson {name: 'Alice', age: 30, email: ''}) "
            "CREATE (:OrmTestPerson {name: 'Bob', age: 40, email: ''})"
        )
        tools = ExtendedAgentTools(schema)
        out = tools.handle_tool_call(
            "search_nodes",
            {"label": "OrmTestPerson", "filters": {"name": "Alice"}, "limit": 5},
        )
        assert out is not None
        cypher, params = out
        rows = gs.execute(cypher, params)
        names = [dict(r["n"]).get("name") for r in rows if r.get("n") is not None]
        assert "Alice" in names


class TestQueryHistoryLive:
    def test_history_records_success_and_failure(self):
        h = QueryHistory(max_entries=5)
        h.add("MATCH (n) RETURN n", {}, result_count=1)
        h.add("BAD CYPHER", {}, error="syntax error")
        assert len(h.entries) == 2
        assert len(h.successful_queries()) == 1
        assert len(h.failed_queries()) == 1
        assert "Previous Queries" in h.to_context()


class TestCypherFnLive:
    def test_aggregate_query_executes(self, db: Neo4jDatabase, schema: GraphSchema):
        gs = GraphSession(db, schema)
        _seed_graph(gs)
        total = CypherFn.count("p")
        avg_age = CypherFn.avg("p.age")
        cypher = (
            Query()
            .match(Person, "p")
            .return_(f"{total} AS total", f"{avg_age} AS avg_age")
        ).build_cypher()
        rows = gs.execute(cypher, {})
        assert rows and rows[0]["total"] == 4
        assert isinstance(rows[0]["avg_age"], (int, float))


@pytest.mark.asyncio
async def test_async_graph_session_roundtrip(
    db: Neo4jDatabase, schema: GraphSchema
):
    ags = AsyncGraphSession(db, schema)
    await ags.execute("MATCH (n) WHERE any(l IN labels(n) WHERE l STARTS WITH 'OrmTest') DETACH DELETE n")
    await ags.execute(
        "CREATE (:OrmTestPerson {name: $n, age: $a, email: ''})",
        {"n": "Eve", "a": 25},
    )
    rows = await ags.execute(
        "MATCH (p:OrmTestPerson {name: 'Eve'}) RETURN p.name AS n, p.age AS a"
    )
    assert rows and rows[0]["n"] == "Eve" and rows[0]["a"] == 25
