"""Tests for the Pydantic Cypher ORM: models, query builder, schema bridge, agent tools."""

import json
import pytest
from cypher_validator.models import (
    NodeModel,
    RelationshipModel,
    Query,
    Cond,
    CondGroup,
    Op,
    RawExpr,
    GraphSchema,
    AgentTools,
    QueryPlan,
    QueryStep,
    QueryResult,
    node,
    relationship,
    _NODE_REGISTRY,
    _REL_REGISTRY,
    _to_upper_snake,
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
# NodeModel tests
# ---------------------------------------------------------------------------


class TestNodeModel:
    def test_label(self):
        assert Person.label() == "Person"
        assert Movie.label() == "Movie"

    def test_property_names(self):
        assert Person.property_names() == ["name", "age"]
        assert Movie.property_names() == ["title", "year"]

    def test_property_types(self):
        types = Person.property_types()
        assert types["name"] == "str"
        assert types["age"] == "int"

    def test_required_properties(self):
        assert Person.required_properties() == ["name"]
        assert Movie.required_properties() == ["title", "year"]

    def test_optional_properties(self):
        assert Person.optional_properties() == ["age"]

    def test_to_property_map(self):
        p = Person(name="Alice", age=30)
        assert p.to_property_map() == {"name": "Alice", "age": 30}

    def test_to_property_map_none_excluded(self):
        p = Person(name="Bob")
        props = p.to_property_map()
        assert "name" in props
        # age=0 should be included (it's 0, not None)
        assert props["age"] == 0

    def test_to_create_cypher(self):
        p = Person(name="Alice", age=30)
        cypher, params = p.to_create_cypher("n")
        assert "CREATE (n:Person" in cypher
        assert "RETURN n" in cypher
        assert params["n_name"] == "Alice"
        assert params["n_age"] == 30

    def test_to_merge_cypher(self):
        p = Person(name="Alice", age=30)
        cypher, params = p.to_merge_cypher("n", merge_keys=["name"])
        assert "MERGE (n:Person {name: $n_name})" in cypher
        assert "ON CREATE SET" in cypher
        assert params["n_name"] == "Alice"

    def test_match_cypher(self):
        cypher, params = Person.match_cypher("p", where={"name": "Alice"})
        assert "MATCH (p:Person)" in cypher
        assert "WHERE p.name = $p_name" in cypher
        assert params["p_name"] == "Alice"

    def test_match_cypher_no_where(self):
        cypher, params = Person.match_cypher("p")
        assert cypher == "MATCH (p:Person) RETURN p"
        assert params == {}

    def test_to_schema_description(self):
        desc = Person.to_schema_description()
        assert "Person" in desc
        assert "name" in desc
        assert "required" in desc.lower()

    def test_registry(self):
        assert "Person" in _NODE_REGISTRY
        assert "Movie" in _NODE_REGISTRY


# ---------------------------------------------------------------------------
# RelationshipModel tests
# ---------------------------------------------------------------------------


class TestRelationshipModel:
    def test_rel_type(self):
        assert ActedIn.rel_type() == "ACTED_IN"
        assert Directed.rel_type() == "DIRECTED"

    def test_source_target(self):
        assert ActedIn.source_label() == "Person"
        assert ActedIn.target_label() == "Movie"

    def test_property_names(self):
        assert ActedIn.property_names() == ["roles"]
        assert Directed.property_names() == []

    def test_to_create_cypher(self):
        rel = ActedIn(roles=["Neo"])
        cypher, params = rel.to_create_cypher(
            src_match={"name": "Keanu"},
            tgt_match={"title": "The Matrix"},
        )
        assert "MATCH (a:Person), (b:Movie)" in cypher
        assert "CREATE (a)-[r:ACTED_IN" in cypher
        assert params["a_name"] == "Keanu"
        assert params["b_title"] == "The Matrix"
        assert params["r_roles"] == ["Neo"]

    def test_to_schema_description(self):
        desc = ActedIn.to_schema_description()
        assert "ACTED_IN" in desc
        assert "Person" in desc
        assert "Movie" in desc

    def test_registry(self):
        assert "ACTED_IN" in _REL_REGISTRY
        assert "DIRECTED" in _REL_REGISTRY


# ---------------------------------------------------------------------------
# Condition tests
# ---------------------------------------------------------------------------


class TestCondition:
    def test_eq(self):
        c = Cond("n.name", "=", "$name")
        assert c.render() == "n.name = $name"

    def test_gt(self):
        c = Cond("n.age", ">", 18)
        assert c.render() == "n.age > 18"

    def test_is_null(self):
        c = Cond("n.email", "IS NULL")
        assert c.render() == "n.email IS NULL"

    def test_is_not_null(self):
        c = Cond("n.email", "IS NOT NULL")
        assert c.render() == "n.email IS NOT NULL"

    def test_contains(self):
        c = Cond("n.name", "CONTAINS", "'ali'")
        assert c.render() == "n.name CONTAINS 'ali'"

    def test_in(self):
        c = Cond("n.age", "IN", [1, 2, 3])
        assert c.render() == "n.age IN [1, 2, 3]"

    def test_bool_value(self):
        c = Cond("n.active", "=", True)
        assert c.render() == "n.active = true"

    def test_and(self):
        c1 = Cond("n.age", ">", 18)
        c2 = Cond("n.name", "=", "$name")
        combined = c1 & c2
        assert isinstance(combined, CondGroup)
        assert "AND" in combined.render()

    def test_or(self):
        c1 = Cond("n.age", ">", 18)
        c2 = Cond("n.age", "<", 65)
        combined = c1 | c2
        assert "OR" in combined.render()

    def test_complex_group(self):
        c1 = Cond("n.age", ">", 18)
        c2 = Cond("n.name", "=", "$name")
        c3 = Cond("n.active", "=", True)
        group = (c1 & c2) | c3
        rendered = group.render()
        assert "OR" in rendered
        assert "AND" in rendered

    def test_property_reference(self):
        c = Cond("n.name", "=", "m.name")
        assert c.render() == "n.name = m.name"

    def test_regex(self):
        c = Cond("n.name", "=~", "'(?i)alice'")
        assert c.render() == "n.name =~ '(?i)alice'"


# ---------------------------------------------------------------------------
# Query Builder tests
# ---------------------------------------------------------------------------


class TestQueryBuilder:
    def test_simple_match_return(self):
        q = Query().match(Person, "p").return_("p")
        cypher, params = q.build()
        assert cypher == "MATCH (p:Person) RETURN p"
        assert params == {}

    def test_match_where_return(self):
        q = (Query()
             .match(Person, "p")
             .where(Cond("p.name", "=", "$name"))
             .return_("p"))
        cypher, _ = q.build()
        assert "MATCH (p:Person)" in cypher
        assert "WHERE p.name = $name" in cypher
        assert "RETURN p" in cypher

    def test_match_with_props(self):
        q = Query().match(Person, "p", props={"name": "Alice"}).return_("p")
        cypher, params = q.build()
        assert "MATCH (p:Person {name:" in cypher
        assert "Alice" in list(params.values())

    def test_create(self):
        q = Query().create(Person, "p", props={"name": "Alice", "age": 30}).return_("p")
        cypher, params = q.build()
        assert "CREATE (p:Person" in cypher
        assert len(params) == 2

    def test_merge(self):
        q = Query().merge(Person, "p", props={"name": "Alice"}).return_("p")
        cypher, params = q.build()
        assert "MERGE (p:Person" in cypher

    def test_match_path(self):
        q = (Query()
             .match_path(
                 (Person, "p", None),
                 (ActedIn, "r", None),
                 (Movie, "m", None),
             )
             .return_("p.name", "m.title"))
        cypher, _ = q.build()
        assert "(p:Person)" in cypher
        assert "ACTED_IN" in cypher
        assert "(m:Movie)" in cypher

    def test_optional_match(self):
        q = Query().match(Person, "p").optional_match(Movie, "m").return_("p", "m")
        cypher, _ = q.build()
        assert "OPTIONAL MATCH (m:Movie)" in cypher

    def test_set_props(self):
        q = (Query()
             .match(Person, "p")
             .where(Cond("p.name", "=", "$name"))
             .set_props("p", {"age": 31})
             .return_("p"))
        cypher, params = q.build()
        assert "SET" in cypher
        assert 31 in list(params.values())

    def test_delete(self):
        q = Query().match(Person, "p").delete("p", detach=True)
        cypher, _ = q.build()
        assert "DETACH DELETE p" in cypher

    def test_with_chain(self):
        q = (Query()
             .match(Person, "p")
             .with_("p.name AS name", "p.age AS age")
             .return_("name", "count(*) AS cnt"))
        cypher, _ = q.build()
        assert "WITH p.name AS name" in cypher

    def test_distinct(self):
        q = Query().match(Person, "p").return_("p.name", distinct=True)
        cypher, _ = q.build()
        assert "RETURN DISTINCT p.name" in cypher

    def test_order_skip_limit(self):
        q = (Query()
             .match(Person, "p")
             .return_("p")
             .order_by("p.name")
             .skip(10)
             .limit(5))
        cypher, _ = q.build()
        assert "ORDER BY p.name" in cypher
        assert "SKIP 10" in cypher
        assert "LIMIT 5" in cypher

    def test_unwind(self):
        q = Query().unwind("[1, 2, 3]", "x").return_("x")
        cypher, _ = q.build()
        assert "UNWIND [1, 2, 3] AS x" in cypher

    def test_call_subquery(self):
        sub = Query().match(Person, "p").return_("p.name AS name")
        q = Query().call_subquery(sub).return_("name")
        cypher, _ = q.build()
        assert "CALL {" in cypher
        assert "MATCH (p:Person)" in cypher

    def test_union(self):
        q1 = Query().match(Person, "p").return_("p.name AS name")
        q2 = Query().match(Movie, "m").return_("m.title AS name")
        q = q1.union(q2)
        cypher, _ = q.build()
        assert "UNION" in cypher

    def test_raw(self):
        q = Query().raw("MATCH (n) RETURN count(n)")
        cypher, _ = q.build()
        assert cypher == "MATCH (n) RETURN count(n)"

    def test_params(self):
        q = (Query()
             .match(Person, "p")
             .where("p.name = $name")
             .return_("p")
             .param("name", "Alice"))
        _, params = q.build()
        assert params["name"] == "Alice"

    def test_str_repr(self):
        q = Query().match(Person, "p").return_("p")
        assert str(q) == "MATCH (p:Person) RETURN p"
        assert "Query(" in repr(q)

    def test_explain(self):
        q = (Query()
             .match(Person, "p")
             .where(Cond("p.age", ">", 18))
             .return_("p.name")
             .limit(10))
        explanation = q.explain()
        assert "Find pattern" in explanation
        assert "Filter" in explanation
        assert "Return" in explanation
        assert "Limit" in explanation

    def test_label_as_string(self):
        q = Query().match("CustomLabel", "n").return_("n")
        cypher, _ = q.build()
        assert "(n:CustomLabel)" in cypher

    def test_rel_as_string(self):
        q = (Query()
             .match_path(
                 ("Person", "p", None),
                 ("KNOWS", "r", None),
                 ("Person", "q", None),
             )
             .return_("p", "q"))
        cypher, _ = q.build()
        assert "KNOWS" in cypher

    def test_variable_length_path(self):
        q = (Query()
             .match_path(
                 (Person, "p", None),
                 ("KNOWS", "r", None),
                 (Person, "q", None),
                 min_hops=1,
                 max_hops=3,
             )
             .return_("p", "q"))
        cypher, _ = q.build()
        assert "*1..3" in cypher

    def test_foreach(self):
        q = (Query()
             .match(Person, "p")
             .foreach("x", "[1,2,3]", "SET p.val = x"))
        cypher, _ = q.build()
        assert "FOREACH" in cypher

    def test_create_path(self):
        q = (Query()
             .create_path(
                 (Person, "p", {"name": "Alice"}),
                 (ActedIn, "r", None),
                 (Movie, "m", {"title": "Matrix"}),
             ))
        cypher, params = q.build()
        assert "CREATE" in cypher
        assert "ACTED_IN" in cypher
        assert "Alice" in list(params.values())

    def test_on_create_set(self):
        q = (Query()
             .merge(Person, "p", props={"name": "Alice"})
             .on_create_set("p.created = timestamp()")
             .on_match_set("p.updated = timestamp()")
             .return_("p"))
        cypher, _ = q.build()
        assert "ON CREATE SET" in cypher
        assert "ON MATCH SET" in cypher

    def test_and_where(self):
        q = (Query()
             .match(Person, "p")
             .where("p.age > 18")
             .and_where("p.name = $name")
             .return_("p"))
        cypher, _ = q.build()
        assert "WHERE p.age > 18 AND p.name = $name" in cypher

    def test_pattern_string(self):
        q = Query().match(pattern="(a:Person)-[:KNOWS]->(b:Person)").return_("a", "b")
        cypher, _ = q.build()
        assert "MATCH (a:Person)-[:KNOWS]->(b:Person)" in cypher

    def test_direction_in(self):
        q = (Query()
             .match_path(
                 (Movie, "m", None),
                 (ActedIn, "r", None),
                 (Person, "p", None),
                 direction="in",
             )
             .return_("p", "m"))
        cypher, _ = q.build()
        assert "<-[r:ACTED_IN]-" in cypher

    def test_direction_undirected(self):
        q = (Query()
             .match_path(
                 (Person, "a", None),
                 ("KNOWS", "r", None),
                 (Person, "b", None),
                 direction="both",
             )
             .return_("a", "b"))
        cypher, _ = q.build()
        assert "-[r:KNOWS]-" in cypher
        assert "->" not in cypher
        assert "<-" not in cypher


# ---------------------------------------------------------------------------
# GraphSchema tests
# ---------------------------------------------------------------------------


class TestGraphSchema:
    def test_from_models(self):
        schema = GraphSchema.from_models([Person, Movie, ActedIn, Directed])
        assert len(schema.node_models) == 2
        assert len(schema.rel_models) == 2

    def test_to_dict(self):
        schema = GraphSchema.from_models([Person, Movie, ActedIn])
        d = schema.to_dict()
        assert "Person" in d["nodes"]
        assert "Movie" in d["nodes"]
        assert "ACTED_IN" in d["relationships"]
        assert d["relationships"]["ACTED_IN"][0] == "Person"
        assert d["relationships"]["ACTED_IN"][1] == "Movie"

    def test_to_json(self):
        schema = GraphSchema.from_models([Person, Movie, ActedIn])
        j = schema.to_json()
        parsed = json.loads(j)
        assert "Person" in parsed["nodes"]

    def test_to_prompt(self):
        schema = GraphSchema.from_models([Person, Movie, ActedIn])
        prompt = schema.to_prompt()
        assert "Person" in prompt
        assert "Movie" in prompt
        assert "ACTED_IN" in prompt

    def test_to_markdown(self):
        schema = GraphSchema.from_models([Person, Movie, ActedIn])
        md = schema.to_markdown()
        assert "| Person |" in md
        assert "| ACTED_IN |" in md

    def test_from_registry(self):
        schema = GraphSchema.from_registry()
        assert len(schema.node_models) >= 2
        assert len(schema.rel_models) >= 2

    def test_merge(self):
        s1 = GraphSchema.from_models([Person])
        s2 = GraphSchema.from_models([Movie, ActedIn])
        merged = s1.merge(s2)
        assert len(merged.node_models) == 2
        assert len(merged.rel_models) == 1

    def test_constraints_indexes(self):
        class ConstrainedNode(NodeModel):
            __label__ = "Constrained"
            __constraints__ = ["CREATE CONSTRAINT FOR (n:Constrained) REQUIRE n.id IS UNIQUE"]
            __indexes__ = ["CREATE INDEX FOR (n:Constrained) ON (n.name)"]
            id: str
            name: str

        schema = GraphSchema.from_models([ConstrainedNode])
        assert len(schema.get_constraints()) == 1
        assert len(schema.get_indexes()) == 1


# ---------------------------------------------------------------------------
# Dynamic model factory tests
# ---------------------------------------------------------------------------


class TestDynamicModels:
    def test_node_factory(self):
        City = node("City", name=(str, ...), population=(int, 0))
        assert City.label() == "City"
        assert "name" in City.property_names()
        c = City(name="Berlin", population=3_600_000)
        assert c.to_property_map()["name"] == "Berlin"

    def test_relationship_factory(self):
        City = node("DynCity", name=str)
        LivesIn = relationship("LIVES_IN", Person, City)
        assert LivesIn.rel_type() == "LIVES_IN"
        assert LivesIn.source_label() == "Person"
        assert LivesIn.target_label() == "DynCity"

    def test_dynamic_in_query(self):
        City = node("QCity", name=str)
        q = Query().match(City, "c").return_("c")
        cypher, _ = q.build()
        assert "(c:QCity)" in cypher


# ---------------------------------------------------------------------------
# Agent Tools tests
# ---------------------------------------------------------------------------


class TestAgentTools:
    @pytest.fixture
    def tools(self):
        schema = GraphSchema.from_models([Person, Movie, ActedIn, Directed])
        return AgentTools(schema)

    def test_query_tool_spec_openai(self, tools):
        spec = tools.query_tool_spec("openai")
        assert spec["type"] == "function"
        assert spec["function"]["name"] == "execute_cypher"
        assert "cypher" in spec["function"]["parameters"]["properties"]

    def test_query_tool_spec_anthropic(self, tools):
        spec = tools.query_tool_spec("anthropic")
        assert spec["name"] == "execute_cypher"
        assert "input_schema" in spec

    def test_create_node_tool_spec(self, tools):
        spec = tools.create_node_tool_spec()
        labels = spec["function"]["parameters"]["properties"]["label"]["enum"]
        assert "Person" in labels
        assert "Movie" in labels

    def test_create_relationship_tool_spec(self, tools):
        spec = tools.create_relationship_tool_spec()
        rels = spec["function"]["parameters"]["properties"]["rel_type"]["enum"]
        assert "ACTED_IN" in rels

    def test_all_tool_specs(self, tools):
        specs = tools.all_tool_specs()
        assert len(specs) == 3

    def test_handle_execute_cypher(self, tools):
        result = tools.handle_tool_call(
            "execute_cypher",
            {"cypher": "MATCH (n) RETURN n", "parameters": {"limit": 10}},
        )
        assert result == ("MATCH (n) RETURN n", {"limit": 10})

    def test_handle_create_node(self, tools):
        result = tools.handle_tool_call(
            "create_node",
            {"label": "Person", "properties": {"name": "Alice", "age": 30}},
        )
        assert result is not None
        cypher, params = result
        assert "CREATE" in cypher
        assert "Person" in cypher

    def test_handle_create_relationship(self, tools):
        result = tools.handle_tool_call(
            "create_relationship",
            {
                "rel_type": "ACTED_IN",
                "source_match": {"name": "Keanu"},
                "target_match": {"title": "Matrix"},
                "properties": {"roles": ["Neo"]},
            },
        )
        assert result is not None
        cypher, params = result
        assert "ACTED_IN" in cypher

    def test_handle_unknown_tool(self, tools):
        assert tools.handle_tool_call("unknown", {}) is None

    def test_schema_context_for_prompt(self, tools):
        ctx = tools.schema_context_for_prompt()
        assert "Neo4j" in ctx
        assert "Person" in ctx
        assert "execute_cypher" in ctx


# ---------------------------------------------------------------------------
# QueryPlan tests
# ---------------------------------------------------------------------------


class TestQueryPlan:
    def test_execution_order(self):
        plan = QueryPlan(
            goal="Find actors and their movies",
            steps=[
                QueryStep(
                    description="Get all persons",
                    cypher="MATCH (p:Person) RETURN p",
                ),
                QueryStep(
                    description="Get movies for each person",
                    cypher="MATCH (p:Person)-[:ACTED_IN]->(m:Movie) RETURN p, m",
                    depends_on=[0],
                ),
            ],
        )
        waves = plan.to_execution_order()
        assert waves == [[0], [1]]

    def test_parallel_steps(self):
        plan = QueryPlan(
            goal="Count nodes",
            steps=[
                QueryStep(description="Count persons", cypher="MATCH (p:Person) RETURN count(p)"),
                QueryStep(description="Count movies", cypher="MATCH (m:Movie) RETURN count(m)"),
            ],
        )
        waves = plan.to_execution_order()
        assert waves == [[0, 1]]

    def test_explain(self):
        plan = QueryPlan(
            goal="Test",
            steps=[
                QueryStep(description="Step 1", cypher="MATCH (n) RETURN n", is_read=True),
                QueryStep(description="Step 2", cypher="CREATE (n:Test)", is_read=False, depends_on=[0]),
            ],
        )
        explanation = plan.explain()
        assert "Wave 1" in explanation
        assert "Wave 2" in explanation
        assert "READ" in explanation
        assert "WRITE" in explanation


# ---------------------------------------------------------------------------
# QueryResult tests
# ---------------------------------------------------------------------------


class TestQueryResult:
    def test_success(self):
        r = QueryResult(
            cypher="MATCH (n) RETURN n",
            records=[{"n": "Alice"}, {"n": "Bob"}],
        )
        assert r.success
        assert r.count == 2

    def test_error(self):
        r = QueryResult(cypher="BAD QUERY", error="Syntax error")
        assert not r.success

    def test_to_markdown(self):
        r = QueryResult(
            cypher="MATCH (n) RETURN n.name",
            records=[{"name": "Alice"}, {"name": "Bob"}],
        )
        md = r.to_markdown()
        assert "Alice" in md
        assert "Bob" in md

    def test_to_markdown_error(self):
        r = QueryResult(cypher="BAD", error="fail")
        assert "Error" in r.to_markdown()

    def test_to_markdown_empty(self):
        r = QueryResult(cypher="MATCH (n) RETURN n")
        assert "No results" in r.to_markdown()

    def test_to_natural_language(self):
        r = QueryResult(
            cypher="q",
            records=[{"name": "Alice"}],
        )
        assert "1 result" in r.to_natural_language()

    def test_to_natural_language_multi(self):
        r = QueryResult(
            cypher="q",
            records=[{"a": 1}, {"a": 2}, {"a": 3}],
        )
        assert "3 results" in r.to_natural_language()

    def test_to_json(self):
        r = QueryResult(cypher="MATCH (n) RETURN n")
        parsed = json.loads(r.to_json())
        assert parsed["cypher"] == "MATCH (n) RETURN n"


# ---------------------------------------------------------------------------
# Helper tests
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_to_upper_snake(self):
        assert _to_upper_snake("ActedIn") == "ACTED_IN"
        assert _to_upper_snake("HasRelation") == "HAS_RELATION"
        assert _to_upper_snake("ABC") == "ABC"
        assert _to_upper_snake("simpleWord") == "SIMPLE_WORD"

    def test_raw_expr(self):
        e = RawExpr("count(*)")
        assert e.render() == "count(*)"

    def test_op_enum(self):
        assert Op.EQ.value == "="
        assert Op.CONTAINS.value == "CONTAINS"
        assert Op.REGEX.value == "=~"


# ---------------------------------------------------------------------------
# Integration tests — Query + Schema together
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_query_schema_prompt_roundtrip(self):
        """Build query, generate schema, verify schema contains needed labels."""
        schema = GraphSchema.from_models([Person, Movie, ActedIn])
        q = (Query()
             .match_path(
                 (Person, "p", None),
                 (ActedIn, "r", None),
                 (Movie, "m", None),
             )
             .where(Cond("p.name", "=", "$name"))
             .return_("p.name", "m.title", "r.roles"))
        cypher, _ = q.build()
        prompt = schema.to_prompt()
        # Schema prompt should mention all types used in query
        assert "Person" in prompt
        assert "Movie" in prompt
        assert "ACTED_IN" in prompt

    def test_agent_tool_handles_model_create(self):
        """Agent creates a node via tool call, result is valid Cypher."""
        schema = GraphSchema.from_models([Person, Movie, ActedIn])
        tools = AgentTools(schema)
        result = tools.handle_tool_call(
            "create_node",
            {"label": "Person", "properties": {"name": "Neo", "age": 35}},
        )
        assert result is not None
        cypher, params = result
        assert "Person" in cypher
        assert params.get("n_name") == "Neo"

    def test_complex_query_build(self):
        """Build a realistic multi-clause query."""
        q = (Query()
             .match_path(
                 (Person, "actor", None),
                 (ActedIn, "r", None),
                 (Movie, "m", None),
             )
             .where(Cond("m.year", ">", 2000))
             .with_("actor", "count(m) AS movie_count")
             .where(Cond("movie_count", ">", 5))
             .return_("actor.name", "movie_count")
             .order_by("movie_count DESC")
             .limit(10))
        cypher, _ = q.build()
        assert "MATCH" in cypher
        assert "WHERE" in cypher
        assert "WITH" in cypher
        assert "ORDER BY" in cypher
        assert "LIMIT 10" in cypher
