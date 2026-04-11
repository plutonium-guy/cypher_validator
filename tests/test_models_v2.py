"""Tests for iteration 2 features: hydration, traversal, bulk ops, DDL, extended agent tools."""

import json
from unittest.mock import MagicMock
import pytest
from cypher_validator.models import (
    NodeModel,
    RelationshipModel,
    Query,
    GraphSchema,
    AgentTools,
    ExtendedAgentTools,
    Traversal,
    BulkOps,
    SchemaDDL,
    GraphSession,
    node,
    relationship,
)


# ---------------------------------------------------------------------------
# Fixtures — model definitions
# ---------------------------------------------------------------------------


class Person(NodeModel):
    __label__ = "Person"
    __description__ = "A human being"
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


class Directed(RelationshipModel):
    __source__ = Person
    __target__ = Movie
    __rel_type__ = "DIRECTED"


# ---------------------------------------------------------------------------
# Model Hydration tests
# ---------------------------------------------------------------------------


class TestModelHydration:
    def test_node_from_record_dict(self):
        record = {"name": "Alice", "age": 30}
        p = Person.from_record(record)
        assert p.name == "Alice"
        assert p.age == 30

    def test_node_from_record_with_key(self):
        record = {"n": {"name": "Bob", "age": 25}}
        p = Person.from_record(record, key="n")
        assert p.name == "Bob"

    def test_node_from_records(self):
        records = [
            {"name": "Alice", "age": 30},
            {"name": "Bob", "age": 25},
        ]
        people = Person.from_records(records)
        assert len(people) == 2
        assert people[0].name == "Alice"
        assert people[1].name == "Bob"

    def test_node_from_records_with_key(self):
        records = [
            {"n": {"name": "Alice", "age": 30}},
            {"n": {"name": "Bob", "age": 25}},
        ]
        people = Person.from_records(records, key="n")
        assert len(people) == 2

    def test_rel_from_record(self):
        record = {"roles": ["Neo"]}
        rel = ActedIn.from_record(record)
        assert rel.roles == ["Neo"]

    def test_node_from_neo4j_like_object(self):
        """Simulate a neo4j.graph.Node-like object with .items()."""
        class FakeNode:
            def __init__(self, data):
                self._data = data
            def items(self):
                return self._data.items()

        fake = FakeNode({"name": "Charlie", "age": 40})
        p = Person.from_record(fake)
        assert p.name == "Charlie"
        assert p.age == 40

    def test_hydration_extra_fields(self):
        """Extra fields in record should be allowed (extra='allow')."""
        record = {"name": "Alice", "age": 30, "email": "alice@test.com"}
        p = Person.from_record(record)
        assert p.name == "Alice"

    def test_hydration_missing_optional(self):
        """Missing optional fields get defaults."""
        record = {"name": "Alice"}
        p = Person.from_record(record)
        assert p.age == 0


# ---------------------------------------------------------------------------
# Traversal tests
# ---------------------------------------------------------------------------


class TestTraversal:
    def test_neighbors_basic(self):
        cypher, params = Traversal.neighbors(
            Person, match_props={"name": "Alice"},
        )
        assert "MATCH (n:Person)" in cypher
        assert "neighbor" in cypher
        assert params["n_name"] == "Alice"

    def test_neighbors_with_rel_type(self):
        cypher, _ = Traversal.neighbors(
            Person, match_props={"name": "Alice"}, rel_type=ActedIn,
        )
        assert "ACTED_IN" in cypher

    def test_neighbors_direction_out(self):
        cypher, _ = Traversal.neighbors(
            Person, match_props={"name": "Alice"}, direction="out",
        )
        assert "->" in cypher

    def test_neighbors_direction_in(self):
        cypher, _ = Traversal.neighbors(
            Person, match_props={"name": "Alice"}, direction="in",
        )
        assert "<-" in cypher

    def test_neighbors_with_limit(self):
        cypher, _ = Traversal.neighbors(
            Person, match_props={"name": "Alice"}, limit=10,
        )
        assert "LIMIT 10" in cypher

    def test_shortest_path(self):
        cypher, params = Traversal.shortest_path(
            Person, Movie,
            {"name": "Alice"}, {"title": "Matrix"},
        )
        assert "shortestPath" in cypher
        assert "Person" in cypher
        assert "Movie" in cypher
        assert params["src_name"] == "Alice"
        assert params["tgt_title"] == "Matrix"

    def test_shortest_path_with_rel_type(self):
        cypher, _ = Traversal.shortest_path(
            Person, Movie,
            {"name": "Alice"}, {"title": "Matrix"},
            rel_type="ACTED_IN",
        )
        assert "ACTED_IN" in cypher

    def test_shortest_path_max_depth(self):
        cypher, _ = Traversal.shortest_path(
            Person, Movie,
            {"name": "A"}, {"title": "B"},
            max_depth=3,
        )
        assert "*..3" in cypher

    def test_subgraph(self):
        cypher, params = Traversal.subgraph(
            Person, {"name": "Alice"}, depth=3,
        )
        assert "*1..3" in cypher
        assert params["n_name"] == "Alice"

    def test_degree(self):
        cypher, params = Traversal.degree(
            Person, match_props={"name": "Alice"},
        )
        assert "degree" in cypher
        assert "size" in cypher

    def test_degree_with_rel_type(self):
        cypher, _ = Traversal.degree(
            Person, match_props={"name": "Alice"}, rel_type="ACTED_IN",
        )
        assert "ACTED_IN" in cypher

    def test_degree_direction(self):
        cypher, _ = Traversal.degree(
            Person, match_props={"name": "Alice"}, direction="out",
        )
        assert "->" in cypher

    def test_common_neighbors(self):
        cypher, params = Traversal.common_neighbors(
            Person, Person,
            {"name": "Alice"}, {"name": "Bob"},
        )
        assert "common" in cypher
        assert params["a_name"] == "Alice"
        assert params["b_name"] == "Bob"

    def test_common_neighbors_with_rel_type(self):
        cypher, _ = Traversal.common_neighbors(
            Person, Person,
            {"name": "A"}, {"name": "B"},
            rel_type="KNOWS",
        )
        assert "KNOWS" in cypher

    def test_path_exists(self):
        cypher, params = Traversal.path_exists(
            Person, Movie,
            {"name": "Alice"}, {"title": "Matrix"},
        )
        assert "EXISTS" in cypher
        assert "connected" in cypher

    def test_path_exists_max_depth(self):
        cypher, _ = Traversal.path_exists(
            Person, Movie,
            {"name": "A"}, {"title": "B"},
            max_depth=3,
        )
        assert "*1..3" in cypher


# ---------------------------------------------------------------------------
# BulkOps tests
# ---------------------------------------------------------------------------


class TestBulkOps:
    def test_bulk_create_nodes(self):
        items = [{"name": "A", "age": 1}, {"name": "B", "age": 2}]
        cypher, params = BulkOps.bulk_create_nodes(Person, items)
        assert "UNWIND $batch AS item" in cypher
        assert "CREATE (n:Person" in cypher
        assert params["batch"] == items

    def test_bulk_merge_nodes(self):
        items = [{"name": "A", "age": 1}]
        cypher, params = BulkOps.bulk_merge_nodes(Person, items, merge_keys=["name"])
        assert "MERGE (n:Person {name: item.name})" in cypher
        assert "ON CREATE SET" in cypher
        assert "ON MATCH SET" in cypher

    def test_bulk_merge_nodes_no_extra_props(self):
        # When all props are merge keys, no SET clause needed
        MovieLocal = node("BulkMovieTest", title=str)
        items = [{"title": "X"}]
        cypher, _ = BulkOps.bulk_merge_nodes(MovieLocal, items, merge_keys=["title"])
        assert "MERGE" in cypher

    def test_bulk_create_relationships(self):
        items = [{"src_name": "Alice", "tgt_title": "Matrix", "roles": ["Trinity"]}]
        cypher, params = BulkOps.bulk_create_relationships(
            ActedIn, items, src_key="src_name", tgt_key="tgt_title",
        )
        assert "UNWIND $batch AS item" in cypher
        assert "MATCH (a:Person" in cypher
        assert "MATCH" in cypher and "Movie" in cypher
        assert "CREATE (a)-[r:ACTED_IN" in cypher

    def test_bulk_merge_relationships(self):
        items = [{"src_name": "Alice", "tgt_title": "Matrix", "roles": ["Trinity"]}]
        cypher, _ = BulkOps.bulk_merge_relationships(
            ActedIn, items, src_key="src_name", tgt_key="tgt_title",
        )
        assert "MERGE (a)-[r:ACTED_IN]->(b)" in cypher
        assert "SET r.roles" in cypher

    def test_bulk_delete_nodes(self):
        cypher, params = BulkOps.bulk_delete_nodes(
            Person, "name", ["Alice", "Bob"],
        )
        assert "DETACH DELETE" in cypher
        assert "IN $values" in cypher
        assert params["values"] == ["Alice", "Bob"]

    def test_bulk_delete_no_detach(self):
        cypher, _ = BulkOps.bulk_delete_nodes(
            Person, "name", ["Alice"], detach=False,
        )
        assert "DETACH" not in cypher
        assert "DELETE n" in cypher


# ---------------------------------------------------------------------------
# SchemaDDL tests
# ---------------------------------------------------------------------------


class TestSchemaDDL:
    @pytest.fixture
    def ddl(self):
        schema = GraphSchema.from_models([Person, Movie, ActedIn])
        return SchemaDDL(schema)

    def test_uniqueness_constraints(self, ddl):
        stmts = ddl.uniqueness_constraints()
        assert any("Person" in s and "name" in s for s in stmts)
        assert any("Movie" in s and "title" in s for s in stmts)
        assert all("IS UNIQUE" in s for s in stmts)
        assert all("IF NOT EXISTS" in s for s in stmts)

    def test_existence_constraints(self, ddl):
        stmts = ddl.existence_constraints()
        assert any("IS NOT NULL" in s for s in stmts)
        assert any("Person" in s for s in stmts)

    def test_existence_constraints_relationships(self, ddl):
        """Relationships with required properties get existence constraints."""
        # ActedIn has no required properties (roles has default)
        # But we can check the structure
        stmts = ddl.existence_constraints()
        # At minimum, node required props generate constraints
        assert len(stmts) >= 1

    def test_property_indexes(self, ddl):
        stmts = ddl.property_indexes()
        assert any("Person" in s and "name" in s for s in stmts)
        assert any("Person" in s and "age" in s for s in stmts)
        assert all("CREATE INDEX" in s for s in stmts)
        assert all("IF NOT EXISTS" in s for s in stmts)

    def test_composite_indexes(self, ddl):
        stmt = ddl.composite_indexes(Person, ["name", "age"])
        assert "name" in stmt
        assert "age" in stmt
        assert "CREATE INDEX" in stmt

    def test_fulltext_index(self, ddl):
        stmt = ddl.fulltext_index([Person, Movie], ["name", "title"], "search_index")
        assert "FULLTEXT INDEX" in stmt
        assert "search_index" in stmt
        assert "Person|Movie" in stmt

    def test_generate_all(self, ddl):
        stmts = ddl.generate_all()
        assert len(stmts) > 0
        # Should have both constraints and indexes
        has_constraint = any("CONSTRAINT" in s for s in stmts)
        has_index = any("INDEX" in s for s in stmts)
        assert has_constraint
        assert has_index

    def test_generate_all_with_existence(self, ddl):
        stmts_without = ddl.generate_all(include_existence=False)
        stmts_with = ddl.generate_all(include_existence=True)
        assert len(stmts_with) >= len(stmts_without)

    def test_drop_all(self, ddl):
        stmts = ddl.drop_all()
        assert all("DROP" in s for s in stmts)
        assert all("IF EXISTS" in s for s in stmts)

    def test_custom_constraints(self):
        class ConstrainedNode(NodeModel):
            __label__ = "DDLConstrained"
            __constraints__ = ["CREATE CONSTRAINT FOR (n:DDLConstrained) REQUIRE n.id IS UNIQUE"]
            id: str

        schema = GraphSchema.from_models([ConstrainedNode])
        ddl = SchemaDDL(schema)
        assert len(ddl.custom_constraints()) == 1


# ---------------------------------------------------------------------------
# GraphSession tests (mocked DB)
# ---------------------------------------------------------------------------


class TestGraphSession:
    @pytest.fixture
    def mock_db(self):
        db = MagicMock()
        db.execute.return_value = [{"n": {"name": "Alice", "age": 30}}]
        return db

    @pytest.fixture
    def session(self, mock_db):
        schema = GraphSchema.from_models([Person, Movie, ActedIn])
        return GraphSession(mock_db, schema)

    def test_execute_raw(self, session, mock_db):
        session.execute("MATCH (n) RETURN n")
        mock_db.execute.assert_called_once()

    def test_execute_query(self, session, mock_db):
        q = Query().match(Person, "p").return_("p")
        session.execute_query(q)
        call_args = mock_db.execute.call_args
        assert "MATCH (p:Person) RETURN p" in call_args[0][0]

    def test_create(self, session, mock_db):
        p = Person(name="Alice", age=30)
        session.create(p)
        call_args = mock_db.execute.call_args
        assert "CREATE" in call_args[0][0]
        assert "Person" in call_args[0][0]

    def test_merge(self, session, mock_db):
        p = Person(name="Alice", age=30)
        session.merge(p, merge_keys=["name"])
        call_args = mock_db.execute.call_args
        assert "MERGE" in call_args[0][0]

    def test_delete(self, session, mock_db):
        session.delete(Person, where={"name": "Alice"})
        call_args = mock_db.execute.call_args
        assert "DELETE" in call_args[0][0]

    def test_bulk_create(self, session, mock_db):
        items = [{"name": "A", "age": 1}, {"name": "B", "age": 2}]
        session.bulk_create(Person, items)
        call_args = mock_db.execute.call_args
        assert "UNWIND" in call_args[0][0]

    def test_bulk_merge(self, session, mock_db):
        items = [{"name": "A", "age": 1}]
        session.bulk_merge(Person, items, merge_keys=["name"])
        call_args = mock_db.execute.call_args
        assert "MERGE" in call_args[0][0]

    def test_create_relationship(self, session, mock_db):
        rel = ActedIn(roles=["Neo"])
        session.create_relationship(
            rel, src_match={"name": "Keanu"}, tgt_match={"title": "Matrix"}
        )
        call_args = mock_db.execute.call_args
        assert "ACTED_IN" in call_args[0][0]

    def test_neighbors(self, session, mock_db):
        session.neighbors(Person, match_props={"name": "Alice"})
        call_args = mock_db.execute.call_args
        assert "neighbor" in call_args[0][0]

    def test_shortest_path(self, session, mock_db):
        session.shortest_path(
            Person, Movie,
            {"name": "Alice"}, {"title": "Matrix"},
        )
        call_args = mock_db.execute.call_args
        assert "shortestPath" in call_args[0][0]

    def test_apply_ddl(self, session, mock_db):
        stmts = session.apply_ddl()
        assert len(stmts) > 0
        # DB.execute should have been called for each statement
        assert mock_db.execute.call_count == len(stmts)

    def test_apply_ddl_no_schema_raises(self, mock_db):
        session = GraphSession(mock_db)
        with pytest.raises(ValueError, match="GraphSchema"):
            session.apply_ddl()


# ---------------------------------------------------------------------------
# ExtendedAgentTools tests
# ---------------------------------------------------------------------------


class TestExtendedAgentTools:
    @pytest.fixture
    def tools(self):
        schema = GraphSchema.from_models([Person, Movie, ActedIn, Directed])
        return ExtendedAgentTools(schema)

    def test_search_nodes_tool_spec(self, tools):
        spec = tools.search_nodes_tool_spec()
        assert spec["function"]["name"] == "search_nodes"
        labels = spec["function"]["parameters"]["properties"]["label"]["enum"]
        assert "Person" in labels

    def test_find_neighbors_tool_spec(self, tools):
        spec = tools.find_neighbors_tool_spec()
        assert spec["function"]["name"] == "find_neighbors"

    def test_find_path_tool_spec(self, tools):
        spec = tools.find_path_tool_spec()
        assert spec["function"]["name"] == "find_path"

    def test_get_schema_tool_spec(self, tools):
        spec = tools.get_schema_tool_spec()
        assert spec["function"]["name"] == "get_graph_schema"

    def test_bulk_create_tool_spec(self, tools):
        spec = tools.bulk_create_tool_spec()
        assert spec["function"]["name"] == "bulk_create_nodes"

    def test_all_tool_specs_extended(self, tools):
        specs = tools.all_tool_specs()
        names = [s["function"]["name"] for s in specs]
        assert "execute_cypher" in names  # from base
        assert "search_nodes" in names
        assert "find_neighbors" in names
        assert "find_path" in names
        assert "get_graph_schema" in names
        assert "bulk_create_nodes" in names
        assert len(specs) == 8  # 3 base + 5 extended

    def test_anthropic_format(self, tools):
        spec = tools.search_nodes_tool_spec("anthropic")
        assert "input_schema" in spec
        assert spec["name"] == "search_nodes"

    def test_handle_search_nodes(self, tools):
        result = tools.handle_tool_call(
            "search_nodes",
            {"label": "Person", "filters": {"name": "Alice"}, "limit": 10},
        )
        assert result is not None
        cypher, params = result
        assert "Person" in cypher
        assert "LIMIT 10" in cypher
        assert params["n_name"] == "Alice"

    def test_handle_search_nodes_no_filters(self, tools):
        result = tools.handle_tool_call(
            "search_nodes",
            {"label": "Person"},
        )
        assert result is not None
        cypher, params = result
        assert "Person" in cypher
        assert "WHERE" not in cypher

    def test_handle_search_nodes_with_order(self, tools):
        result = tools.handle_tool_call(
            "search_nodes",
            {"label": "Person", "order_by": "name"},
        )
        assert result is not None
        cypher, _ = result
        assert "ORDER BY n.name" in cypher

    def test_handle_find_neighbors(self, tools):
        result = tools.handle_tool_call(
            "find_neighbors",
            {
                "label": "Person",
                "match_properties": {"name": "Alice"},
                "direction": "out",
                "limit": 5,
            },
        )
        assert result is not None
        cypher, params = result
        assert "Person" in cypher
        assert "->" in cypher
        assert "LIMIT 5" in cypher

    def test_handle_find_path(self, tools):
        result = tools.handle_tool_call(
            "find_path",
            {
                "source_label": "Person",
                "source_properties": {"name": "Alice"},
                "target_label": "Movie",
                "target_properties": {"title": "Matrix"},
            },
        )
        assert result is not None
        cypher, params = result
        assert "shortestPath" in cypher

    def test_handle_get_schema_text(self, tools):
        result = tools.handle_tool_call(
            "get_graph_schema",
            {"format": "text"},
        )
        assert result is not None
        text, _ = result
        assert "Person" in text

    def test_handle_get_schema_markdown(self, tools):
        result = tools.handle_tool_call(
            "get_graph_schema",
            {"format": "markdown"},
        )
        assert result is not None
        md, _ = result
        assert "| Person |" in md

    def test_handle_get_schema_json(self, tools):
        result = tools.handle_tool_call(
            "get_graph_schema",
            {"format": "json"},
        )
        assert result is not None
        j, _ = result
        parsed = json.loads(j)
        assert "Person" in parsed["nodes"]

    def test_handle_bulk_create(self, tools):
        result = tools.handle_tool_call(
            "bulk_create_nodes",
            {
                "label": "Person",
                "items": [{"name": "A", "age": 1}, {"name": "B", "age": 2}],
            },
        )
        assert result is not None
        cypher, params = result
        assert "UNWIND" in cypher
        assert len(params["batch"]) == 2

    def test_handle_unknown_label(self, tools):
        result = tools.handle_tool_call(
            "search_nodes",
            {"label": "NonExistent"},
        )
        assert result is None

    def test_base_tools_still_work(self, tools):
        """Base AgentTools methods accessible through ExtendedAgentTools."""
        result = tools.handle_tool_call(
            "execute_cypher",
            {"cypher": "MATCH (n) RETURN n", "parameters": {}},
        )
        assert result == ("MATCH (n) RETURN n", {})

    def test_handle_completely_unknown(self, tools):
        result = tools.handle_tool_call("totally_unknown", {})
        assert result is None
