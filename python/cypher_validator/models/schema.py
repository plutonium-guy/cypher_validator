"""GraphSchema, SchemaDDL, SchemaDiff — schema management and migration."""

from __future__ import annotations

import json
from typing import (
    Any,
    Sequence,
    Type,
)

from cypher_validator.models.orm import (
    NodeModel,
    RelationshipModel,
    _NODE_REGISTRY,
    _REL_REGISTRY,
    node,
    relationship,
)


# ---------------------------------------------------------------------------
# GraphSchema — bridge Pydantic models ↔ Rust Schema
# ---------------------------------------------------------------------------


class GraphSchema:
    """Collect NodeModel/RelationshipModel classes and convert to the
    Rust-backed ``Schema`` object used by CypherValidator.

    Usage::

        schema = GraphSchema.from_models([Person, Movie, ActedIn])
        rust_schema = schema.to_cypher_schema()
        validator = CypherValidator(rust_schema)

    Or discover from registry::

        schema = GraphSchema.from_registry()
    """

    def __init__(
        self,
        node_models: list[Type[NodeModel]] | None = None,
        rel_models: list[Type[RelationshipModel]] | None = None,
    ) -> None:
        self.node_models: list[Type[NodeModel]] = list(node_models or [])
        self.rel_models: list[Type[RelationshipModel]] = list(rel_models or [])

    @classmethod
    def from_models(cls, models: Sequence[Type[NodeModel] | Type[RelationshipModel]]) -> GraphSchema:
        """Create from a mixed list of node and relationship model classes."""
        nodes: list[Type[NodeModel]] = []
        rels: list[Type[RelationshipModel]] = []
        for m in models:
            if issubclass(m, RelationshipModel):
                rels.append(m)  # type: ignore[arg-type]
            elif issubclass(m, NodeModel):
                nodes.append(m)  # type: ignore[arg-type]
            else:
                raise TypeError(f"Expected NodeModel or RelationshipModel subclass, got {m}")
        return cls(nodes, rels)

    @classmethod
    def from_registry(cls) -> GraphSchema:
        """Create from all auto-registered models."""
        return cls(
            list(_NODE_REGISTRY.values()),
            list(_REL_REGISTRY.values()),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to the dict format expected by Schema.from_dict()."""
        nodes: dict[str, list[str]] = {}
        for m in self.node_models:
            nodes[m.label()] = m.property_names()
        rels: dict[str, tuple[str, str, list[str]]] = {}
        for m in self.rel_models:
            rels[m.rel_type()] = (
                m.source_label(),
                m.target_label(),
                m.property_names(),
            )
        return {"nodes": nodes, "relationships": rels}

    def to_cypher_schema(self) -> Any:
        """Convert to the Rust-backed Schema object."""
        from cypher_validator._cypher_validator import Schema
        d = self.to_dict()
        return Schema(d["nodes"], d["relationships"])

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GraphSchema:
        """Create from a schema dict (as returned by `to_dict()`).

        Dynamically creates NodeModel/RelationshipModel subclasses.

        Usage::

            schema = GraphSchema.from_dict({
                "nodes": {"Person": ["name", "age"], "Movie": ["title", "year"]},
                "relationships": {"ACTED_IN": ["Person", "Movie", ["roles"]]}
            })
        """
        node_models_list: list[Type[NodeModel]] = []
        for label, props in data.get("nodes", {}).items():
            field_defs = {p: (str, "") for p in props}
            m = node(label, **field_defs)
            node_models_list.append(m)

        # Build label → model lookup for relationship source/target
        label_to_model = {m.label(): m for m in node_models_list}

        rel_models_list: list[Type[RelationshipModel]] = []
        for rel_type_name, rel_info in data.get("relationships", {}).items():
            if isinstance(rel_info, (list, tuple)) and len(rel_info) >= 2:
                src_label = rel_info[0]
                tgt_label = rel_info[1]
                rel_props = rel_info[2] if len(rel_info) > 2 else []
                src_model = label_to_model.get(src_label)
                tgt_model = label_to_model.get(tgt_label)
                if src_model and tgt_model:
                    field_defs = {p: (str, "") for p in rel_props}
                    m = relationship(rel_type_name, src_model, tgt_model, **field_defs)
                    rel_models_list.append(m)

        return cls(node_models_list, rel_models_list)

    @classmethod
    def from_neo4j_db(cls, db: Any, sample_limit: int = 1000) -> GraphSchema:
        """Create a GraphSchema by introspecting a live Neo4j database.

        Dynamically creates Pydantic NodeModel/RelationshipModel classes
        from the database's actual schema. This is ideal for AI agents
        connecting to unknown databases.

        Args:
            db: A Neo4jDatabase instance (or any object with `introspect_schema()`
                or `execute()` methods).
            sample_limit: Max nodes/relationships to sample per type.

        Usage::

            from cypher_validator import Neo4jDatabase
            db = Neo4jDatabase("bolt://localhost:7687", "neo4j", "password")
            schema = GraphSchema.from_neo4j_db(db)
            tools = AgentTools(schema)
        """
        # If db has introspect_schema, use it to get a Rust Schema
        if hasattr(db, "introspect_schema"):
            rust_schema = db.introspect_schema(sample_limit=sample_limit)
            schema_dict = rust_schema.to_dict()
            return cls.from_dict(schema_dict)

        # Fallback: batch introspection via Cypher (2 queries instead of N+1)
        nodes_dict: dict[str, set[str]] = {}
        rels_dict: dict[str, list[Any]] = {}

        try:
            records = db.execute(
                "MATCH (n) "
                "UNWIND labels(n) AS label "
                "WITH label, keys(n) AS ks "
                "UNWIND CASE WHEN size(ks) = 0 THEN [null] ELSE ks END AS k "
                "RETURN label, collect(DISTINCT k) AS props "
                f"LIMIT {sample_limit}"
            )
            for rec in records:
                label = rec.get("label", "")
                if label:
                    props = [p for p in rec.get("props", []) if p is not None]
                    nodes_dict[label] = set(props)
        except Exception:
            pass

        try:
            records = db.execute(
                "MATCH (a)-[r]->(b) "
                "WITH type(r) AS rtype, labels(a)[0] AS src, labels(b)[0] AS tgt, keys(r) AS ks "
                "UNWIND CASE WHEN size(ks) = 0 THEN [null] ELSE ks END AS k "
                "RETURN rtype, head(collect(src)) AS src, head(collect(tgt)) AS tgt, "
                "collect(DISTINCT k) AS props "
                f"LIMIT {sample_limit}"
            )
            for rec in records:
                rtype = rec.get("rtype", "")
                if rtype:
                    src = rec.get("src", "Unknown")
                    tgt = rec.get("tgt", "Unknown")
                    props = [p for p in rec.get("props", []) if p is not None]
                    rels_dict[rtype] = [src, tgt, props]
        except Exception:
            pass

        nodes_final = {k: list(v) for k, v in nodes_dict.items()}
        return cls.from_dict({"nodes": nodes_final, "relationships": rels_dict})

    def to_json(self) -> str:
        d = self.to_dict()
        # Convert tuples to lists for JSON serialization
        rels_serializable = {}
        for k, v in d["relationships"].items():
            rels_serializable[k] = list(v)
        return json.dumps({"nodes": d["nodes"], "relationships": rels_serializable}, indent=2)

    def to_prompt(self) -> str:
        """LLM-friendly schema description."""
        lines = ["# Graph Schema", ""]
        lines.append("## Node Types")
        for m in self.node_models:
            lines.append(m.to_schema_description())
            lines.append("")
        lines.append("## Relationship Types")
        for m in self.rel_models:
            lines.append(m.to_schema_description())
            lines.append("")
        return "\n".join(lines)

    def to_markdown(self) -> str:
        """Markdown table format."""
        lines = ["## Nodes", "", "| Label | Properties | Required |", "|-------|-----------|----------|"]
        for m in self.node_models:
            props = ", ".join(m.property_names())
            req = ", ".join(m.required_properties())
            lines.append(f"| {m.label()} | {props} | {req} |")
        lines.extend(["", "## Relationships", "", "| Type | Source | Target | Properties |", "|------|--------|--------|-----------|"])
        for m in self.rel_models:
            props = ", ".join(m.property_names())
            lines.append(f"| {m.rel_type()} | {m.source_label()} | {m.target_label()} | {props} |")
        return "\n".join(lines)

    def merge(self, other: GraphSchema) -> GraphSchema:
        """Merge two schemas."""
        seen_labels = {m.label() for m in self.node_models}
        seen_types = {m.rel_type() for m in self.rel_models}
        nodes = list(self.node_models)
        rels = list(self.rel_models)
        for m in other.node_models:
            if m.label() not in seen_labels:
                nodes.append(m)
        for m in other.rel_models:
            if m.rel_type() not in seen_types:
                rels.append(m)
        return GraphSchema(nodes, rels)

    def get_constraints(self) -> list[str]:
        """Collect all constraint statements from models."""
        constraints: list[str] = []
        for m in self.node_models:
            constraints.extend(m.__constraints__)
        for m in self.rel_models:
            constraints.extend(m.__constraints__)
        return constraints

    def get_indexes(self) -> list[str]:
        """Collect all index statements from models."""
        indexes: list[str] = []
        for m in self.node_models:
            indexes.extend(m.__indexes__)
        return indexes


# ---------------------------------------------------------------------------
# Schema Migration DDL
# ---------------------------------------------------------------------------


class SchemaDDL:
    """Auto-generate Cypher DDL (constraints, indexes) from model definitions.

    Usage::

        schema = GraphSchema.from_models([Person, Movie, ActedIn])
        ddl = SchemaDDL(schema)
        for stmt in ddl.generate_all():
            db.execute(stmt)
    """

    def __init__(self, schema: GraphSchema) -> None:
        self.schema = schema

    def uniqueness_constraints(self) -> list[str]:
        """Generate UNIQUENESS constraints for required properties."""
        stmts: list[str] = []
        for m in self.schema.node_models:
            for prop in m.required_properties():
                name = f"uniq_{m.label().lower()}_{prop}"
                stmts.append(
                    f"CREATE CONSTRAINT {name} IF NOT EXISTS "
                    f"FOR (n:{m.label()}) REQUIRE n.{prop} IS UNIQUE"
                )
        return stmts

    def existence_constraints(self) -> list[str]:
        """Generate EXISTS constraints for required properties (Enterprise only)."""
        stmts: list[str] = []
        for m in self.schema.node_models:
            for prop in m.required_properties():
                name = f"exists_{m.label().lower()}_{prop}"
                stmts.append(
                    f"CREATE CONSTRAINT {name} IF NOT EXISTS "
                    f"FOR (n:{m.label()}) REQUIRE n.{prop} IS NOT NULL"
                )
        for m in self.schema.rel_models:
            for prop in m.required_properties():
                name = f"exists_{m.rel_type().lower()}_{prop}"
                stmts.append(
                    f"CREATE CONSTRAINT {name} IF NOT EXISTS "
                    f"FOR ()-[r:{m.rel_type()}]-() REQUIRE r.{prop} IS NOT NULL"
                )
        return stmts

    def _should_skip_btree_index(self, model: Type[NodeModel], prop: str) -> bool:
        """Return True if a property should not get a B-tree index."""
        if prop.endswith("_embedding"):
            return True
        exclude = getattr(model, "__index_exclude__", set())
        if prop in exclude:
            return True
        field_info = model.model_fields.get(prop)
        if field_info is not None:
            annotation = field_info.annotation
            if annotation is list or annotation is list[float]:
                return True
            origin = getattr(annotation, "__origin__", None)
            if origin is list:
                args = getattr(annotation, "__args__", ())
                if not args or args == (float,):
                    return True
        return False

    def property_indexes(self) -> list[str]:
        """Generate property indexes for all node properties.

        Skips fields that end with '_embedding', have list[float] type
        annotation, or are listed in the model's __index_exclude__ set.
        """
        stmts: list[str] = []
        for m in self.schema.node_models:
            for prop in m.property_names():
                if self._should_skip_btree_index(m, prop):
                    continue
                name = f"idx_{m.label().lower()}_{prop}"
                stmts.append(
                    f"CREATE INDEX {name} IF NOT EXISTS "
                    f"FOR (n:{m.label()}) ON (n.{prop})"
                )
        return stmts

    def composite_indexes(self, model: Type[NodeModel], props: list[str]) -> str:
        """Generate a composite index on multiple properties."""
        name = f"idx_{model.label().lower()}_{'_'.join(props)}"
        on_clause = ", ".join(f"n.{p}" for p in props)
        return (
            f"CREATE INDEX {name} IF NOT EXISTS "
            f"FOR (n:{model.label()}) ON ({on_clause})"
        )

    def fulltext_index(
        self, models: list[Type[NodeModel]], props: list[str], index_name: str
    ) -> str:
        """Generate a fulltext index across labels and properties."""
        labels = "|".join(m.label() for m in models)
        prop_list = ", ".join(f"n.{p}" for p in props)
        return (
            f'CREATE FULLTEXT INDEX {index_name} IF NOT EXISTS '
            f'FOR (n:{labels}) ON EACH [{prop_list}]'
        )

    def vector_indexes(self) -> list[str]:
        """Generate VECTOR INDEX statements for properties declared in __vector_indexes__."""
        stmts: list[str] = []
        for m in self.schema.node_models:
            for prop, vec in getattr(m, "__vector_indexes__", {}).items():
                label = m.label()
                name = f"idx_{label.lower()}_{prop}_vector"
                stmts.append(
                    f"CREATE VECTOR INDEX {name} IF NOT EXISTS "
                    f"FOR (n:{label}) ON (n.{prop}) "
                    f"OPTIONS {{indexConfig: {{`vector.dimensions`: {vec.dimensions}, "
                    f"`vector.similarity_function`: '{vec.similarity}'}}}}"
                )
        return stmts

    def custom_constraints(self) -> list[str]:
        """Collect manually-defined constraints from model __constraints__."""
        return self.schema.get_constraints()

    def custom_indexes(self) -> list[str]:
        """Collect manually-defined indexes from model __indexes__."""
        return self.schema.get_indexes()

    def generate_all(self, include_existence: bool = False) -> list[str]:
        """Generate all DDL statements.

        Args:
            include_existence: Include IS NOT NULL constraints (Neo4j Enterprise).
        """
        stmts: list[str] = []
        stmts.extend(self.uniqueness_constraints())
        if include_existence:
            stmts.extend(self.existence_constraints())
        stmts.extend(self.property_indexes())
        stmts.extend(self.vector_indexes())
        stmts.extend(self.custom_constraints())
        stmts.extend(self.custom_indexes())
        return stmts

    def drop_all(self) -> list[str]:
        """Generate DROP statements for all generated constraints/indexes."""
        stmts: list[str] = []
        for m in self.schema.node_models:
            for prop in m.required_properties():
                stmts.append(f"DROP CONSTRAINT uniq_{m.label().lower()}_{prop} IF EXISTS")
            for prop in m.property_names():
                stmts.append(f"DROP INDEX idx_{m.label().lower()}_{prop} IF EXISTS")
            for prop in getattr(m, "__vector_indexes__", {}):
                stmts.append(f"DROP INDEX idx_{m.label().lower()}_{prop}_vector IF EXISTS")
        return stmts


# ---------------------------------------------------------------------------
# Schema Diff — compare schemas for migration planning
# ---------------------------------------------------------------------------


class SchemaDiff:
    """Compare two GraphSchemas and generate migration information.

    Usage::

        old_schema = GraphSchema.from_models([Person])
        new_schema = GraphSchema.from_models([Person, Movie, ActedIn])
        diff = SchemaDiff(old_schema, new_schema)
        print(diff.summary())
        migration_stmts = diff.migration_ddl()
    """

    def __init__(self, old: GraphSchema, new: GraphSchema) -> None:
        self.old = old
        self.new = new
        self._compute()

    def _compute(self) -> None:
        old_labels = {m.label() for m in self.old.node_models}
        new_labels = {m.label() for m in self.new.node_models}
        old_rels = {m.rel_type() for m in self.old.rel_models}
        new_rels = {m.rel_type() for m in self.new.rel_models}

        self.added_labels = new_labels - old_labels
        self.removed_labels = old_labels - new_labels
        self.unchanged_labels = old_labels & new_labels

        self.added_rel_types = new_rels - old_rels
        self.removed_rel_types = old_rels - new_rels
        self.unchanged_rel_types = old_rels & new_rels

        # Property changes for unchanged labels
        self.added_properties: dict[str, list[str]] = {}
        self.removed_properties: dict[str, list[str]] = {}

        old_models = {m.label(): m for m in self.old.node_models}
        new_models = {m.label(): m for m in self.new.node_models}

        for label in self.unchanged_labels:
            old_props = set(old_models[label].property_names())
            new_props = set(new_models[label].property_names())
            added = new_props - old_props
            removed = old_props - new_props
            if added:
                self.added_properties[label] = sorted(added)
            if removed:
                self.removed_properties[label] = sorted(removed)

    @property
    def has_changes(self) -> bool:
        return bool(
            self.added_labels or self.removed_labels
            or self.added_rel_types or self.removed_rel_types
            or self.added_properties or self.removed_properties
        )

    def summary(self) -> str:
        """Human-readable diff summary."""
        if not self.has_changes:
            return "Schemas are identical."
        lines = ["## Schema Diff"]
        if self.added_labels:
            lines.append(f"\n### Added Node Labels: {', '.join(sorted(self.added_labels))}")
        if self.removed_labels:
            lines.append(f"\n### Removed Node Labels: {', '.join(sorted(self.removed_labels))}")
        if self.added_rel_types:
            lines.append(f"\n### Added Relationship Types: {', '.join(sorted(self.added_rel_types))}")
        if self.removed_rel_types:
            lines.append(f"\n### Removed Relationship Types: {', '.join(sorted(self.removed_rel_types))}")
        if self.added_properties:
            lines.append("\n### Added Properties:")
            for label, props in sorted(self.added_properties.items()):
                lines.append(f"  - {label}: {', '.join(props)}")
        if self.removed_properties:
            lines.append("\n### Removed Properties:")
            for label, props in sorted(self.removed_properties.items()):
                lines.append(f"  - {label}: {', '.join(props)}")
        return "\n".join(lines)

    def migration_ddl(self) -> list[str]:
        """Generate DDL statements to migrate from old to new schema.

        Creates constraints/indexes for new labels and properties.
        Generates DROP statements for removed ones.
        """
        stmts: list[str] = []
        new_models = {m.label(): m for m in self.new.node_models}

        # New labels: create indexes/constraints
        for label in self.added_labels:
            if label in new_models:
                m = new_models[label]
                for prop in m.required_properties():
                    stmts.append(
                        f"CREATE CONSTRAINT uniq_{label.lower()}_{prop} IF NOT EXISTS "
                        f"FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE"
                    )
                for prop in m.property_names():
                    stmts.append(
                        f"CREATE INDEX idx_{label.lower()}_{prop} IF NOT EXISTS "
                        f"FOR (n:{label}) ON (n.{prop})"
                    )

        # New properties on existing labels: create indexes
        for label, props in self.added_properties.items():
            for prop in props:
                stmts.append(
                    f"CREATE INDEX idx_{label.lower()}_{prop} IF NOT EXISTS "
                    f"FOR (n:{label}) ON (n.{prop})"
                )

        # Removed labels: drop constraints/indexes
        old_models = {m.label(): m for m in self.old.node_models}
        for label in self.removed_labels:
            if label in old_models:
                m = old_models[label]
                for prop in m.required_properties():
                    stmts.append(f"DROP CONSTRAINT uniq_{label.lower()}_{prop} IF EXISTS")
                for prop in m.property_names():
                    stmts.append(f"DROP INDEX idx_{label.lower()}_{prop} IF EXISTS")

        # Removed properties: drop indexes
        for label, props in self.removed_properties.items():
            for prop in props:
                stmts.append(f"DROP INDEX idx_{label.lower()}_{prop} IF EXISTS")

        return stmts

    def to_dict(self) -> dict[str, Any]:
        """Serializable representation of the diff."""
        return {
            "has_changes": self.has_changes,
            "added_labels": sorted(self.added_labels),
            "removed_labels": sorted(self.removed_labels),
            "added_rel_types": sorted(self.added_rel_types),
            "removed_rel_types": sorted(self.removed_rel_types),
            "added_properties": self.added_properties,
            "removed_properties": self.removed_properties,
        }


# ---------------------------------------------------------------------------
# Pipeline Integration — bridge to LLMNLToCypher
# ---------------------------------------------------------------------------


def schema_to_pipeline_kwargs(schema: GraphSchema) -> dict[str, Any]:
    """Convert a GraphSchema to kwargs suitable for LLMNLToCypher.

    Usage::

        from cypher_validator import LLMNLToCypher
        schema = GraphSchema.from_models([Person, Movie, ActedIn])
        pipeline = LLMNLToCypher.from_openai(api_key="...", **schema_to_pipeline_kwargs(schema))
    """
    return {
        "schema": schema.to_cypher_schema(),
    }
