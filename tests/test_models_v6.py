"""Tests for iteration 6: Query serialization, GraphSchema.from_dict/from_neo4j_db."""

import json
from unittest.mock import MagicMock
import pytest
from cypher_validator.models import (
    NodeModel,
    RelationshipModel,
    Query,
    Cond,
    GraphSchema,
    node,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Query Serialization tests
# ---------------------------------------------------------------------------


class TestQuerySerialization:
    def test_to_dict(self):
        q = (Query()
             .match(Person, "p")
             .where(Cond("p.age", ">", 18))
             .return_("p"))
        d = q.to_dict()
        assert "cypher" in d
        assert "parameters" in d
        assert "clauses" in d
        assert "Person" in d["cypher"]

    def test_to_json(self):
        q = Query().match(Person, "p").return_("p")
        j = q.to_json()
        parsed = json.loads(j)
        assert "cypher" in parsed
        assert "Person" in parsed["cypher"]

    def test_from_dict_with_clauses(self):
        q1 = (Query()
              .match(Person, "p")
              .where("p.age > 18")
              .return_("p"))
        d = q1.to_dict()
        q2 = Query.from_dict(d)
        assert q2.build_cypher() == q1.build_cypher()

    def test_from_dict_with_params(self):
        q1 = (Query()
              .match(Person, "p")
              .return_("p")
              .param("limit", 10))
        d = q1.to_dict()
        q2 = Query.from_dict(d)
        _, params = q2.build()
        assert params["limit"] == 10

    def test_from_dict_raw_cypher(self):
        d = {"cypher": "MATCH (n) RETURN n", "parameters": {"x": 1}}
        q = Query.from_dict(d)
        cypher, params = q.build()
        assert cypher == "MATCH (n) RETURN n"
        assert params == {"x": 1}

    def test_from_json(self):
        q1 = Query().match(Person, "p").return_("p")
        j = q1.to_json()
        q2 = Query.from_json(j)
        assert q2.build_cypher() == q1.build_cypher()

    def test_roundtrip(self):
        q1 = (Query()
              .match(Person, "p")
              .where(Cond("p.name", "=", "$name"))
              .return_("p.name", "p.age")
              .order_by("p.name")
              .limit(10)
              .param("name", "Alice"))
        j = q1.to_json()
        q2 = Query.from_json(j)
        c1, p1 = q1.build()
        c2, p2 = q2.build()
        assert c1 == c2
        assert p1 == p2

    def test_empty_query_serialization(self):
        q = Query()
        d = q.to_dict()
        assert d["cypher"] == ""
        assert d["parameters"] == {}
        q2 = Query.from_dict(d)
        assert q2.build_cypher() == ""


# ---------------------------------------------------------------------------
# GraphSchema.from_dict tests
# ---------------------------------------------------------------------------


class TestGraphSchemaFromDict:
    def test_basic(self):
        schema = GraphSchema.from_dict({
            "nodes": {
                "Person": ["name", "age"],
                "Movie": ["title", "year"],
            },
            "relationships": {
                "ACTED_IN": ["Person", "Movie", ["roles"]],
            },
        })
        assert len(schema.node_models) == 2
        assert len(schema.rel_models) == 1

    def test_node_labels(self):
        schema = GraphSchema.from_dict({
            "nodes": {"Foo": ["x", "y"]},
        })
        assert schema.node_models[0].label() == "Foo"
        assert "x" in schema.node_models[0].property_names()

    def test_rel_types(self):
        schema = GraphSchema.from_dict({
            "nodes": {"A": ["id"], "B": ["id"]},
            "relationships": {"CONNECTS": ["A", "B", ["weight"]]},
        })
        assert schema.rel_models[0].rel_type() == "CONNECTS"
        assert schema.rel_models[0].source_label() == "A"
        assert schema.rel_models[0].target_label() == "B"

    def test_no_relationships(self):
        schema = GraphSchema.from_dict({
            "nodes": {"X": ["a"]},
        })
        assert len(schema.node_models) == 1
        assert len(schema.rel_models) == 0

    def test_empty_dict(self):
        schema = GraphSchema.from_dict({})
        assert len(schema.node_models) == 0
        assert len(schema.rel_models) == 0

    def test_roundtrip(self):
        """from_dict(to_dict()) should produce equivalent schema."""
        original = GraphSchema.from_models([Person, Movie, ActedIn])
        d = original.to_dict()
        # Convert tuples to lists for from_dict compatibility
        rels = {}
        for k, v in d["relationships"].items():
            rels[k] = list(v)
        reconstructed = GraphSchema.from_dict({"nodes": d["nodes"], "relationships": rels})
        assert len(reconstructed.node_models) == len(original.node_models)
        assert len(reconstructed.rel_models) == len(original.rel_models)

    def test_generates_usable_models(self):
        """Dynamic models from from_dict should be usable in Query builder."""
        schema = GraphSchema.from_dict({
            "nodes": {"Widget": ["name", "color"]},
        })
        WidgetModel = schema.node_models[0]
        q = Query().match(WidgetModel, "w").return_("w")
        cypher, _ = q.build()
        assert "(w:Widget)" in cypher

    def test_to_prompt_after_from_dict(self):
        schema = GraphSchema.from_dict({
            "nodes": {"Car": ["make", "model"]},
            "relationships": {"OWNS": ["Person", "Car", []]},
        })
        # Person doesn't exist in this schema, so rel won't be created
        prompt = schema.to_prompt()
        assert "Car" in prompt

    def test_rel_with_no_props(self):
        schema = GraphSchema.from_dict({
            "nodes": {"A": ["id"], "B": ["id"]},
            "relationships": {"LINKS": ["A", "B"]},
        })
        assert len(schema.rel_models) == 1
        assert schema.rel_models[0].property_names() == []


# ---------------------------------------------------------------------------
# GraphSchema.from_neo4j_db tests (mocked)
# ---------------------------------------------------------------------------


class TestGraphSchemaFromNeo4jDb:
    def test_with_introspect_schema(self):
        """When db has introspect_schema, use it."""
        mock_db = MagicMock()
        mock_schema = MagicMock()
        mock_schema.to_dict.return_value = {
            "nodes": {"User": ["email", "name"]},
            "relationships": {"FOLLOWS": ("User", "User", ["since"])},
        }
        mock_db.introspect_schema.return_value = mock_schema

        schema = GraphSchema.from_neo4j_db(mock_db)
        assert len(schema.node_models) == 1
        assert schema.node_models[0].label() == "User"

    def test_fallback_cypher_introspection(self):
        """When no introspect_schema, fall back to Cypher queries."""
        mock_db = MagicMock()
        del mock_db.introspect_schema  # Force fallback path

        # Mock execute for label discovery
        def mock_execute(cypher, params=None):
            if "db.labels" in cypher:
                return [{"label": "Item"}]
            if "keys(n)" in cypher:
                return [{"props": ["name", "price"]}]
            if "db.relationshipTypes" in cypher:
                return [{"relationshipType": "CONTAINS"}]
            if "labels(a)" in cypher:
                return [{"src": "Item", "tgt": "Item", "props": ["qty"]}]
            return []

        mock_db.execute = mock_execute

        schema = GraphSchema.from_neo4j_db(mock_db)
        assert len(schema.node_models) >= 1
        assert schema.node_models[0].label() == "Item"

    def test_empty_db(self):
        """Empty database should return empty schema."""
        mock_db = MagicMock()
        # Remove introspect_schema so it falls back to Cypher
        del mock_db.introspect_schema
        mock_db.execute.return_value = []

        schema = GraphSchema.from_neo4j_db(mock_db)
        assert len(schema.node_models) == 0
        assert len(schema.rel_models) == 0


# ---------------------------------------------------------------------------
# Integration: serialize → agent → deserialize
# ---------------------------------------------------------------------------


class TestAgentWorkflow:
    def test_query_passed_between_agents(self):
        """Simulate: Agent A builds query, serializes, Agent B deserializes and validates."""
        # Agent A builds
        q = (Query()
             .match(Person, "p")
             .where(Cond("p.age", ">", 18))
             .return_("p.name")
             .limit(5)
             .param("min_age", 18))
        message = q.to_json()

        # Agent B receives
        q2 = Query.from_json(message)
        cypher, params = q2.build()
        assert "Person" in cypher
        assert "p.age > 18" in cypher
        assert params["min_age"] == 18

    def test_schema_discovery_then_query(self):
        """Simulate: discover schema from DB, build query, validate."""
        schema = GraphSchema.from_dict({
            "nodes": {
                "Customer": ["id", "name", "email"],
                "Product": ["id", "name", "price"],
            },
            "relationships": {
                "PURCHASED": ["Customer", "Product", ["date", "quantity"]],
            },
        })
        Customer = schema.node_models[0]
        Product = schema.node_models[1]

        q = (Query()
             .match(Customer, "c")
             .return_("c.name", "c.email")
             .limit(10))
        cypher, _ = q.build()
        assert "(c:Customer)" in cypher

        # Schema prompt should be useful for agents
        prompt = schema.to_prompt()
        assert "Customer" in prompt
        assert "Product" in prompt
        assert "PURCHASED" in prompt
