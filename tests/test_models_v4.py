"""Tests for iteration 4: CypherFn, multi-label, PathBuilder, Repository."""

from unittest.mock import MagicMock
import pytest
from cypher_validator.models import (
    NodeModel,
    RelationshipModel,
    Query,
    GraphSchema,
    NodeRef,
    RelRef,
    PropExpr,
    CypherFn,
    fn,
    PathBuilder,
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


class Actor(NodeModel):
    __labels__ = ["Person", "Actor"]
    name: str
    guild_id: str = ""


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
# Multi-label tests
# ---------------------------------------------------------------------------


class TestMultiLabel:
    def test_labels_single(self):
        assert Person.labels() == ["Person"]

    def test_labels_multi(self):
        assert Actor.labels() == ["Person", "Actor"]

    def test_label_returns_first(self):
        assert Actor.label() == "Person"

    def test_labels_cypher(self):
        assert Actor.labels_cypher() == ":Person:Actor"

    def test_multi_label_in_query(self):
        q = Query().match(Actor, "a").return_("a")
        cypher, _ = q.build()
        assert "(a:Person:Actor)" in cypher

    def test_multi_label_in_path_builder(self):
        path = PathBuilder(Actor, "a").rel(ActedIn, "r").to(Movie, "m")
        built = path.build()
        assert "(a:Person:Actor)" in built
        assert "(m:Movie)" in built


# ---------------------------------------------------------------------------
# CypherFn tests
# ---------------------------------------------------------------------------


class TestCypherFn:
    # -- Aggregation --

    def test_count_star(self):
        assert CypherFn.count() == "count(*)"
        assert fn.count() == "count(*)"

    def test_count_var(self):
        assert fn.count("n") == "count(n)"

    def test_count_node_ref(self):
        p = NodeRef(Person, "p")
        assert fn.count(p) == "count(p)"

    def test_count_prop_expr(self):
        p = NodeRef(Person, "p")
        assert fn.count(p.name) == "count(p.name)"

    def test_count_distinct(self):
        p = NodeRef(Person, "p")
        assert fn.count_distinct(p) == "count(DISTINCT p)"
        assert fn.count_distinct(p.name) == "count(DISTINCT p.name)"
        assert fn.count_distinct("n") == "count(DISTINCT n)"

    def test_sum(self):
        assert fn.sum("n.age") == "sum(n.age)"
        p = NodeRef(Person, "p")
        assert fn.sum(p.age) == "sum(p.age)"

    def test_avg(self):
        assert fn.avg("n.age") == "avg(n.age)"

    def test_min(self):
        assert fn.min("n.age") == "min(n.age)"

    def test_max(self):
        assert fn.max("n.age") == "max(n.age)"

    def test_collect(self):
        assert fn.collect("n.name") == "collect(n.name)"
        p = NodeRef(Person, "p")
        assert fn.collect(p) == "collect(p)"
        assert fn.collect(p.name) == "collect(p.name)"

    def test_collect_distinct(self):
        assert fn.collect_distinct("n.name") == "collect(DISTINCT n.name)"

    # -- Scalar --

    def test_coalesce(self):
        p = NodeRef(Person, "p")
        assert fn.coalesce(p.name, "'Unknown'") == "coalesce(p.name, 'Unknown')"

    def test_size(self):
        assert fn.size("n.roles") == "size(n.roles)"

    def test_length(self):
        assert fn.length("path") == "length(path)"

    def test_type(self):
        r = RelRef(ActedIn, "r")
        assert fn.type(r) == "type(r)"
        assert fn.type("r") == "type(r)"

    def test_labels(self):
        p = NodeRef(Person, "p")
        assert fn.labels(p) == "labels(p)"
        assert fn.labels("n") == "labels(n)"

    def test_id(self):
        p = NodeRef(Person, "p")
        assert fn.id(p) == "id(p)"

    def test_element_id(self):
        p = NodeRef(Person, "p")
        assert fn.element_id(p) == "elementId(p)"

    # -- String --

    def test_to_lower(self):
        assert fn.to_lower("n.name") == "toLower(n.name)"

    def test_to_upper(self):
        assert fn.to_upper("n.name") == "toUpper(n.name)"

    def test_trim(self):
        assert fn.trim("n.name") == "trim(n.name)"

    def test_replace(self):
        assert fn.replace("n.name", " ", "_") == "replace(n.name, ' ', '_')"

    def test_substring(self):
        assert fn.substring("n.name", 0, 3) == "substring(n.name, 0, 3)"
        assert fn.substring("n.name", 5) == "substring(n.name, 5)"

    # -- Math --

    def test_abs(self):
        assert fn.abs("n.val") == "abs(n.val)"

    def test_ceil(self):
        assert fn.ceil("n.val") == "ceil(n.val)"

    def test_floor(self):
        assert fn.floor("n.val") == "floor(n.val)"

    def test_round(self):
        assert fn.round("n.val") == "round(n.val)"

    # -- Temporal --

    def test_timestamp(self):
        assert fn.timestamp() == "timestamp()"

    def test_date(self):
        assert fn.date() == "date()"
        assert fn.date("'2024-01-01'") == "date('2024-01-01')"

    def test_datetime(self):
        assert fn.datetime() == "datetime()"

    # -- Alias --

    def test_as(self):
        assert fn.as_("count(n)", "total") == "count(n) AS total"

    # -- Integration with Query builder --

    def test_fn_in_return(self):
        p = NodeRef(Person, "p")
        q = (Query()
             .match(p)
             .return_(
                 fn.as_(fn.count(p), "total"),
                 fn.as_(fn.avg(p.age), "avg_age"),
             ))
        cypher, _ = q.build()
        assert "count(p) AS total" in cypher
        assert "avg(p.age) AS avg_age" in cypher

    def test_fn_in_with(self):
        p = NodeRef(Person, "p")
        q = (Query()
             .match(p)
             .with_(fn.as_(fn.collect(p.name), "names"))
             .return_("names"))
        cypher, _ = q.build()
        assert "collect(p.name) AS names" in cypher


# ---------------------------------------------------------------------------
# PathBuilder tests
# ---------------------------------------------------------------------------


class TestPathBuilder:
    def test_simple_path(self):
        path = PathBuilder(Person, "p").rel(ActedIn, "r").to(Movie, "m")
        built = path.build()
        assert "(p:Person)" in built
        assert "ACTED_IN" in built
        assert "(m:Movie)" in built
        assert "->" in built

    def test_multi_hop(self):
        path = (PathBuilder(Person, "actor")
                .rel(ActedIn, "r")
                .to(Movie, "movie")
                .rel("DIRECTED", direction="in")
                .to(Person, "director"))
        built = path.build()
        assert "(actor:Person)" in built
        assert "(movie:Movie)" in built
        assert "(director:Person)" in built
        assert "ACTED_IN" in built
        assert "DIRECTED" in built
        assert "<-" in built

    def test_direction_in(self):
        path = PathBuilder(Movie, "m").rel(ActedIn, direction="in").to(Person, "p")
        built = path.build()
        assert "<-[" in built

    def test_direction_both(self):
        path = PathBuilder(Person, "a").rel("KNOWS", direction="both").to(Person, "b")
        built = path.build()
        assert "-[" in built
        assert "]-" in built
        assert "->" not in built
        assert "<-" not in built

    def test_variable_length(self):
        path = PathBuilder(Person, "a").rel("KNOWS", min_hops=1, max_hops=3).to(Person, "b")
        built = path.build()
        assert "*1..3" in built

    def test_with_props(self):
        path = PathBuilder(Person, "p", props={"name": "Alice"}).rel(ActedIn).to(Movie, "m")
        built = path.build()
        params = path.params
        assert "name:" in built
        assert "Alice" in list(params.values())

    def test_str_repr(self):
        path = PathBuilder(Person, "p").rel(ActedIn).to(Movie, "m")
        assert "(p:Person)" in str(path)
        assert "PathBuilder" in repr(path)

    def test_to_query(self):
        path = PathBuilder(Person, "p").rel(ActedIn, "r").to(Movie, "m")
        q = path.to_query().return_("p", "m")
        cypher, _ = q.build()
        assert "MATCH" in cypher
        assert "(p:Person)" in cypher

    def test_in_query_match(self):
        path = PathBuilder(Person, "p").rel(ActedIn, "r").to(Movie, "m")
        q = Query().match(pattern=path.build()).return_("p.name", "m.title")
        cypher, _ = q.build()
        assert "MATCH (p:Person)" in cypher

    def test_no_var_no_label(self):
        path = PathBuilder(Person, "p").rel(ActedIn).to(Movie)
        built = path.build()
        assert "(:Movie)" in built

    def test_rel_no_type(self):
        path = PathBuilder(Person, "p").rel().to(Movie, "m")
        built = path.build()
        assert "-[]->" in built


# ---------------------------------------------------------------------------
# Repository tests
# ---------------------------------------------------------------------------


class TestRepository:
    @pytest.fixture
    def mock_db(self):
        db = MagicMock()
        db.execute.return_value = [{"n": {"name": "Alice", "age": 30}}]
        return db

    @pytest.fixture
    def repo(self, mock_db):
        return Repository(Person, mock_db)

    def test_find_all(self, repo, mock_db):
        repo.find_all()
        call_args = mock_db.execute.call_args
        assert "MATCH (n:Person) RETURN n" == call_args[0][0]

    def test_find_all_with_limit(self, repo, mock_db):
        repo.find_all(limit=10)
        cypher = mock_db.execute.call_args[0][0]
        assert "LIMIT 10" in cypher

    def test_find_all_with_order(self, repo, mock_db):
        repo.find_all(order_by="name")
        cypher = mock_db.execute.call_args[0][0]
        assert "ORDER BY n.name" in cypher

    def test_find_all_with_skip(self, repo, mock_db):
        repo.find_all(skip=5, limit=10)
        cypher = mock_db.execute.call_args[0][0]
        assert "SKIP 5" in cypher
        assert "LIMIT 10" in cypher

    def test_find_by(self, repo, mock_db):
        repo.find_by(name="Alice")
        cypher = mock_db.execute.call_args[0][0]
        params = mock_db.execute.call_args[0][1]
        assert "WHERE n.name = $n_name" in cypher
        assert params["n_name"] == "Alice"

    def test_find_by_multiple(self, repo, mock_db):
        repo.find_by(name="Alice", age=30)
        cypher = mock_db.execute.call_args[0][0]
        assert "n.name = $n_name" in cypher
        assert "n.age = $n_age" in cypher

    def test_find_one(self, repo, mock_db):
        result = repo.find_one(name="Alice")
        cypher = mock_db.execute.call_args[0][0]
        assert "LIMIT 1" in cypher

    def test_find_one_not_found(self, repo, mock_db):
        mock_db.execute.return_value = []
        result = repo.find_one(name="Nobody")
        assert result is None

    def test_exists(self, repo, mock_db):
        mock_db.execute.return_value = [{"exists": True}]
        assert repo.exists(name="Alice") is True

    def test_exists_false(self, repo, mock_db):
        mock_db.execute.return_value = [{"exists": False}]
        assert repo.exists(name="Nobody") is False

    def test_count(self, repo, mock_db):
        mock_db.execute.return_value = [{"count": 42}]
        assert repo.count() == 42

    def test_count_filtered(self, repo, mock_db):
        mock_db.execute.return_value = [{"count": 5}]
        result = repo.count(age=30)
        cypher = mock_db.execute.call_args[0][0]
        assert "WHERE" in cypher
        assert result == 5

    def test_create(self, repo, mock_db):
        p = Person(name="Bob", age=25)
        repo.create(p)
        cypher = mock_db.execute.call_args[0][0]
        assert "CREATE" in cypher
        assert "Person" in cypher

    def test_create_many(self, repo, mock_db):
        items = [{"name": "A", "age": 1}, {"name": "B", "age": 2}]
        repo.create_many(items)
        cypher = mock_db.execute.call_args[0][0]
        assert "UNWIND" in cypher

    def test_merge(self, repo, mock_db):
        p = Person(name="Alice", age=30)
        repo.merge(p, merge_keys=["name"])
        cypher = mock_db.execute.call_args[0][0]
        assert "MERGE" in cypher

    def test_merge_many(self, repo, mock_db):
        items = [{"name": "A", "age": 1}]
        repo.merge_many(items, merge_keys=["name"])
        cypher = mock_db.execute.call_args[0][0]
        assert "MERGE" in cypher
        assert "UNWIND" in cypher

    def test_update(self, repo, mock_db):
        repo.update({"name": "Alice"}, {"age": 31})
        cypher = mock_db.execute.call_args[0][0]
        params = mock_db.execute.call_args[0][1]
        assert "SET" in cypher
        assert "WHERE" in cypher
        assert params["match_name"] == "Alice"
        assert params["set_age"] == 31

    def test_delete(self, repo, mock_db):
        repo.delete(name="Alice")
        cypher = mock_db.execute.call_args[0][0]
        assert "DETACH DELETE" in cypher
        assert "WHERE" in cypher

    def test_delete_no_detach(self, repo, mock_db):
        repo.delete(detach=False, name="Alice")
        cypher = mock_db.execute.call_args[0][0]
        assert "DETACH" not in cypher
        assert "DELETE n" in cypher

    def test_delete_all(self, repo, mock_db):
        repo.delete_all()
        cypher = mock_db.execute.call_args[0][0]
        assert "DETACH DELETE" in cypher
        assert "WHERE" not in cypher

    def test_query(self, repo):
        q = repo.query().where("n.age > 18").return_("n")
        cypher, _ = q.build()
        assert "MATCH (n:Person)" in cypher
        assert "n.age > 18" in cypher


# ---------------------------------------------------------------------------
# Integration: fn + PathBuilder + Query
# ---------------------------------------------------------------------------


class TestIteration4Integration:
    def test_complex_aggregation_query(self):
        p = NodeRef(Person, "p")
        m = NodeRef(Movie, "m")
        path = PathBuilder(Person, "p").rel(ActedIn, "r").to(Movie, "m")
        q = (path.to_query()
             .with_("p", fn.as_(fn.count(m), "movie_count"))
             .where("movie_count > 5")
             .return_(
                 "p.name",
                 "movie_count",
             )
             .order_by("movie_count DESC")
             .limit(10))
        cypher, _ = q.build()
        assert "MATCH (p:Person)" in cypher
        assert "ACTED_IN" in cypher
        assert "count(m) AS movie_count" in cypher
        assert "ORDER BY movie_count DESC" in cypher
        assert "LIMIT 10" in cypher

    def test_repo_query_with_fn(self):
        mock_db = MagicMock()
        mock_db.execute.return_value = [{"total": 42}]
        repo = Repository(Person, mock_db)
        q = (repo.query()
             .return_(fn.as_(fn.count("n"), "total")))
        cypher, _ = q.build()
        assert "count(n) AS total" in cypher

    def test_multi_label_in_schema(self):
        schema = GraphSchema.from_models([Actor, Movie])
        d = schema.to_dict()
        # Primary label is "Person" (first in __labels__)
        assert "Person" in d["nodes"]
        prompt = schema.to_prompt()
        assert "Person" in prompt
