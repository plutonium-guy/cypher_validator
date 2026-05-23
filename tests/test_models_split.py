"""Tests to verify the models.py → models/ package split.

Checks backwards compatibility of all import paths and verifies
that key functionality still works after the refactor.
"""
from __future__ import annotations

import pytest


class TestBackwardsCompatImports:
    """All existing import paths continue to work after the split."""

    def test_import_from_models_package(self):
        """All 30+ public names importable from cypher_validator.models."""
        from cypher_validator.models import (
            # orm
            NodeModel,
            RelationshipModel,
            node,
            relationship,
            _NODE_REGISTRY,
            _REL_REGISTRY,
            # query
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
            QueryHistoryEntry,
            QueryHistory,
            CypherFn,
            fn,
            PathBuilder,
            # schema
            GraphSchema,
            SchemaDDL,
            SchemaDiff,
            schema_to_pipeline_kwargs,
            # session
            Traversal,
            BulkOps,
            GraphSession,
            AsyncGraphSession,
            Repository,
            # agents
            AgentTools,
            ExtendedAgentTools,
        )
        # Just confirm they're all non-None
        assert NodeModel is not None
        assert RelationshipModel is not None
        assert Query is not None
        assert GraphSchema is not None
        assert AgentTools is not None
        assert ExtendedAgentTools is not None
        assert fn is CypherFn

    def test_import_from_top_level(self):
        """All names importable from cypher_validator (top-level package)."""
        from cypher_validator import (
            NodeModel,
            RelationshipModel,
            Query,
            Cond,
            CondGroup,
            Op,
            RawExpr,
            GraphSchema,
            AgentTools,
            ExtendedAgentTools,
            QueryPlan,
            QueryStep,
            QueryResult,
            Traversal,
            BulkOps,
            SchemaDDL,
            GraphSession,
            AsyncGraphSession,
            PropExpr,
            NodeRef,
            RelRef,
            QueryHistory,
            SchemaDiff,
            CypherFn,
            fn,
            PathBuilder,
            Repository,
            schema_to_pipeline_kwargs,
            node,
            relationship,
        )
        assert NodeModel is not None
        assert Query is not None
        assert GraphSchema is not None

    def test_import_from_submodules(self):
        """Direct submodule imports work."""
        from cypher_validator.models.orm import NodeModel, RelationshipModel, node, relationship
        from cypher_validator.models.query import Query, Cond, Op, NodeRef, RelRef, PathBuilder
        from cypher_validator.models.schema import GraphSchema, SchemaDDL, SchemaDiff
        from cypher_validator.models.session import GraphSession, Traversal, BulkOps, Repository
        from cypher_validator.models.agents import AgentTools, ExtendedAgentTools
        assert NodeModel is not None
        assert Query is not None
        assert GraphSchema is not None
        assert AgentTools is not None

    def test_registry_shared(self):
        """_NODE_REGISTRY and _REL_REGISTRY are the same objects across imports."""
        from cypher_validator.models.orm import _NODE_REGISTRY as reg1, _REL_REGISTRY as rreg1
        from cypher_validator.models import _NODE_REGISTRY as reg2, _REL_REGISTRY as rreg2
        assert reg1 is reg2, "_NODE_REGISTRY must be the same object"
        assert rreg1 is rreg2, "_REL_REGISTRY must be the same object"

    def test_node_factory(self):
        """node() factory function creates working NodeModel subclass."""
        from cypher_validator.models import node, NodeModel
        Person = node("Person_SplitTest", name=(str, ...), age=(int, 0))
        assert issubclass(Person, NodeModel)
        assert Person.label() == "Person_SplitTest"
        p = Person(name="Alice")
        assert p.name == "Alice"
        assert p.age == 0

    def test_query_builder_still_works(self):
        """Query builder produces valid cypher strings."""
        from cypher_validator.models import Query, Cond, node

        Person2 = node("Person2_SplitTest", name=(str, ...), age=(int, 0))

        q = (
            Query()
            .match(Person2, "p")
            .where(Cond("p.name", "=", "$name"))
            .return_("p")
        )
        cypher, params = q.build()
        assert "MATCH" in cypher
        assert "Person2_SplitTest" in cypher
        assert "WHERE" in cypher
        assert "RETURN" in cypher

    def test_graph_schema_from_dict(self):
        """GraphSchema.from_dict() creates working schema."""
        from cypher_validator.models import GraphSchema
        schema = GraphSchema.from_dict({
            "nodes": {
                "Person_Dict": ["name", "age"],
                "Movie_Dict": ["title", "year"],
            },
            "relationships": {
                "ACTED_IN_DICT": ["Person_Dict", "Movie_Dict", ["roles"]],
            },
        })
        assert len(schema.node_models) == 2
        assert len(schema.rel_models) == 1
        labels = {m.label() for m in schema.node_models}
        assert "Person_Dict" in labels
        assert "Movie_Dict" in labels
        rel_types = {m.rel_type() for m in schema.rel_models}
        assert "ACTED_IN_DICT" in rel_types

    def test_node_ref_and_prop_expr(self):
        """NodeRef and PropExpr work correctly with Query builder."""
        from cypher_validator.models import NodeRef, PropExpr, Query, node

        Movie = node("Movie_SplitTest", title=(str, ...), year=(int, 2000))
        m = NodeRef(Movie, "m")
        q = (
            Query()
            .match(m)
            .where(m.year > 2010)
            .return_(m)
        )
        cypher, _ = q.build()
        assert "Movie_SplitTest" in cypher
        assert ">" in cypher
        assert "RETURN m" in cypher

    def test_cypher_fn(self):
        """CypherFn generates correct function strings."""
        from cypher_validator.models import CypherFn, fn
        assert CypherFn.count("n") == "count(n)"
        assert fn.count("n") == "count(n)"  # alias works
        assert CypherFn.avg("n.age") == "avg(n.age)"
        assert CypherFn.to_lower("n.name") == "toLower(n.name)"

    def test_path_builder(self):
        """PathBuilder generates correct path pattern strings."""
        from cypher_validator.models import PathBuilder, node, relationship

        PersonPB = node("PersonPB", name=(str, ...))
        MoviePB = node("MoviePB", title=(str, ...))
        ActedInPB = relationship("ACTED_IN_PB", PersonPB, MoviePB)

        path = (
            PathBuilder(PersonPB, "actor")
            .rel(ActedInPB, "r")
            .to(MoviePB, "movie")
        )
        pattern = path.build()
        assert "PersonPB" in pattern
        assert "ACTED_IN_PB" in pattern
        assert "MoviePB" in pattern

    def test_query_history(self):
        """QueryHistory records and retrieves entries."""
        from cypher_validator.models import QueryHistory
        h = QueryHistory(max_entries=10)
        h.add("MATCH (n) RETURN n", {}, result_count=5)
        assert len(h.entries) == 1
        assert h.last.cypher == "MATCH (n) RETURN n"
        assert h.last.result_count == 5

    def test_schema_ddl(self):
        """SchemaDDL generates DDL statements."""
        from cypher_validator.models import GraphSchema, SchemaDDL, node

        PersonDDL = node("PersonDDL", name=(str, ...))
        schema = GraphSchema.from_models([PersonDDL])
        ddl = SchemaDDL(schema)
        stmts = ddl.generate_all()
        assert any("CONSTRAINT" in s for s in stmts)
        assert any("INDEX" in s for s in stmts)

    def test_schema_diff(self):
        """SchemaDiff detects schema changes correctly."""
        from cypher_validator.models import GraphSchema, SchemaDiff, node

        PersonOld = node("PersonDiff", name=(str, ...))
        PersonNew = node("PersonDiff", name=(str, ...), email=(str, ""))
        old_schema = GraphSchema.from_models([PersonOld])
        new_schema = GraphSchema.from_models([PersonNew])
        diff = SchemaDiff(old_schema, new_schema)
        assert diff.has_changes
        assert "email" in diff.added_properties.get("PersonDiff", [])

    def test_bulk_ops(self):
        """BulkOps generates correct UNWIND cypher."""
        from cypher_validator.models import BulkOps, node

        PersonBulk = node("PersonBulk", name=(str, ...), age=(int, 0))
        cypher, params = BulkOps.bulk_create_nodes(
            PersonBulk,
            [{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}]
        )
        assert "UNWIND" in cypher
        assert "$batch" in cypher
        assert "PersonBulk" in cypher
        assert params["batch"][0]["name"] == "Alice"

    def test_agent_tools(self):
        """AgentTools generates valid tool specs."""
        from cypher_validator.models import GraphSchema, AgentTools, node, relationship

        PersonAT = node("PersonAT", name=(str, ...))
        MovieAT = node("MovieAT", title=(str, ...))
        ActedInAT = relationship("ACTED_IN_AT", PersonAT, MovieAT)
        schema = GraphSchema.from_models([PersonAT, MovieAT, ActedInAT])
        tools = AgentTools(schema)

        openai_spec = tools.query_tool_spec("openai")
        assert openai_spec["function"]["name"] == "execute_cypher"

        anthropic_spec = tools.query_tool_spec("anthropic")
        assert anthropic_spec["name"] == "execute_cypher"
        assert "input_schema" in anthropic_spec

        all_specs = tools.all_tool_specs()
        assert len(all_specs) == 3
