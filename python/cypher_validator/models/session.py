"""GraphSession, AsyncGraphSession, Repository, Traversal, BulkOps."""

from __future__ import annotations

import inspect
from typing import (
    Any,
    Sequence,
    Type,
)

from cypher_validator.models.orm import NodeModel, RelationshipModel
from cypher_validator.models.query import Query, QueryHistory
from cypher_validator.models.schema import GraphSchema, SchemaDDL


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

    @staticmethod
    def shortest_path_by_id(
        src_id: str,
        tgt_id: str,
        max_depth: int = 5,
        rel_type: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Find shortest path between two nodes by element ID."""
        params = {"src_id": src_id, "tgt_id": tgt_id}
        rel_spec = f":{rel_type}" if rel_type else ""
        cypher = (
            f"MATCH (src), (tgt), "
            f"path = shortestPath((src)-[{rel_spec}*..{max_depth}]-(tgt)) "
            f"WHERE elementId(src) = $src_id AND elementId(tgt) = $tgt_id "
            f"RETURN path, length(path) AS distance"
        )
        return cypher, params

    @staticmethod
    def common_neighbors_by_id(
        src_id: str,
        tgt_id: str,
        rel_type: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Find common neighbors of two nodes by element ID."""
        params = {"src_id": src_id, "tgt_id": tgt_id}
        rtype = f":{rel_type}" if rel_type else ""
        cypher = (
            f"MATCH (a)-[{rtype}]-(common)-[{rtype}]-(b) "
            f"WHERE elementId(a) = $src_id AND elementId(b) = $tgt_id "
            f"AND a <> b AND common <> a AND common <> b "
            f"RETURN DISTINCT common"
        )
        return cypher, params

    @staticmethod
    def neighbors_by_id(
        element_id: str,
        rel_type: str | None = None,
        direction: str = "both",
        limit: int | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Find neighbors of a node by element ID."""
        _validate_direction(direction)
        params = {"eid": element_id}
        rtype = f":{rel_type}" if rel_type else ""
        if direction == "out":
            rel_pat = f"-[r{rtype}]->"
        elif direction == "in":
            rel_pat = f"<-[r{rtype}]-"
        else:
            rel_pat = f"-[r{rtype}]-"
        cypher = (
            f"MATCH (n){rel_pat}(neighbor) "
            f"WHERE elementId(n) = $eid "
            f"RETURN n, r, neighbor"
        )
        if limit:
            cypher += f" LIMIT {limit}"
        return cypher, params

    @staticmethod
    def subgraph_by_id(
        element_id: str,
        depth: int = 2,
    ) -> tuple[str, dict[str, Any]]:
        """Extract a subgraph around a node by element ID."""
        params = {"eid": element_id}
        cypher = (
            f"MATCH path = (n)-[*1..{depth}]-(connected) "
            f"WHERE elementId(n) = $eid "
            f"RETURN path"
        )
        return cypher, params


# ---------------------------------------------------------------------------
# Bulk Operations
# ---------------------------------------------------------------------------


_MATCH_OPS = {"eq", "starts_with", "contains"}


def _validate_match_op(op: str, param_name: str) -> None:
    if op not in _MATCH_OPS:
        raise ValueError(
            f"Invalid match operator '{op}' for {param_name}. "
            f"Must be one of: {', '.join(sorted(_MATCH_OPS))}"
        )


def _build_match_pattern(
    op: str, var: str, label: str, prop: str, item_key: str,
) -> tuple[str, str]:
    """Return (pattern, where_fragment) for a match operator."""
    if op == "eq":
        return f"({var}:{label} {{{prop}: item.{item_key}}})", ""
    elif op == "starts_with":
        return f"({var}:{label})", f"{var}.{prop} STARTS WITH item.{item_key}"
    else:  # contains
        return f"({var}:{label})", f"{var}.{prop} CONTAINS item.{item_key}"


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
        src_match: str = "eq",
        tgt_match: str = "eq",
    ) -> tuple[str, dict[str, Any]]:
        """UNWIND-based bulk CREATE for relationships.

        Each item dict should contain *src_key* and *tgt_key* to match
        source/target nodes, plus any relationship properties.

        *src_match* and *tgt_match* control the match operator:
        ``"eq"`` (default), ``"starts_with"``, or ``"contains"``.

        Example::

            cypher, params = BulkOps.bulk_create_relationships(
                ActedIn,
                [{"src_name": "Alice", "tgt_title": "Matrix", "roles": ["Trinity"]}],
                src_key="src_name", tgt_key="tgt_title",
            )
        """
        _validate_match_op(src_match, "src_match")
        _validate_match_op(tgt_match, "tgt_match")
        params = {"batch": items}
        src_label = rel_model.source_label()
        tgt_label = rel_model.target_label()
        rel_type = rel_model.rel_type()
        src_prop = src_key.replace("src_", "")
        tgt_prop = tgt_key.replace("tgt_", "")
        rel_props = rel_model.property_names()
        prop_str = ""
        if rel_props:
            prop_str = " {" + ", ".join(f"{k}: item.{k}" for k in rel_props) + "}"
        src_pattern, src_where = _build_match_pattern(src_match, "a", src_label, src_prop, src_key)
        tgt_pattern, tgt_where = _build_match_pattern(tgt_match, "b", tgt_label, tgt_prop, tgt_key)
        where_parts = [w for w in [src_where, tgt_where] if w]
        where_clause = f" WHERE {' AND '.join(where_parts)}" if where_parts else ""
        cypher = (
            f"UNWIND $batch AS item "
            f"MATCH {src_pattern}, {tgt_pattern}{where_clause} "
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
        src_match: str = "eq",
        tgt_match: str = "eq",
    ) -> tuple[str, dict[str, Any]]:
        """UNWIND-based bulk MERGE for relationships.

        *src_match* and *tgt_match* control the match operator:
        ``"eq"`` (default), ``"starts_with"``, or ``"contains"``.
        """
        _validate_match_op(src_match, "src_match")
        _validate_match_op(tgt_match, "tgt_match")
        params = {"batch": items}
        src_label = rel_model.source_label()
        tgt_label = rel_model.target_label()
        rel_type = rel_model.rel_type()
        src_prop = src_key.replace("src_", "")
        tgt_prop = tgt_key.replace("tgt_", "")
        rel_props = rel_model.property_names()
        src_pattern, src_where = _build_match_pattern(src_match, "a", src_label, src_prop, src_key)
        tgt_pattern, tgt_where = _build_match_pattern(tgt_match, "b", tgt_label, tgt_prop, tgt_key)
        where_parts = [w for w in [src_where, tgt_where] if w]
        where_clause = f" WHERE {' AND '.join(where_parts)}" if where_parts else ""
        cypher = (
            f"UNWIND $batch AS item "
            f"MATCH {src_pattern}, {tgt_pattern}{where_clause} "
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

    def bulk_create_relationships(
        self,
        rel_model: Type[RelationshipModel],
        items: list[dict[str, Any]],
        src_key: str,
        tgt_key: str,
        src_match: str = "eq",
        tgt_match: str = "eq",
    ) -> list[dict[str, Any]]:
        """Bulk create relationships using UNWIND."""
        cypher, params = BulkOps.bulk_create_relationships(
            rel_model, items, src_key, tgt_key, src_match, tgt_match
        )
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

    def vector_search(
        self,
        model: Type[NodeModel],
        index_property: str,
        query_vector: list[float],
        top_k: int = 10,
    ) -> list[Any]:
        """Vector similarity search using a pre-built vector index."""
        label = model.label()
        index_name = f"idx_{label.lower()}_{index_property}_vector"
        q = (Query()
             .vector_search(index_name, query_vector, top_k)
             .return_("node", "score"))
        cypher, params = q.build()
        records = self.execute(cypher, params)
        return [{"node": model.from_record(r, key="node"), "score": r["score"]} for r in records]

    def semantic_search(
        self,
        model: Type[NodeModel],
        index_property: str,
        query: str,
        embedding_fn: Any,
        top_k: int = 10,
    ) -> list[Any]:
        """Embed a text query and run vector similarity search."""
        vector = embedding_fn(query)
        return self.vector_search(model, index_property, vector, top_k)

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

    async def vector_search(
        self,
        model: Type[NodeModel],
        index_property: str,
        query_vector: list[float],
        top_k: int = 10,
    ) -> list[Any]:
        """Async vector similarity search using a pre-built vector index."""
        label = model.label()
        index_name = f"idx_{label.lower()}_{index_property}_vector"
        q = (Query()
             .vector_search(index_name, query_vector, top_k)
             .return_("node", "score"))
        cypher, params = q.build()
        records = await self.execute(cypher, params)
        return [{"node": model.from_record(r, key="node"), "score": r["score"]} for r in records]

    async def semantic_search(
        self,
        model: Type[NodeModel],
        index_property: str,
        query: str,
        embedding_fn: Any,
        top_k: int = 10,
    ) -> list[Any]:
        """Async: embed a text query and run vector similarity search."""
        vector = embedding_fn(query)
        return await self.vector_search(model, index_property, vector, top_k)

    async def __aenter__(self) -> AsyncGraphSession:
        return self

    async def __aexit__(self, *_args: Any) -> None:
        if hasattr(self.db, "close"):
            if hasattr(self.db.close, "__call__"):
                if inspect.iscoroutinefunction(self.db.close):
                    await self.db.close()
                else:
                    self.db.close()


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

    def find_by_id(self, element_id: str) -> Any | None:
        """Find a node by Neo4j element ID."""
        cypher = (
            f"MATCH ({self.var}:{self.model.label()}) "
            f"WHERE elementId({self.var}) = $eid "
            f"RETURN {self.var}"
        )
        records = self._execute(cypher, {"eid": element_id})
        results = self.model.from_records(records, self.var)
        return results[0] if results else None

    def update_by_id(self, element_id: str, set_props: dict[str, Any]) -> list[dict[str, Any]]:
        """Update a node by element ID."""
        params: dict[str, Any] = {"eid": element_id}
        set_parts = []
        for k, v in set_props.items():
            pname = f"set_{k}"
            params[pname] = v
            set_parts.append(f"{self.var}.{k} = ${pname}")
        cypher = (
            f"MATCH ({self.var}:{self.model.label()}) "
            f"WHERE elementId({self.var}) = $eid "
            f"SET {', '.join(set_parts)} "
            f"RETURN {self.var}"
        )
        return self._execute(cypher, params)

    def delete_by_id(self, element_id: str, detach: bool = True) -> list[dict[str, Any]]:
        """Delete a node by element ID."""
        delete_kw = "DETACH DELETE" if detach else "DELETE"
        cypher = (
            f"MATCH ({self.var}:{self.model.label()}) "
            f"WHERE elementId({self.var}) = $eid "
            f"{delete_kw} {self.var}"
        )
        return self._execute(cypher, {"eid": element_id})

    def query(self) -> Query:
        """Start a Query builder pre-configured with MATCH for this model."""
        return Query().match(self.model, self.var)
