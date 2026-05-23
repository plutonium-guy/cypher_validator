"""Query builder, conditions, expressions, path builder, history."""

from __future__ import annotations

import json
from enum import Enum
from typing import (
    Any,
    Type,
)

from pydantic import BaseModel, ConfigDict

from cypher_validator.models.orm import NodeModel, RelationshipModel


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
