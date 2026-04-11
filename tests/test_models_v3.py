"""Tests for iteration 3: property expressions, query history, schema diff, async session, pipeline bridge."""

import asyncio
import json
from unittest.mock import MagicMock, AsyncMock
import pytest
from cypher_validator.models import (
    NodeModel,
    RelationshipModel,
    Query,
    Cond,
    GraphSchema,
    PropExpr,
    NodeRef,
    RelRef,
    QueryHistory,
    QueryResult,
    SchemaDiff,
    AsyncGraphSession,
    schema_to_pipeline_kwargs,
    node,
    relationship,
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
# PropExpr tests
# ---------------------------------------------------------------------------


class TestPropExpr:
    def test_ref(self):
        e = PropExpr("p", "name")
        assert e.ref == "p.name"
        assert str(e) == "p.name"

    def test_eq(self):
        e = PropExpr("p", "name")
        cond = e == "$name"
        assert isinstance(cond, Cond)
        assert cond.render() == "p.name = $name"

    def test_ne(self):
        e = PropExpr("p", "age")
        cond = e != 0
        assert cond.render() == "p.age <> 0"

    def test_lt(self):
        e = PropExpr("p", "age")
        cond = e < 18
        assert cond.render() == "p.age < 18"

    def test_le(self):
        e = PropExpr("p", "age")
        cond = e <= 65
        assert cond.render() == "p.age <= 65"

    def test_gt(self):
        e = PropExpr("p", "age")
        cond = e > 18
        assert cond.render() == "p.age > 18"

    def test_ge(self):
        e = PropExpr("p", "age")
        cond = e >= 21
        assert cond.render() == "p.age >= 21"

    def test_contains(self):
        e = PropExpr("p", "name")
        cond = e.contains("'ali'")
        assert "CONTAINS" in cond.render()

    def test_starts_with(self):
        e = PropExpr("p", "name")
        cond = e.starts_with("'A'")
        assert "STARTS WITH" in cond.render()

    def test_ends_with(self):
        e = PropExpr("p", "name")
        cond = e.ends_with("'son'")
        assert "ENDS WITH" in cond.render()

    def test_in(self):
        e = PropExpr("p", "age")
        cond = e.in_([1, 2, 3])
        assert "IN" in cond.render()

    def test_is_null(self):
        e = PropExpr("p", "email")
        cond = e.is_null()
        assert cond.render() == "p.email IS NULL"

    def test_is_not_null(self):
        e = PropExpr("p", "email")
        cond = e.is_not_null()
        assert cond.render() == "p.email IS NOT NULL"

    def test_regex(self):
        e = PropExpr("p", "name")
        cond = e.regex("'(?i)alice'")
        assert "=~" in cond.render()

    def test_combined_with_and(self):
        e1 = PropExpr("p", "age")
        e2 = PropExpr("p", "name")
        combined = (e1 > 18) & (e2 == "$name")
        rendered = combined.render()
        assert "AND" in rendered
        assert "p.age > 18" in rendered
        assert "p.name = $name" in rendered


# ---------------------------------------------------------------------------
# NodeRef tests
# ---------------------------------------------------------------------------


class TestNodeRef:
    def test_attribute_access(self):
        p = NodeRef(Person, "p")
        assert isinstance(p.name, PropExpr)
        assert p.name.ref == "p.name"
        assert p.age.ref == "p.age"

    def test_str(self):
        p = NodeRef(Person, "p")
        assert str(p) == "p"

    def test_repr(self):
        p = NodeRef(Person, "p")
        assert "Person" in repr(p)
        assert "p" in repr(p)

    def test_model_var(self):
        p = NodeRef(Person, "p")
        assert p.model is Person
        assert p.var == "p"

    def test_private_attr_raises(self):
        p = NodeRef(Person, "p")
        with pytest.raises(AttributeError):
            _ = p._private

    def test_in_query_match(self):
        p = NodeRef(Person, "p")
        q = Query().match(p).return_("p")
        cypher, _ = q.build()
        assert "(p:Person)" in cypher

    def test_in_query_where(self):
        p = NodeRef(Person, "p")
        q = (Query()
             .match(p)
             .where(p.name == "$name")
             .where(p.age > 18)
             .return_("p"))
        cypher, _ = q.build()
        assert "p.name = $name" in cypher
        assert "p.age > 18" in cypher

    def test_in_query_return(self):
        p = NodeRef(Person, "p")
        q = Query().match(p).return_(p)
        cypher, _ = q.build()
        assert "RETURN p" in cypher

    def test_prop_expr_in_return(self):
        p = NodeRef(Person, "p")
        q = Query().match(p).return_(p.name, p.age)
        cypher, _ = q.build()
        assert "RETURN p.name, p.age" in cypher

    def test_complex_query_with_refs(self):
        p = NodeRef(Person, "p")
        m = NodeRef(Movie, "m")
        q = (Query()
             .match(p)
             .match(m)
             .where((p.age > 18) & (m.year > 2000))
             .return_(p.name, m.title))
        cypher, _ = q.build()
        assert "p.age > 18" in cypher
        assert "m.year > 2000" in cypher
        assert "RETURN p.name, m.title" in cypher


# ---------------------------------------------------------------------------
# RelRef tests
# ---------------------------------------------------------------------------


class TestRelRef:
    def test_attribute_access(self):
        r = RelRef(ActedIn, "r")
        assert r.roles.ref == "r.roles"

    def test_str(self):
        r = RelRef(ActedIn, "r")
        assert str(r) == "r"

    def test_repr(self):
        r = RelRef(ActedIn, "r")
        assert "ACTED_IN" in repr(r)

    def test_model_var(self):
        r = RelRef(ActedIn, "r")
        assert r.model is ActedIn
        assert r.var == "r"


# ---------------------------------------------------------------------------
# QueryHistory tests
# ---------------------------------------------------------------------------


class TestQueryHistory:
    def test_add_and_entries(self):
        h = QueryHistory()
        h.add("MATCH (n) RETURN n", {}, result_count=5)
        assert len(h.entries) == 1
        assert h.last is not None
        assert h.last.result_count == 5

    def test_max_entries(self):
        h = QueryHistory(max_entries=3)
        for i in range(5):
            h.add(f"QUERY {i}", {})
        assert len(h.entries) == 3
        assert h.entries[0].cypher == "QUERY 2"

    def test_add_from_result(self):
        h = QueryHistory()
        r = QueryResult(
            cypher="MATCH (n) RETURN n",
            records=[{"n": 1}, {"n": 2}],
            summary="Found 2 nodes",
        )
        h.add_from_result(r)
        assert h.last.result_count == 2
        assert h.last.summary == "Found 2 nodes"

    def test_clear(self):
        h = QueryHistory()
        h.add("Q1", {})
        h.add("Q2", {})
        h.clear()
        assert len(h.entries) == 0
        assert h.last is None

    def test_to_context(self):
        h = QueryHistory()
        h.add("MATCH (n:Person) RETURN n", {}, result_count=5)
        h.add("BAD QUERY", {}, error="Syntax error")
        ctx = h.to_context()
        assert "Previous Queries" in ctx
        assert "5 results" in ctx
        assert "error: Syntax error" in ctx

    def test_to_context_empty(self):
        h = QueryHistory()
        ctx = h.to_context()
        assert "No previous queries" in ctx

    def test_to_context_last_n(self):
        h = QueryHistory()
        for i in range(10):
            h.add(f"Q{i}", {})
        ctx = h.to_context(last_n=3)
        assert "Q7" in ctx
        assert "Q0" not in ctx

    def test_to_list(self):
        h = QueryHistory()
        h.add("Q1", {"a": 1}, result_count=3)
        data = h.to_list()
        assert len(data) == 1
        assert data[0]["cypher"] == "Q1"
        assert data[0]["parameters"] == {"a": 1}

    def test_successful_queries(self):
        h = QueryHistory()
        h.add("Q1", {}, result_count=5)
        h.add("Q2", {}, error="fail")
        h.add("Q3", {}, result_count=2)
        assert len(h.successful_queries()) == 2
        assert len(h.failed_queries()) == 1

    def test_find_similar(self):
        h = QueryHistory()
        h.add("MATCH (n:Person) RETURN n", {})
        h.add("MATCH (m:Movie) RETURN m", {})
        h.add("MATCH (n:Person) WHERE n.age > 18 RETURN n", {})
        similar = h.find_similar("MATCH (n:Person) RETURN n")
        assert len(similar) >= 1


# ---------------------------------------------------------------------------
# SchemaDiff tests
# ---------------------------------------------------------------------------


class TestSchemaDiff:
    def test_no_changes(self):
        s = GraphSchema.from_models([Person, Movie])
        diff = SchemaDiff(s, s)
        assert not diff.has_changes
        assert "identical" in diff.summary().lower()

    def test_added_labels(self):
        old = GraphSchema.from_models([Person])
        new = GraphSchema.from_models([Person, Movie])
        diff = SchemaDiff(old, new)
        assert diff.has_changes
        assert "Movie" in diff.added_labels
        assert len(diff.removed_labels) == 0

    def test_removed_labels(self):
        old = GraphSchema.from_models([Person, Movie])
        new = GraphSchema.from_models([Person])
        diff = SchemaDiff(old, new)
        assert "Movie" in diff.removed_labels

    def test_added_rel_types(self):
        old = GraphSchema.from_models([Person, Movie])
        new = GraphSchema.from_models([Person, Movie, ActedIn])
        diff = SchemaDiff(old, new)
        assert "ACTED_IN" in diff.added_rel_types

    def test_property_changes(self):
        PersonV1 = node("DiffPerson1", name=str)
        PersonV2 = node("DiffPerson1", name=str, age=(int, 0), email=(str, ""))
        old = GraphSchema(node_models=[PersonV1])
        new = GraphSchema(node_models=[PersonV2])
        diff = SchemaDiff(old, new)
        assert "DiffPerson1" in diff.added_properties
        added_props = diff.added_properties["DiffPerson1"]
        assert "age" in added_props
        assert "email" in added_props

    def test_removed_properties(self):
        PersonV1 = node("DiffPerson2", name=str, age=(int, 0), email=(str, ""))
        PersonV2 = node("DiffPerson2B", name=str)
        # Use same label via overriding
        PersonV2.__label__ = "DiffPerson2"
        old = GraphSchema(node_models=[PersonV1])
        new = GraphSchema(node_models=[PersonV2])
        diff = SchemaDiff(old, new)
        assert "DiffPerson2" in diff.removed_properties

    def test_summary(self):
        old = GraphSchema.from_models([Person])
        new = GraphSchema.from_models([Person, Movie, ActedIn])
        diff = SchemaDiff(old, new)
        summary = diff.summary()
        assert "Added Node Labels" in summary
        assert "Movie" in summary
        assert "Added Relationship Types" in summary

    def test_migration_ddl(self):
        old = GraphSchema.from_models([Person])
        new = GraphSchema.from_models([Person, Movie, ActedIn])
        diff = SchemaDiff(old, new)
        stmts = diff.migration_ddl()
        # Should have CREATE statements for Movie
        assert any("Movie" in s and "CREATE" in s for s in stmts)
        assert len(stmts) > 0

    def test_migration_ddl_removed(self):
        old = GraphSchema.from_models([Person, Movie])
        new = GraphSchema.from_models([Person])
        diff = SchemaDiff(old, new)
        stmts = diff.migration_ddl()
        # Should have DROP statements for Movie
        assert any("movie" in s.lower() and "DROP" in s for s in stmts)

    def test_to_dict(self):
        old = GraphSchema.from_models([Person])
        new = GraphSchema.from_models([Person, Movie])
        diff = SchemaDiff(old, new)
        d = diff.to_dict()
        assert d["has_changes"] is True
        assert "Movie" in d["added_labels"]


# ---------------------------------------------------------------------------
# AsyncGraphSession tests
# ---------------------------------------------------------------------------


class TestAsyncGraphSession:
    @pytest.fixture
    def async_db(self):
        db = MagicMock()
        db.execute = AsyncMock(return_value=[{"n": {"name": "Alice", "age": 30}}])
        db.close = AsyncMock()
        return db

    @pytest.fixture
    def sync_db(self):
        db = MagicMock()
        db.execute.return_value = [{"n": {"name": "Alice", "age": 30}}]
        return db

    def test_execute_async_db(self, async_db):
        session = AsyncGraphSession(async_db)
        result = asyncio.run(session.execute("MATCH (n) RETURN n"))
        assert len(result) == 1
        async_db.execute.assert_awaited_once()

    def test_execute_sync_db(self, sync_db):
        session = AsyncGraphSession(sync_db)
        result = asyncio.run(session.execute("MATCH (n) RETURN n"))
        assert len(result) == 1

    def test_execute_query(self, async_db):
        session = AsyncGraphSession(async_db)
        q = Query().match(Person, "p").return_("p")
        result = asyncio.run(session.execute_query(q))
        assert len(result) == 1

    def test_create(self, async_db):
        session = AsyncGraphSession(async_db)
        p = Person(name="Alice", age=30)
        asyncio.run(session.create(p))
        call_args = async_db.execute.call_args
        assert "CREATE" in call_args[0][0]

    def test_merge(self, async_db):
        session = AsyncGraphSession(async_db)
        p = Person(name="Alice", age=30)
        asyncio.run(session.merge(p, merge_keys=["name"]))
        call_args = async_db.execute.call_args
        assert "MERGE" in call_args[0][0]

    def test_bulk_create(self, async_db):
        session = AsyncGraphSession(async_db)
        items = [{"name": "A", "age": 1}]
        asyncio.run(session.bulk_create(Person, items))
        call_args = async_db.execute.call_args
        assert "UNWIND" in call_args[0][0]

    def test_bulk_merge(self, async_db):
        session = AsyncGraphSession(async_db)
        items = [{"name": "A", "age": 1}]
        asyncio.run(session.bulk_merge(Person, items, merge_keys=["name"]))
        call_args = async_db.execute.call_args
        assert "MERGE" in call_args[0][0]

    def test_neighbors(self, async_db):
        session = AsyncGraphSession(async_db)
        asyncio.run(session.neighbors(Person, match_props={"name": "Alice"}))
        call_args = async_db.execute.call_args
        assert "neighbor" in call_args[0][0]

    def test_history_tracking(self, async_db):
        session = AsyncGraphSession(async_db)
        asyncio.run(session.execute("Q1"))
        asyncio.run(session.execute("Q2"))
        assert len(session.history.entries) == 2

    def test_history_records_errors(self, async_db):
        async_db.execute = AsyncMock(side_effect=RuntimeError("DB error"))
        session = AsyncGraphSession(async_db)
        with pytest.raises(RuntimeError):
            asyncio.run(session.execute("BAD"))
        assert len(session.history.entries) == 1
        assert session.history.last.error == "DB error"

    def test_context_manager(self, async_db):
        async def run():
            async with AsyncGraphSession(async_db) as session:
                await session.execute("Q1")
            return True
        assert asyncio.run(run()) is True
        async_db.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# Pipeline integration tests
# ---------------------------------------------------------------------------


class TestPipelineIntegration:
    def test_schema_to_pipeline_kwargs(self):
        schema = GraphSchema.from_models([Person, Movie, ActedIn])
        kwargs = schema_to_pipeline_kwargs(schema)
        assert "schema" in kwargs
        # The schema should be the Rust Schema object
        rust_schema = kwargs["schema"]
        assert rust_schema.has_node_label("Person")
        assert rust_schema.has_node_label("Movie")
        assert rust_schema.has_rel_type("ACTED_IN")


# ---------------------------------------------------------------------------
# End-to-end integration: NodeRef + Query + History
# ---------------------------------------------------------------------------


class TestEndToEnd:
    def test_noderef_query_history_flow(self):
        """Simulate agent workflow: build query with NodeRef, track in history."""
        p = NodeRef(Person, "p")
        m = NodeRef(Movie, "m")

        q = (Query()
             .match(p)
             .match(m)
             .where((p.age > 18) & (m.year > 2000))
             .return_(p.name, m.title)
             .limit(10))

        cypher, params = q.build()
        history = QueryHistory()
        history.add(cypher, params, result_count=3, summary="Found 3 adult actors in modern movies")

        ctx = history.to_context()
        assert "Person" in ctx
        assert "3 results" in ctx

    def test_schema_diff_to_migration(self):
        """Full migration workflow."""
        PersonV1 = node("MigPerson", name=str)
        MovieV1 = node("MigMovie", title=str)

        PersonV2 = node("MigPerson2", name=str, age=(int, 0))
        PersonV2.__label__ = "MigPerson"  # Override to match
        MovieV2 = node("MigMovie2", title=str, year=(int, 0))
        MovieV2.__label__ = "MigMovie"
        ReviewNode = node("MigReview", text=str, rating=(int, 0))

        old = GraphSchema(node_models=[PersonV1, MovieV1])
        new = GraphSchema(node_models=[PersonV2, MovieV2, ReviewNode])
        diff = SchemaDiff(old, new)

        assert diff.has_changes
        assert "MigReview" in diff.added_labels
        assert "MigPerson" in diff.added_properties

        stmts = diff.migration_ddl()
        assert len(stmts) > 0
        summary = diff.summary()
        assert "MigReview" in summary
