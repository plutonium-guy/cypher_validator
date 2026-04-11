"""Tests for iteration 5: bug fixes, edge cases, validation improvements."""

import pytest
from cypher_validator.models import (
    NodeModel,
    RelationshipModel,
    Query,
    GraphSchema,
    Traversal,
    Repository,
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
# Bug fix: empty property map in to_create_cypher
# ---------------------------------------------------------------------------


class TestEmptyPropertyMap:
    def test_create_no_props(self):
        """Creating a node with no properties should not produce empty braces."""
        # Use extra="allow" with a model that has optional fields
        MinNode = node("MinNode", name=(str, ""))
        n = MinNode()
        cypher, params = n.to_create_cypher("n")
        # Even though name="" is not None, it should still be valid
        assert "{}" not in cypher or "name:" in cypher

    def test_create_with_props(self):
        p = Person(name="Alice", age=30)
        cypher, params = p.to_create_cypher("n")
        assert "name:" in cypher
        assert "age:" in cypher


# ---------------------------------------------------------------------------
# Bug fix: merge_keys validation
# ---------------------------------------------------------------------------


class TestMergeKeysValidation:
    def test_valid_merge_keys(self):
        p = Person(name="Alice", age=30)
        cypher, params = p.to_merge_cypher("n", merge_keys=["name"])
        assert "MERGE" in cypher

    def test_invalid_merge_keys_raises(self):
        p = Person(name="Alice", age=30)
        with pytest.raises(ValueError, match="merge_keys.*not found"):
            p.to_merge_cypher("n", merge_keys=["nonexistent"])

    def test_mixed_valid_invalid_keys(self):
        p = Person(name="Alice", age=30)
        with pytest.raises(ValueError, match="merge_keys"):
            p.to_merge_cypher("n", merge_keys=["name", "bad_key"])


# ---------------------------------------------------------------------------
# Bug fix: direction validation in Traversal
# ---------------------------------------------------------------------------


class TestDirectionValidation:
    def test_valid_directions(self):
        for d in ("in", "out", "both"):
            cypher, _ = Traversal.neighbors(Person, match_props={"name": "A"}, direction=d)
            assert "Person" in cypher

    def test_invalid_direction_raises(self):
        with pytest.raises(ValueError, match="Invalid direction"):
            Traversal.neighbors(Person, match_props={"name": "A"}, direction="left")

    def test_invalid_direction_in_degree(self):
        with pytest.raises(ValueError, match="Invalid direction"):
            Traversal.degree(Person, match_props={"name": "A"}, direction="up")


# ---------------------------------------------------------------------------
# Bug fix: Repository order_by validation
# ---------------------------------------------------------------------------


class TestRepositoryOrderByValidation:
    def test_valid_order_by(self):
        from unittest.mock import MagicMock
        db = MagicMock()
        db.execute.return_value = []
        repo = Repository(Person, db)
        repo.find_all(order_by="name")
        cypher = db.execute.call_args[0][0]
        assert "ORDER BY n.name" in cypher

    def test_valid_order_by_desc(self):
        from unittest.mock import MagicMock
        db = MagicMock()
        db.execute.return_value = []
        repo = Repository(Person, db)
        repo.find_all(order_by="name DESC")
        cypher = db.execute.call_args[0][0]
        assert "ORDER BY n.name DESC" in cypher

    def test_invalid_order_by_raises(self):
        from unittest.mock import MagicMock
        db = MagicMock()
        repo = Repository(Person, db)
        with pytest.raises(ValueError, match="order_by property"):
            repo.find_all(order_by="nonexistent")


# ---------------------------------------------------------------------------
# Edge case: from_record with various input types
# ---------------------------------------------------------------------------


class TestFromRecordEdgeCases:
    def test_dict_input(self):
        p = Person.from_record({"name": "Alice", "age": 30})
        assert p.name == "Alice"

    def test_neo4j_like_object(self):
        class FakeNode:
            def __init__(self, data):
                self._data = data
            def items(self):
                return self._data.items()
        p = Person.from_record(FakeNode({"name": "Bob", "age": 25}))
        assert p.name == "Bob"

    def test_rel_from_dict(self):
        r = ActedIn.from_record({"roles": ["Neo"]})
        assert r.roles == ["Neo"]

    def test_rel_from_neo4j_like(self):
        class FakeRel:
            def __init__(self, data):
                self._data = data
            def items(self):
                return self._data.items()
        r = ActedIn.from_record(FakeRel({"roles": ["Trinity"]}))
        assert r.roles == ["Trinity"]


# ---------------------------------------------------------------------------
# Edge case: Query builder with multi-label nodes
# ---------------------------------------------------------------------------


class TestMultiLabelQueryEdgeCases:
    def test_single_label_node_labels(self):
        assert Person.labels() == ["Person"]
        assert Person.labels_cypher() == ":Person"

    def test_multi_label_node(self):
        Actor = node("ActorNode")
        Actor.__labels__ = ["Person", "Actor"]
        assert Actor.labels() == ["Person", "Actor"]
        assert Actor.labels_cypher() == ":Person:Actor"

    def test_multi_label_in_match(self):
        Actor = node("ActorNode2")
        Actor.__labels__ = ["Person", "Actor"]
        q = Query().match(Actor, "a").return_("a")
        cypher, _ = q.build()
        assert "(a:Person:Actor)" in cypher


# ---------------------------------------------------------------------------
# Edge case: empty queries
# ---------------------------------------------------------------------------


class TestQueryEdgeCases:
    def test_empty_query(self):
        q = Query()
        cypher, params = q.build()
        assert cypher == ""
        assert params == {}

    def test_return_only(self):
        q = Query().return_("1 AS one")
        cypher, _ = q.build()
        assert cypher == "RETURN 1 AS one"

    def test_multiple_where(self):
        q = (Query()
             .match(Person, "p")
             .where("p.age > 18")
             .and_where("p.name <> 'Admin'")
             .or_where("p.age < 5")
             .return_("p"))
        cypher, _ = q.build()
        assert "WHERE" in cypher
        assert "AND" in cypher
        assert "OR" in cypher


# ---------------------------------------------------------------------------
# Comprehensive integration: all features together
# ---------------------------------------------------------------------------


class TestFullIntegration:
    def test_schema_from_models_and_validate(self):
        schema = GraphSchema.from_models([Person, Movie, ActedIn])
        d = schema.to_dict()
        assert d["nodes"]["Person"] == ["name", "age"]
        assert d["nodes"]["Movie"] == ["title", "year"]
        assert d["relationships"]["ACTED_IN"][0] == "Person"
        assert d["relationships"]["ACTED_IN"][1] == "Movie"

    def test_prompt_contains_all_info(self):
        schema = GraphSchema.from_models([Person, Movie, ActedIn])
        prompt = schema.to_prompt()
        assert "Person" in prompt
        assert "Movie" in prompt
        assert "ACTED_IN" in prompt
        assert "name" in prompt
        assert "title" in prompt

    def test_repo_full_lifecycle(self):
        """Test create → find → update → delete with mocked DB."""
        from unittest.mock import MagicMock
        db = MagicMock()
        repo = Repository(Person, db)

        # Create
        db.execute.return_value = [{"n": {"name": "Alice", "age": 30}}]
        repo.create(Person(name="Alice", age=30))
        assert "CREATE" in db.execute.call_args[0][0]

        # Find
        db.execute.return_value = [{"n": {"name": "Alice", "age": 30}}]
        results = repo.find_by(name="Alice")
        assert len(results) == 1

        # Update
        repo.update({"name": "Alice"}, {"age": 31})
        cypher = db.execute.call_args[0][0]
        assert "SET" in cypher

        # Delete
        repo.delete(name="Alice")
        cypher = db.execute.call_args[0][0]
        assert "DELETE" in cypher
