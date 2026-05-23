"""Base ORM classes: NodeModel, RelationshipModel, metaclasses, registries, factory functions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import (
    Any,
    ClassVar,
    Sequence,
    Type,
)

from pydantic import BaseModel, ConfigDict


# ---------------------------------------------------------------------------
# Vector property descriptor
# ---------------------------------------------------------------------------


@dataclass
class VectorProperty:
    """Descriptor for a Neo4j vector index on a node property.

    Usage::

        class Document(NodeModel):
            __label__ = "Document"
            __vector_indexes__ = {
                "embedding": VectorProperty(dimensions=1536, similarity="cosine"),
            }
            embedding: list[float] = []
    """

    _VALID_SIMILARITIES = frozenset({"cosine", "euclidean"})

    dimensions: int
    similarity: str = "cosine"

    def __post_init__(self) -> None:
        if self.similarity not in self._VALID_SIMILARITIES:
            raise ValueError(
                f"Invalid similarity {self.similarity!r}, must be one of: {', '.join(sorted(self._VALID_SIMILARITIES))}"
            )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_NODE_REGISTRY: dict[str, Type[NodeModel]] = {}
_REL_REGISTRY: dict[str, Type[RelationshipModel]] = {}


# ---------------------------------------------------------------------------
# NodeModel
# ---------------------------------------------------------------------------


class _NodeMeta(type(BaseModel)):
    """Metaclass that auto-registers NodeModel subclasses."""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)

    def __init__(self, name: str, bases: tuple, namespace: dict, **kwargs: Any) -> None:
        super().__init__(name, bases, namespace, **kwargs)
        if name == "NodeModel":
            return
        if any(b.__name__ == "NodeModel" or hasattr(b, "__label__") for b in bases):
            label = getattr(self, "__label__", name)
            self.__label__ = label  # type: ignore[attr-defined]
            _NODE_REGISTRY[label] = self  # type: ignore[arg-type]


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
    __vector_indexes__: ClassVar[dict[str, VectorProperty]] = {}

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

    def __init__(self, name: str, bases: tuple, namespace: dict, **kwargs: Any) -> None:
        super().__init__(name, bases, namespace, **kwargs)
        if name == "RelationshipModel":
            return
        if any(b.__name__ == "RelationshipModel" or hasattr(b, "__rel_type__") for b in bases):
            rel_type = getattr(self, "__rel_type__", _to_upper_snake(name))
            self.__rel_type__ = rel_type  # type: ignore[attr-defined]
            _REL_REGISTRY[rel_type] = self  # type: ignore[arg-type]


_CAMEL_RE1 = re.compile(r"([A-Z]+)([A-Z][a-z])")
_CAMEL_RE2 = re.compile(r"([a-z\d])([A-Z])")


def _to_upper_snake(name: str) -> str:
    """CamelCase → UPPER_SNAKE_CASE."""
    s = _CAMEL_RE1.sub(r"\1_\2", name)
    s = _CAMEL_RE2.sub(r"\1_\2", s)
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
