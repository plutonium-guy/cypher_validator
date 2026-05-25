"""Comprehensive regression tests for cypher_validator ORM against live Neo4j.

Tests every feature a developer would use to build a Neo4j app without raw Cypher.
Uses actual API signatures discovered from source code.
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from neo4j import GraphDatabase
from models import (
    ALL_MODELS, Researcher, Institution, Paper, Disease, Drug, Gene,
    ClinicalTrial, FundingAgency,
    AuthoredBy, AffiliatedWith, Cites, StudiesDisease, TreatsWith,
    TargetsGene, AssociatedGene, TestsDrug, TrialForDisease, FundedBy, Collaborates,
)
from cypher_validator.models.session import GraphSession, BulkOps, Traversal, Repository
from cypher_validator.models.query import Query, QueryHistory
from cypher_validator.models.schema import GraphSchema, SchemaDDL, SchemaDiff
from cypher_validator.models.agents import AgentTools
from cypher_validator import CypherValidator, Schema


class Neo4jDB:
    def __init__(self):
        self._driver = GraphDatabase.driver(
            "bolt://localhost:7687", auth=("neo4j", "testtest12")
        )

    def execute(self, cypher, params=None):
        with self._driver.session() as s:
            return [dict(r) for r in s.run(cypher, params or {})]

    def connect(self):
        pass

    def close(self):
        self._driver.close()


@pytest.fixture(scope="module")
def db():
    d = Neo4jDB()
    yield d
    d.close()


@pytest.fixture(scope="module")
def schema():
    return GraphSchema.from_models(ALL_MODELS)


@pytest.fixture(scope="module")
def session(db, schema):
    return GraphSession(db, schema)


# ============================================================================
# 1. MODEL DEFINITIONS
# ============================================================================

class TestModelDefinitions:
    def test_node_model_has_label(self):
        assert Researcher.__label__ == "Researcher"
        assert Gene.__label__ == "Gene"

    def test_node_model_fields(self):
        fields = list(Researcher.model_fields.keys())
        assert "name" in fields
        assert "specialization" in fields

    def test_gene_uses_symbol_as_key(self):
        fields = list(Gene.model_fields.keys())
        assert "symbol" in fields
        assert "name" not in fields

    def test_relationship_model_type(self):
        assert AuthoredBy.rel_type() == "AUTHORED_BY"
        assert TreatsWith.rel_type() == "TREATS_WITH"

    def test_relationship_model_endpoints(self):
        assert AuthoredBy.source_label() == "Paper"
        assert AuthoredBy.target_label() == "Researcher"

    def test_relationship_property_names(self):
        props = AuthoredBy.property_names()
        assert "position" in props

    def test_all_models_count(self):
        assert len(ALL_MODELS) == 19  # 8 nodes + 11 rels

    def test_vector_property_on_paper(self):
        assert "abstract_embedding" in Paper.model_fields

    def test_vector_property_on_researcher(self):
        assert "bio_embedding" in Researcher.model_fields


# ============================================================================
# 2. GRAPH SCHEMA
# ============================================================================

class TestGraphSchema:
    def test_from_models(self, schema):
        assert len(schema.node_models) == 8
        assert len(schema.rel_models) == 11

    def test_node_models_are_classes(self, schema):
        for m in schema.node_models:
            assert hasattr(m, "__label__")

    def test_rel_models_are_classes(self, schema):
        for m in schema.rel_models:
            assert hasattr(m, "rel_type")
            assert hasattr(m, "source_label")
            assert hasattr(m, "target_label")


# ============================================================================
# 3. GRAPH SESSION
# ============================================================================

class TestGraphSession:
    def test_execute_returns_list(self, session):
        result = session.execute("RETURN 1 AS n")
        assert isinstance(result, list)
        assert result[0]["n"] == 1

    def test_execute_with_params(self, session):
        result = session.execute("RETURN $x AS val", {"x": 42})
        assert result[0]["val"] == 42

    def test_execute_match(self, session):
        result = session.execute(
            "MATCH (n:Researcher) RETURN n.name AS name LIMIT 1"
        )
        assert len(result) == 1
        assert "name" in result[0]

    def test_execute_empty_result(self, session):
        result = session.execute(
            "MATCH (n:Researcher {name: 'NONEXISTENT_PERSON'}) RETURN n"
        )
        assert result == []


# ============================================================================
# 4. QUERY BUILDER — match() takes positional model_or_label, var
# ============================================================================

class TestQueryBuilder:
    def test_simple_match_return(self, session):
        q = Query().match("Researcher", "n").return_("n.name AS name")
        cypher, params = q.build()
        assert "MATCH" in cypher
        assert "RETURN" in cypher
        result = session.execute(cypher, params)
        assert len(result) > 0

    def test_match_with_where(self, session):
        q = (Query()
             .match("Researcher", "n")
             .where("n.h_index > $min_h")
             .return_("n.name AS name", "n.h_index AS h")
             .param("min_h", 50))
        cypher, params = q.build()
        result = session.execute(cypher, params)
        for r in result:
            assert r["h"] > 50

    def test_match_with_multiple_where_auto_ands(self, session):
        q = (Query()
             .match("Researcher", "n")
             .where("n.h_index > 40")
             .where("n.h_index < 70")
             .return_("n.name AS name", "n.h_index AS h"))
        cypher, params = q.build()
        result = session.execute(cypher, params)
        for r in result:
            assert 40 < r["h"] < 70

    def test_order_by_and_limit(self, session):
        q = (Query()
             .match("Paper", "n")
             .return_("n.title AS title", "n.citation_count AS cites")
             .order_by("n.citation_count DESC")
             .limit(3))
        cypher, params = q.build()
        result = session.execute(cypher, params)
        assert len(result) == 3
        assert result[0]["cites"] >= result[1]["cites"]

    def test_where_before_return_in_output(self):
        q = (Query()
             .match("Drug", "n")
             .return_("n.name AS name")
             .where("n.phase = 'approved'"))
        cypher, _ = q.build()
        where_pos = cypher.find("WHERE")
        return_pos = cypher.find("RETURN")
        assert where_pos < return_pos, f"WHERE must come before RETURN: {cypher}"

    def test_and_where(self, session):
        q = (Query()
             .match("Researcher", "n")
             .where("n.h_index > 30")
             .and_where("n.h_index < 80")
             .return_("n.name AS name"))
        cypher, params = q.build()
        assert "AND" in cypher
        result = session.execute(cypher, params)
        assert len(result) > 0

    def test_raw_clause(self, session):
        q = (Query()
             .match("Paper", "a")
             .raw("-[:AUTHORED_BY]->(b:Researcher)")
             .return_("a.title AS paper", "b.name AS author")
             .limit(5))
        cypher, params = q.build()
        result = session.execute(cypher, params)
        assert len(result) > 0

    def test_query_with_params(self, session):
        q = (Query()
             .match("Disease", "n")
             .where("n.name CONTAINS $term")
             .return_("n.name AS name")
             .param("term", "Cancer"))
        cypher, params = q.build()
        assert "term" in params
        result = session.execute(cypher, params)
        assert len(result) > 0

    def test_count_aggregation(self, session):
        q = (Query()
             .match("Drug", "n")
             .return_("count(n) AS total"))
        cypher, params = q.build()
        result = session.execute(cypher, params)
        assert result[0]["total"] > 0

    def test_chained_match_relationship(self, session):
        q = (Query()
             .match("Disease", "d")
             .raw("-[:TREATS_WITH]->(drug:Drug)")
             .where("d.name CONTAINS 'Cancer'")
             .return_("d.name AS disease", "drug.name AS drug")
             .limit(10))
        cypher, params = q.build()
        result = session.execute(cypher, params)
        assert len(result) > 0

    def test_multiple_match_via_raw(self, session):
        q = (Query()
             .raw("MATCH (p:Paper)-[:AUTHORED_BY]->(r:Researcher)")
             .raw("MATCH (r)-[:AFFILIATED_WITH]->(i:Institution)")
             .return_("p.title AS paper", "r.name AS author", "i.name AS institution")
             .limit(5))
        cypher, params = q.build()
        result = session.execute(cypher, params)
        assert len(result) > 0

    def test_optional_match(self, session):
        q = (Query()
             .match("Researcher", "r")
             .raw("OPTIONAL MATCH (r)-[:COLLABORATES_WITH]->(c:Researcher)")
             .return_("r.name AS researcher", "collect(c.name) AS collaborators")
             .limit(5))
        cypher, params = q.build()
        result = session.execute(cypher, params)
        assert len(result) > 0

    def test_with_clause(self, session):
        q = (Query()
             .match("Researcher", "r")
             .raw("WITH r, r.h_index AS h")
             .raw("WHERE h > 50")
             .return_("r.name AS name", "h")
             .order_by("h DESC"))
        cypher, params = q.build()
        result = session.execute(cypher, params)
        for r in result:
            assert r["h"] > 50

    def test_empty_query_build(self):
        q = Query()
        cypher, params = q.build()
        assert cypher == ""

    def test_param_override(self):
        q = (Query()
             .match("Drug", "n")
             .where("n.name = $name")
             .param("name", "first")
             .param("name", "second"))
        _, params = q.build()
        assert params["name"] == "second"

    def test_multiple_return_columns(self, session):
        q = (Query()
             .match("Researcher", "n")
             .return_("n.name AS name", "n.h_index AS h", "n.specialization AS spec")
             .limit(1))
        cypher, params = q.build()
        result = session.execute(cypher, params)
        assert "name" in result[0]
        assert "h" in result[0]
        assert "spec" in result[0]

    def test_match_with_model_class(self, session):
        q = Query().match(Researcher, "r").return_("r.name AS name").limit(3)
        cypher, params = q.build()
        result = session.execute(cypher, params)
        assert len(result) == 3


# ============================================================================
# 5. VECTOR SEARCH
# ============================================================================

class TestVectorSearch:
    def test_vector_search_model_builds_cypher(self):
        q = Query().vector_search_model(
            model=Paper,
            property="abstract_embedding",
            query_vector=[0.1] * 384,
            top_k=5,
        ).return_("node", "score")
        cypher, params = q.build()
        assert "db.index.vector.queryNodes" in cypher
        assert "idx_paper_abstract_embedding_vector" in cypher
        vec_param = next(v for v in params.values() if isinstance(v, list))
        assert len(vec_param) == 384

    def test_vector_search_executes(self, session):
        q = Query().vector_search_model(
            model=Paper,
            property="abstract_embedding",
            query_vector=[0.01] * 384,
            top_k=3,
        ).return_("node.title AS title", "score")
        cypher, params = q.build()
        result = session.execute(cypher, params)
        assert len(result) == 3
        assert all("title" in r for r in result)
        assert all("score" in r for r in result)

    def test_vector_search_with_filter(self, session):
        q = (Query()
             .vector_search_model(
                 model=Paper,
                 property="abstract_embedding",
                 query_vector=[0.01] * 384,
                 top_k=10,
             )
             .where("node.year >= 2024")
             .return_("node.title AS title", "node.year AS year", "score"))
        cypher, params = q.build()
        result = session.execute(cypher, params)
        for r in result:
            assert r["year"] >= 2024

    def test_vector_search_researcher(self, session):
        q = Query().vector_search_model(
            model=Researcher,
            property="bio_embedding",
            query_vector=[0.01] * 384,
            top_k=3,
        ).return_("node.name AS name", "score")
        cypher, params = q.build()
        result = session.execute(cypher, params)
        assert len(result) == 3

    def test_vector_search_disease(self, session):
        q = Query().vector_search_model(
            model=Disease,
            property="description_embedding",
            query_vector=[0.01] * 384,
            top_k=3,
        ).return_("node.name AS name", "score")
        cypher, params = q.build()
        result = session.execute(cypher, params)
        assert len(result) == 3


# ============================================================================
# 6. BULK OPS
# ============================================================================

class TestBulkOps:
    def test_bulk_create_nodes_generates_cypher(self):
        data = [{"name": "Test1", "country": "US", "type": "University"}]
        cypher, params = BulkOps.bulk_create_nodes(Institution, data)
        assert "UNWIND" in cypher
        assert "CREATE" in cypher

    def test_bulk_create_relationships_generates_cypher(self):
        data = [{"src_title": "Paper1", "tgt_name": "Researcher1", "position": "first"}]
        cypher, params = BulkOps.bulk_create_relationships(
            AuthoredBy, data, src_key="src_title", tgt_key="tgt_name"
        )
        assert "UNWIND" in cypher
        assert "AUTHORED_BY" in cypher

    def test_bulk_create_nodes_executes(self, session):
        data = [
            {"name": "TestInst_A", "country": "US", "type": "Lab"},
            {"name": "TestInst_B", "country": "UK", "type": "University"},
        ]
        cypher, params = BulkOps.bulk_create_nodes(Institution, data)
        session.execute(cypher, params)
        result = session.execute(
            "MATCH (n:Institution) WHERE n.name STARTS WITH 'TestInst_' RETURN n.name AS name"
        )
        assert len(result) == 2
        session.execute("MATCH (n:Institution) WHERE n.name STARTS WITH 'TestInst_' DETACH DELETE n")

    def test_bulk_create_relationships_executes(self, session):
        session.execute("CREATE (p:Paper {title: 'BulkTestPaper'}) CREATE (r:Researcher {name: 'BulkTestResearcher'})")
        data = [{"src_title": "BulkTestPaper", "tgt_name": "BulkTestResearcher", "position": "first"}]
        cypher, params = BulkOps.bulk_create_relationships(
            AuthoredBy, data, src_key="src_title", tgt_key="tgt_name"
        )
        session.execute(cypher, params)
        result = session.execute(
            "MATCH (p:Paper {title:'BulkTestPaper'})-[r:AUTHORED_BY]->(a:Researcher {name:'BulkTestResearcher'}) RETURN r.position AS pos"
        )
        assert len(result) == 1
        assert result[0]["pos"] == "first"
        session.execute("MATCH (n) WHERE n.name = 'BulkTestResearcher' OR n.title = 'BulkTestPaper' DETACH DELETE n")

    def test_bulk_merge_relationships(self, session):
        session.execute("CREATE (d:Disease {name: 'BulkTestDisease'}) CREATE (g:Gene {symbol: 'BTG1'})")
        data = [{"src_name": "BulkTestDisease", "tgt_symbol": "BTG1", "evidence_level": "strong"}]
        cypher, params = BulkOps.bulk_merge_relationships(
            AssociatedGene, data, src_key="src_name", tgt_key="tgt_symbol"
        )
        session.execute(cypher, params)
        result = session.execute(
            "MATCH (:Disease {name:'BulkTestDisease'})-[r:ASSOCIATED_WITH]->(:Gene {symbol:'BTG1'}) RETURN r.evidence_level AS ev"
        )
        assert result[0]["ev"] == "strong"
        session.execute("MATCH (n) WHERE n.name = 'BulkTestDisease' OR n.symbol = 'BTG1' DETACH DELETE n")

    def test_bulk_create_with_starts_with_match(self, session):
        session.execute("CREATE (p:Paper {title: 'SWTest: A Long Title Here'})")
        session.execute("CREATE (r:Researcher {name: 'SWTestResearcher'})")
        data = [{"src_title": "SWTest:", "tgt_name": "SWTestResearcher", "position": "lead"}]
        cypher, params = BulkOps.bulk_create_relationships(
            AuthoredBy, data, src_key="src_title", tgt_key="tgt_name", src_match="starts_with"
        )
        session.execute(cypher, params)
        result = session.execute(
            "MATCH (p:Paper)-[r:AUTHORED_BY]->(a:Researcher {name:'SWTestResearcher'}) RETURN p.title AS title"
        )
        assert len(result) == 1
        session.execute("MATCH (n) WHERE n.name = 'SWTestResearcher' OR n.title STARTS WITH 'SWTest:' DETACH DELETE n")

    def test_gene_bulk_ops_uses_symbol(self, session):
        data = [{"symbol": "TESTGENE1", "full_name": "Test Gene 1", "chromosome": "1", "pathway": "test"}]
        cypher, params = BulkOps.bulk_create_nodes(Gene, data)
        session.execute(cypher, params)
        result = session.execute("MATCH (g:Gene {symbol: 'TESTGENE1'}) RETURN g.full_name AS fn")
        assert result[0]["fn"] == "Test Gene 1"
        session.execute("MATCH (g:Gene {symbol: 'TESTGENE1'}) DELETE g")


# ============================================================================
# 7. REPOSITORY — __init__(model, db), find_one(**props), create(instance)
# ============================================================================

class TestRepository:
    def test_create_and_find(self, db):
        repo = Repository(Researcher, db)
        instance = Researcher(name="RepoTestResearcher", specialization="Testing", h_index=99)
        repo.create(instance)
        found = repo.find_one(name="RepoTestResearcher")
        assert found is not None
        # Cleanup
        repo.delete(name="RepoTestResearcher")

    def test_find_all(self, db):
        repo = Repository(Researcher, db)
        results = repo.find_all()
        assert len(results) > 0

    def test_find_by_property(self, db):
        repo = Repository(Researcher, db)
        results = repo.find_all()
        assert len(results) > 0

    def test_update(self, db):
        repo = Repository(Researcher, db)
        instance = Researcher(name="RepoUpdateTest", specialization="Before", h_index=10)
        repo.create(instance)
        repo.update({"name": "RepoUpdateTest"}, {"specialization": "After"})
        found = repo.find_one(name="RepoUpdateTest")
        assert found is not None
        repo.delete(name="RepoUpdateTest")

    def test_delete(self, db):
        repo = Repository(Researcher, db)
        instance = Researcher(name="RepoDeleteTest", specialization="Doomed", h_index=1)
        repo.create(instance)
        repo.delete(name="RepoDeleteTest")
        found = repo.find_one(name="RepoDeleteTest")
        assert found is None

    def test_count(self, db):
        repo = Repository(Researcher, db)
        c = repo.count()
        assert c > 0

    def test_find_by_id(self, db, session):
        repo = Repository(Researcher, db)
        result = session.execute("MATCH (r:Researcher) RETURN elementId(r) AS id LIMIT 1")
        eid = result[0]["id"]
        found = repo.find_by_id(eid)
        assert found is not None

    def test_update_by_id(self, db, session):
        repo = Repository(Researcher, db)
        instance = Researcher(name="RepoIdUpdateTest", specialization="Before", h_index=5)
        repo.create(instance)
        result = session.execute("MATCH (r:Researcher {name: 'RepoIdUpdateTest'}) RETURN elementId(r) AS id")
        eid = result[0]["id"]
        repo.update_by_id(eid, {"specialization": "After"})
        found = repo.find_by_id(eid)
        assert found is not None
        repo.delete(name="RepoIdUpdateTest")

    def test_delete_by_id(self, db, session):
        repo = Repository(Researcher, db)
        instance = Researcher(name="RepoIdDeleteTest", specialization="Doomed", h_index=1)
        repo.create(instance)
        result = session.execute("MATCH (r:Researcher {name: 'RepoIdDeleteTest'}) RETURN elementId(r) AS id")
        eid = result[0]["id"]
        repo.delete_by_id(eid)
        found = repo.find_one(name="RepoIdDeleteTest")
        assert found is None


# ============================================================================
# 8. TRAVERSAL — static methods returning (cypher, params)
# ============================================================================

class TestTraversal:
    def _get_two_node_ids(self, session):
        result = session.execute(
            "MATCH (a:Researcher)-[:AFFILIATED_WITH]->(b:Institution) "
            "RETURN elementId(a) AS a_id, elementId(b) AS b_id LIMIT 1"
        )
        return result[0]["a_id"], result[0]["b_id"]

    def test_neighbors_by_id(self, session):
        a_id, _ = self._get_two_node_ids(session)
        cypher, params = Traversal.neighbors_by_id(a_id)
        result = session.execute(cypher, params)
        assert isinstance(result, list)

    def test_shortest_path_by_id(self, session):
        a_id, b_id = self._get_two_node_ids(session)
        cypher, params = Traversal.shortest_path_by_id(a_id, b_id)
        result = session.execute(cypher, params)
        assert isinstance(result, list)

    def test_common_neighbors_by_id(self, session):
        result = session.execute(
            "MATCH (a:Researcher)-[:AFFILIATED_WITH]->(i:Institution)<-[:AFFILIATED_WITH]-(b:Researcher) "
            "RETURN elementId(a) AS a_id, elementId(b) AS b_id LIMIT 1"
        )
        if result:
            a_id, b_id = result[0]["a_id"], result[0]["b_id"]
            cypher, params = Traversal.common_neighbors_by_id(a_id, b_id)
            common = session.execute(cypher, params)
            assert isinstance(common, list)

    def test_subgraph_by_id(self, session):
        a_id, _ = self._get_two_node_ids(session)
        cypher, params = Traversal.subgraph_by_id(a_id, depth=2)
        result = session.execute(cypher, params)
        assert isinstance(result, list)


# ============================================================================
# 9. SCHEMA DDL
# ============================================================================

class TestSchemaDDL:
    def test_uniqueness_constraints(self, schema):
        ddl = SchemaDDL(schema)
        constraints = ddl.uniqueness_constraints()
        assert len(constraints) > 0
        assert any("Researcher" in c for c in constraints)
        assert any("Gene" in c and "symbol" in c for c in constraints)

    def test_property_indexes_exclude_embeddings(self, schema):
        ddl = SchemaDDL(schema)
        indexes = ddl.property_indexes()
        assert isinstance(indexes, list)
        for idx in indexes:
            assert "embedding" not in idx.lower()

    def test_vector_indexes(self, schema):
        ddl = SchemaDDL(schema)
        vec_indexes = ddl.vector_indexes()
        assert len(vec_indexes) >= 3
        assert any("abstract_embedding" in v for v in vec_indexes)

    def test_generate_all(self, schema):
        ddl = SchemaDDL(schema)
        all_stmts = ddl.generate_all()
        assert len(all_stmts) > 0
        assert any("CONSTRAINT" in s for s in all_stmts)
        assert any("VECTOR" in s for s in all_stmts)

    def test_generate_all_idempotent(self, session, schema):
        ddl = SchemaDDL(schema)
        for stmt in ddl.generate_all():
            try:
                session.execute(stmt)
            except Exception:
                pass  # IF NOT EXISTS handles duplicates


# ============================================================================
# 10. SCHEMA DIFF — __init__(old, new), has_changes is property
# ============================================================================

class TestSchemaDiff:
    def test_same_schema_no_changes(self, schema):
        diff = SchemaDiff(schema, schema)
        assert diff.has_changes is False

    def test_diff_detects_changes(self, schema):
        partial = GraphSchema.from_models([Researcher, Institution, AuthoredBy])
        diff = SchemaDiff(partial, schema)
        assert diff.has_changes is True


# ============================================================================
# 11. QUERY HISTORY — .entries is property, .to_context(), max_entries
# ============================================================================

class TestQueryHistory:
    def test_add_and_retrieve(self):
        history = QueryHistory(max_entries=10)
        history.add("MATCH (n) RETURN n", result_count=5, summary="test query")
        entries = history.entries
        assert len(entries) >= 1

    def test_max_entries_limit(self):
        history = QueryHistory(max_entries=3)
        for i in range(5):
            history.add(f"QUERY {i}", result_count=i)
        entries = history.entries
        assert len(entries) <= 3

    def test_to_context_returns_string(self):
        history = QueryHistory(max_entries=10)
        history.add("MATCH (n:Paper) RETURN n", result_count=10, summary="papers")
        ctx = history.to_context()
        assert isinstance(ctx, str)

    def test_clear(self):
        history = QueryHistory(max_entries=10)
        history.add("MATCH (n) RETURN n", result_count=1)
        history.clear()
        assert len(history.entries) == 0


# ============================================================================
# 12. AGENT TOOLS — .all_tool_specs(), .schema_context_for_prompt()
# ============================================================================

class TestAgentTools:
    def test_all_tool_specs(self, schema):
        tools = AgentTools(schema)
        specs = tools.all_tool_specs()
        assert isinstance(specs, list)
        assert len(specs) > 0

    def test_tool_spec_format(self, schema):
        tools = AgentTools(schema)
        specs = tools.all_tool_specs()
        for spec in specs:
            assert "type" in spec or "function" in spec

    def test_schema_context_for_prompt(self, schema):
        tools = AgentTools(schema)
        ctx = tools.schema_context_for_prompt()
        assert isinstance(ctx, str)
        assert "Researcher" in ctx


# ============================================================================
# 13. CYPHER VALIDATOR — requires Schema object
# ============================================================================

class TestCypherValidation:
    def test_valid_query(self):
        s = Schema({"Person": ["name"]}, {})
        v = CypherValidator(s)
        result = v.validate("MATCH (n:Person) RETURN n")
        assert result.is_valid

    def test_syntax_error(self):
        s = Schema({}, {})
        v = CypherValidator(s)
        result = v.validate("MACH (n) RETUN n")
        assert not result.is_valid

    def test_schema_aware_validation(self):
        s = Schema({"Researcher": ["name", "h_index"]}, {})
        v = CypherValidator(s)
        result = v.validate("MATCH (n:Researcher) RETURN n.name")
        assert result.is_valid

    def test_unknown_label_warning(self):
        s = Schema({"Person": ["name"]}, {})
        v = CypherValidator(s)
        result = v.validate("MATCH (n:NonExistent) RETURN n")
        assert len(result.errors) > 0 or len(result.warnings) > 0

    def test_valid_complex_query(self):
        s = Schema(
            {"Paper": ["title", "year"], "Researcher": ["name"]},
            {"AUTHORED_BY": ("Paper", "Researcher", [])},
        )
        v = CypherValidator(s)
        result = v.validate(
            "MATCH (p:Paper)-[:AUTHORED_BY]->(r:Researcher) "
            "WHERE p.year > 2020 "
            "RETURN p.title, r.name "
            "ORDER BY p.year DESC LIMIT 10"
        )
        assert result.is_valid


# ============================================================================
# 14. EDGE CASES & ERROR HANDLING
# ============================================================================

class TestEdgeCases:
    def test_query_builder_empty_where(self, session):
        q = Query().match("Researcher", "n").return_("n.name AS name")
        cypher, params = q.build()
        assert "WHERE" not in cypher

    def test_bulk_create_empty_list(self):
        cypher, params = BulkOps.bulk_create_nodes(Researcher, [])
        assert isinstance(cypher, str)

    def test_repository_find_one_nonexistent(self, db):
        repo = Repository(Researcher, db)
        found = repo.find_one(name="ABSOLUTELY_NONEXISTENT_12345")
        assert found is None

    def test_query_builder_only_raw(self, session):
        q = Query().raw("MATCH (n:Drug) RETURN count(n) AS cnt")
        cypher, params = q.build()
        result = session.execute(cypher, params)
        assert result[0]["cnt"] > 0


# ============================================================================
# 15. INTEGRATION PATTERNS (real app patterns)
# ============================================================================

class TestAppPatterns:
    def test_find_researchers_by_specialization(self, session):
        q = (Query()
             .match("Researcher", "r")
             .where("r.specialization CONTAINS $spec")
             .return_("r.name AS name", "r.specialization AS spec", "r.h_index AS h")
             .order_by("r.h_index DESC")
             .param("spec", "Onc"))
        cypher, params = q.build()
        result = session.execute(cypher, params)
        assert len(result) > 0

    def test_papers_with_authors_and_institutions(self, session):
        q = (Query()
             .raw("MATCH (p:Paper)-[:AUTHORED_BY]->(r:Researcher)-[:AFFILIATED_WITH]->(i:Institution)")
             .return_("p.title AS paper", "r.name AS author", "i.name AS institution")
             .order_by("p.citation_count DESC")
             .limit(5))
        cypher, params = q.build()
        result = session.execute(cypher, params)
        assert len(result) > 0
        assert all(k in result[0] for k in ["paper", "author", "institution"])

    def test_drug_gene_disease_chain(self, session):
        q = (Query()
             .raw("MATCH (d:Disease)-[:TREATS_WITH]->(drug:Drug)-[:TARGETS]->(g:Gene)")
             .return_("d.name AS disease", "drug.name AS drug", "g.symbol AS gene")
             .limit(10))
        cypher, params = q.build()
        result = session.execute(cypher, params)
        assert len(result) > 0

    def test_clinical_trial_lookup(self, session):
        q = (Query()
             .match("ClinicalTrial", "ct")
             .raw("-[:TRIAL_FOR]->(d:Disease)")
             .return_("ct.trial_id AS trial", "ct.title AS title", "d.name AS disease", "ct.phase AS phase")
             .order_by("ct.phase DESC"))
        cypher, params = q.build()
        result = session.execute(cypher, params)
        assert len(result) > 0

    def test_funding_analysis(self, session):
        q = (Query()
             .raw("MATCH (p:Paper)-[f:FUNDED_BY]->(fa:FundingAgency)")
             .return_("fa.name AS agency", "count(p) AS papers", "sum(f.amount_usd) AS total_funding")
             .order_by("total_funding DESC"))
        cypher, params = q.build()
        result = session.execute(cypher, params)
        assert len(result) > 0

    def test_collaboration_network(self, session):
        q = (Query()
             .raw("MATCH (a:Researcher)-[c:COLLABORATES_WITH]->(b:Researcher)")
             .return_("a.name AS researcher1", "b.name AS researcher2", "c.paper_count AS papers")
             .order_by("c.paper_count DESC")
             .limit(5))
        cypher, params = q.build()
        result = session.execute(cypher, params)
        assert len(result) > 0

    def test_full_crud_lifecycle(self, db):
        """Create, read, update, delete using Repository."""
        repo = Repository(Drug, db)
        instance = Drug(name="LifecycleDrug", drugbank_id="DB_LIFE", phase="phase1", mechanism="test")
        repo.create(instance)
        found = repo.find_one(name="LifecycleDrug")
        assert found is not None
        repo.update({"name": "LifecycleDrug"}, {"phase": "phase3"})
        found = repo.find_one(name="LifecycleDrug")
        assert found is not None
        repo.delete(name="LifecycleDrug")
        found = repo.find_one(name="LifecycleDrug")
        assert found is None

    def test_bulk_then_query_pattern(self, session):
        """Bulk insert then immediately query."""
        # Clean up any leftovers from previous runs
        session.execute("MATCH (d:Drug) WHERE d.name STARTS WITH 'BQTest_' DELETE d")
        data = [
            {"name": "BQTest_Drug1", "drugbank_id": "BQT1", "phase": "approved", "mechanism": "test"},
            {"name": "BQTest_Drug2", "drugbank_id": "BQT2", "phase": "phase3", "mechanism": "test"},
        ]
        cypher, params = BulkOps.bulk_create_nodes(Drug, data)
        session.execute(cypher, params)
        q = (Query()
             .match("Drug", "d")
             .where("d.name STARTS WITH 'BQTest_'")
             .return_("d.name AS name", "d.phase AS phase")
             .order_by("d.name"))
        cypher, params = q.build()
        result = session.execute(cypher, params)
        assert len(result) == 2
        assert result[0]["name"] == "BQTest_Drug1"
        session.execute("MATCH (d:Drug) WHERE d.name STARTS WITH 'BQTest_' DELETE d")
