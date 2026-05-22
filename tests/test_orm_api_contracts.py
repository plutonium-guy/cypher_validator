"""API contract tests for the ORM layer.

These assert the documented surface-level caveats that came out of the
live Neo4j integration sweep:

- Query.where() does NOT auto-parameterize values; use .params(**) or
  pass a Cond (which inlines literals).
- Cond inlines literal scalar values directly into Cypher.
- Traversal.path_exists returns column name "connected".
- Repository / GraphSession / AsyncGraphSession take a Neo4jDatabase
  instance (or any execute-compatible object), not URI/user/password.
- BulkOps.* are staticmethods returning (cypher, params).

No live database required — these run as plain pytest unit tests.
"""
from __future__ import annotations

import inspect

import pytest

from cypher_validator import (
    AsyncGraphSession,
    BulkOps,
    Cond,
    CypherFn,
    GraphSchema,
    GraphSession,
    NodeModel,
    Query,
    RelationshipModel,
    Repository,
    Traversal,
)


# ---------------------------------------------------------------------------
# Domain models (separate labels to avoid registry collisions with other tests)
# ---------------------------------------------------------------------------

class _AcPerson(NodeModel):
    __label__ = "AcPerson"
    name: str
    age: int = 0


class _AcCompany(NodeModel):
    __label__ = "AcCompany"
    name: str


class _AcWorksFor(RelationshipModel):
    __source__ = _AcPerson
    __target__ = _AcCompany
    __rel_type__ = "AC_WORKS_FOR"
    since: int = 0


# ---------------------------------------------------------------------------
# Cond + Query.where contract
# ---------------------------------------------------------------------------

class TestCondInlining:
    def test_cond_inlines_int_literal(self):
        cypher, params = (
            Query().match(_AcPerson, "p").where(Cond("p.age", ">=", 18)).return_("p")
        ).build()
        assert "p.age >= 18" in cypher
        # int literal MUST NOT be parameterized
        assert 18 not in params.values()

    def test_cond_inlines_string_literal_with_quotes(self):
        cypher, _ = (
            Query().match(_AcPerson, "p").where(Cond("p.name", "=", "Alice")).return_("p")
        ).build()
        # Single-quoted string literal inlined
        assert "p.name = 'Alice'" in cypher

    def test_cond_preserves_dollar_param_reference(self):
        cypher, _ = (
            Query().match(_AcPerson, "p").where(Cond("p.name", "=", "$n")).return_("p")
        ).build()
        # If user passes a $param ref Cond keeps it as-is
        assert "p.name = $n" in cypher

    def test_cond_inlines_bool_and_null(self):
        c1 = Cond("p.active", "=", True).render()
        c2 = Cond("p.deleted", "=", None).render()
        assert c1 == "p.active = true"
        assert c2 == "p.deleted = null"


class TestWhereNoAutoParam:
    def test_where_string_is_literal(self):
        """Query.where('p.age > $min_age') keeps the $ref; values come via .params()."""
        q = (
            Query()
            .match(_AcPerson, "p")
            .where("p.age > $min_age")
            .params(min_age=30)
            .return_("p")
        )
        cypher, params = q.build()
        assert "$min_age" in cypher
        assert params.get("min_age") == 30

    def test_where_does_not_bind_kwargs_silently(self):
        """Passing kwargs to .where() must fail — the API is single-arg."""
        with pytest.raises(TypeError):
            Query().match(_AcPerson, "p").where("p.age > $x", x=1)  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Traversal column name contract
# ---------------------------------------------------------------------------

class TestTraversalColumnNames:
    def test_path_exists_column_is_connected(self):
        cypher, _ = Traversal.path_exists(
            _AcPerson, _AcPerson, {"name": "A"}, {"name": "B"}, max_depth=3
        )
        assert "AS connected" in cypher
        # Documented column name surfaced from live driver:
        assert "AS path_exists" not in cypher

    def test_shortest_path_returns_distance(self):
        cypher, _ = Traversal.shortest_path(
            _AcPerson, _AcPerson, {"name": "A"}, {"name": "B"}
        )
        assert "AS distance" in cypher
        assert "shortestPath" in cypher

    def test_degree_returns_degree(self):
        cypher, _ = Traversal.degree(_AcPerson, "p", {"name": "A"})
        assert "AS degree" in cypher

    def test_neighbors_returns_var_r_neighbor(self):
        cypher, _ = Traversal.neighbors(_AcPerson, "p", {"name": "A"})
        # Public contract: caller can read keys "p", "r", "neighbor"
        assert "RETURN p, r, neighbor" in cypher


# ---------------------------------------------------------------------------
# Session / Repository constructor contracts
# ---------------------------------------------------------------------------

class _FakeDB:
    """Minimal duck-typed DB capturing every execute() call."""

    def __init__(self):
        self.calls = []

    def execute(self, cypher, params=None):
        self.calls.append((cypher, params or {}))
        return []


class TestSessionConstructors:
    def test_graph_session_takes_db_instance(self):
        sig = inspect.signature(GraphSession.__init__)
        params = list(sig.parameters)
        # self, db, schema=None — NOT (uri, user, password, ...)
        assert params == ["self", "db", "schema"]

    def test_async_graph_session_takes_db_instance(self):
        sig = inspect.signature(AsyncGraphSession.__init__)
        params = list(sig.parameters)
        assert params == ["self", "db", "schema"]

    def test_repository_takes_model_and_db(self):
        sig = inspect.signature(Repository.__init__)
        params = list(sig.parameters)
        assert params == ["self", "model", "db", "var"]

    def test_graph_session_rejects_uri_kwargs(self):
        """GraphSession(URI, USER, PASSWORD) must not silently work."""
        with pytest.raises(TypeError):
            GraphSession("bolt://localhost:7687", "neo4j", "x")  # type: ignore[call-arg]

    def test_graph_session_uses_db_execute(self):
        fake = _FakeDB()
        gs = GraphSession(fake)
        gs.execute("MATCH (n) RETURN n", {"k": "v"})
        assert fake.calls == [("MATCH (n) RETURN n", {"k": "v"})]


# ---------------------------------------------------------------------------
# BulkOps shape contract
# ---------------------------------------------------------------------------

class TestBulkOpsShape:
    def test_bulk_create_nodes_is_static(self):
        assert isinstance(
            inspect.getattr_static(BulkOps, "bulk_create_nodes"), staticmethod
        )

    def test_bulk_merge_nodes_returns_cypher_params(self):
        cypher, params = BulkOps.bulk_merge_nodes(
            _AcPerson,
            [{"name": "A", "age": 1}, {"name": "B", "age": 2}],
            merge_keys=["name"],
        )
        assert "UNWIND $batch AS item" in cypher
        assert "MERGE (n:AcPerson" in cypher
        assert params == {"batch": [{"name": "A", "age": 1}, {"name": "B", "age": 2}]}

    def test_bulk_merge_relationships_uses_src_tgt_keys(self):
        cypher, params = BulkOps.bulk_merge_relationships(
            _AcWorksFor,
            [{"src_name": "A", "tgt_name": "C", "since": 2020}],
            src_key="src_name",
            tgt_key="tgt_name",
        )
        assert "MATCH (a:AcPerson {name: item.src_name})" in cypher
        assert "(b:AcCompany {name: item.tgt_name})" in cypher
        assert "MERGE (a)-[r:AC_WORKS_FOR]->(b)" in cypher
        assert params["batch"][0]["since"] == 2020


# ---------------------------------------------------------------------------
# CypherFn rendering contract (used by aggregates)
# ---------------------------------------------------------------------------

class TestCypherFnRendering:
    def test_count_returns_str(self):
        assert str(CypherFn.count("p")) == "count(p)"

    def test_avg_returns_str(self):
        assert str(CypherFn.avg("p.age")) == "avg(p.age)"

    def test_as_aliases(self):
        """as_ is a two-arg helper, not a method on the returned string."""
        assert CypherFn.as_(CypherFn.count("p"), "total") == "count(p) AS total"
