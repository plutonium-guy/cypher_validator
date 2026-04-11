"""Pydantic-based Cypher ORM: declarative graph schema, query builder, and AI agent tools.

Define your graph schema as Python classes, build type-safe parameterized Cypher
queries with a fluent API, and get AI-agent-friendly tool specs for function calling.

Example::

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

    # Query builder
    q = (Query()
         .match(Person, "p")
         .where(Cond("p.name", "=", "$name"))
         .return_("p"))
    print(q.build())
    # MATCH (p:Person) WHERE p.name = $name RETURN p

    # Schema bridge
    schema = GraphSchema.from_models([Person, Movie, ActedIn])
    validator = CypherValidator(schema.to_cypher_schema())
"""

from __future__ import annotations

import inspect
import json
import re
from enum import Enum
from typing import (
    Any,
    ClassVar,
    Sequence,
    Type,
)

from pydantic import BaseModel, ConfigDict


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_NODE_REGISTRY: dict[str, Type[NodeModel]] = {}
_REL_REGISTRY: dict[str, Type[RelationshipModel]] = {}


def _all_node_models() -> dict[str, Type[NodeModel]]:
    return dict(_NODE_REGISTRY)


def _all_rel_models() -> dict[str, Type[RelationshipModel]]:
    return dict(_REL_REGISTRY)


# ---------------------------------------------------------------------------
# NodeModel
# ---------------------------------------------------------------------------


class _NodeMeta(type(BaseModel)):
    """Metaclass that auto-registers NodeModel subclasses."""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)

    def __init__(cls, name: str, bases: tuple, namespace: dict, **kwargs: Any) -> None:
        super().__init__(name, bases, namespace, **kwargs)
        if name != "NodeModel" and any(
            b.__name__ == "NodeModel" for b in bases
        ):
            label = getattr(cls, "__label__", name)
            cls.__label__ = label  # type: ignore[attr-defined]
            _NODE_REGISTRY[label] = cls  # type: ignore[arg-type]
        elif name != "NodeModel":
            # Handle deeper inheritance
            for b in bases:
                if hasattr(b, "__label__"):
                    label = getattr(cls, "__label__", name)
                    cls.__label__ = label  # type: ignore[attr-defined]
                    _NODE_REGISTRY[label] = cls  # type: ignore[arg-type]
                    break


class NodeModel(BaseModel, metaclass=_NodeMeta):
    """Base class for graph node models.

    Subclass and add typed fields to define node properties.
    Set ``__label__`` to override the Cypher label (defaults to class name).

    Optional class-level attributes:
        __label__: str - Cypher node label
        __description__: str - Human/AI-readable description of this node type
        __constraints__: list[str] - Cypher constraint statements
        __indexes__: list[str] - Cypher index statements
    """

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    __label__: ClassVar[str] = ""
    __labels__: ClassVar[list[str]] = []
    __description__: ClassVar[str] = ""
    __constraints__: ClassVar[list[str]] = []
    __indexes__: ClassVar[list[str]] = []

    @classmethod
    def label(cls) -> str:
        """Primary label (first label if multi-label)."""
        return cls.__label__ or (cls.__labels__[0] if cls.__labels__ else cls.__name__)

    @classmethod
    def labels(cls) -> list[str]:
        """All labels for this node type."""
        if cls.__labels__:
            return list(cls.__labels__)
        return [cls.label()]

    @classmethod
    def labels_cypher(cls) -> str:
        """Labels formatted for Cypher: ':Label1:Label2'."""
        return ":" + ":".join(cls.labels())

    @classmethod
    def property_names(cls) -> list[str]:
        return list(cls.model_fields.keys())

    @classmethod
    def property_types(cls) -> dict[str, str]:
        """Return {prop_name: type_string} for each declared field."""
        out: dict[str, str] = {}
        for name, field in cls.model_fields.items():
            annotation = field.annotation
            out[name] = annotation.__name__ if hasattr(annotation, "__name__") else str(annotation)
        return out

    @classmethod
    def required_properties(cls) -> list[str]:
        return [
            name
            for name, field in cls.model_fields.items()
            if field.is_required()
        ]

    @classmethod
    def optional_properties(cls) -> list[str]:
        return [
            name
            for name, field in cls.model_fields.items()
            if not field.is_required()
        ]

    @classmethod
    def from_record(cls, record: dict[str, Any], key: str | None = None) -> NodeModel:
        """Hydrate a model instance from a Neo4j record dict.

        If *key* is given, extract that key from the record first.
        Handles both raw dicts and neo4j.graph.Node objects.
        """
        data = record[key] if key else record
        # neo4j driver Node objects expose dict-like access via .items()
        if isinstance(data, dict):
            props = data
        elif hasattr(data, "items"):
            props = dict(data.items())
        else:
            props = dict(data)
        return cls.model_validate(props)

    @classmethod
    def from_records(cls, records: list[dict[str, Any]], key: str | None = None) -> list[NodeModel]:
        """Hydrate multiple model instances from a list of Neo4j records."""
        return [cls.from_record(r, key) for r in records]

    def to_property_map(self) -> dict[str, Any]:
        """Return non-None properties as a dict suitable for Cypher params."""
        return {k: v for k, v in self.model_dump().items() if v is not None}

    def to_create_cypher(self, var: str = "n") -> tuple[str, dict[str, Any]]:
        """Generate CREATE (var:Label {props}) RETURN var."""
        props = self.to_property_map()
        params = {f"{var}_{k}": v for k, v in props.items()}
        if props:
            prop_str = ", ".join(f"{k}: ${var}_{k}" for k in props)
            cypher = f"CREATE ({var}:{self.label()} {{{prop_str}}}) RETURN {var}"
        else:
            cypher = f"CREATE ({var}:{self.label()}) RETURN {var}"
        return cypher, params

    def to_merge_cypher(
        self, var: str = "n", merge_keys: Sequence[str] | None = None
    ) -> tuple[str, dict[str, Any]]:
        """Generate MERGE on merge_keys, SET remaining props."""
        props = self.to_property_map()
        keys = list(merge_keys or self.required_properties() or list(props.keys())[:1])
        # Validate merge keys exist as properties
        valid_props = set(self.property_names())
        bad_keys = [k for k in keys if k not in valid_props]
        if bad_keys:
            raise ValueError(
                f"merge_keys {bad_keys} not found in {self.label()} properties: {sorted(valid_props)}"
            )
        params = {f"{var}_{k}": v for k, v in props.items()}
        merge_prop_str = ", ".join(f"{k}: ${var}_{k}" for k in keys)
        set_props = {k: v for k, v in props.items() if k not in keys}
        cypher = f"MERGE ({var}:{self.label()} {{{merge_prop_str}}})"
        if set_props:
            set_str = ", ".join(f"{var}.{k} = ${var}_{k}" for k in set_props)
            cypher += f" ON CREATE SET {set_str} ON MATCH SET {set_str}"
        cypher += f" RETURN {var}"
        return cypher, params

    @classmethod
    def match_cypher(
        cls, var: str = "n", where: dict[str, Any] | None = None
    ) -> tuple[str, dict[str, Any]]:
        """Generate MATCH (var:Label) WHERE ... RETURN var."""
        params: dict[str, Any] = {}
        cypher = f"MATCH ({var}:{cls.label()})"
        if where:
            params = {f"{var}_{k}": v for k, v in where.items()}
            conds = " AND ".join(f"{var}.{k} = ${var}_{k}" for k in where)
            cypher += f" WHERE {conds}"
        cypher += f" RETURN {var}"
        return cypher, params

    @classmethod
    def to_schema_description(cls) -> str:
        """AI-readable description of this node type."""
        desc = cls.__description__ or f"Node type '{cls.label()}'"
        props = cls.property_types()
        req = cls.required_properties()
        lines = [f"{desc}:", f"  Label: {cls.label()}", "  Properties:"]
        for pname, ptype in props.items():
            marker = " (required)" if pname in req else ""
            lines.append(f"    - {pname}: {ptype}{marker}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# RelationshipModel
# ---------------------------------------------------------------------------


class _RelMeta(type(BaseModel)):
    """Metaclass that auto-registers RelationshipModel subclasses."""

    def __init__(cls, name: str, bases: tuple, namespace: dict, **kwargs: Any) -> None:
        super().__init__(name, bases, namespace, **kwargs)
        if name != "RelationshipModel" and any(
            b.__name__ == "RelationshipModel" for b in bases
        ):
            rel_type = getattr(cls, "__rel_type__", _to_upper_snake(name))
            cls.__rel_type__ = rel_type  # type: ignore[attr-defined]
            _REL_REGISTRY[rel_type] = cls  # type: ignore[arg-type]
        elif name != "RelationshipModel":
            for b in bases:
                if hasattr(b, "__rel_type__"):
                    rel_type = getattr(cls, "__rel_type__", _to_upper_snake(name))
                    cls.__rel_type__ = rel_type  # type: ignore[attr-defined]
                    _REL_REGISTRY[rel_type] = cls  # type: ignore[arg-type]
                    break


def _to_upper_snake(name: str) -> str:
    """CamelCase → UPPER_SNAKE_CASE."""
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    s = re.sub(r"([a-z\d])([A-Z])", r"\1_\2", s)
    return s.upper()


class RelationshipModel(BaseModel, metaclass=_RelMeta):
    """Base class for graph relationship models.

    Set ``__source__`` and ``__target__`` to NodeModel subclasses,
    and ``__rel_type__`` to the Cypher relationship type string.
    Add typed fields for relationship properties.
    """

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    __source__: ClassVar[Type[NodeModel]]
    __target__: ClassVar[Type[NodeModel]]
    __rel_type__: ClassVar[str] = ""
    __description__: ClassVar[str] = ""
    __constraints__: ClassVar[list[str]] = []

    @classmethod
    def rel_type(cls) -> str:
        return cls.__rel_type__ or _to_upper_snake(cls.__name__)

    @classmethod
    def source_label(cls) -> str:
        return cls.__source__.label()

    @classmethod
    def target_label(cls) -> str:
        return cls.__target__.label()

    @classmethod
    def property_names(cls) -> list[str]:
        return list(cls.model_fields.keys())

    @classmethod
    def property_types(cls) -> dict[str, str]:
        out: dict[str, str] = {}
        for name, field in cls.model_fields.items():
            annotation = field.annotation
            out[name] = annotation.__name__ if hasattr(annotation, "__name__") else str(annotation)
        return out

    @classmethod
    def required_properties(cls) -> list[str]:
        return [
            name
            for name, field in cls.model_fields.items()
            if field.is_required()
        ]

    @classmethod
    def from_record(cls, record: dict[str, Any], key: str | None = None) -> RelationshipModel:
        """Hydrate from a Neo4j record dict."""
        data = record[key] if key else record
        if isinstance(data, dict):
            props = data
        elif hasattr(data, "items"):
            props = dict(data.items())
        else:
            props = dict(data)
        return cls.model_validate(props)

    def to_property_map(self) -> dict[str, Any]:
        return {k: v for k, v in self.model_dump().items() if v is not None}

    def to_create_cypher(
        self,
        src_var: str = "a",
        tgt_var: str = "b",
        rel_var: str = "r",
        src_match: dict[str, Any] | None = None,
        tgt_match: dict[str, Any] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Generate MATCH src, tgt CREATE (src)-[r:TYPE {props}]->(tgt) RETURN r."""
        props = self.to_property_map()
        params: dict[str, Any] = {}
        # Source match
        src_where = ""
        if src_match:
            for k, v in src_match.items():
                params[f"{src_var}_{k}"] = v
            src_where_parts = [f"{src_var}.{k} = ${src_var}_{k}" for k in src_match]
            src_where = " WHERE " + " AND ".join(src_where_parts)
        # Target match
        tgt_where = ""
        if tgt_match:
            for k, v in tgt_match.items():
                params[f"{tgt_var}_{k}"] = v
            tgt_where_parts = [f"{tgt_var}.{k} = ${tgt_var}_{k}" for k in tgt_match]
            tgt_where = " AND " + " AND ".join(tgt_where_parts) if src_match else " WHERE " + " AND ".join(tgt_where_parts)
        # Rel props
        for k, v in props.items():
            params[f"{rel_var}_{k}"] = v
        prop_str = ", ".join(f"{k}: ${rel_var}_{k}" for k in props)
        prop_clause = f" {{{prop_str}}}" if props else ""
        cypher = (
            f"MATCH ({src_var}:{self.source_label()}), ({tgt_var}:{self.target_label()})"
            f"{src_where}{tgt_where}"
            f" CREATE ({src_var})-[{rel_var}:{self.rel_type()}{prop_clause}]->({tgt_var})"
            f" RETURN {rel_var}"
        )
        return cypher, params

    @classmethod
    def to_schema_description(cls) -> str:
        desc = cls.__description__ or f"Relationship '{cls.rel_type()}'"
        props = cls.property_types()
        lines = [
            f"{desc}:",
            f"  Type: {cls.rel_type()}",
            f"  Direction: (:{cls.source_label()})-[:{cls.rel_type()}]->(:{cls.target_label()})",
        ]
        if props:
            lines.append("  Properties:")
            req = cls.required_properties()
            for pname, ptype in props.items():
                marker = " (required)" if pname in req else ""
                lines.append(f"    - {pname}: {ptype}{marker}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Condition & Expression helpers
# ---------------------------------------------------------------------------


class Op(str, Enum):
    EQ = "="
    NEQ = "<>"
    LT = "<"
    LTE = "<="
    GT = ">"
    GTE = ">="
    CONTAINS = "CONTAINS"
    STARTS_WITH = "STARTS WITH"
    ENDS_WITH = "ENDS WITH"
    IN = "IN"
    IS_NULL = "IS NULL"
    IS_NOT_NULL = "IS NOT NULL"
    REGEX = "=~"


class Cond:
    """Single WHERE condition.

    Usage::

        Cond("n.name", "=", "$name")
        Cond("n.age", ">", 18)
        Cond("n.status", "IS NULL")
    """

    __slots__ = ("left", "op", "right")

    def __init__(self, left: str, op: str | Op, right: Any = None) -> None:
        self.left = left
        self.op = Op(op) if isinstance(op, str) else op
        self.right = right

    def render(self) -> str:
        if self.op in (Op.IS_NULL, Op.IS_NOT_NULL):
            return f"{self.left} {self.op.value}"
        right_str = self._render_value(self.right)
        return f"{self.left} {self.op.value} {right_str}"

    @staticmethod
    def _render_value(v: Any) -> str:
        if isinstance(v, str) and v.startswith("$"):
            return v  # parameter reference
        if isinstance(v, str) and (v.startswith("'") or v.startswith('"')):
            return v  # already quoted
        if isinstance(v, str) and ("." in v or v.isidentifier()):
            if "." in v:
                return v
            return f"'{v}'"
        if isinstance(v, str):
            return f"'{v}'"
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (int, float)):
            return str(v)
        if isinstance(v, list):
            items = ", ".join(Cond._render_value(x) for x in v)
            return f"[{items}]"
        if v is None:
            return "null"
        return str(v)

    def __and__(self, other: Cond) -> CondGroup:
        return CondGroup([self, other], "AND")

    def __or__(self, other: Cond) -> CondGroup:
        return CondGroup([self, other], "OR")


class CondGroup:
    """Group of conditions joined by AND/OR."""

    __slots__ = ("conditions", "operator")

    def __init__(self, conditions: list[Cond | CondGroup], operator: str = "AND") -> None:
        self.conditions = conditions
        self.operator = operator

    def render(self) -> str:
        parts = []
        for c in self.conditions:
            rendered = c.render()
            if isinstance(c, CondGroup) and c.operator != self.operator:
                rendered = f"({rendered})"
            parts.append(rendered)
        return f" {self.operator} ".join(parts)

    def __and__(self, other: Cond | CondGroup) -> CondGroup:
        if self.operator == "AND":
            return CondGroup([*self.conditions, other], "AND")
        return CondGroup([self, other], "AND")

    def __or__(self, other: Cond | CondGroup) -> CondGroup:
        if self.operator == "OR":
            return CondGroup([*self.conditions, other], "OR")
        return CondGroup([self, other], "OR")


# ---------------------------------------------------------------------------
# RawExpr — escape hatch for arbitrary Cypher expressions
# ---------------------------------------------------------------------------


class RawExpr:
    """Inject a raw Cypher expression string into the query builder."""

    __slots__ = ("expr",)

    def __init__(self, expr: str) -> None:
        self.expr = expr

    def render(self) -> str:
        return self.expr


# ---------------------------------------------------------------------------
# Query Builder
# ---------------------------------------------------------------------------


class Query:
    """Fluent, chainable Cypher query builder.

    Every method returns ``self`` so calls can be chained::

        q = (Query()
             .match(Person, "p")
             .where(Cond("p.age", ">", 18))
             .return_("p.name", "p.age")
             .order_by("p.name")
             .limit(10))
        cypher, params = q.build()
    """

    def __init__(self) -> None:
        self._clauses: list[tuple[str, str]] = []  # (clause_type, text)
        self._params: dict[str, Any] = {}
        self._param_counter: int = 0

    # -- helpers --

    def _next_param(self, prefix: str = "p") -> str:
        self._param_counter += 1
        return f"{prefix}_{self._param_counter}"

    def _node_pattern(
        self,
        model_or_label: Type[NodeModel] | str | None,
        var: str | None = None,
        props: dict[str, Any] | None = None,
    ) -> str:
        label_str = ""
        if model_or_label is not None:
            if isinstance(model_or_label, str):
                label_str = f":{model_or_label}"
            elif hasattr(model_or_label, 'labels') and len(model_or_label.labels()) > 1:
                label_str = model_or_label.labels_cypher()
            else:
                label_str = f":{model_or_label.label()}"
        var_str = var or ""
        prop_str = ""
        if props:
            parts = []
            for k, v in props.items():
                pname = self._next_param(var or "n")
                self._params[pname] = v
                parts.append(f"{k}: ${pname}")
            prop_str = " {" + ", ".join(parts) + "}"
        return f"({var_str}{label_str}{prop_str})"

    def _rel_pattern(
        self,
        model_or_type: Type[RelationshipModel] | str | None = None,
        var: str | None = None,
        props: dict[str, Any] | None = None,
        direction: str = "out",
        min_hops: int | None = None,
        max_hops: int | None = None,
    ) -> str:
        rel_type = ""
        if model_or_type is not None:
            if isinstance(model_or_type, str):
                rel_type = model_or_type
            else:
                rel_type = model_or_type.rel_type()
        var_str = var or ""
        type_str = f":{rel_type}" if rel_type else ""
        prop_str = ""
        if props:
            parts = []
            for k, v in props.items():
                pname = self._next_param(var or "r")
                self._params[pname] = v
                parts.append(f"{k}: ${pname}")
            prop_str = " {" + ", ".join(parts) + "}"
        range_str = ""
        if min_hops is not None or max_hops is not None:
            mn = str(min_hops) if min_hops is not None else ""
            mx = str(max_hops) if max_hops is not None else ""
            range_str = f"*{mn}..{mx}"
        inner = f"[{var_str}{type_str}{range_str}{prop_str}]"
        if direction == "out":
            return f"-{inner}->"
        elif direction == "in":
            return f"<-{inner}-"
        else:
            return f"-{inner}-"

    # -- MATCH / OPTIONAL MATCH --

    def match(
        self,
        model_or_label: Type[NodeModel] | str | None = None,
        var: str | None = None,
        props: dict[str, Any] | None = None,
        *,
        pattern: str | None = None,
    ) -> Query:
        """MATCH clause. Provide model+var or raw pattern string."""
        if pattern:
            self._clauses.append(("MATCH", pattern))
        else:
            self._clauses.append(("MATCH", self._node_pattern(model_or_label, var, props)))
        return self

    def optional_match(
        self,
        model_or_label: Type[NodeModel] | str | None = None,
        var: str | None = None,
        props: dict[str, Any] | None = None,
        *,
        pattern: str | None = None,
    ) -> Query:
        if pattern:
            self._clauses.append(("OPTIONAL MATCH", pattern))
        else:
            self._clauses.append(("OPTIONAL MATCH", self._node_pattern(model_or_label, var, props)))
        return self

    def match_path(
        self,
        src: tuple[Type[NodeModel] | str | None, str | None, dict[str, Any] | None],
        rel: tuple[Type[RelationshipModel] | str | None, str | None, dict[str, Any] | None] | None,
        tgt: tuple[Type[NodeModel] | str | None, str | None, dict[str, Any] | None],
        *,
        direction: str = "out",
        optional: bool = False,
        min_hops: int | None = None,
        max_hops: int | None = None,
    ) -> Query:
        """MATCH path pattern: (src)-[rel]->(tgt)."""
        src_pat = self._node_pattern(src[0], src[1], src[2] if len(src) > 2 else None)
        tgt_pat = self._node_pattern(tgt[0], tgt[1], tgt[2] if len(tgt) > 2 else None)
        if rel:
            rel_pat = self._rel_pattern(
                rel[0], rel[1], rel[2] if len(rel) > 2 else None,
                direction=direction, min_hops=min_hops, max_hops=max_hops,
            )
        else:
            if direction == "out":
                rel_pat = "-->"
            elif direction == "in":
                rel_pat = "<--"
            else:
                rel_pat = "--"
        clause_type = "OPTIONAL MATCH" if optional else "MATCH"
        self._clauses.append((clause_type, f"{src_pat}{rel_pat}{tgt_pat}"))
        return self

    # -- WHERE --

    def where(self, condition: Cond | CondGroup | str) -> Query:
        if isinstance(condition, str):
            text = condition
        else:
            text = condition.render()
        self._clauses.append(("WHERE", text))
        return self

    def and_where(self, condition: Cond | CondGroup | str) -> Query:
        if isinstance(condition, str):
            text = condition
        else:
            text = condition.render()
        self._clauses.append(("AND", text))
        return self

    def or_where(self, condition: Cond | CondGroup | str) -> Query:
        if isinstance(condition, str):
            text = condition
        else:
            text = condition.render()
        self._clauses.append(("OR", text))
        return self

    # -- CREATE / MERGE --

    def create(
        self,
        model_or_label: Type[NodeModel] | str | None = None,
        var: str | None = None,
        props: dict[str, Any] | None = None,
        *,
        pattern: str | None = None,
    ) -> Query:
        if pattern:
            self._clauses.append(("CREATE", pattern))
        else:
            self._clauses.append(("CREATE", self._node_pattern(model_or_label, var, props)))
        return self

    def merge(
        self,
        model_or_label: Type[NodeModel] | str | None = None,
        var: str | None = None,
        props: dict[str, Any] | None = None,
        *,
        pattern: str | None = None,
    ) -> Query:
        if pattern:
            self._clauses.append(("MERGE", pattern))
        else:
            self._clauses.append(("MERGE", self._node_pattern(model_or_label, var, props)))
        return self

    def create_path(
        self,
        src: tuple[Type[NodeModel] | str | None, str | None, dict[str, Any] | None],
        rel: tuple[Type[RelationshipModel] | str | None, str | None, dict[str, Any] | None],
        tgt: tuple[Type[NodeModel] | str | None, str | None, dict[str, Any] | None],
        *,
        direction: str = "out",
    ) -> Query:
        """CREATE (src)-[r:TYPE]->(tgt)."""
        src_pat = self._node_pattern(src[0], src[1], src[2] if len(src) > 2 else None)
        tgt_pat = self._node_pattern(tgt[0], tgt[1], tgt[2] if len(tgt) > 2 else None)
        rel_pat = self._rel_pattern(
            rel[0], rel[1], rel[2] if len(rel) > 2 else None, direction=direction,
        )
        self._clauses.append(("CREATE", f"{src_pat}{rel_pat}{tgt_pat}"))
        return self

    # -- SET / REMOVE / DELETE --

    def set(self, *assignments: str) -> Query:
        self._clauses.append(("SET", ", ".join(assignments)))
        return self

    def set_props(self, var: str, props: dict[str, Any]) -> Query:
        """SET var.key = $param for each prop."""
        parts = []
        for k, v in props.items():
            pname = self._next_param(var)
            self._params[pname] = v
            parts.append(f"{var}.{k} = ${pname}")
        self._clauses.append(("SET", ", ".join(parts)))
        return self

    def on_create_set(self, *assignments: str) -> Query:
        self._clauses.append(("ON CREATE SET", ", ".join(assignments)))
        return self

    def on_match_set(self, *assignments: str) -> Query:
        self._clauses.append(("ON MATCH SET", ", ".join(assignments)))
        return self

    def remove(self, *items: str) -> Query:
        self._clauses.append(("REMOVE", ", ".join(items)))
        return self

    def delete(self, *vars: str, detach: bool = False) -> Query:
        keyword = "DETACH DELETE" if detach else "DELETE"
        self._clauses.append((keyword, ", ".join(vars)))
        return self

    # -- WITH / RETURN --

    def with_(self, *items: str, distinct: bool = False) -> Query:
        keyword = "WITH DISTINCT" if distinct else "WITH"
        self._clauses.append((keyword, ", ".join(items)))
        return self

    def return_(self, *items: str, distinct: bool = False) -> Query:
        keyword = "RETURN DISTINCT" if distinct else "RETURN"
        self._clauses.append((keyword, ", ".join(items)))
        return self

    # -- ORDER BY / SKIP / LIMIT --

    def order_by(self, *items: str) -> Query:
        self._clauses.append(("ORDER BY", ", ".join(items)))
        return self

    def skip(self, n: int | str) -> Query:
        self._clauses.append(("SKIP", str(n)))
        return self

    def limit(self, n: int | str) -> Query:
        self._clauses.append(("LIMIT", str(n)))
        return self

    # -- UNWIND --

    def unwind(self, expr: str, var: str) -> Query:
        self._clauses.append(("UNWIND", f"{expr} AS {var}"))
        return self

    # -- CALL subquery --

    def call_subquery(self, subquery: Query | str) -> Query:
        if isinstance(subquery, Query):
            sub_cypher, sub_params = subquery.build()
            self._params.update(sub_params)
        else:
            sub_cypher = subquery
        self._clauses.append(("CALL", f"{{\n  {sub_cypher}\n}}"))
        return self

    # -- FOREACH --

    def foreach(self, var: str, list_expr: str, *actions: str) -> Query:
        action_str = " ".join(actions)
        self._clauses.append(("FOREACH", f"({var} IN {list_expr} | {action_str})"))
        return self

    # -- UNION --

    def union(self, other: Query, all: bool = False) -> Query:
        keyword = "UNION ALL" if all else "UNION"
        other_cypher, other_params = other.build()
        self._params.update(other_params)
        self._clauses.append((keyword, other_cypher))
        return self

    # -- Raw clause --

    def raw(self, clause: str) -> Query:
        """Append arbitrary Cypher text."""
        self._clauses.append(("", clause))
        return self

    # -- Parameters --

    def param(self, name: str, value: Any) -> Query:
        """Bind a parameter value."""
        self._params[name] = value
        return self

    def params(self, **kwargs: Any) -> Query:
        """Bind multiple parameters."""
        self._params.update(kwargs)
        return self

    # -- Build --

    def build(self) -> tuple[str, dict[str, Any]]:
        """Render the query as (cypher_string, parameters_dict)."""
        parts: list[str] = []
        for clause_type, text in self._clauses:
            if clause_type:
                parts.append(f"{clause_type} {text}")
            else:
                parts.append(text)
        cypher = " ".join(parts)
        return cypher, dict(self._params)

    def build_cypher(self) -> str:
        """Render just the Cypher string (no params)."""
        return self.build()[0]

    def __str__(self) -> str:
        return self.build_cypher()

    def __repr__(self) -> str:
        cypher, params = self.build()
        return f"Query({cypher!r}, params={params!r})"

    # -- Serialization --

    def to_dict(self) -> dict[str, Any]:
        """Serialize query to a dict for agent message passing."""
        cypher, params = self.build()
        return {
            "cypher": cypher,
            "parameters": params,
            "clauses": [(ct, text) for ct, text in self._clauses],
        }

    def to_json(self) -> str:
        """Serialize query to JSON string."""
        return json.dumps(self.to_dict(), default=str)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Query:
        """Deserialize query from a dict.

        If 'clauses' is present, reconstructs the full query builder.
        Otherwise, creates a raw query from 'cypher' and 'parameters'.
        """
        q = cls()
        if "clauses" in data:
            q._clauses = [(ct, text) for ct, text in data["clauses"]]
        elif "cypher" in data:
            q._clauses = [("", data["cypher"])]
        if "parameters" in data:
            q._params = dict(data["parameters"])
        return q

    @classmethod
    def from_json(cls, json_str: str) -> Query:
        """Deserialize query from JSON string."""
        return cls.from_dict(json.loads(json_str))

    # -- Validation integration --

    def validate(self, schema: Any) -> Any:
        """Validate this query against a CypherValidator or Schema.

        Returns ValidationResult from the Rust validator.
        """
        from cypher_validator._cypher_validator import CypherValidator as _CV, Schema as _Schema

        cypher = self.build_cypher()
        if isinstance(schema, _CV):
            return schema.validate(cypher)
        if isinstance(schema, _Schema):
            return _CV(schema).validate(cypher)
        # Assume it's a GraphSchema
        if hasattr(schema, "to_cypher_schema"):
            return _CV(schema.to_cypher_schema()).validate(cypher)
        raise TypeError(f"Expected CypherValidator, Schema, or GraphSchema, got {type(schema)}")

    def explain(self) -> str:
        """Return a human/AI-readable explanation of what this query does."""
        parts = []
        for clause_type, text in self._clauses:
            if clause_type in ("MATCH", "OPTIONAL MATCH"):
                parts.append(f"Find pattern: {text}")
            elif clause_type == "WHERE":
                parts.append(f"Filter: {text}")
            elif clause_type in ("AND", "OR"):
                parts.append(f"  {clause_type}: {text}")
            elif clause_type in ("CREATE",):
                parts.append(f"Create: {text}")
            elif clause_type in ("MERGE",):
                parts.append(f"Merge (create if not exists): {text}")
            elif clause_type in ("SET", "ON CREATE SET", "ON MATCH SET"):
                parts.append(f"Set properties: {text}")
            elif clause_type in ("DELETE", "DETACH DELETE"):
                parts.append(f"Delete: {text}")
            elif clause_type in ("RETURN", "RETURN DISTINCT"):
                parts.append(f"Return: {text}")
            elif clause_type == "ORDER BY":
                parts.append(f"Order by: {text}")
            elif clause_type == "SKIP":
                parts.append(f"Skip first {text} results")
            elif clause_type == "LIMIT":
                parts.append(f"Limit to {text} results")
            elif clause_type == "UNWIND":
                parts.append(f"Unwind list: {text}")
            elif clause_type == "WITH":
                parts.append(f"Pipe through: {text}")
            else:
                parts.append(f"{clause_type}: {text}" if clause_type else text)
        return "\n".join(parts)


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

        # Fallback: manual introspection via Cypher
        nodes_dict: dict[str, list[str]] = {}
        rels_dict: dict[str, list[Any]] = {}

        # Discover node labels and properties
        try:
            label_records = db.execute("CALL db.labels() YIELD label RETURN label")
            for rec in label_records:
                label = rec.get("label", "")
                if label:
                    prop_records = db.execute(
                        f"MATCH (n:{label}) RETURN keys(n) AS props LIMIT 1"
                    )
                    props: list[str] = []
                    if prop_records:
                        props = prop_records[0].get("props", [])
                    nodes_dict[label] = props
        except Exception:
            pass

        # Discover relationship types
        try:
            rel_records = db.execute(
                "CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType"
            )
            for rec in rel_records:
                rtype = rec.get("relationshipType", "")
                if rtype:
                    endpoint_records = db.execute(
                        f"MATCH (a)-[r:{rtype}]->(b) "
                        f"RETURN labels(a)[0] AS src, labels(b)[0] AS tgt, keys(r) AS props "
                        f"LIMIT 1"
                    )
                    if endpoint_records:
                        src = endpoint_records[0].get("src", "Unknown")
                        tgt = endpoint_records[0].get("tgt", "Unknown")
                        props = endpoint_records[0].get("props", [])
                        rels_dict[rtype] = [src, tgt, props]
        except Exception:
            pass

        return cls.from_dict({"nodes": nodes_dict, "relationships": rels_dict})

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
# AI Agent Tools
# ---------------------------------------------------------------------------


class AgentTools:
    """Generate AI-agent-friendly tool specs and helpers.

    Produces OpenAI/Anthropic function-calling tool definitions from
    your Pydantic graph schema, enabling agents to build validated
    Cypher queries via structured function calls.
    """

    def __init__(self, schema: GraphSchema) -> None:
        self.schema = schema

    def query_tool_spec(self, format: str = "openai") -> dict[str, Any]:
        """Tool spec for generating Cypher queries.

        Args:
            format: "openai" or "anthropic"

        Returns:
            Tool definition dict ready for function-calling APIs.
        """
        schema_text = self.schema.to_prompt()
        properties: dict[str, Any] = {
            "query_type": {
                "type": "string",
                "enum": ["match", "create", "merge", "delete", "update"],
                "description": "Type of Cypher operation",
            },
            "cypher": {
                "type": "string",
                "description": f"Valid Cypher query. Schema:\n{schema_text}",
            },
            "parameters": {
                "type": "object",
                "description": "Query parameters as key-value pairs. Use $param_name in Cypher.",
                "additionalProperties": True,
            },
            "explanation": {
                "type": "string",
                "description": "Brief natural language explanation of what the query does",
            },
        }
        tool_def = {
            "type": "function",
            "function": {
                "name": "execute_cypher",
                "description": (
                    "Execute a Cypher query against the graph database. "
                    "Always use parameterized queries ($param) for values."
                ),
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": ["query_type", "cypher"],
                },
            },
        }
        if format == "anthropic":
            return {
                "name": "execute_cypher",
                "description": tool_def["function"]["description"],
                "input_schema": tool_def["function"]["parameters"],
            }
        return tool_def

    def create_node_tool_spec(self, format: str = "openai") -> dict[str, Any]:
        """Tool spec for creating nodes with proper validation."""
        node_schemas: dict[str, Any] = {}
        for m in self.schema.node_models:
            props: dict[str, Any] = {}
            for pname, ptype in m.property_types().items():
                json_type = _python_type_to_json_type(ptype)
                props[pname] = {"type": json_type}
            node_schemas[m.label()] = {
                "type": "object",
                "properties": props,
                "required": m.required_properties(),
            }

        properties = {
            "label": {
                "type": "string",
                "enum": [m.label() for m in self.schema.node_models],
                "description": "Node label",
            },
            "properties": {
                "type": "object",
                "description": "Node properties",
                "additionalProperties": True,
            },
        }
        tool_def = {
            "type": "function",
            "function": {
                "name": "create_node",
                "description": (
                    "Create a node in the graph database. "
                    f"Available labels: {', '.join(m.label() for m in self.schema.node_models)}"
                ),
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": ["label", "properties"],
                },
            },
        }
        if format == "anthropic":
            return {
                "name": "create_node",
                "description": tool_def["function"]["description"],
                "input_schema": tool_def["function"]["parameters"],
            }
        return tool_def

    def create_relationship_tool_spec(self, format: str = "openai") -> dict[str, Any]:
        """Tool spec for creating relationships."""
        rel_info = []
        for m in self.schema.rel_models:
            rel_info.append(
                f"(:{m.source_label()})-[:{m.rel_type()}]->(:{m.target_label()})"
            )

        properties = {
            "rel_type": {
                "type": "string",
                "enum": [m.rel_type() for m in self.schema.rel_models],
                "description": "Relationship type",
            },
            "source_match": {
                "type": "object",
                "description": "Properties to match the source node",
                "additionalProperties": True,
            },
            "target_match": {
                "type": "object",
                "description": "Properties to match the target node",
                "additionalProperties": True,
            },
            "properties": {
                "type": "object",
                "description": "Relationship properties",
                "additionalProperties": True,
            },
        }
        tool_def = {
            "type": "function",
            "function": {
                "name": "create_relationship",
                "description": (
                    "Create a relationship between nodes. "
                    f"Available patterns: {', '.join(rel_info)}"
                ),
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": ["rel_type", "source_match", "target_match"],
                },
            },
        }
        if format == "anthropic":
            return {
                "name": "create_relationship",
                "description": tool_def["function"]["description"],
                "input_schema": tool_def["function"]["parameters"],
            }
        return tool_def

    def all_tool_specs(self, format: str = "openai") -> list[dict[str, Any]]:
        """All tool specs as a list."""
        return [
            self.query_tool_spec(format),
            self.create_node_tool_spec(format),
            self.create_relationship_tool_spec(format),
        ]

    def handle_tool_call(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> tuple[str, dict[str, Any]] | None:
        """Convert a tool call from an AI agent into a (cypher, params) tuple.

        Returns None if tool_name is not recognized.
        """
        if tool_name == "execute_cypher":
            return arguments["cypher"], arguments.get("parameters", {})
        elif tool_name == "create_node":
            label = arguments["label"]
            props = arguments.get("properties", {})
            # Find matching model
            for m in self.schema.node_models:
                if m.label() == label:
                    instance = m(**props)
                    return instance.to_create_cypher()
            # Fallback: raw create
            params = {f"n_{k}": v for k, v in props.items()}
            prop_str = ", ".join(f"{k}: $n_{k}" for k in props)
            return f"CREATE (n:{label} {{{prop_str}}}) RETURN n", params
        elif tool_name == "create_relationship":
            rel_type_str = arguments["rel_type"]
            src_match = arguments.get("source_match", {})
            tgt_match = arguments.get("target_match", {})
            rel_props = arguments.get("properties", {})
            for m in self.schema.rel_models:
                if m.rel_type() == rel_type_str:
                    instance = m(**rel_props)
                    return instance.to_create_cypher(
                        src_match=src_match, tgt_match=tgt_match
                    )
            return None
        return None

    def schema_context_for_prompt(self) -> str:
        """Complete schema context string suitable for LLM system prompts."""
        return (
            "You have access to a Neo4j graph database with the following schema.\n"
            "Always use parameterized queries ($param) for values to prevent injection.\n\n"
            + self.schema.to_prompt()
            + "\n\nAvailable tools: execute_cypher, create_node, create_relationship\n"
        )


# ---------------------------------------------------------------------------
# QueryPlan — structured query decomposition for agents
# ---------------------------------------------------------------------------


class QueryStep(BaseModel):
    """Single step in a query plan."""
    description: str
    cypher: str
    parameters: dict[str, Any] = {}
    depends_on: list[int] = []
    is_read: bool = True


class QueryPlan(BaseModel):
    """Multi-step query plan for complex operations.

    AI agents can build a QueryPlan to decompose complex tasks into
    ordered, validated steps.
    """
    goal: str
    steps: list[QueryStep]

    def validate_all(self, schema: Any) -> list[tuple[int, Any]]:
        """Validate all steps, return list of (step_index, validation_result)."""
        results = []
        for i, step in enumerate(self.steps):
            q = Query().raw(step.cypher)
            result = q.validate(schema)
            results.append((i, result))
        return results

    def to_execution_order(self) -> list[list[int]]:
        """Return steps grouped by execution wave (parallel within wave)."""
        done: set[int] = set()
        waves: list[list[int]] = []
        remaining = set(range(len(self.steps)))
        while remaining:
            wave = [
                i for i in remaining
                if all(d in done for d in self.steps[i].depends_on)
            ]
            if not wave:
                # Cycle or impossible deps — just dump remaining
                waves.append(sorted(remaining))
                break
            waves.append(sorted(wave))
            done.update(wave)
            remaining -= set(wave)
        return waves

    def explain(self) -> str:
        lines = [f"Goal: {self.goal}", ""]
        waves = self.to_execution_order()
        for wi, wave in enumerate(waves):
            lines.append(f"Wave {wi + 1}:")
            for idx in wave:
                step = self.steps[idx]
                rw = "READ" if step.is_read else "WRITE"
                deps = f" (after steps {step.depends_on})" if step.depends_on else ""
                lines.append(f"  Step {idx}: [{rw}] {step.description}{deps}")
                lines.append(f"    {step.cypher}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# QueryResult — structured result wrapper
# ---------------------------------------------------------------------------


class QueryResult(BaseModel):
    """Structured wrapper for Cypher query results, useful for AI agents."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    cypher: str
    parameters: dict[str, Any] = {}
    records: list[dict[str, Any]] = []
    summary: str = ""
    error: str | None = None
    is_valid: bool = True
    validation_errors: list[str] = []

    @property
    def success(self) -> bool:
        return self.error is None and self.is_valid

    @property
    def count(self) -> int:
        return len(self.records)

    def to_markdown(self) -> str:
        if self.error:
            return f"**Error**: {self.error}"
        if not self.records:
            return "*No results*"
        keys = list(self.records[0].keys())
        lines = [
            "| " + " | ".join(keys) + " |",
            "| " + " | ".join("---" for _ in keys) + " |",
        ]
        for rec in self.records:
            vals = [str(rec.get(k, "")) for k in keys]
            lines.append("| " + " | ".join(vals) + " |")
        return "\n".join(lines)

    def to_json(self) -> str:
        return self.model_dump_json(indent=2)

    def to_natural_language(self) -> str:
        """Simple NL summary of results."""
        if self.error:
            return f"Query failed: {self.error}"
        if not self.records:
            return "The query returned no results."
        if len(self.records) == 1:
            rec = self.records[0]
            parts = [f"{k}: {v}" for k, v in rec.items()]
            return "Found 1 result — " + ", ".join(parts)
        return f"Found {len(self.records)} results."


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _python_type_to_json_type(type_str: str) -> str:
    """Map Python type names to JSON Schema types."""
    mapping = {
        "str": "string",
        "int": "integer",
        "float": "number",
        "bool": "boolean",
        "list": "array",
        "dict": "object",
    }
    lower = type_str.lower().split("[")[0].strip()
    return mapping.get(lower, "string")


# ---------------------------------------------------------------------------
# Convenience factory functions
# ---------------------------------------------------------------------------


def node(label: str, **field_defs: Any) -> Type[NodeModel]:
    """Dynamically create a NodeModel subclass.

    Usage::

        Person = node("Person", name=(str, ...), age=(int, 0))

    Field definitions follow Pydantic's (type, default) tuple convention.
    A bare type like ``str`` means required with no default.
    """
    annotations: dict[str, Any] = {}
    defaults: dict[str, Any] = {}
    for fname, fdef in field_defs.items():
        if isinstance(fdef, tuple):
            annotations[fname] = fdef[0]
            if fdef[1] is not ...:
                defaults[fname] = fdef[1]
        else:
            # Bare type = required
            annotations[fname] = fdef
    namespace: dict[str, Any] = {
        "__annotations__": annotations,
        "__label__": label,
        "__module__": __name__,
        "__qualname__": label,
    }
    namespace.update(defaults)
    return type(label, (NodeModel,), namespace)  # type: ignore[return-value]


def relationship(
    rel_type: str,
    source: Type[NodeModel],
    target: Type[NodeModel],
    **field_defs: Any,
) -> Type[RelationshipModel]:
    """Dynamically create a RelationshipModel subclass.

    Usage::

        ActedIn = relationship("ACTED_IN", Person, Movie, roles=(list, []))
    """
    annotations: dict[str, Any] = {}
    defaults: dict[str, Any] = {}
    for fname, fdef in field_defs.items():
        if isinstance(fdef, tuple):
            annotations[fname] = fdef[0]
            if fdef[1] is not ...:
                defaults[fname] = fdef[1]
        else:
            annotations[fname] = fdef
    class_name = rel_type.replace("_", " ").title().replace(" ", "")
    namespace: dict[str, Any] = {
        "__annotations__": annotations,
        "__source__": source,
        "__target__": target,
        "__rel_type__": rel_type,
        "__module__": __name__,
        "__qualname__": class_name,
    }
    namespace.update(defaults)
    return type(class_name, (RelationshipModel,), namespace)  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Graph Traversal Helpers
# ---------------------------------------------------------------------------


_VALID_DIRECTIONS = {"in", "out", "both"}


def _validate_direction(direction: str) -> None:
    if direction not in _VALID_DIRECTIONS:
        raise ValueError(
            f"Invalid direction '{direction}'. Must be one of: {', '.join(sorted(_VALID_DIRECTIONS))}"
        )


class Traversal:
    """Pre-built query patterns for common graph traversals.

    All methods return ``(cypher, params)`` tuples ready for execution.
    """

    @staticmethod
    def neighbors(
        model: Type[NodeModel],
        var: str = "n",
        match_props: dict[str, Any] | None = None,
        rel_type: str | Type[RelationshipModel] | None = None,
        direction: str = "both",
        limit: int | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Find neighbor nodes connected to a matched node.

        Returns (source_node, relationship, neighbor_node) triples.
        """
        _validate_direction(direction)
        params: dict[str, Any] = {}
        label = model.label()

        # Match source
        where_parts = []
        if match_props:
            for k, v in match_props.items():
                params[f"{var}_{k}"] = v
                where_parts.append(f"{var}.{k} = ${var}_{k}")

        # Relationship pattern
        rtype = ""
        if rel_type:
            rtype = f":{rel_type.rel_type() if isinstance(rel_type, type) and issubclass(rel_type, RelationshipModel) else rel_type}"
        if direction == "out":
            rel_pat = f"-[r{rtype}]->"
        elif direction == "in":
            rel_pat = f"<-[r{rtype}]-"
        else:
            rel_pat = f"-[r{rtype}]-"

        cypher = f"MATCH ({var}:{label}){rel_pat}(neighbor)"
        if where_parts:
            cypher += " WHERE " + " AND ".join(where_parts)
        cypher += f" RETURN {var}, r, neighbor"
        if limit:
            cypher += f" LIMIT {limit}"
        return cypher, params

    @staticmethod
    def shortest_path(
        src_model: Type[NodeModel],
        tgt_model: Type[NodeModel],
        src_props: dict[str, Any],
        tgt_props: dict[str, Any],
        rel_type: str | None = None,
        max_depth: int | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Find shortest path between two nodes."""
        params: dict[str, Any] = {}
        for k, v in src_props.items():
            params[f"src_{k}"] = v
        for k, v in tgt_props.items():
            params[f"tgt_{k}"] = v

        src_where = " AND ".join(f"src.{k} = $src_{k}" for k in src_props)
        tgt_where = " AND ".join(f"tgt.{k} = $tgt_{k}" for k in tgt_props)

        rel_spec = f":{rel_type}" if rel_type else ""
        depth_spec = f"*..{max_depth}" if max_depth else "*"

        cypher = (
            f"MATCH (src:{src_model.label()}), (tgt:{tgt_model.label()}), "
            f"path = shortestPath((src)-[{rel_spec}{depth_spec}]-(tgt)) "
            f"WHERE {src_where} AND {tgt_where} "
            f"RETURN path, length(path) AS distance"
        )
        return cypher, params

    @staticmethod
    def subgraph(
        model: Type[NodeModel],
        match_props: dict[str, Any],
        depth: int = 2,
        var: str = "n",
    ) -> tuple[str, dict[str, Any]]:
        """Extract a subgraph around a node up to a given depth."""
        params: dict[str, Any] = {}
        for k, v in match_props.items():
            params[f"{var}_{k}"] = v
        where = " AND ".join(f"{var}.{k} = ${var}_{k}" for k in match_props)
        cypher = (
            f"MATCH path = ({var}:{model.label()})-[*1..{depth}]-(connected) "
            f"WHERE {where} "
            f"RETURN path"
        )
        return cypher, params

    @staticmethod
    def degree(
        model: Type[NodeModel],
        var: str = "n",
        match_props: dict[str, Any] | None = None,
        rel_type: str | None = None,
        direction: str = "both",
    ) -> tuple[str, dict[str, Any]]:
        """Count the degree (number of relationships) of nodes."""
        _validate_direction(direction)
        params: dict[str, Any] = {}
        label = model.label()
        where_parts = []
        if match_props:
            for k, v in match_props.items():
                params[f"{var}_{k}"] = v
                where_parts.append(f"{var}.{k} = ${var}_{k}")

        rtype = f":{rel_type}" if rel_type else ""
        if direction == "out":
            rel_pat = f"-[r{rtype}]->()"
        elif direction == "in":
            rel_pat = f"<-[r{rtype}]-()"
        else:
            rel_pat = f"-[r{rtype}]-()"

        cypher = f"MATCH ({var}:{label})"
        if where_parts:
            cypher += " WHERE " + " AND ".join(where_parts)
        cypher += f" RETURN {var}, size([({var}){rel_pat} | 1]) AS degree"
        return cypher, params

    @staticmethod
    def common_neighbors(
        model_a: Type[NodeModel],
        model_b: Type[NodeModel],
        props_a: dict[str, Any],
        props_b: dict[str, Any],
        rel_type: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Find nodes connected to both A and B."""
        params: dict[str, Any] = {}
        for k, v in props_a.items():
            params[f"a_{k}"] = v
        for k, v in props_b.items():
            params[f"b_{k}"] = v

        where_a = " AND ".join(f"a.{k} = $a_{k}" for k in props_a)
        where_b = " AND ".join(f"b.{k} = $b_{k}" for k in props_b)
        rtype = f":{rel_type}" if rel_type else ""

        cypher = (
            f"MATCH (a:{model_a.label()})-[{rtype}]-(common)-[{rtype}]-(b:{model_b.label()}) "
            f"WHERE {where_a} AND {where_b} "
            f"RETURN DISTINCT common"
        )
        return cypher, params

    @staticmethod
    def path_exists(
        src_model: Type[NodeModel],
        tgt_model: Type[NodeModel],
        src_props: dict[str, Any],
        tgt_props: dict[str, Any],
        max_depth: int = 5,
    ) -> tuple[str, dict[str, Any]]:
        """Check if any path exists between two nodes."""
        params: dict[str, Any] = {}
        for k, v in src_props.items():
            params[f"src_{k}"] = v
        for k, v in tgt_props.items():
            params[f"tgt_{k}"] = v

        src_where = " AND ".join(f"src.{k} = $src_{k}" for k in src_props)
        tgt_where = " AND ".join(f"tgt.{k} = $tgt_{k}" for k in tgt_props)

        cypher = (
            f"MATCH (src:{src_model.label()}), (tgt:{tgt_model.label()}) "
            f"WHERE {src_where} AND {tgt_where} "
            f"RETURN EXISTS((src)-[*1..{max_depth}]-(tgt)) AS connected"
        )
        return cypher, params


# ---------------------------------------------------------------------------
# Bulk Operations
# ---------------------------------------------------------------------------


class BulkOps:
    """Batch operations for creating/merging nodes and relationships.

    Generates efficient UNWIND-based Cypher for bulk operations,
    which is much faster than individual CREATE/MERGE statements.
    """

    @staticmethod
    def bulk_create_nodes(
        model: Type[NodeModel],
        items: list[dict[str, Any]],
        var: str = "n",
    ) -> tuple[str, dict[str, Any]]:
        """UNWIND-based bulk CREATE for nodes.

        Example::

            cypher, params = BulkOps.bulk_create_nodes(
                Person, [{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}]
            )
        """
        params = {"batch": items}
        props = ", ".join(f"{k}: item.{k}" for k in model.property_names())
        cypher = (
            f"UNWIND $batch AS item "
            f"CREATE ({var}:{model.label()} {{{props}}}) "
            f"RETURN {var}"
        )
        return cypher, params

    @staticmethod
    def bulk_merge_nodes(
        model: Type[NodeModel],
        items: list[dict[str, Any]],
        merge_keys: list[str],
        var: str = "n",
    ) -> tuple[str, dict[str, Any]]:
        """UNWIND-based bulk MERGE for nodes.

        Merges on *merge_keys*, sets remaining properties.
        """
        params = {"batch": items}
        merge_props = ", ".join(f"{k}: item.{k}" for k in merge_keys)
        set_keys = [k for k in model.property_names() if k not in merge_keys]
        cypher = f"UNWIND $batch AS item MERGE ({var}:{model.label()} {{{merge_props}}})"
        if set_keys:
            set_str = ", ".join(f"{var}.{k} = item.{k}" for k in set_keys)
            cypher += f" ON CREATE SET {set_str} ON MATCH SET {set_str}"
        cypher += f" RETURN {var}"
        return cypher, params

    @staticmethod
    def bulk_create_relationships(
        rel_model: Type[RelationshipModel],
        items: list[dict[str, Any]],
        src_key: str,
        tgt_key: str,
    ) -> tuple[str, dict[str, Any]]:
        """UNWIND-based bulk CREATE for relationships.

        Each item dict should contain *src_key* and *tgt_key* to match
        source/target nodes, plus any relationship properties.

        Example::

            cypher, params = BulkOps.bulk_create_relationships(
                ActedIn,
                [{"src_name": "Alice", "tgt_title": "Matrix", "roles": ["Trinity"]}],
                src_key="src_name", tgt_key="tgt_title",
            )
        """
        params = {"batch": items}
        src_label = rel_model.source_label()
        tgt_label = rel_model.target_label()
        rel_type = rel_model.rel_type()
        # Determine the source/target property names from keys
        src_prop = src_key.replace("src_", "")
        tgt_prop = tgt_key.replace("tgt_", "")
        rel_props = rel_model.property_names()
        prop_str = ""
        if rel_props:
            prop_str = " {" + ", ".join(f"{k}: item.{k}" for k in rel_props) + "}"
        cypher = (
            f"UNWIND $batch AS item "
            f"MATCH (a:{src_label} {{{src_prop}: item.{src_key}}}), "
            f"(b:{tgt_label} {{{tgt_prop}: item.{tgt_key}}}) "
            f"CREATE (a)-[r:{rel_type}{prop_str}]->(b) "
            f"RETURN r"
        )
        return cypher, params

    @staticmethod
    def bulk_merge_relationships(
        rel_model: Type[RelationshipModel],
        items: list[dict[str, Any]],
        src_key: str,
        tgt_key: str,
    ) -> tuple[str, dict[str, Any]]:
        """UNWIND-based bulk MERGE for relationships."""
        params = {"batch": items}
        src_label = rel_model.source_label()
        tgt_label = rel_model.target_label()
        rel_type = rel_model.rel_type()
        src_prop = src_key.replace("src_", "")
        tgt_prop = tgt_key.replace("tgt_", "")
        rel_props = rel_model.property_names()
        cypher = (
            f"UNWIND $batch AS item "
            f"MATCH (a:{src_label} {{{src_prop}: item.{src_key}}}), "
            f"(b:{tgt_label} {{{tgt_prop}: item.{tgt_key}}}) "
            f"MERGE (a)-[r:{rel_type}]->(b)"
        )
        if rel_props:
            set_str = ", ".join(f"r.{k} = item.{k}" for k in rel_props)
            cypher += f" SET {set_str}"
        cypher += " RETURN r"
        return cypher, params

    @staticmethod
    def bulk_delete_nodes(
        model: Type[NodeModel],
        match_key: str,
        values: list[Any],
        detach: bool = True,
    ) -> tuple[str, dict[str, Any]]:
        """Bulk delete nodes matching a property value list."""
        params = {"values": values}
        delete_kw = "DETACH DELETE" if detach else "DELETE"
        cypher = (
            f"MATCH (n:{model.label()}) "
            f"WHERE n.{match_key} IN $values "
            f"{delete_kw} n"
        )
        return cypher, params


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

    def property_indexes(self) -> list[str]:
        """Generate property indexes for all node properties."""
        stmts: list[str] = []
        for m in self.schema.node_models:
            for prop in m.property_names():
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
        return stmts


# ---------------------------------------------------------------------------
# GraphSession — execute queries with model hydration
# ---------------------------------------------------------------------------


class GraphSession:
    """Execute Cypher queries against a Neo4j database with Pydantic model hydration.

    Wraps the existing Neo4jDatabase class from gliner2_integration.

    Usage::

        session = GraphSession(db, schema)
        people = session.query(Person, where={"name": "Alice"})
        session.create(Person(name="Bob", age=25))
        session.bulk_create(Person, [{"name": "C"}, {"name": "D"}])
    """

    def __init__(self, db: Any, schema: GraphSchema | None = None) -> None:
        self.db = db
        self.schema = schema

    def execute(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Execute raw Cypher, return list of record dicts."""
        return self.db.execute(cypher, params or {})

    def execute_query(self, query: Query) -> list[dict[str, Any]]:
        """Execute a Query builder query."""
        cypher, params = query.build()
        return self.execute(cypher, params)

    def query(
        self,
        model: Type[NodeModel],
        var: str = "n",
        where: dict[str, Any] | None = None,
        limit: int | None = None,
        order_by: str | None = None,
    ) -> list[Any]:
        """Query nodes and return hydrated Pydantic model instances."""
        cypher, params = model.match_cypher(var, where)
        if order_by:
            cypher += f" ORDER BY {order_by}"
        if limit:
            cypher += f" LIMIT {limit}"
        records = self.execute(cypher, params)
        return model.from_records(records, var)

    def create(self, instance: NodeModel, var: str = "n") -> list[dict[str, Any]]:
        """Create a node from a model instance."""
        cypher, params = instance.to_create_cypher(var)
        return self.execute(cypher, params)

    def merge(
        self,
        instance: NodeModel,
        var: str = "n",
        merge_keys: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Merge a node from a model instance."""
        cypher, params = instance.to_merge_cypher(var, merge_keys)
        return self.execute(cypher, params)

    def delete(
        self,
        model: Type[NodeModel],
        where: dict[str, Any],
        var: str = "n",
        detach: bool = True,
    ) -> list[dict[str, Any]]:
        """Delete nodes matching a filter."""
        q = Query().match(model, var)
        params: dict[str, Any] = {}
        where_parts = []
        for k, v in where.items():
            pname = f"{var}_{k}"
            params[pname] = v
            where_parts.append(f"{var}.{k} = ${pname}")
        q = q.where(" AND ".join(where_parts)).delete(var, detach=detach)
        cypher = q.build_cypher()
        return self.execute(cypher, params)

    def bulk_create(
        self, model: Type[NodeModel], items: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Bulk create nodes using UNWIND."""
        cypher, params = BulkOps.bulk_create_nodes(model, items)
        return self.execute(cypher, params)

    def bulk_merge(
        self,
        model: Type[NodeModel],
        items: list[dict[str, Any]],
        merge_keys: list[str],
    ) -> list[dict[str, Any]]:
        """Bulk merge nodes using UNWIND."""
        cypher, params = BulkOps.bulk_merge_nodes(model, items, merge_keys)
        return self.execute(cypher, params)

    def create_relationship(
        self,
        rel_instance: RelationshipModel,
        src_match: dict[str, Any],
        tgt_match: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Create a relationship from a model instance."""
        cypher, params = rel_instance.to_create_cypher(
            src_match=src_match, tgt_match=tgt_match
        )
        return self.execute(cypher, params)

    def neighbors(
        self,
        model: Type[NodeModel],
        match_props: dict[str, Any],
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Find neighbor nodes."""
        cypher, params = Traversal.neighbors(model, match_props=match_props, **kwargs)
        return self.execute(cypher, params)

    def shortest_path(
        self,
        src_model: Type[NodeModel],
        tgt_model: Type[NodeModel],
        src_props: dict[str, Any],
        tgt_props: dict[str, Any],
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Find shortest path between two nodes."""
        cypher, params = Traversal.shortest_path(
            src_model, tgt_model, src_props, tgt_props, **kwargs
        )
        return self.execute(cypher, params)

    def apply_ddl(self, include_existence: bool = False) -> list[str]:
        """Apply all schema DDL (constraints + indexes) to the database.

        Returns list of executed statements.
        """
        if not self.schema:
            raise ValueError("GraphSession needs a GraphSchema to generate DDL")
        ddl = SchemaDDL(self.schema)
        stmts = ddl.generate_all(include_existence=include_existence)
        for stmt in stmts:
            self.execute(stmt)
        return stmts


# ---------------------------------------------------------------------------
# Extended AgentTools — additional tool specs
# ---------------------------------------------------------------------------


class ExtendedAgentTools(AgentTools):
    """Extended agent tools with search, graph traversal, and schema info.

    Builds on AgentTools with more specialized tool specs that let AI
    agents perform complex graph operations through structured function calls.
    """

    def search_nodes_tool_spec(self, format: str = "openai") -> dict[str, Any]:
        """Tool spec for searching nodes by property values."""
        properties = {
            "label": {
                "type": "string",
                "enum": [m.label() for m in self.schema.node_models],
                "description": "Node label to search",
            },
            "filters": {
                "type": "object",
                "description": "Property-value pairs to filter on",
                "additionalProperties": True,
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of results (default: 25)",
                "default": 25,
            },
            "order_by": {
                "type": "string",
                "description": "Property to sort by, optionally with DESC suffix",
            },
        }
        tool_def = {
            "type": "function",
            "function": {
                "name": "search_nodes",
                "description": "Search for nodes by label and property filters",
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": ["label"],
                },
            },
        }
        if format == "anthropic":
            return {
                "name": "search_nodes",
                "description": tool_def["function"]["description"],
                "input_schema": tool_def["function"]["parameters"],
            }
        return tool_def

    def find_neighbors_tool_spec(self, format: str = "openai") -> dict[str, Any]:
        """Tool spec for finding neighbor nodes."""
        rel_types = [m.rel_type() for m in self.schema.rel_models]
        properties = {
            "label": {
                "type": "string",
                "enum": [m.label() for m in self.schema.node_models],
                "description": "Label of the source node",
            },
            "match_properties": {
                "type": "object",
                "description": "Properties to identify the source node",
                "additionalProperties": True,
            },
            "relationship_type": {
                "type": "string",
                "enum": rel_types,
                "description": "Filter by relationship type (optional)",
            },
            "direction": {
                "type": "string",
                "enum": ["in", "out", "both"],
                "description": "Direction of relationships (default: both)",
                "default": "both",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of neighbors to return",
                "default": 25,
            },
        }
        tool_def = {
            "type": "function",
            "function": {
                "name": "find_neighbors",
                "description": "Find nodes connected to a given node via relationships",
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": ["label", "match_properties"],
                },
            },
        }
        if format == "anthropic":
            return {
                "name": "find_neighbors",
                "description": tool_def["function"]["description"],
                "input_schema": tool_def["function"]["parameters"],
            }
        return tool_def

    def find_path_tool_spec(self, format: str = "openai") -> dict[str, Any]:
        """Tool spec for finding paths between nodes."""
        properties = {
            "source_label": {
                "type": "string",
                "enum": [m.label() for m in self.schema.node_models],
            },
            "source_properties": {
                "type": "object",
                "additionalProperties": True,
            },
            "target_label": {
                "type": "string",
                "enum": [m.label() for m in self.schema.node_models],
            },
            "target_properties": {
                "type": "object",
                "additionalProperties": True,
            },
            "max_depth": {
                "type": "integer",
                "description": "Maximum path length (default: 5)",
                "default": 5,
            },
        }
        tool_def = {
            "type": "function",
            "function": {
                "name": "find_path",
                "description": "Find the shortest path between two nodes in the graph",
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": [
                        "source_label", "source_properties",
                        "target_label", "target_properties",
                    ],
                },
            },
        }
        if format == "anthropic":
            return {
                "name": "find_path",
                "description": tool_def["function"]["description"],
                "input_schema": tool_def["function"]["parameters"],
            }
        return tool_def

    def get_schema_tool_spec(self, format: str = "openai") -> dict[str, Any]:
        """Tool spec for retrieving schema information."""
        tool_def = {
            "type": "function",
            "function": {
                "name": "get_graph_schema",
                "description": "Get the schema of the graph database (node types, relationship types, properties)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "format": {
                            "type": "string",
                            "enum": ["text", "markdown", "json"],
                            "description": "Output format (default: text)",
                            "default": "text",
                        },
                    },
                },
            },
        }
        if format == "anthropic":
            return {
                "name": "get_graph_schema",
                "description": tool_def["function"]["description"],
                "input_schema": tool_def["function"]["parameters"],
            }
        return tool_def

    def bulk_create_tool_spec(self, format: str = "openai") -> dict[str, Any]:
        """Tool spec for bulk node creation."""
        properties = {
            "label": {
                "type": "string",
                "enum": [m.label() for m in self.schema.node_models],
                "description": "Node label to create",
            },
            "items": {
                "type": "array",
                "items": {"type": "object", "additionalProperties": True},
                "description": "List of property dicts, one per node",
            },
        }
        tool_def = {
            "type": "function",
            "function": {
                "name": "bulk_create_nodes",
                "description": "Create multiple nodes at once efficiently",
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": ["label", "items"],
                },
            },
        }
        if format == "anthropic":
            return {
                "name": "bulk_create_nodes",
                "description": tool_def["function"]["description"],
                "input_schema": tool_def["function"]["parameters"],
            }
        return tool_def

    def all_tool_specs(self, format: str = "openai") -> list[dict[str, Any]]:
        """All tool specs including extended ones."""
        base = super().all_tool_specs(format)
        base.extend([
            self.search_nodes_tool_spec(format),
            self.find_neighbors_tool_spec(format),
            self.find_path_tool_spec(format),
            self.get_schema_tool_spec(format),
            self.bulk_create_tool_spec(format),
        ])
        return base

    def handle_tool_call(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> tuple[str, dict[str, Any]] | None:
        """Handle all tool calls including extended ones."""
        # Check base tools first
        result = super().handle_tool_call(tool_name, arguments)
        if result is not None:
            return result

        if tool_name == "search_nodes":
            label = arguments["label"]
            filters = arguments.get("filters", {})
            limit = arguments.get("limit", 25)
            order_by = arguments.get("order_by")
            # Find model
            for m in self.schema.node_models:
                if m.label() == label:
                    q = Query().match(m, "n")
                    params: dict[str, Any] = {}
                    if filters:
                        where_parts = []
                        for k, v in filters.items():
                            params[f"n_{k}"] = v
                            where_parts.append(f"n.{k} = $n_{k}")
                        q = q.where(" AND ".join(where_parts))
                    q = q.return_("n")
                    if order_by:
                        q = q.order_by(f"n.{order_by}")
                    q = q.limit(limit)
                    cypher = q.build_cypher()
                    return cypher, params
            return None

        elif tool_name == "find_neighbors":
            label = arguments["label"]
            match_props = arguments["match_properties"]
            rel_type = arguments.get("relationship_type")
            direction = arguments.get("direction", "both")
            limit = arguments.get("limit", 25)
            for m in self.schema.node_models:
                if m.label() == label:
                    return Traversal.neighbors(
                        m, match_props=match_props,
                        rel_type=rel_type, direction=direction, limit=limit,
                    )
            return None

        elif tool_name == "find_path":
            src_label = arguments["source_label"]
            tgt_label = arguments["target_label"]
            src_props = arguments["source_properties"]
            tgt_props = arguments["target_properties"]
            max_depth = arguments.get("max_depth", 5)
            src_model = tgt_model = None
            for m in self.schema.node_models:
                if m.label() == src_label:
                    src_model = m
                if m.label() == tgt_label:
                    tgt_model = m
            if src_model and tgt_model:
                return Traversal.shortest_path(
                    src_model, tgt_model, src_props, tgt_props, max_depth=max_depth,
                )
            return None

        elif tool_name == "get_graph_schema":
            fmt = arguments.get("format", "text")
            if fmt == "markdown":
                return self.schema.to_markdown(), {}
            elif fmt == "json":
                return self.schema.to_json(), {}
            else:
                return self.schema.to_prompt(), {}

        elif tool_name == "bulk_create_nodes":
            label = arguments["label"]
            items = arguments["items"]
            for m in self.schema.node_models:
                if m.label() == label:
                    return BulkOps.bulk_create_nodes(m, items)
            return None

        return None


# ---------------------------------------------------------------------------
# Property Expressions — type-safe query conditions
# ---------------------------------------------------------------------------


class PropExpr:
    """A property expression bound to a variable, enabling type-safe conditions.

    Usage::

        p = NodeRef(Person, "p")
        q = (Query()
             .match(Person, "p")
             .where(p.name == "$name")
             .where(p.age > 18)
             .return_("p"))

    Comparison operators (==, !=, <, <=, >, >=) return Cond objects.
    """

    __slots__ = ("_var", "_prop", "_model")

    def __init__(self, var: str, prop: str, model: Type[NodeModel] | Type[RelationshipModel] | None = None) -> None:
        self._var = var
        self._prop = prop
        self._model = model

    @property
    def ref(self) -> str:
        """The full Cypher reference: 'var.prop'."""
        return f"{self._var}.{self._prop}"

    def __str__(self) -> str:
        return self.ref

    def __repr__(self) -> str:
        return f"PropExpr({self.ref!r})"

    # -- Comparison operators returning Cond --

    def __eq__(self, other: Any) -> Cond:  # type: ignore[override]
        return Cond(self.ref, "=", other)

    def __ne__(self, other: Any) -> Cond:  # type: ignore[override]
        return Cond(self.ref, "<>", other)

    def __lt__(self, other: Any) -> Cond:
        return Cond(self.ref, "<", other)

    def __le__(self, other: Any) -> Cond:
        return Cond(self.ref, "<=", other)

    def __gt__(self, other: Any) -> Cond:
        return Cond(self.ref, ">", other)

    def __ge__(self, other: Any) -> Cond:
        return Cond(self.ref, ">=", other)

    def contains(self, value: Any) -> Cond:
        return Cond(self.ref, "CONTAINS", value)

    def starts_with(self, value: Any) -> Cond:
        return Cond(self.ref, "STARTS WITH", value)

    def ends_with(self, value: Any) -> Cond:
        return Cond(self.ref, "ENDS WITH", value)

    def in_(self, values: list[Any]) -> Cond:
        return Cond(self.ref, "IN", values)

    def is_null(self) -> Cond:
        return Cond(self.ref, "IS NULL")

    def is_not_null(self) -> Cond:
        return Cond(self.ref, "IS NOT NULL")

    def regex(self, pattern: str) -> Cond:
        return Cond(self.ref, "=~", pattern)


class NodeRef:
    """Typed variable reference to a node in a query.

    Creates PropExpr objects for each property via attribute access::

        p = NodeRef(Person, "p")
        p.name   # → PropExpr("p.name")
        p.age    # → PropExpr("p.age")

    Also usable directly in Query methods::

        q = Query().match(p).where(p.name == "$name").return_(p)
    """

    def __init__(self, model: Type[NodeModel], var: str) -> None:
        self._model = model
        self._var = var

    @property
    def model(self) -> Type[NodeModel]:
        return self._model

    @property
    def var(self) -> str:
        return self._var

    def __getattr__(self, name: str) -> PropExpr:
        if name.startswith("_"):
            raise AttributeError(name)
        return PropExpr(self._var, name, self._model)

    def __str__(self) -> str:
        return self._var

    def __repr__(self) -> str:
        return f"NodeRef({self._model.label()!r}, {self._var!r})"


class RelRef:
    """Typed variable reference to a relationship in a query.

    Same as NodeRef but for RelationshipModel::

        r = RelRef(ActedIn, "r")
        r.roles  # → PropExpr("r.roles")
    """

    def __init__(self, model: Type[RelationshipModel], var: str) -> None:
        self._model = model
        self._var = var

    @property
    def model(self) -> Type[RelationshipModel]:
        return self._model

    @property
    def var(self) -> str:
        return self._var

    def __getattr__(self, name: str) -> PropExpr:
        if name.startswith("_"):
            raise AttributeError(name)
        return PropExpr(self._var, name, self._model)

    def __str__(self) -> str:
        return self._var

    def __repr__(self) -> str:
        return f"RelRef({self._model.rel_type()!r}, {self._var!r})"


# ---------------------------------------------------------------------------
# Query Builder extensions for NodeRef/RelRef
# ---------------------------------------------------------------------------

# Patch Query.match/return_ to accept NodeRef
_orig_match = Query.match
_orig_return = Query.return_


def _match_with_ref(
    self: Query,
    model_or_label: Type[NodeModel] | str | NodeRef | None = None,
    var: str | None = None,
    props: dict[str, Any] | None = None,
    *,
    pattern: str | None = None,
) -> Query:
    if isinstance(model_or_label, NodeRef):
        return _orig_match(self, model_or_label.model, model_or_label.var, props, pattern=pattern)
    return _orig_match(self, model_or_label, var, props, pattern=pattern)


def _return_with_ref(
    self: Query,
    *items: str | NodeRef | RelRef | PropExpr,
    distinct: bool = False,
) -> Query:
    resolved = []
    for item in items:
        if isinstance(item, (NodeRef, RelRef)):
            resolved.append(str(item))
        elif isinstance(item, PropExpr):
            resolved.append(item.ref)
        else:
            resolved.append(item)
    return _orig_return(self, *resolved, distinct=distinct)


Query.match = _match_with_ref  # type: ignore[assignment]
Query.return_ = _return_with_ref  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Query History — conversation context for agents
# ---------------------------------------------------------------------------


class QueryHistoryEntry(BaseModel):
    """Single entry in query history."""
    cypher: str
    parameters: dict[str, Any] = {}
    result_count: int = 0
    error: str | None = None
    summary: str = ""


class QueryHistory:
    """Track query history for AI agent conversation context.

    Agents can use this to remember what they've queried, avoid repeating
    queries, and build context-aware follow-ups.

    Usage::

        history = QueryHistory(max_entries=50)
        history.add("MATCH (n:Person) RETURN n", {}, result_count=5)
        context = history.to_context()  # For LLM system prompt
    """

    def __init__(self, max_entries: int = 50) -> None:
        self._entries: list[QueryHistoryEntry] = []
        self._max_entries = max_entries

    def add(
        self,
        cypher: str,
        parameters: dict[str, Any] | None = None,
        result_count: int = 0,
        error: str | None = None,
        summary: str = "",
    ) -> None:
        """Record a query execution."""
        entry = QueryHistoryEntry(
            cypher=cypher,
            parameters=parameters or {},
            result_count=result_count,
            error=error,
            summary=summary,
        )
        self._entries.append(entry)
        if len(self._entries) > self._max_entries:
            self._entries = self._entries[-self._max_entries:]

    def add_from_result(self, result: QueryResult) -> None:
        """Record from a QueryResult object."""
        self.add(
            cypher=result.cypher,
            parameters=result.parameters,
            result_count=result.count,
            error=result.error,
            summary=result.summary,
        )

    @property
    def entries(self) -> list[QueryHistoryEntry]:
        return list(self._entries)

    @property
    def last(self) -> QueryHistoryEntry | None:
        return self._entries[-1] if self._entries else None

    def clear(self) -> None:
        self._entries.clear()

    def to_context(self, last_n: int | None = None) -> str:
        """Generate context string for LLM prompts.

        Shows recent query history so the agent knows what's been tried.
        """
        entries = self._entries[-(last_n or len(self._entries)):]
        if not entries:
            return "No previous queries in this session."
        lines = ["## Previous Queries"]
        for i, e in enumerate(entries, 1):
            status = f"error: {e.error}" if e.error else f"{e.result_count} results"
            lines.append(f"{i}. `{e.cypher}` → {status}")
            if e.summary:
                lines.append(f"   Summary: {e.summary}")
        return "\n".join(lines)

    def to_list(self) -> list[dict[str, Any]]:
        """Serialize history to list of dicts."""
        return [e.model_dump() for e in self._entries]

    def successful_queries(self) -> list[QueryHistoryEntry]:
        """Return only queries that succeeded."""
        return [e for e in self._entries if e.error is None]

    def failed_queries(self) -> list[QueryHistoryEntry]:
        """Return only queries that failed."""
        return [e for e in self._entries if e.error is not None]

    def find_similar(self, cypher: str) -> list[QueryHistoryEntry]:
        """Find history entries with similar Cypher patterns."""
        # Simple substring matching — good enough for agent context
        normalized = cypher.strip().upper()
        results = []
        for e in self._entries:
            if normalized in e.cypher.upper() or e.cypher.upper() in normalized:
                results.append(e)
        return results


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
# AsyncGraphSession
# ---------------------------------------------------------------------------


class AsyncGraphSession:
    """Async version of GraphSession for use in agent frameworks.

    Expects *db* to have an ``execute`` method that is either already async
    or a sync method that will be wrapped.

    Usage::

        async with AsyncGraphSession(db, schema) as session:
            people = await session.query(Person, where={"name": "Alice"})
            await session.create(Person(name="Bob", age=25))
    """

    def __init__(self, db: Any, schema: GraphSchema | None = None) -> None:
        self.db = db
        self.schema = schema
        self._history = QueryHistory()

    @property
    def history(self) -> QueryHistory:
        return self._history

    async def execute(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Execute Cypher query asynchronously."""
        import asyncio
        p = params or {}
        try:
            if inspect.iscoroutinefunction(self.db.execute):
                result = await self.db.execute(cypher, p)
            else:
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, self.db.execute, cypher, p)
            self._history.add(cypher, p, result_count=len(result) if result else 0)
            return result or []
        except Exception as e:
            self._history.add(cypher, p, error=str(e))
            raise

    async def execute_query(self, query: Query) -> list[dict[str, Any]]:
        cypher, params = query.build()
        return await self.execute(cypher, params)

    async def query(
        self,
        model: Type[NodeModel],
        var: str = "n",
        where: dict[str, Any] | None = None,
        limit: int | None = None,
        order_by: str | None = None,
    ) -> list[Any]:
        cypher, params = model.match_cypher(var, where)
        if order_by:
            cypher += f" ORDER BY {order_by}"
        if limit:
            cypher += f" LIMIT {limit}"
        records = await self.execute(cypher, params)
        return model.from_records(records, var)

    async def create(self, instance: NodeModel, var: str = "n") -> list[dict[str, Any]]:
        cypher, params = instance.to_create_cypher(var)
        return await self.execute(cypher, params)

    async def merge(
        self,
        instance: NodeModel,
        var: str = "n",
        merge_keys: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        cypher, params = instance.to_merge_cypher(var, merge_keys)
        return await self.execute(cypher, params)

    async def bulk_create(
        self, model: Type[NodeModel], items: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        cypher, params = BulkOps.bulk_create_nodes(model, items)
        return await self.execute(cypher, params)

    async def bulk_merge(
        self,
        model: Type[NodeModel],
        items: list[dict[str, Any]],
        merge_keys: list[str],
    ) -> list[dict[str, Any]]:
        cypher, params = BulkOps.bulk_merge_nodes(model, items, merge_keys)
        return await self.execute(cypher, params)

    async def neighbors(
        self,
        model: Type[NodeModel],
        match_props: dict[str, Any],
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        cypher, params = Traversal.neighbors(model, match_props=match_props, **kwargs)
        return await self.execute(cypher, params)

    async def __aenter__(self) -> AsyncGraphSession:
        return self

    async def __aexit__(self, *args: Any) -> None:
        if hasattr(self.db, "close"):
            if hasattr(self.db.close, "__call__"):
                import asyncio
                if inspect.iscoroutinefunction(self.db.close):
                    await self.db.close()
                else:
                    self.db.close()


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


# ---------------------------------------------------------------------------
# Cypher Function Wrappers
# ---------------------------------------------------------------------------


class CypherFn:
    """Type-safe wrappers for common Cypher functions.

    Use in Query builder return/where clauses::

        p = NodeRef(Person, "p")
        q = (Query()
             .match(p)
             .return_(CypherFn.count(p), CypherFn.avg("p.age")))
    """

    # -- Aggregation --

    @staticmethod
    def count(expr: str | NodeRef | RelRef | PropExpr = "*") -> str:
        if isinstance(expr, (NodeRef, RelRef)):
            return f"count({expr.var})"
        if isinstance(expr, PropExpr):
            return f"count({expr.ref})"
        return f"count({expr})"

    @staticmethod
    def count_distinct(expr: str | NodeRef | RelRef | PropExpr) -> str:
        if isinstance(expr, (NodeRef, RelRef)):
            return f"count(DISTINCT {expr.var})"
        if isinstance(expr, PropExpr):
            return f"count(DISTINCT {expr.ref})"
        return f"count(DISTINCT {expr})"

    @staticmethod
    def sum(expr: str | PropExpr) -> str:
        ref = expr.ref if isinstance(expr, PropExpr) else expr
        return f"sum({ref})"

    @staticmethod
    def avg(expr: str | PropExpr) -> str:
        ref = expr.ref if isinstance(expr, PropExpr) else expr
        return f"avg({ref})"

    @staticmethod
    def min(expr: str | PropExpr) -> str:
        ref = expr.ref if isinstance(expr, PropExpr) else expr
        return f"min({ref})"

    @staticmethod
    def max(expr: str | PropExpr) -> str:
        ref = expr.ref if isinstance(expr, PropExpr) else expr
        return f"max({ref})"

    @staticmethod
    def collect(expr: str | PropExpr | NodeRef) -> str:
        if isinstance(expr, NodeRef):
            return f"collect({expr.var})"
        ref = expr.ref if isinstance(expr, PropExpr) else expr
        return f"collect({ref})"

    @staticmethod
    def collect_distinct(expr: str | PropExpr) -> str:
        ref = expr.ref if isinstance(expr, PropExpr) else expr
        return f"collect(DISTINCT {ref})"

    # -- Scalar --

    @staticmethod
    def coalesce(*exprs: str | PropExpr) -> str:
        parts = [e.ref if isinstance(e, PropExpr) else e for e in exprs]
        return f"coalesce({', '.join(parts)})"

    @staticmethod
    def head(expr: str) -> str:
        return f"head({expr})"

    @staticmethod
    def last(expr: str) -> str:
        return f"last({expr})"

    @staticmethod
    def size(expr: str | PropExpr) -> str:
        ref = expr.ref if isinstance(expr, PropExpr) else expr
        return f"size({ref})"

    @staticmethod
    def length(expr: str) -> str:
        return f"length({expr})"

    @staticmethod
    def type(expr: str | RelRef) -> str:
        ref = expr.var if isinstance(expr, RelRef) else expr
        return f"type({ref})"

    @staticmethod
    def labels(expr: str | NodeRef) -> str:
        ref = expr.var if isinstance(expr, NodeRef) else expr
        return f"labels({ref})"

    @staticmethod
    def id(expr: str | NodeRef | RelRef) -> str:
        if isinstance(expr, (NodeRef, RelRef)):
            return f"id({expr.var})"
        return f"id({expr})"

    @staticmethod
    def element_id(expr: str | NodeRef | RelRef) -> str:
        if isinstance(expr, (NodeRef, RelRef)):
            return f"elementId({expr.var})"
        return f"elementId({expr})"

    # -- String --

    @staticmethod
    def to_lower(expr: str | PropExpr) -> str:
        ref = expr.ref if isinstance(expr, PropExpr) else expr
        return f"toLower({ref})"

    @staticmethod
    def to_upper(expr: str | PropExpr) -> str:
        ref = expr.ref if isinstance(expr, PropExpr) else expr
        return f"toUpper({ref})"

    @staticmethod
    def trim(expr: str | PropExpr) -> str:
        ref = expr.ref if isinstance(expr, PropExpr) else expr
        return f"trim({ref})"

    @staticmethod
    def replace(expr: str | PropExpr, search: str, replacement: str) -> str:
        ref = expr.ref if isinstance(expr, PropExpr) else expr
        return f"replace({ref}, '{search}', '{replacement}')"

    @staticmethod
    def substring(expr: str | PropExpr, start: int, length: int | None = None) -> str:
        ref = expr.ref if isinstance(expr, PropExpr) else expr
        if length is not None:
            return f"substring({ref}, {start}, {length})"
        return f"substring({ref}, {start})"

    # -- Math --

    @staticmethod
    def abs(expr: str | PropExpr) -> str:
        ref = expr.ref if isinstance(expr, PropExpr) else expr
        return f"abs({ref})"

    @staticmethod
    def ceil(expr: str | PropExpr) -> str:
        ref = expr.ref if isinstance(expr, PropExpr) else expr
        return f"ceil({ref})"

    @staticmethod
    def floor(expr: str | PropExpr) -> str:
        ref = expr.ref if isinstance(expr, PropExpr) else expr
        return f"floor({ref})"

    @staticmethod
    def round(expr: str | PropExpr) -> str:
        ref = expr.ref if isinstance(expr, PropExpr) else expr
        return f"round({ref})"

    # -- Temporal --

    @staticmethod
    def timestamp() -> str:
        return "timestamp()"

    @staticmethod
    def date(expr: str | None = None) -> str:
        return f"date({expr})" if expr else "date()"

    @staticmethod
    def datetime(expr: str | None = None) -> str:
        return f"datetime({expr})" if expr else "datetime()"

    # -- Aliasing helper --

    @staticmethod
    def as_(expr: str, alias: str) -> str:
        """Wrap expression with AS alias: 'count(n) AS total'."""
        return f"{expr} AS {alias}"


# Convenient shorthand
fn = CypherFn


# ---------------------------------------------------------------------------
# PathBuilder — fluent multi-hop path construction
# ---------------------------------------------------------------------------


class PathBuilder:
    """Build multi-hop path patterns for MATCH clauses.

    Usage::

        path = (PathBuilder(Person, "actor")
                .rel(ActedIn, "r")
                .to(Movie, "movie")
                .rel("DIRECTED", direction="in")
                .to(Person, "director"))
        q = Query().match(pattern=path.build()).return_("actor", "director")

    Generates::

        (actor:Person)-[r:ACTED_IN]->(movie:Movie)<-[:DIRECTED]-(director:Person)
    """

    def __init__(
        self,
        model_or_label: Type[NodeModel] | str | None = None,
        var: str | None = None,
        props: dict[str, Any] | None = None,
    ) -> None:
        self._segments: list[str] = []
        self._params: dict[str, Any] = {}
        self._param_counter = 0
        # Start node
        self._segments.append(self._node_str(model_or_label, var, props))

    def _next_param(self, prefix: str = "p") -> str:
        self._param_counter += 1
        return f"{prefix}_{self._param_counter}"

    def _node_str(
        self,
        model_or_label: Type[NodeModel] | str | None,
        var: str | None = None,
        props: dict[str, Any] | None = None,
    ) -> str:
        label_str = ""
        if model_or_label is not None:
            if isinstance(model_or_label, str):
                label_str = f":{model_or_label}"
            elif hasattr(model_or_label, 'labels') and len(model_or_label.labels()) > 1:
                label_str = model_or_label.labels_cypher()
            else:
                label_str = f":{model_or_label.label()}"
        var_str = var or ""
        prop_str = ""
        if props:
            parts = []
            for k, v in props.items():
                pname = self._next_param(var or "n")
                self._params[pname] = v
                parts.append(f"{k}: ${pname}")
            prop_str = " {" + ", ".join(parts) + "}"
        return f"({var_str}{label_str}{prop_str})"

    def _rel_str(
        self,
        model_or_type: Type[RelationshipModel] | str | None = None,
        var: str | None = None,
        props: dict[str, Any] | None = None,
        direction: str = "out",
        min_hops: int | None = None,
        max_hops: int | None = None,
    ) -> str:
        rel_type = ""
        if model_or_type is not None:
            if isinstance(model_or_type, str):
                rel_type = model_or_type
            else:
                rel_type = model_or_type.rel_type()
        var_str = var or ""
        type_str = f":{rel_type}" if rel_type else ""
        prop_str = ""
        if props:
            parts = []
            for k, v in props.items():
                pname = self._next_param(var or "r")
                self._params[pname] = v
                parts.append(f"{k}: ${pname}")
            prop_str = " {" + ", ".join(parts) + "}"
        range_str = ""
        if min_hops is not None or max_hops is not None:
            mn = str(min_hops) if min_hops is not None else ""
            mx = str(max_hops) if max_hops is not None else ""
            range_str = f"*{mn}..{mx}"
        inner = f"[{var_str}{type_str}{range_str}{prop_str}]"
        if direction == "out":
            return f"-{inner}->"
        elif direction == "in":
            return f"<-{inner}-"
        else:
            return f"-{inner}-"

    def rel(
        self,
        model_or_type: Type[RelationshipModel] | str | None = None,
        var: str | None = None,
        props: dict[str, Any] | None = None,
        direction: str = "out",
        min_hops: int | None = None,
        max_hops: int | None = None,
    ) -> PathBuilder:
        """Add a relationship segment."""
        self._segments.append(
            self._rel_str(model_or_type, var, props, direction, min_hops, max_hops)
        )
        return self

    def to(
        self,
        model_or_label: Type[NodeModel] | str | None = None,
        var: str | None = None,
        props: dict[str, Any] | None = None,
    ) -> PathBuilder:
        """Add a target node segment."""
        self._segments.append(self._node_str(model_or_label, var, props))
        return self

    def build(self) -> str:
        """Render the path pattern string."""
        return "".join(self._segments)

    @property
    def params(self) -> dict[str, Any]:
        """Parameters collected from property maps in the path."""
        return dict(self._params)

    def __str__(self) -> str:
        return self.build()

    def __repr__(self) -> str:
        return f"PathBuilder({self.build()!r})"

    def to_query(self) -> Query:
        """Convert to a Query with this path as a MATCH clause."""
        q = Query().match(pattern=self.build())
        q._params.update(self._params)
        return q


# ---------------------------------------------------------------------------
# Repository — typed CRUD for a single model
# ---------------------------------------------------------------------------


class Repository:
    """Typed repository for a single NodeModel with CRUD operations.

    Usage::

        repo = Repository(Person, db)
        alice = repo.find_one(name="Alice")
        all_people = repo.find_all(limit=100)
        count = repo.count()
        repo.create(Person(name="Bob", age=25))
        repo.update({"name": "Alice"}, {"age": 31})
        repo.delete(name="Alice")
    """

    def __init__(
        self,
        model: Type[NodeModel],
        db: Any,
        var: str = "n",
    ) -> None:
        self.model = model
        self.db = db
        self.var = var

    def _execute(self, cypher: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        return self.db.execute(cypher, params)

    def find_all(
        self,
        limit: int | None = None,
        order_by: str | None = None,
        skip: int | None = None,
    ) -> list[Any]:
        """Return all nodes of this type."""
        cypher = f"MATCH ({self.var}:{self.model.label()}) RETURN {self.var}"
        if order_by:
            # Strip DESC/ASC suffix for validation, allow property names only
            prop_name = order_by.split()[0].rstrip(",")
            valid_props = self.model.property_names()
            if prop_name not in valid_props:
                raise ValueError(
                    f"order_by property '{prop_name}' not found in {self.model.label()} "
                    f"properties: {valid_props}"
                )
            cypher += f" ORDER BY {self.var}.{order_by}"
        if skip:
            cypher += f" SKIP {skip}"
        if limit:
            cypher += f" LIMIT {limit}"
        records = self._execute(cypher, {})
        return self.model.from_records(records, self.var)

    def find_by(self, limit: int | None = None, **props: Any) -> list[Any]:
        """Find nodes matching property filters."""
        params = {f"{self.var}_{k}": v for k, v in props.items()}
        where = " AND ".join(f"{self.var}.{k} = ${self.var}_{k}" for k in props)
        cypher = f"MATCH ({self.var}:{self.model.label()}) WHERE {where} RETURN {self.var}"
        if limit:
            cypher += f" LIMIT {limit}"
        records = self._execute(cypher, params)
        return self.model.from_records(records, self.var)

    def find_one(self, **props: Any) -> Any | None:
        """Find a single node matching filters. Returns None if not found."""
        results = self.find_by(limit=1, **props)
        return results[0] if results else None

    def exists(self, **props: Any) -> bool:
        """Check if a node matching filters exists."""
        params = {f"{self.var}_{k}": v for k, v in props.items()}
        where = " AND ".join(f"{self.var}.{k} = ${self.var}_{k}" for k in props)
        cypher = (
            f"MATCH ({self.var}:{self.model.label()}) WHERE {where} "
            f"RETURN count({self.var}) > 0 AS exists"
        )
        records = self._execute(cypher, params)
        if records:
            return bool(records[0].get("exists", False))
        return False

    def count(self, **props: Any) -> int:
        """Count nodes, optionally filtered."""
        params: dict[str, Any] = {}
        cypher = f"MATCH ({self.var}:{self.model.label()})"
        if props:
            params = {f"{self.var}_{k}": v for k, v in props.items()}
            where = " AND ".join(f"{self.var}.{k} = ${self.var}_{k}" for k in props)
            cypher += f" WHERE {where}"
        cypher += f" RETURN count({self.var}) AS count"
        records = self._execute(cypher, params)
        if records:
            return int(records[0].get("count", 0))
        return 0

    def create(self, instance: NodeModel) -> list[dict[str, Any]]:
        """Create a node."""
        cypher, params = instance.to_create_cypher(self.var)
        return self._execute(cypher, params)

    def create_many(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Bulk create nodes."""
        cypher, params = BulkOps.bulk_create_nodes(self.model, items, self.var)
        return self._execute(cypher, params)

    def merge(
        self,
        instance: NodeModel,
        merge_keys: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Merge (upsert) a node."""
        cypher, params = instance.to_merge_cypher(self.var, merge_keys)
        return self._execute(cypher, params)

    def merge_many(
        self, items: list[dict[str, Any]], merge_keys: list[str]
    ) -> list[dict[str, Any]]:
        """Bulk merge nodes."""
        cypher, params = BulkOps.bulk_merge_nodes(self.model, items, merge_keys, self.var)
        return self._execute(cypher, params)

    def update(self, match_props: dict[str, Any], set_props: dict[str, Any]) -> list[dict[str, Any]]:
        """Update nodes matching filters with new property values."""
        params: dict[str, Any] = {}
        where_parts = []
        for k, v in match_props.items():
            pname = f"match_{k}"
            params[pname] = v
            where_parts.append(f"{self.var}.{k} = ${pname}")
        set_parts = []
        for k, v in set_props.items():
            pname = f"set_{k}"
            params[pname] = v
            set_parts.append(f"{self.var}.{k} = ${pname}")
        cypher = (
            f"MATCH ({self.var}:{self.model.label()}) "
            f"WHERE {' AND '.join(where_parts)} "
            f"SET {', '.join(set_parts)} "
            f"RETURN {self.var}"
        )
        return self._execute(cypher, params)

    def delete(self, detach: bool = True, **props: Any) -> list[dict[str, Any]]:
        """Delete nodes matching filters."""
        params = {f"{self.var}_{k}": v for k, v in props.items()}
        where = " AND ".join(f"{self.var}.{k} = ${self.var}_{k}" for k in props)
        delete_kw = "DETACH DELETE" if detach else "DELETE"
        cypher = (
            f"MATCH ({self.var}:{self.model.label()}) "
            f"WHERE {where} {delete_kw} {self.var}"
        )
        return self._execute(cypher, params)

    def delete_all(self, detach: bool = True) -> list[dict[str, Any]]:
        """Delete all nodes of this type."""
        delete_kw = "DETACH DELETE" if detach else "DELETE"
        cypher = f"MATCH ({self.var}:{self.model.label()}) {delete_kw} {self.var}"
        return self._execute(cypher, {})

    def query(self) -> Query:
        """Start a Query builder pre-configured with MATCH for this model."""
        return Query().match(self.model, self.var)
