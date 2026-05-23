"""Integration tests for vector support — requires Docker Neo4j 5.26+.

Run: docker run -d --name neo4j-vector-test \
    -p 7474:7474 -p 7687:7687 \
    -e NEO4J_AUTH=neo4j/testtest12 \
    neo4j:5.26-community

Skip with: pytest -m "not integration"
"""

import time
import pytest
from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable

from cypher_validator.models.orm import NodeModel, VectorProperty
from cypher_validator.models.query import Query
from cypher_validator.models.schema import GraphSchema, SchemaDDL
from cypher_validator.models.session import GraphSession

NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASS = "testtest12"


class Neo4jWrapper:
    """Minimal wrapper so GraphSession.execute() works with neo4j driver."""

    def __init__(self, driver, database="neo4j"):
        self._driver = driver
        self._database = database

    def execute(self, cypher, params=None):
        with self._driver.session(database=self._database) as session:
            result = session.run(cypher, params or {})
            return [dict(r) for r in result]


def _wait_for_neo4j(uri, auth, timeout=30):
    """Wait for Neo4j to be ready."""
    driver = GraphDatabase.driver(uri, auth=auth)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            driver.verify_connectivity()
            return driver
        except (ServiceUnavailable, Exception):
            time.sleep(1)
    raise RuntimeError(f"Neo4j not ready after {timeout}s")


@pytest.fixture(scope="module")
def neo4j_driver():
    try:
        driver = _wait_for_neo4j(NEO4J_URI, (NEO4J_USER, NEO4J_PASS), timeout=30)
    except RuntimeError:
        pytest.skip(
            "Neo4j not available — start with: docker run -d --name neo4j-vector-test "
            "-p 7474:7474 -p 7687:7687 -e NEO4J_AUTH=neo4j/testtest12 neo4j:5.26-community"
        )
    yield driver
    driver.close()


@pytest.fixture(autouse=True)
def clean_db(neo4j_driver):
    """Clean up test data before each test."""
    with neo4j_driver.session() as session:
        session.run("MATCH (n:TestDoc) DETACH DELETE n")
    yield
    with neo4j_driver.session() as session:
        session.run("MATCH (n:TestDoc) DETACH DELETE n")


class TestDoc(NodeModel):
    __label__ = "TestDoc"
    __vector_indexes__ = {
        "embedding": VectorProperty(dimensions=3, similarity="cosine"),
    }
    title: str
    embedding: list[float] = []


@pytest.mark.integration
class TestVectorIntegration:
    def test_create_vector_index(self, neo4j_driver):
        schema = GraphSchema.from_models([TestDoc])
        ddl = SchemaDDL(schema)
        stmts = ddl.vector_indexes()
        assert len(stmts) == 1
        with neo4j_driver.session() as session:
            session.run(stmts[0])
        time.sleep(2)
        with neo4j_driver.session() as session:
            result = session.run(
                "SHOW INDEXES YIELD name WHERE name = 'idx_testdoc_embedding_vector' RETURN name"
            )
            names = [r["name"] for r in result]
            assert "idx_testdoc_embedding_vector" in names

    def test_insert_and_vector_search(self, neo4j_driver):
        schema = GraphSchema.from_models([TestDoc])
        ddl = SchemaDDL(schema)

        with neo4j_driver.session() as session:
            for stmt in ddl.vector_indexes():
                session.run(stmt)

        db = Neo4jWrapper(neo4j_driver)
        gs = GraphSession(db, schema)

        gs.create(TestDoc(title="cats", embedding=[1.0, 0.0, 0.0]))
        gs.create(TestDoc(title="dogs", embedding=[0.9, 0.1, 0.0]))
        gs.create(TestDoc(title="planes", embedding=[0.0, 0.0, 1.0]))

        time.sleep(3)

        q = (Query()
             .vector_search("idx_testdoc_embedding_vector", [1.0, 0.0, 0.0], top_k=2)
             .return_("node", "score"))
        cypher, params = q.build()
        records = db.execute(cypher, params)
        assert len(records) == 2
        titles = [dict(r["node"])["title"] for r in records]
        assert titles[0] == "cats"
        assert titles[1] == "dogs"

    def test_graph_session_vector_search(self, neo4j_driver):
        schema = GraphSchema.from_models([TestDoc])
        ddl = SchemaDDL(schema)

        with neo4j_driver.session() as session:
            for stmt in ddl.vector_indexes():
                session.run(stmt)

        db = Neo4jWrapper(neo4j_driver)
        gs = GraphSession(db, schema)

        gs.create(TestDoc(title="alpha", embedding=[1.0, 0.0, 0.0]))
        gs.create(TestDoc(title="beta", embedding=[0.0, 1.0, 0.0]))

        time.sleep(3)

        results = gs.vector_search(TestDoc, "embedding", [1.0, 0.0, 0.0], top_k=1)
        assert len(results) == 1
        assert results[0]["node"].title == "alpha"
        assert results[0]["score"] > 0.9

    def test_semantic_search_with_mock_embedder(self, neo4j_driver):
        schema = GraphSchema.from_models([TestDoc])
        ddl = SchemaDDL(schema)

        with neo4j_driver.session() as session:
            for stmt in ddl.vector_indexes():
                session.run(stmt)

        db = Neo4jWrapper(neo4j_driver)
        gs = GraphSession(db, schema)

        gs.create(TestDoc(title="python", embedding=[0.8, 0.2, 0.0]))
        gs.create(TestDoc(title="rust", embedding=[0.0, 0.8, 0.2]))

        time.sleep(3)

        def mock_embed(text: str) -> list[float]:
            return [0.8, 0.2, 0.0]

        results = gs.semantic_search(TestDoc, "embedding", "python programming", mock_embed, top_k=1)
        assert len(results) == 1
        assert results[0]["node"].title == "python"
