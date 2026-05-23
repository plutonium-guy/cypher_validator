"""Tests for cypher_validator.cli — validate, parse, and generate commands."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cypher_validator.cli import app

runner = CliRunner()

# ── Schema fixture ───────────────────────────────────────────────────────

SCHEMA_DICT = {
    "nodes": {"Person": ["name", "age"], "Movie": ["title"]},
    "relationships": {"ACTED_IN": ["Person", "Movie", ["role"]]},
}


@pytest.fixture()
def schema_file(tmp_path: Path) -> Path:
    p = tmp_path / "schema.json"
    p.write_text(json.dumps(SCHEMA_DICT))
    return p


@pytest.fixture()
def cypher_file(tmp_path: Path) -> Path:
    p = tmp_path / "query.cypher"
    p.write_text("MATCH (n:Person) RETURN n")
    return p


# ── validate ─────────────────────────────────────────────────────────────


class TestValidate:
    def test_valid_query_text(self):
        result = runner.invoke(app, ["validate", "MATCH (n:Person) RETURN n"])
        assert result.exit_code == 0
        assert "OK" in result.output

    def test_valid_query_json(self):
        result = runner.invoke(app, ["validate", "MATCH (n) RETURN n", "--format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["is_valid"] is True

    def test_invalid_query_text(self):
        result = runner.invoke(app, ["validate", "MATC (n) RETURN n"])
        assert result.exit_code == 1

    def test_invalid_query_json(self):
        result = runner.invoke(app, ["validate", "MATC (n) RETURN n", "--format", "json"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["is_valid"] is False
        assert len(data["errors"]) > 0

    def test_valid_with_schema(self, schema_file: Path):
        result = runner.invoke(
            app, ["validate", "MATCH (n:Person) RETURN n", "--schema", str(schema_file)]
        )
        assert result.exit_code == 0
        assert "OK" in result.output

    def test_invalid_label_with_schema(self, schema_file: Path):
        result = runner.invoke(
            app, ["validate", "MATCH (n:Bogus) RETURN n", "--schema", str(schema_file)]
        )
        assert result.exit_code == 1

    def test_schema_json_output(self, schema_file: Path):
        result = runner.invoke(
            app,
            ["validate", "MATCH (n:Person) RETURN n", "--schema", str(schema_file), "--format", "json"],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["is_valid"] is True

    def test_file_input(self, cypher_file: Path):
        result = runner.invoke(app, ["validate", str(cypher_file)])
        assert result.exit_code == 0
        assert "OK" in result.output

    def test_file_input_with_schema(self, schema_file: Path, cypher_file: Path):
        result = runner.invoke(
            app, ["validate", str(cypher_file), "--schema", str(schema_file)]
        )
        assert result.exit_code == 0


# ── parse ────────────────────────────────────────────────────────────────


class TestParse:
    def test_parse_json(self):
        result = runner.invoke(app, ["parse", "MATCH (n:Person) RETURN n"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["is_valid"] is True
        assert "Person" in data["labels_used"]

    def test_parse_tree(self):
        result = runner.invoke(
            app, ["parse", "MATCH (n:Person)-[:KNOWS]->(m) RETURN m", "--format", "tree"]
        )
        assert result.exit_code == 0
        assert "Person" in result.output
        assert "KNOWS" in result.output

    def test_parse_invalid(self):
        result = runner.invoke(app, ["parse", "NOT_CYPHER!!!"])
        assert result.exit_code == 1

    def test_parse_properties(self):
        result = runner.invoke(app, ["parse", "MATCH (n:Person) WHERE n.age > 30 RETURN n.name"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "age" in data["properties_used"] or "name" in data["properties_used"]


# ── generate ─────────────────────────────────────────────────────────────


class TestGenerate:
    def test_list_types(self, schema_file: Path):
        result = runner.invoke(app, ["generate", "--schema", str(schema_file)])
        assert result.exit_code == 0
        assert "match_return" in result.output

    def test_list_types_json(self, schema_file: Path):
        result = runner.invoke(
            app, ["generate", "--schema", str(schema_file), "--format", "json"]
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "match_return" in data["supported_types"]

    def test_generate_one(self, schema_file: Path):
        result = runner.invoke(
            app, ["generate", "--schema", str(schema_file), "--type", "match_return"]
        )
        assert result.exit_code == 0
        assert "MATCH" in result.output

    def test_generate_multiple(self, schema_file: Path):
        result = runner.invoke(
            app,
            ["generate", "--schema", str(schema_file), "--type", "create", "-n", "3"],
        )
        assert result.exit_code == 0
        lines = [l for l in result.output.strip().splitlines() if l.strip()]
        assert len(lines) == 3

    def test_generate_json(self, schema_file: Path):
        result = runner.invoke(
            app,
            [
                "generate",
                "--schema", str(schema_file),
                "--type", "match_return",
                "-n", "2",
                "--format", "json",
            ],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data["queries"]) == 2

    def test_generate_unknown_type(self, schema_file: Path):
        result = runner.invoke(
            app, ["generate", "--schema", str(schema_file), "--type", "nonexistent"]
        )
        assert result.exit_code == 1

    def test_generate_create_relationship(self, schema_file: Path):
        result = runner.invoke(
            app, ["generate", "--schema", str(schema_file), "--type", "create_relationship"]
        )
        assert result.exit_code == 0
        assert "ACTED_IN" in result.output


# ── schema diff ─────────────────────────────────────────────────────────

OLD_SCHEMA = {
    "nodes": {"Person": ["name", "age"]},
    "relationships": {},
}

NEW_SCHEMA = {
    "nodes": {"Person": ["name", "age", "email"], "Movie": ["title"]},
    "relationships": {"ACTED_IN": ["Person", "Movie", ["role"]]},
}


@pytest.fixture()
def old_schema_file(tmp_path: Path) -> Path:
    p = tmp_path / "old.json"
    p.write_text(json.dumps(OLD_SCHEMA))
    return p


@pytest.fixture()
def new_schema_file(tmp_path: Path) -> Path:
    p = tmp_path / "new.json"
    p.write_text(json.dumps(NEW_SCHEMA))
    return p


class TestSchemaDiff:
    def test_diff_text(self, old_schema_file: Path, new_schema_file: Path):
        result = runner.invoke(app, ["schema", "diff", str(old_schema_file), str(new_schema_file)])
        assert result.exit_code == 0
        assert "Movie" in result.output
        assert "email" in result.output

    def test_diff_json(self, old_schema_file: Path, new_schema_file: Path):
        result = runner.invoke(
            app,
            ["schema", "diff", str(old_schema_file), str(new_schema_file), "--format", "json"],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["has_changes"] is True
        assert "Movie" in data["added_labels"]
        assert "email" in data["added_properties"].get("Person", [])

    def test_diff_no_changes(self, old_schema_file: Path):
        result = runner.invoke(app, ["schema", "diff", str(old_schema_file), str(old_schema_file)])
        assert result.exit_code == 0
        assert "No schema changes" in result.output

    def test_diff_no_changes_json(self, old_schema_file: Path):
        result = runner.invoke(
            app,
            ["schema", "diff", str(old_schema_file), str(old_schema_file), "--format", "json"],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["has_changes"] is False


# ── schema migrate ──────────────────────────────────────────────────────


class TestSchemaMigrate:
    def test_migrate_text(self, old_schema_file: Path, new_schema_file: Path):
        result = runner.invoke(
            app, ["schema", "migrate", str(old_schema_file), str(new_schema_file)]
        )
        assert result.exit_code == 0
        # DDL statements should contain CREATE INDEX or similar
        assert "CREATE" in result.output or "DROP" in result.output

    def test_migrate_json(self, old_schema_file: Path, new_schema_file: Path):
        result = runner.invoke(
            app,
            ["schema", "migrate", str(old_schema_file), str(new_schema_file), "--format", "json"],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "statements" in data
        assert len(data["statements"]) > 0

    def test_migrate_no_changes(self, old_schema_file: Path):
        result = runner.invoke(
            app, ["schema", "migrate", str(old_schema_file), str(old_schema_file)]
        )
        assert result.exit_code == 0
        assert "No migration statements needed" in result.output

    def test_migrate_execute_missing_uri(self, old_schema_file: Path, new_schema_file: Path):
        result = runner.invoke(
            app,
            ["schema", "migrate", str(old_schema_file), str(new_schema_file), "--execute"],
        )
        assert result.exit_code == 1
        assert "ERROR" in result.output


# ── schema discover ─────────────────────────────────────────────────────


class TestSchemaDiscover:
    @pytest.fixture(autouse=True)
    def _mock_from_neo4j(self, monkeypatch):
        """Mock Schema.from_neo4j for all discover tests."""
        from cypher_validator import Schema

        mock_schema = Schema.from_dict(
            {"nodes": {"Person": ["name"]}, "relationships": {}}
        )
        monkeypatch.setattr(Schema, "from_neo4j", staticmethod(lambda *a, **kw: mock_schema))

    def test_discover_stdout(self):
        result = runner.invoke(
            app,
            ["schema", "discover", "--uri", "bolt://localhost:7687", "--password", "test"],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "Person" in data["nodes"]

    def test_discover_output_file(self, tmp_path: Path):
        out = tmp_path / "discovered.json"
        result = runner.invoke(
            app,
            [
                "schema", "discover",
                "--uri", "bolt://localhost:7687",
                "--password", "test",
                "--output", str(out),
            ],
        )
        assert result.exit_code == 0
        assert out.exists()
        data = json.loads(out.read_text())
        assert "Person" in data["nodes"]


# ── vector search ──────────────────────────────────────────────────────


class TestVectorSearch:
    def test_vector_search_requires_index(self):
        result = runner.invoke(app, ["vector", "search", "--vector", "[0.1, 0.2]"])
        assert result.exit_code != 0

    def test_vector_search_raw_vector_no_db(self):
        result = runner.invoke(
            app,
            [
                "vector", "search",
                "--index", "idx_document_embedding_vector",
                "--vector", "[0.1, 0.2, 0.3]",
                "--uri", "bolt://localhost:7687",
                "--password", "test",
            ],
        )
        # Will fail to connect but should parse args successfully
        assert result.exit_code != 0

    def test_vector_search_missing_both_query_and_vector(self):
        result = runner.invoke(
            app,
            [
                "vector", "search",
                "--index", "idx_test_vector",
                "--uri", "bolt://localhost:7687",
                "--password", "test",
            ],
        )
        assert result.exit_code == 1
        assert "query" in result.output.lower() or "vector" in result.output.lower()
