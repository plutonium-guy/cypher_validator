"""CLI for cypher_validator — validate, parse, and generate Cypher queries."""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Optional

import typer

app = typer.Typer(name="cypher", help="Cypher query validator, generator, and schema tools.")
schema_app = typer.Typer(name="schema", help="Schema diff, migration, and discovery.")
app.add_typer(schema_app, name="schema")
vector_app = typer.Typer(name="vector", help="Vector search operations.")
app.add_typer(vector_app, name="vector")


# ── helpers ──────────────────────────────────────────────────────────────


class OutputFormat(str, Enum):
    text = "text"
    json = "json"


class ParseFormat(str, Enum):
    json = "json"
    tree = "tree"


def _load_schema(path: Path):
    """Load a Schema from a JSON file."""
    from cypher_validator import Schema

    text = path.read_text()
    # Try from_json first (expects the canonical format produced by to_json).
    # Fall back to from_dict for plain Python-style dicts stored as JSON.
    try:
        return Schema.from_json(text)
    except Exception:
        return Schema.from_dict(json.loads(text))


def _read_query(query: str) -> str:
    """Return *query* as-is, or read it from a file if it looks like a path."""
    p = Path(query)
    if p.is_file():
        return p.read_text().strip()
    return query


# ── validate ─────────────────────────────────────────────────────────────


@app.command()
def validate(
    query: str = typer.Argument(..., help="Cypher query string or path to a .cypher file."),
    schema: Optional[Path] = typer.Option(
        None, "--schema", "-s", help="Path to a JSON schema file for semantic validation."
    ),
    format: OutputFormat = typer.Option(
        OutputFormat.text, "--format", "-f", help="Output format."
    ),
) -> None:
    """Validate a Cypher query (syntax only, or schema-aware with --schema)."""
    from cypher_validator import CypherValidator, parse_query

    cypher = _read_query(query)

    if schema is not None:
        s = _load_schema(schema)
        validator = CypherValidator(s)
        result = validator.validate(cypher)

        if format == OutputFormat.json:
            typer.echo(result.to_json())
        else:
            if result.is_valid:
                typer.echo("OK — query is valid.")
            else:
                for err in result.errors:
                    typer.echo(f"ERROR: {err}", err=True)
                for warn in result.warnings:
                    typer.echo(f"WARNING: {warn}", err=True)

        raise typer.Exit(code=0 if result.is_valid else 1)

    # No schema — syntax-only via parse_query.
    info = parse_query(cypher)

    if format == OutputFormat.json:
        typer.echo(
            json.dumps(
                {
                    "is_valid": info.is_valid,
                    "labels_used": info.labels_used,
                    "rel_types_used": info.rel_types_used,
                    "properties_used": info.properties_used,
                    "errors": info.errors,
                },
                indent=2,
            )
        )
    else:
        if info.is_valid:
            typer.echo("OK — query is syntactically valid.")
        else:
            for err in info.errors:
                typer.echo(f"ERROR: {err}", err=True)

    raise typer.Exit(code=0 if info.is_valid else 1)


# ── parse ────────────────────────────────────────────────────────────────


@app.command()
def parse(
    query: str = typer.Argument(..., help="Cypher query string."),
    format: ParseFormat = typer.Option(
        ParseFormat.json, "--format", "-f", help="Output format (json or tree)."
    ),
) -> None:
    """Parse a Cypher query and display its AST information."""
    from cypher_validator import parse_query

    info = parse_query(query)

    if not info.is_valid:
        for err in info.errors:
            typer.echo(f"ERROR: {err}", err=True)
        raise typer.Exit(code=1)

    data = {
        "is_valid": info.is_valid,
        "labels_used": info.labels_used,
        "rel_types_used": info.rel_types_used,
        "properties_used": info.properties_used,
    }

    if format == ParseFormat.json:
        typer.echo(json.dumps(data, indent=2))
    else:
        # Simple tree-style rendering.
        typer.echo("Query")
        if data["labels_used"]:
            typer.echo(f"  Labels: {', '.join(data['labels_used'])}")
        if data["rel_types_used"]:
            typer.echo(f"  Relationships: {', '.join(data['rel_types_used'])}")
        if data["properties_used"]:
            typer.echo(f"  Properties: {', '.join(data['properties_used'])}")

    raise typer.Exit(code=0)


# ── generate ─────────────────────────────────────────────────────────────


@app.command()
def generate(
    schema: Path = typer.Option(
        ..., "--schema", "-s", help="Path to a JSON schema file (required)."
    ),
    type: Optional[str] = typer.Option(
        None, "--type", "-t", help="Query type to generate (e.g. match_return, create). Omit to list available types."
    ),
    n: int = typer.Option(1, "-n", help="Number of queries to generate."),
    format: OutputFormat = typer.Option(
        OutputFormat.text, "--format", "-f", help="Output format."
    ),
) -> None:
    """Generate random Cypher queries from a schema."""
    from cypher_validator import CypherGenerator

    s = _load_schema(schema)
    gen = CypherGenerator(s)

    if type is None:
        types = gen.supported_types()
        if format == OutputFormat.json:
            typer.echo(json.dumps({"supported_types": types}, indent=2))
        else:
            typer.echo("Supported query types:")
            for t in types:
                typer.echo(f"  - {t}")
        raise typer.Exit(code=0)

    supported = gen.supported_types()
    if type not in supported:
        typer.echo(f"ERROR: Unknown query type '{type}'. Supported: {', '.join(supported)}", err=True)
        raise typer.Exit(code=1)

    queries = [gen.generate(type) for _ in range(n)]

    if format == OutputFormat.json:
        typer.echo(json.dumps({"queries": queries}, indent=2))
    else:
        for q in queries:
            typer.echo(q)

    raise typer.Exit(code=0)


# ── schema helpers ──────────────────────────────────────────────────────


def _load_graph_schema(path: Path):
    """Load a GraphSchema from a JSON file."""
    from cypher_validator.models import GraphSchema

    data = json.loads(path.read_text())
    return GraphSchema.from_dict(data)


# ── schema diff ─────────────────────────────────────────────────────────


@schema_app.command("diff")
def schema_diff(
    old: Path = typer.Argument(..., help="Path to the old schema JSON file."),
    new: Path = typer.Argument(..., help="Path to the new schema JSON file."),
    format: OutputFormat = typer.Option(
        OutputFormat.text, "--format", "-f", help="Output format."
    ),
) -> None:
    """Compare two schema files and show what changed."""
    from cypher_validator.models import SchemaDiff

    old_schema = _load_graph_schema(old)
    new_schema = _load_graph_schema(new)
    diff = SchemaDiff(old_schema, new_schema)

    if format == OutputFormat.json:
        typer.echo(json.dumps(diff.to_dict(), indent=2))
    else:
        if diff.has_changes:
            typer.echo(diff.summary())
        else:
            typer.echo("No schema changes detected.")

    raise typer.Exit(code=0)


# ── schema migrate ──────────────────────────────────────────────────────


@schema_app.command("migrate")
def schema_migrate(
    old: Path = typer.Argument(..., help="Path to the old schema JSON file."),
    new: Path = typer.Argument(..., help="Path to the new schema JSON file."),
    execute: bool = typer.Option(
        False, "--execute", help="Execute DDL statements against Neo4j."
    ),
    uri: Optional[str] = typer.Option(
        None, "--uri", help="Neo4j URI (required with --execute)."
    ),
    password: Optional[str] = typer.Option(
        None, "--password", help="Neo4j password (required with --execute)."
    ),
    username: str = typer.Option("neo4j", "--username", help="Neo4j username."),
    database: str = typer.Option("neo4j", "--database", help="Neo4j database name."),
    format: OutputFormat = typer.Option(
        OutputFormat.text, "--format", "-f", help="Output format."
    ),
) -> None:
    """Generate (and optionally execute) DDL migration statements between two schemas."""
    from cypher_validator.models import SchemaDiff

    old_schema = _load_graph_schema(old)
    new_schema = _load_graph_schema(new)
    diff = SchemaDiff(old_schema, new_schema)
    stmts = diff.migration_ddl()

    if not stmts:
        typer.echo("No migration statements needed.")
        raise typer.Exit(code=0)

    if execute:
        if not uri or not password:
            typer.echo("ERROR: --uri and --password are required with --execute.", err=True)
            raise typer.Exit(code=1)
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(uri, auth=(username, password))
        with driver.session(database=database) as session:
            for stmt in stmts:
                session.run(stmt)
        driver.close()
        typer.echo(f"Executed {len(stmts)} migration statement(s).")
        raise typer.Exit(code=0)

    if format == OutputFormat.json:
        typer.echo(json.dumps({"statements": stmts}, indent=2))
    else:
        for stmt in stmts:
            typer.echo(stmt)

    raise typer.Exit(code=0)


# ── schema discover ─────────────────────────────────────────────────────


@schema_app.command("discover")
def schema_discover(
    uri: str = typer.Option(..., "--uri", help="Neo4j URI (e.g. bolt://localhost:7687)."),
    password: str = typer.Option(..., "--password", help="Neo4j password."),
    username: str = typer.Option("neo4j", "--username", help="Neo4j username."),
    database: str = typer.Option("neo4j", "--database", help="Neo4j database name."),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Write schema JSON to a file instead of stdout."
    ),
) -> None:
    """Discover schema from a live Neo4j database and output as JSON."""
    from cypher_validator import Schema

    schema = Schema.from_neo4j(uri, username, password, database=database)
    schema_json = schema.to_json()

    if output is not None:
        output.write_text(schema_json)
        typer.echo(f"Schema written to {output}")
    else:
        typer.echo(schema_json)

    raise typer.Exit(code=0)


# ── vector search ────────────────────────────────────────────────────────


@vector_app.command("search")
def vector_search(
    index: str = typer.Option(..., "--index", help="Vector index name or 'Model.property'."),
    query: Optional[str] = typer.Option(None, "--query", "-q", help="Text to embed and search for."),
    vector: Optional[str] = typer.Option(None, "--vector", help="Raw vector as JSON array."),
    top_k: int = typer.Option(10, "--top-k", "-k", help="Number of results."),
    embedding_provider: Optional[str] = typer.Option(
        None, "--embedding-provider", help="'openai', 'sentence-transformers', or 'cohere'."
    ),
    embedding_model: Optional[str] = typer.Option(None, "--embedding-model", help="Model name for provider."),
    uri: Optional[str] = typer.Option(None, "--uri", help="Neo4j URI (or NEO4J_URI env)."),
    password: Optional[str] = typer.Option(None, "--password", help="Neo4j password."),
    username: str = typer.Option("neo4j", "--username", help="Neo4j username."),
    database: str = typer.Option("neo4j", "--database", help="Neo4j database name."),
    format: OutputFormat = typer.Option(OutputFormat.text, "--format", "-f", help="Output format."),
) -> None:
    """Search a Neo4j vector index by embedding or raw vector."""
    import os

    uri_resolved = uri or os.environ.get("NEO4J_URI")
    password_resolved = password or os.environ.get("NEO4J_PASSWORD")

    if not uri_resolved or not password_resolved:
        typer.echo("ERROR: --uri and --password required (or NEO4J_URI/NEO4J_PASSWORD env).", err=True)
        raise typer.Exit(code=1)

    if not query and not vector:
        typer.echo("ERROR: Provide --query (text to embed) or --vector (raw JSON array).", err=True)
        raise typer.Exit(code=1)

    # Resolve vector
    if vector:
        query_vec = json.loads(vector)
    else:
        if not embedding_provider:
            typer.echo("ERROR: --embedding-provider required with --query.", err=True)
            raise typer.Exit(code=1)

        from cypher_validator.embeddings import (
            OpenAIEmbeddings,
            SentenceTransformerEmbeddings,
            CohereEmbeddings,
        )
        providers = {
            "openai": lambda: OpenAIEmbeddings(model=embedding_model or "text-embedding-3-small"),
            "sentence-transformers": lambda: SentenceTransformerEmbeddings(model=embedding_model or "all-MiniLM-L6-v2"),
            "cohere": lambda: CohereEmbeddings(model=embedding_model or "embed-english-v3.0"),
        }
        if embedding_provider not in providers:
            typer.echo(f"ERROR: Unknown provider '{embedding_provider}'. Use: {', '.join(providers)}", err=True)
            raise typer.Exit(code=1)
        emb_fn = providers[embedding_provider]()
        query_vec = emb_fn(query)

    # Resolve index name (support "Model.property" syntax)
    index_name = index
    if "." in index and not index.startswith("idx_"):
        parts = index.split(".", 1)
        index_name = f"idx_{parts[0].lower()}_{parts[1]}_vector"

    # Execute search
    from neo4j import GraphDatabase
    driver = GraphDatabase.driver(uri_resolved, auth=(username, password_resolved))
    try:
        with driver.session(database=database) as session:
            cypher = (
                f"CALL db.index.vector.queryNodes('{index_name}', {top_k}, $vec) "
                f"YIELD node, score RETURN node, score"
            )
            result = session.run(cypher, {"vec": query_vec})
            records = [{"node": dict(r["node"]), "score": r["score"]} for r in result]
    except Exception as e:
        typer.echo(f"ERROR: {e}", err=True)
        raise typer.Exit(code=1)
    finally:
        driver.close()

    if format == OutputFormat.json:
        typer.echo(json.dumps({"results": records, "count": len(records)}, indent=2, default=str))
    else:
        if not records:
            typer.echo("No results found.")
        else:
            for i, r in enumerate(records, 1):
                typer.echo(f"{i}. score={r['score']:.4f}  {r['node']}")

    raise typer.Exit(code=0)
