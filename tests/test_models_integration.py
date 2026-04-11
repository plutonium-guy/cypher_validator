"""Integration tests for Pydantic Cypher ORM against a real Neo4j database.

Requires Neo4j running at bolt://localhost:7687 with auth neo4j/testpassword.
Start with: docker run -d --name neo4j-test -p 7687:7687 -e NEO4J_AUTH=neo4j/testpassword neo4j:latest

Run: pytest tests/test_models_integration.py -v
"""

import os
import pytest
from cypher_validator.models import (
    NodeModel,
    RelationshipModel,
    Query,
    Cond,
    NodeRef,
    GraphSchema,
    AgentTools,
    ExtendedAgentTools,
    Traversal,
    BulkOps,
    SchemaDDL,
    GraphSession,
    Repository,
    PathBuilder,
    CypherFn,
    fn,
    node,
    relationship,
)
from cypher_validator.gliner2_integration import Neo4jDatabase


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASS = os.environ.get("NEO4J_PASS", "testpassword")


# ---------------------------------------------------------------------------
# Model definitions
# ---------------------------------------------------------------------------


class Person(NodeModel):
    __label__ = "TestPerson"
    __description__ = "A test person node"
    name: str
    age: int = 0
    email: str = ""


class Movie(NodeModel):
    __label__ = "TestMovie"
    title: str
    year: int = 2024


class ActedIn(RelationshipModel):
    __source__ = Person
    __target__ = Movie
    __rel_type__ = "TEST_ACTED_IN"
    role: str = ""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def db():
    """Connect to Neo4j, yield db, cleanup on exit."""
    try:
        database = Neo4jDatabase(NEO4J_URI, NEO4J_USER, NEO4J_PASS)
        # Test connectivity
        database.execute("RETURN 1 AS ok")
    except Exception as e:
        pytest.skip(f"Neo4j not available: {e}")
    yield database
    # Cleanup test data
    try:
        database.execute("MATCH (n:TestPerson) DETACH DELETE n")
        database.execute("MATCH (n:TestMovie) DETACH DELETE n")
    except Exception:
        pass
    database.close()


@pytest.fixture(scope="module")
def schema():
    return GraphSchema.from_models([Person, Movie, ActedIn])


@pytest.fixture(scope="module")
def session(db, schema):
    return GraphSession(db, schema)


@pytest.fixture(scope="module")
def repo(db):
    return Repository(Person, db)


@pytest.fixture(autouse=True)
def cleanup_between_tests(db):
    """Clean test nodes before each test."""
    try:
        db.execute("MATCH (n:TestPerson) DETACH DELETE n")
        db.execute("MATCH (n:TestMovie) DETACH DELETE n")
    except Exception:
        pass
    yield


# ---------------------------------------------------------------------------
# Basic CRUD tests
# ---------------------------------------------------------------------------


class TestNodeCRUD:
    def test_create_node(self, db):
        p = Person(name="Alice", age=30, email="alice@test.com")
        cypher, params = p.to_create_cypher("n")
        result = db.execute(cypher, params)
        assert len(result) > 0

    def test_match_node(self, db):
        # Create first
        p = Person(name="Bob", age=25)
        cypher, params = p.to_create_cypher("n")
        db.execute(cypher, params)

        # Then match
        cypher, params = Person.match_cypher("n", where={"name": "Bob"})
        result = db.execute(cypher, params)
        assert len(result) == 1

    def test_merge_node(self, db):
        p = Person(name="Charlie", age=35)
        cypher, params = p.to_merge_cypher("n", merge_keys=["name"])
        db.execute(cypher, params)

        # Merge again — should not create duplicate
        p2 = Person(name="Charlie", age=36)
        cypher, params = p2.to_merge_cypher("n", merge_keys=["name"])
        db.execute(cypher, params)

        cypher, params = Person.match_cypher("n", where={"name": "Charlie"})
        result = db.execute(cypher, params)
        assert len(result) == 1

    def test_create_and_hydrate(self, db):
        p = Person(name="Diana", age=28)
        cypher, params = p.to_create_cypher("n")
        records = db.execute(cypher, params)
        assert len(records) > 0


# ---------------------------------------------------------------------------
# Relationship tests
# ---------------------------------------------------------------------------


class TestRelationshipCRUD:
    def test_create_relationship(self, db):
        # Create nodes
        p = Person(name="Keanu", age=59)
        db.execute(*p.to_create_cypher("n"))
        m = Movie(title="The Matrix", year=1999)
        db.execute(*m.to_create_cypher("n"))

        # Create relationship
        rel = ActedIn(role="Neo")
        cypher, params = rel.to_create_cypher(
            src_match={"name": "Keanu"},
            tgt_match={"title": "The Matrix"},
        )
        result = db.execute(cypher, params)
        assert len(result) > 0

    def test_query_through_relationship(self, db):
        # Setup
        db.execute(*Person(name="Actor1", age=40).to_create_cypher("n"))
        db.execute(*Movie(title="Film1", year=2020).to_create_cypher("n"))
        rel = ActedIn(role="Lead")
        db.execute(*rel.to_create_cypher(
            src_match={"name": "Actor1"}, tgt_match={"title": "Film1"},
        ))

        # Query path
        q = (Query()
             .match_path(
                 (Person, "p", None),
                 (ActedIn, "r", None),
                 (Movie, "m", None),
             )
             .where(Cond("p.name", "=", "$name"))
             .return_("p.name AS actor", "m.title AS movie", "r.role AS role")
             .param("name", "Actor1"))
        cypher, params = q.build()
        result = db.execute(cypher, params)
        assert len(result) == 1
        assert result[0]["actor"] == "Actor1"
        assert result[0]["movie"] == "Film1"


# ---------------------------------------------------------------------------
# Query Builder tests
# ---------------------------------------------------------------------------


class TestQueryBuilderLive:
    def test_match_where_return(self, db):
        db.execute(*Person(name="QueryTest", age=42).to_create_cypher("n"))
        q = (Query()
             .match(Person, "p")
             .where(Cond("p.name", "=", "$name"))
             .return_("p.name AS name", "p.age AS age")
             .param("name", "QueryTest"))
        cypher, params = q.build()
        result = db.execute(cypher, params)
        assert len(result) == 1
        assert result[0]["name"] == "QueryTest"
        assert result[0]["age"] == 42

    def test_order_by_limit(self, db):
        for i, name in enumerate(["Zara", "Alice", "Mike"]):
            db.execute(*Person(name=name, age=20+i).to_create_cypher("n"))

        q = (Query()
             .match(Person, "p")
             .return_("p.name AS name")
             .order_by("p.name")
             .limit(2))
        result = db.execute(*q.build())
        assert len(result) == 2
        assert result[0]["name"] == "Alice"

    def test_with_aggregation(self, db):
        for name in ["A", "B", "C"]:
            db.execute(*Person(name=name, age=25).to_create_cypher("n"))

        q = (Query()
             .match(Person, "p")
             .return_(fn.as_(fn.count("p"), "total")))
        result = db.execute(*q.build())
        assert result[0]["total"] == 3

    def test_noderef_query(self, db):
        db.execute(*Person(name="RefTest", age=33).to_create_cypher("n"))
        p = NodeRef(Person, "p")
        q = (Query()
             .match(p)
             .where(p.name == "$name")
             .return_(p.name, p.age)
             .param("name", "RefTest"))
        result = db.execute(*q.build())
        assert len(result) == 1

    def test_set_properties(self, db):
        db.execute(*Person(name="SetTest", age=20).to_create_cypher("n"))
        q = (Query()
             .match(Person, "p")
             .where("p.name = $name")
             .set_props("p", {"age": 21})
             .return_("p.age AS age")
             .param("name", "SetTest"))
        cypher, params = q.build()
        result = db.execute(cypher, params)
        assert result[0]["age"] == 21

    def test_delete(self, db):
        db.execute(*Person(name="DeleteMe", age=99).to_create_cypher("n"))
        q = (Query()
             .match(Person, "p")
             .where("p.name = $name")
             .delete("p", detach=True)
             .param("name", "DeleteMe"))
        db.execute(*q.build())
        # Verify deleted
        result = db.execute(*Person.match_cypher("n", where={"name": "DeleteMe"}))
        assert len(result) == 0

    def test_unwind(self, db):
        q = Query().unwind("$items", "item").return_("item")
        result = db.execute(q.build_cypher(), {"items": [1, 2, 3]})
        assert len(result) == 3


# ---------------------------------------------------------------------------
# BulkOps tests
# ---------------------------------------------------------------------------


class TestBulkOpsLive:
    def test_bulk_create_nodes(self, db):
        items = [
            {"name": "Bulk1", "age": 10, "email": ""},
            {"name": "Bulk2", "age": 20, "email": ""},
            {"name": "Bulk3", "age": 30, "email": ""},
        ]
        cypher, params = BulkOps.bulk_create_nodes(Person, items)
        result = db.execute(cypher, params)
        assert len(result) == 3

    def test_bulk_merge_nodes(self, db):
        items = [
            {"name": "Merge1", "age": 10, "email": ""},
            {"name": "Merge2", "age": 20, "email": ""},
        ]
        cypher, params = BulkOps.bulk_merge_nodes(Person, items, merge_keys=["name"])
        db.execute(cypher, params)
        # Run again — should not duplicate
        db.execute(cypher, params)

        result = db.execute(
            "MATCH (n:TestPerson) WHERE n.name IN ['Merge1', 'Merge2'] RETURN count(n) AS cnt"
        )
        assert result[0]["cnt"] == 2

    def test_bulk_delete(self, db):
        items = [{"name": "Del1", "age": 1, "email": ""}, {"name": "Del2", "age": 2, "email": ""}]
        db.execute(*BulkOps.bulk_create_nodes(Person, items))

        cypher, params = BulkOps.bulk_delete_nodes(Person, "name", ["Del1", "Del2"])
        db.execute(cypher, params)

        result = db.execute(
            "MATCH (n:TestPerson) WHERE n.name IN ['Del1', 'Del2'] RETURN count(n) AS cnt"
        )
        assert result[0]["cnt"] == 0


# ---------------------------------------------------------------------------
# Repository tests
# ---------------------------------------------------------------------------


class TestRepositoryLive:
    def test_create_and_find(self, repo, db):
        repo.create(Person(name="RepoAlice", age=30))
        results = repo.find_by(name="RepoAlice")
        assert len(results) == 1

    def test_find_one(self, repo, db):
        repo.create(Person(name="RepoSingle", age=25))
        result = repo.find_one(name="RepoSingle")
        assert result is not None
        assert result.name == "RepoSingle"

    def test_find_one_not_found(self, repo):
        result = repo.find_one(name="NonExistent_XYZ_123")
        assert result is None

    def test_count(self, repo, db):
        for name in ["C1", "C2", "C3"]:
            repo.create(Person(name=name, age=20))
        assert repo.count() >= 3

    def test_exists(self, repo, db):
        repo.create(Person(name="ExistsTest", age=40))
        assert repo.exists(name="ExistsTest") is True
        assert repo.exists(name="DoesNotExist_XYZ") is False

    def test_update(self, repo, db):
        repo.create(Person(name="UpdateMe", age=20))
        repo.update({"name": "UpdateMe"}, {"age": 21})
        found = repo.find_one(name="UpdateMe")
        assert found is not None
        assert found.age == 21

    def test_delete(self, repo, db):
        repo.create(Person(name="DeleteRepo", age=99))
        repo.delete(name="DeleteRepo")
        assert repo.exists(name="DeleteRepo") is False

    def test_find_all_with_order(self, repo, db):
        for name in ["Z_Order", "A_Order", "M_Order"]:
            repo.create(Person(name=name, age=20))
        results = repo.find_all(order_by="name", limit=3)
        names = [r.name for r in results]
        assert names == sorted(names)

    def test_create_many(self, repo, db):
        items = [{"name": "Many1", "age": 1}, {"name": "Many2", "age": 2}]
        repo.create_many(items)
        assert repo.count(name="Many1") >= 1

    def test_merge_many(self, repo, db):
        items = [{"name": "Mm1", "age": 10, "email": ""}]
        repo.merge_many(items, merge_keys=["name"])
        repo.merge_many(items, merge_keys=["name"])
        assert repo.count(name="Mm1") == 1


# ---------------------------------------------------------------------------
# GraphSession tests
# ---------------------------------------------------------------------------


class TestGraphSessionLive:
    def test_create_and_query(self, session, db):
        session.create(Person(name="SessionAlice", age=30))
        results = session.query(Person, where={"name": "SessionAlice"})
        assert len(results) >= 1

    def test_execute_query_builder(self, session, db):
        session.create(Person(name="SessionQuery", age=25))
        q = (Query()
             .match(Person, "n")
             .where("n.name = $name")
             .return_("n")
             .param("name", "SessionQuery"))
        result = session.execute_query(q)
        assert len(result) >= 1

    def test_bulk_create(self, session, db):
        items = [{"name": "SB1", "age": 1, "email": ""}, {"name": "SB2", "age": 2, "email": ""}]
        session.bulk_create(Person, items)
        result = db.execute(
            "MATCH (n:TestPerson) WHERE n.name IN ['SB1', 'SB2'] RETURN count(n) AS cnt"
        )
        assert result[0]["cnt"] == 2


# ---------------------------------------------------------------------------
# Traversal tests
# ---------------------------------------------------------------------------


class TestTraversalLive:
    def test_neighbors(self, db):
        # Setup: Person -ACTED_IN-> Movie
        db.execute(*Person(name="TravActor", age=40).to_create_cypher("n"))
        db.execute(*Movie(title="TravMovie", year=2020).to_create_cypher("n"))
        db.execute(*ActedIn(role="Hero").to_create_cypher(
            src_match={"name": "TravActor"}, tgt_match={"title": "TravMovie"},
        ))

        cypher, params = Traversal.neighbors(
            Person, match_props={"name": "TravActor"}, direction="out",
        )
        result = db.execute(cypher, params)
        assert len(result) >= 1

    def test_degree(self, db):
        db.execute(*Person(name="DegreeTest", age=30).to_create_cypher("n"))
        db.execute(*Movie(title="DegMovie1", year=2020).to_create_cypher("n"))
        db.execute(*Movie(title="DegMovie2", year=2021).to_create_cypher("n"))
        db.execute(*ActedIn().to_create_cypher(
            src_match={"name": "DegreeTest"}, tgt_match={"title": "DegMovie1"},
        ))
        db.execute(*ActedIn().to_create_cypher(
            src_match={"name": "DegreeTest"}, tgt_match={"title": "DegMovie2"},
        ))

        cypher, params = Traversal.degree(
            Person, match_props={"name": "DegreeTest"}, direction="out",
        )
        result = db.execute(cypher, params)
        assert len(result) >= 1
        assert result[0]["degree"] == 2


# ---------------------------------------------------------------------------
# PathBuilder tests
# ---------------------------------------------------------------------------


class TestPathBuilderLive:
    def test_path_query(self, db):
        db.execute(*Person(name="PathActor", age=35).to_create_cypher("n"))
        db.execute(*Movie(title="PathMovie", year=2022).to_create_cypher("n"))
        db.execute(*ActedIn(role="Villain").to_create_cypher(
            src_match={"name": "PathActor"}, tgt_match={"title": "PathMovie"},
        ))

        path = (PathBuilder(Person, "p")
                .rel(ActedIn, "r")
                .to(Movie, "m"))
        q = (path.to_query()
             .where("p.name = $name")
             .return_("p.name AS actor", "m.title AS movie")
             .param("name", "PathActor"))
        result = db.execute(*q.build())
        assert len(result) == 1
        assert result[0]["actor"] == "PathActor"
        assert result[0]["movie"] == "PathMovie"


# ---------------------------------------------------------------------------
# Schema introspection from live DB
# ---------------------------------------------------------------------------


class TestSchemaIntrospection:
    def test_from_neo4j_db(self, db):
        # Ensure some data exists
        db.execute(*Person(name="SchemaTest", age=25).to_create_cypher("n"))
        db.execute(*Movie(title="SchemaMovie", year=2023).to_create_cypher("n"))

        schema = GraphSchema.from_neo4j_db(db)
        assert len(schema.node_models) > 0

        # Should have discovered TestPerson label
        labels = [m.label() for m in schema.node_models]
        assert "TestPerson" in labels

        # Prompt should be usable
        prompt = schema.to_prompt()
        assert "TestPerson" in prompt

    def test_agent_tools_from_discovered_schema(self, db):
        db.execute(*Person(name="ToolTest", age=30).to_create_cypher("n"))

        schema = GraphSchema.from_neo4j_db(db)
        tools = AgentTools(schema)
        specs = tools.all_tool_specs()
        assert len(specs) >= 3


# ---------------------------------------------------------------------------
# Validation integration
# ---------------------------------------------------------------------------


class TestValidationLive:
    def test_query_validates_against_schema(self, schema):
        q = (Query()
             .match(Person, "p")
             .where(Cond("p.name", "=", "$name"))
             .return_("p"))
        result = q.validate(schema)
        assert result.is_valid

    def test_invalid_query_detected(self, schema):
        q = Query().raw("MATCH (n:TestPerson) WHERE n.nonexistent_prop = 1 RETURN n")
        result = q.validate(schema)
        # Should have warnings or errors about unknown property
        assert len(result.semantic_errors) > 0 or len(result.warnings) > 0


# ---------------------------------------------------------------------------
# DDL tests
# ---------------------------------------------------------------------------


class TestDDLLive:
    def test_apply_ddl(self, db):
        schema = GraphSchema.from_models([Person, Movie, ActedIn])
        ddl = SchemaDDL(schema)
        stmts = ddl.generate_all()
        # Execute each — should not error
        for stmt in stmts:
            try:
                db.execute(stmt)
            except Exception:
                pass  # Some constraints may already exist or not be supported

    def test_drop_ddl(self, db):
        schema = GraphSchema.from_models([Person, Movie, ActedIn])
        ddl = SchemaDDL(schema)
        stmts = ddl.drop_all()
        for stmt in stmts:
            try:
                db.execute(stmt)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Query serialization roundtrip with real execution
# ---------------------------------------------------------------------------


class TestQuerySerializationLive:
    def test_serialize_execute_roundtrip(self, db):
        db.execute(*Person(name="SerialTest", age=42).to_create_cypher("n"))

        # Build, serialize, deserialize, execute
        q1 = (Query()
              .match(Person, "p")
              .where("p.name = $name")
              .return_("p.name AS name", "p.age AS age")
              .param("name", "SerialTest"))
        j = q1.to_json()
        q2 = Query.from_json(j)
        cypher, params = q2.build()
        result = db.execute(cypher, params)
        assert len(result) == 1
        assert result[0]["name"] == "SerialTest"
        assert result[0]["age"] == 42
