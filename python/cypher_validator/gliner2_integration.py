"""
GLiNER2 relation extraction  →  Cypher query generation  →  optional Neo4j execution.

Usage
-----
Low-level converter (no ML model needed)::

    from cypher_validator import RelationToCypherConverter

    results = {
        "relation_extraction": {
            "works_for": [("John", "Apple Inc.")],
            "lives_in":  [("John", "San Francisco")],
        }
    }
    converter = RelationToCypherConverter()
    print(converter.convert(results, mode="merge"))

End-to-end pipeline (Cypher generation only)::

    from cypher_validator import NLToCypher

    pipeline = NLToCypher.from_pretrained("fastino/gliner2-large-v1", schema=schema)
    cypher = pipeline(
        "John works for Apple Inc. and lives in San Francisco.",
        ["works_for", "lives_in"],
        mode="create",
    )

End-to-end pipeline with Neo4j execution::

    from cypher_validator import NLToCypher, Neo4jDatabase

    db = Neo4jDatabase("bolt://localhost:7687", "neo4j", "password")
    pipeline = NLToCypher.from_pretrained(
        "fastino/gliner2-large-v1",
        schema=schema,
        db=db,
    )
    cypher, results = pipeline(
        "John works for Apple Inc.",
        ["works_for"],
        mode="create",
        execute=True,
    )
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple, Union


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_cypher_rel_type(rel_type: str) -> str:
    """Convert any-case relation type to UPPER_SNAKE_CASE (Cypher convention)."""
    return rel_type.upper()


def _inline_params(cypher: str, params: Dict[str, Any]) -> str:
    """Substitute ``$placeholder`` tokens in *cypher* with their literal values.

    Produces a human-readable Cypher string with actual entity values instead
    of parameter references.  String values are double-quoted and internal
    double-quotes / backslashes are escaped.  Non-string scalars (int, float,
    bool, None) are rendered without quotes.

    The substitution is applied longest-key-first to avoid partial replacement
    (e.g. ``$a10_val`` must be replaced before ``$a1_val``).
    """
    result = cypher
    for key in sorted(params.keys(), key=len, reverse=True):
        val = params[key]
        if val is None:
            inline = "null"
        elif isinstance(val, bool):
            inline = "true" if val else "false"
        elif isinstance(val, (int, float)):
            inline = str(val)
        else:
            escaped = str(val).replace("\\", "\\\\").replace('"', '\\"')
            inline = f'"{escaped}"'
        result = result.replace(f"${key}", inline)
    return result


# ---------------------------------------------------------------------------
# Neo4jDatabase
# ---------------------------------------------------------------------------

class Neo4jDatabase:
    """Thin wrapper around the Neo4j Python driver for executing Cypher queries.

    Requires the ``neo4j`` package::

        pip install neo4j

    Can be used as a context manager::

        with Neo4jDatabase("bolt://localhost:7687", "neo4j", "password") as db:
            results = db.execute("MATCH (n:Person) RETURN n LIMIT 5")

    Or directly passed to :class:`NLToCypher` to enable database-aware execution::

        db = Neo4jDatabase("bolt://localhost:7687", "neo4j", "password")
        pipeline = NLToCypher.from_pretrained("fastino/gliner2-large-v1", db=db)
        cypher, results = pipeline(
            "John works for Apple Inc.",
            ["works_for"],
            mode="create",
            execute=True,
        )

    Parameters
    ----------
    uri:
        Bolt or neo4j URI, e.g. ``"bolt://localhost:7687"`` or
        ``"neo4j+s://xxx.databases.neo4j.io"``.
    username:
        Neo4j username (default: ``"neo4j"``).
    password:
        Neo4j password.
    database:
        Target database name (default: ``"neo4j"``).

    Raises
    ------
    ImportError
        If the ``neo4j`` package is not installed.
    """

    def __init__(
        self,
        uri: str,
        username: str,
        password: str,
        database: str = "neo4j",
    ) -> None:
        try:
            from neo4j import GraphDatabase  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "The 'neo4j' package is required for database execution.\n"
                "Install it with: pip install neo4j"
            ) from exc

        self._driver = GraphDatabase.driver(uri, auth=(username, password))
        self._database = database

    # ------------------------------------------------------------------

    def execute(
        self,
        cypher: str,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Execute a Cypher query and return results as a list of record dicts.

        Parameters
        ----------
        cypher:
            Cypher query string to execute.
        parameters:
            Optional query parameters (e.g. ``{"name": "Alice"}`` for
            ``WHERE n.name = $name``).

        Returns
        -------
        list[dict]
            One dict per returned record, keyed by the ``RETURN`` aliases.
            Empty list when the query returns no rows (e.g. a bare ``CREATE``).
        """
        with self._driver.session(database=self._database) as session:
            result = session.run(cypher, parameters or {})
            return [dict(record) for record in result]

    def introspect_schema(self, sample_limit: int = 1000) -> "Any":
        """Discover the graph schema by inspecting the live database.

        Tries the built-in ``db.schema.nodeTypeProperties()`` and
        ``db.schema.relTypeProperties()`` procedures first (Neo4j 4.3+).
        Falls back to sampling existing nodes and relationships when those
        procedures are unavailable (older Neo4j, Memgraph, etc.).

        Parameters
        ----------
        sample_limit:
            Maximum number of node/relationship rows to sample in the
            fallback path (default: 1000).

        Returns
        -------
        Schema
            A :class:`~cypher_validator.Schema` populated from the live graph.

        Examples
        --------
        ::

            db = Neo4jDatabase("bolt://localhost:7687", "neo4j", "password")
            schema = db.introspect_schema()
            validator = CypherValidator(schema)
        """
        from cypher_validator import Schema

        nodes: dict = {}
        rels: dict = {}

        # ── Attempt 1: built-in schema procedures (Neo4j 4.3+) ──────────
        try:
            rows = self.execute(
                "CALL db.schema.nodeTypeProperties() YIELD nodeType, propertyName"
            )
            for row in rows:
                label = row.get("nodeType", "").strip(":`")
                prop = row.get("propertyName")
                if label:
                    nodes.setdefault(label, [])
                    if prop and prop not in nodes[label]:
                        nodes[label].append(prop)
        except Exception:
            pass  # procedure not available — fall through to sampling

        # ── Attempt 2: fallback sampling for node labels ─────────────────
        if not nodes:
            try:
                rows = self.execute(
                    f"MATCH (n) "
                    f"WITH labels(n) AS lbls, keys(n) AS props "
                    f"UNWIND lbls AS label "
                    f"UNWIND (CASE WHEN size(props) = 0 THEN [null] ELSE props END) AS prop "
                    f"RETURN DISTINCT label, prop "
                    f"ORDER BY label, prop LIMIT {sample_limit}"
                )
                for row in rows:
                    label = row.get("label") or ""
                    prop = row.get("prop")
                    if label:
                        nodes.setdefault(label, [])
                        if prop and prop not in nodes[label]:
                            nodes[label].append(prop)
            except Exception:
                pass

        # ── Attempt 3: built-in rel-type properties procedure ────────────
        try:
            rows = self.execute(
                "CALL db.schema.relTypeProperties() YIELD relType, propertyName"
            )
            for row in rows:
                rel_type = row.get("relType", "").strip(":`")
                prop = row.get("propertyName")
                if rel_type:
                    if rel_type not in rels:
                        rels[rel_type] = ("", "", [])
                    if prop:
                        src, tgt, props = rels[rel_type]
                        if prop not in props:
                            rels[rel_type] = (src, tgt, props + [prop])
        except Exception:
            pass

        # ── Always: discover rel endpoints and missing types via sampling ─
        try:
            rows = self.execute(
                f"MATCH (a)-[r]->(b) "
                f"RETURN DISTINCT "
                f"  type(r) AS rel_type, "
                f"  head(labels(a)) AS src, "
                f"  head(labels(b)) AS tgt "
                f"LIMIT {sample_limit}"
            )
            for row in rows:
                rel_type = row.get("rel_type") or ""
                src = row.get("src") or ""
                tgt = row.get("tgt") or ""
                if rel_type:
                    if rel_type in rels:
                        _, _, props = rels[rel_type]
                        rels[rel_type] = (src, tgt, props)
                    else:
                        rels[rel_type] = (src, tgt, [])
        except Exception:
            pass

        # ── Fallback for rel properties when procedure unavailable ────────
        if not any(props for _, _, props in rels.values()):
            try:
                rows = self.execute(
                    f"MATCH ()-[r]->() "
                    f"WITH type(r) AS rel_type, keys(r) AS props "
                    f"UNWIND (CASE WHEN size(props) = 0 THEN [null] ELSE props END) AS prop "
                    f"RETURN DISTINCT rel_type, prop "
                    f"LIMIT {sample_limit}"
                )
                for row in rows:
                    rel_type = row.get("rel_type") or ""
                    prop = row.get("prop")
                    if rel_type and rel_type in rels and prop:
                        src, tgt, props = rels[rel_type]
                        if prop not in props:
                            rels[rel_type] = (src, tgt, props + [prop])
            except Exception:
                pass

        return Schema(nodes=nodes, relationships=rels)

    def execute_and_format(
        self,
        cypher: str,
        format: str = "markdown",  # noqa: A002
        parameters: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Execute a Cypher query and return results formatted for LLM context.

        Combines :meth:`execute` and
        :func:`~cypher_validator.llm_utils.format_records` in one call.

        Parameters
        ----------
        cypher:
            Cypher query string.
        format:
            Output format — ``"markdown"`` (default), ``"csv"``, ``"json"``,
            or ``"text"``.
        parameters:
            Optional query parameters.

        Returns
        -------
        str
            Formatted result string, or ``""`` when no rows are returned.

        Examples
        --------
        ::

            table = db.execute_and_format(
                "MATCH (p:Person)-[:WORKS_FOR]->(c:Company) RETURN p.name, c.name LIMIT 5"
            )
            # | p.name | c.name    |
            # |--------|-----------|
            # | Alice  | Acme Corp |
        """
        from cypher_validator.llm_utils import format_records

        records = self.execute(cypher, parameters)
        return format_records(records, format=format)

    def execute_many(
        self,
        queries: List[str],
        parameters_list: Optional[List[Optional[Dict[str, Any]]]] = None,
    ) -> List[List[Dict[str, Any]]]:
        """Execute multiple Cypher queries in sequence and return all results.

        Parameters
        ----------
        queries:
            List of Cypher query strings to execute.
        parameters_list:
            Optional list of parameter dicts, one per query.  When *None*
            (or shorter than *queries*), missing entries default to no
            parameters.

        Returns
        -------
        list[list[dict]]
            One inner list per query, each containing the record dicts
            returned by that query.
        """
        params = parameters_list or []
        return [
            self.execute(q, params[i] if i < len(params) else None)
            for i, q in enumerate(queries)
        ]

    def close(self) -> None:
        """Close the underlying driver and release all connections."""
        self._driver.close()

    def __enter__(self) -> "Neo4jDatabase":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"Neo4jDatabase(database={self._database!r})"


# ---------------------------------------------------------------------------
# RelationToCypherConverter
# ---------------------------------------------------------------------------

class RelationToCypherConverter:
    """Convert GLiNER2 relation-extraction output to a Cypher query.

    Works with any dict matching the GLiNER2 output schema::

        {
            "relation_extraction": {
                "works_for": [("John", "Apple Inc.")],
                "lives_in":  [("John", "San Francisco")],
                "founded":   [],   # requested but not found
            }
        }

    Three Cypher generation modes are supported via :meth:`convert`:

    * ``"match"``  — ``MATCH … WHERE …`` (read, find existing nodes)
    * ``"merge"``  — ``MERGE …`` (upsert nodes and relationships)
    * ``"create"`` — ``CREATE …`` (insert new nodes and relationships)

    Parameters
    ----------
    schema:
        Optional ``cypher_validator.Schema`` instance.  When provided,
        source/target node labels are automatically added to ``MERGE``/``CREATE``
        clauses using the schema's relationship endpoint information.
    name_property:
        Node property key used to store entity text spans (default: ``"name"``).
    """

    def __init__(
        self,
        schema: Any = None,
        name_property: str = "name",
    ) -> None:
        self.schema = schema
        self.name_property = name_property

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_endpoints(self, cypher_rel: str) -> Tuple[str, str]:
        """Return ``(src_label, tgt_label)`` from schema, or ``("", "")``."""
        if self.schema is not None:
            endpoints = self.schema.rel_endpoints(cypher_rel)
            if endpoints is not None:
                return endpoints[0], endpoints[1]
        return "", ""

    def _clean_pairs(
        self, pairs: List[Any]
    ) -> List[Tuple[str, str]]:
        """Drop falsy entries and coerce to (str, str) tuples."""
        return [(str(s), str(o)) for s, o in pairs if s and o]

    # ------------------------------------------------------------------
    # MATCH
    # ------------------------------------------------------------------

    def to_match_query(
        self,
        relations: Dict[str, Any],
        return_clause: Optional[str] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """Build ``MATCH`` clauses for the extracted relations.

        Each (subject, object) pair produces its own ``MATCH`` clause using
        ``$param`` placeholders—one clause per pair, regardless of how many
        pairs share the same relation type.  Entity values are **never**
        interpolated directly into the query string, which prevents Cypher
        injection via adversarial entity names.

        Parameters
        ----------
        relations:
            GLiNER2 output dict.
        return_clause:
            Custom ``RETURN …`` tail.  Auto-generated from pattern variables
            when *None*.

        Returns
        -------
        tuple[str, dict]
            ``(cypher_query, parameters)`` where *parameters* maps each
            ``$placeholder`` name to its entity-text value.  Pass both to
            :meth:`Neo4jDatabase.execute` so the driver handles escaping.
            Returns ``("", {})`` when nothing was extracted.
        """
        rel_data: Dict[str, List[Any]] = relations.get("relation_extraction", {})
        clauses: List[str] = []
        return_vars: List[str] = []
        params: Dict[str, Any] = {}
        np = self.name_property
        idx = 0
        seen: set = set()  # (subject, obj, cypher_rel) deduplication

        for rel_type, raw_pairs in rel_data.items():
            pairs = self._clean_pairs(raw_pairs)
            if not pairs:
                continue

            cypher_rel = _to_cypher_rel_type(rel_type)

            for subject, obj in pairs:
                key = (subject, obj, cypher_rel)
                if key in seen:
                    continue
                seen.add(key)
                a_var, b_var = f"a{idx}", f"b{idx}"
                a_param, b_param = f"{a_var}_val", f"{b_var}_val"
                params[a_param] = subject
                params[b_param] = obj
                clauses.append(
                    f'MATCH ({a_var} {{{np}: ${a_param}}})'
                    f"-[:{cypher_rel}]->"
                    f'({b_var} {{{np}: ${b_param}}})'
                )
                return_vars.extend([a_var, b_var])
                idx += 1

        if not clauses:
            return "", {}

        ret = (
            return_clause
            if return_clause is not None
            else f"RETURN {', '.join(return_vars)}"
        )
        return "\n".join(clauses) + f"\n{ret}", params

    # ------------------------------------------------------------------
    # MERGE
    # ------------------------------------------------------------------

    def to_merge_query(
        self,
        relations: Dict[str, Any],
        return_clause: Optional[str] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """Build ``MERGE`` clauses to upsert extracted entities/relationships.

        When a ``schema`` is available and the relation type is known, node
        labels are added automatically (e.g. ``:Person``, ``:Company``).
        Entity values are passed as ``$param`` placeholders to prevent
        Cypher injection.

        Parameters
        ----------
        relations:
            GLiNER2 output dict.
        return_clause:
            Custom ``RETURN …`` tail.

        Returns
        -------
        tuple[str, dict]
            ``(cypher_query, parameters)``.  Returns ``("", {})`` when
            nothing was extracted.
        """
        return self._build_clause("MERGE", relations, return_clause)

    # ------------------------------------------------------------------
    # CREATE
    # ------------------------------------------------------------------

    def to_create_query(
        self,
        relations: Dict[str, Any],
        return_clause: Optional[str] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """Build ``CREATE`` clauses to insert extracted entities/relationships.

        Entity values are passed as ``$param`` placeholders to prevent
        Cypher injection.

        Parameters
        ----------
        relations:
            GLiNER2 output dict.
        return_clause:
            Custom ``RETURN …`` tail.

        Returns
        -------
        tuple[str, dict]
            ``(cypher_query, parameters)``.  Returns ``("", {})`` when
            nothing was extracted.
        """
        return self._build_clause("CREATE", relations, return_clause)

    # ------------------------------------------------------------------
    # Shared builder for MERGE / CREATE
    # ------------------------------------------------------------------

    def _build_clause(
        self,
        keyword: str,
        relations: Dict[str, Any],
        return_clause: Optional[str],
    ) -> Tuple[str, Dict[str, Any]]:
        rel_data: Dict[str, List[Any]] = relations.get("relation_extraction", {})
        clauses: List[str] = []
        return_vars: List[str] = []
        params: Dict[str, Any] = {}
        np = self.name_property
        idx = 0
        seen: set = set()  # (subject, obj, cypher_rel) deduplication

        for rel_type, raw_pairs in rel_data.items():
            pairs = self._clean_pairs(raw_pairs)
            if not pairs:
                continue

            cypher_rel = _to_cypher_rel_type(rel_type)
            src_label, tgt_label = self._get_endpoints(cypher_rel)
            src_l = f":{src_label}" if src_label else ""
            tgt_l = f":{tgt_label}" if tgt_label else ""

            for subject, obj in pairs:
                key = (subject, obj, cypher_rel)
                if key in seen:
                    continue
                seen.add(key)
                a_var, b_var = f"a{idx}", f"b{idx}"
                a_param, b_param = f"{a_var}_val", f"{b_var}_val"
                params[a_param] = subject
                params[b_param] = obj
                clauses.append(
                    f'{keyword} ({a_var}{src_l} {{{np}: ${a_param}}})'
                    f"-[:{cypher_rel}]->"
                    f'({b_var}{tgt_l} {{{np}: ${b_param}}})'
                )
                return_vars.extend([a_var, b_var])
                idx += 1

        if not clauses:
            return "", {}

        ret = (
            return_clause
            if return_clause is not None
            else f"RETURN {', '.join(return_vars)}"
        )
        return "\n".join(clauses) + f"\n{ret}", params

    # ------------------------------------------------------------------
    # Unified entry point
    # ------------------------------------------------------------------

    def convert(
        self,
        relations: Dict[str, Any],
        mode: str = "match",
        **kwargs: Any,
    ) -> Tuple[str, Dict[str, Any]]:
        """Convert extracted relations to a parameterized Cypher query.

        Parameters
        ----------
        relations:
            Output from :meth:`GLiNER2RelationExtractor.extract_relations`.
        mode:
            ``"match"``, ``"merge"``, or ``"create"``.
        **kwargs:
            Forwarded to the chosen generator method
            (e.g. ``return_clause="RETURN *"``).

        Returns
        -------
        tuple[str, dict]
            ``(cypher_query, parameters)`` where *parameters* maps each
            ``$placeholder`` to its entity-text value.  Pass both to
            :meth:`Neo4jDatabase.execute`.  Returns ``("", {})`` when
            nothing was extracted.

        Raises
        ------
        ValueError
            For an unrecognised *mode*.
        """
        if mode == "match":
            return self.to_match_query(relations, **kwargs)
        elif mode == "merge":
            return self.to_merge_query(relations, **kwargs)
        elif mode == "create":
            return self.to_create_query(relations, **kwargs)
        else:
            raise ValueError(
                f"Unknown mode '{mode}'.  Use 'match', 'merge', or 'create'."
            )

    # ------------------------------------------------------------------
    # DB-aware: MATCH existing, CREATE new
    # ------------------------------------------------------------------

    def to_db_aware_query(
        self,
        relations: Dict[str, Any],
        entity_status: Dict[str, Dict[str, Any]],
        return_clause: Optional[str] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """Build a mixed MATCH/CREATE query from pre-computed entity existence.

        Entities whose ``"found"`` flag is ``True`` in *entity_status* are
        rendered as ``MATCH`` clauses (placed at the top of the query).
        New entities are ``CREATE``d inline the first time they appear in a
        relation clause.  Subsequent references reuse the already-bound
        Cypher variable without repeating label or properties.

        All entity values are passed as ``$param`` placeholders.

        Parameters
        ----------
        relations:
            GLiNER2 output dict (same format as :meth:`convert`).
        entity_status:
            Mapping ``entity_name → status`` as returned by
            :meth:`NLToCypher._collect_entity_status`.  Each entry must have:

            * ``"var"`` — unique Cypher variable name (e.g. ``"e0"``).
            * ``"label"`` — node label string or ``""`` if unknown.
            * ``"param_key"`` — ``$placeholder`` name (e.g. ``"e0_val"``).
            * ``"found"`` — ``True`` when the entity exists in the DB.
            * ``"introduced"`` — initially ``False``; set to ``True`` here
              once the variable is emitted.

        return_clause:
            Custom ``RETURN …`` tail.  Auto-generated when *None*.

        Returns
        -------
        tuple[str, dict]
            ``(cypher_query, parameters)``.  Returns ``("", {})`` when nothing
            was extracted.

        Example
        -------
        John exists → MATCHed; Apple Inc. is new → CREATEd inline::

            MATCH (e0:Person {name: $e0_val})
            CREATE (e0)-[:WORKS_FOR]->(e1:Company {name: $e1_val})
            RETURN e0, e1
        """
        rel_data: Dict[str, List[Any]] = relations.get("relation_extraction", {})
        np = self.name_property
        match_clauses: List[str] = []
        create_clauses: List[str] = []
        params: Dict[str, Any] = {}
        return_vars: List[str] = []
        seen_rels: set = set()

        # ── Step 1: MATCH all entities that already exist in the DB ──────
        for entity_name, info in entity_status.items():
            if info["found"]:
                var = info["var"]
                label = info["label"]
                param_key = info["param_key"]
                label_str = f":{label}" if label else ""
                match_clauses.append(
                    f"MATCH ({var}{label_str} {{{np}: ${param_key}}})"
                )
                params[param_key] = entity_name
                if var not in return_vars:
                    return_vars.append(var)
                info["introduced"] = True

        # ── Step 2: CREATE for each relation pair ─────────────────────────
        for rel_type, raw_pairs in rel_data.items():
            pairs = self._clean_pairs(raw_pairs)
            if not pairs:
                continue

            cypher_rel = _to_cypher_rel_type(rel_type)

            for subject, obj in pairs:
                key = (subject, obj, cypher_rel)
                if key in seen_rels:
                    continue
                seen_rels.add(key)

                sub_info = entity_status.get(subject)
                obj_info = entity_status.get(obj)
                if sub_info is None or obj_info is None:
                    continue

                sub_var = sub_info["var"]
                obj_var = obj_info["var"]

                # Subject side — inline pattern for first appearance
                if sub_info["introduced"]:
                    sub_pat = sub_var
                else:
                    sub_label = sub_info["label"]
                    sub_label_str = f":{sub_label}" if sub_label else ""
                    sub_param = sub_info["param_key"]
                    params[sub_param] = subject
                    sub_pat = f"{sub_var}{sub_label_str} {{{np}: ${sub_param}}}"
                    sub_info["introduced"] = True
                    if sub_var not in return_vars:
                        return_vars.append(sub_var)

                # Object side — inline pattern for first appearance
                if obj_info["introduced"]:
                    obj_pat = obj_var
                else:
                    obj_label = obj_info["label"]
                    obj_label_str = f":{obj_label}" if obj_label else ""
                    obj_param = obj_info["param_key"]
                    params[obj_param] = obj
                    obj_pat = f"{obj_var}{obj_label_str} {{{np}: ${obj_param}}}"
                    obj_info["introduced"] = True
                    if obj_var not in return_vars:
                        return_vars.append(obj_var)

                create_clauses.append(
                    f"CREATE ({sub_pat})-[:{cypher_rel}]->({obj_pat})"
                )

        if not match_clauses and not create_clauses:
            return "", {}

        all_clauses = match_clauses + create_clauses
        ret = (
            return_clause
            if return_clause is not None
            else f"RETURN {', '.join(return_vars)}"
        )
        return "\n".join(all_clauses) + f"\n{ret}", params

    def __repr__(self) -> str:
        return (
            f"RelationToCypherConverter("
            f"schema={self.schema!r}, name_property={self.name_property!r})"
        )


# ---------------------------------------------------------------------------
# EntityNERExtractor  (optional — spaCy or HuggingFace backends)
# ---------------------------------------------------------------------------

class EntityNERExtractor:
    """Optional NER model wrapper for entity type detection.

    Used by :class:`NLToCypher` when ``ner_extractor=`` is supplied to enrich
    or override schema-based label resolution during DB-aware query generation.
    Supports **spaCy** (lightweight, fast) and **HuggingFace Transformers**
    (e.g. ``dmis-lab/biobert-v1.1``, ``dbmdz/bert-large-cased-finetuned-conll03-english``).

    Example — spaCy
    ---------------
    ::

        ner = EntityNERExtractor.from_spacy("en_core_web_sm")
        ner.extract("John works for Apple Inc.")
        # [{"text": "John", "label": "Person"},
        #  {"text": "Apple Inc.", "label": "Organization"}]

    Example — HuggingFace (biomedical)
    -----------------------------------
    ::

        ner = EntityNERExtractor.from_transformers("dmis-lab/biobert-v1.1")
        ner.extract("Aspirin inhibits COX-1.")
        # [{"text": "Aspirin", "label": "Chemical"}, ...]

    Parameters
    ----------
    model:
        Loaded spaCy ``nlp`` object or HuggingFace ``pipeline`` instance.
    backend:
        ``"spacy"`` or ``"transformers"``.
    label_map:
        Mapping from raw model label (e.g. ``"PERSON"``, ``"ORG"``) to graph
        node label (e.g. ``"Person"``, ``"Organization"``).  Merged with the
        backend's built-in defaults.
    """

    # Default spaCy entity type → graph node-label mapping
    _SPACY_DEFAULTS: Dict[str, str] = {
        "PERSON": "Person",
        "ORG": "Organization",
        "GPE": "Location",
        "LOC": "Location",
        "FAC": "Facility",
        "PRODUCT": "Product",
        "EVENT": "Event",
        "WORK_OF_ART": "Work",
        "LAW": "Law",
        "LANGUAGE": "Language",
        "DATE": "Date",
        "TIME": "Time",
        "MONEY": "Money",
        "QUANTITY": "Quantity",
        "NORP": "Group",
    }

    # Default HuggingFace NER label → graph node-label mapping
    _HF_DEFAULTS: Dict[str, str] = {
        "PER": "Person",
        "PERSON": "Person",
        "ORG": "Organization",
        "LOC": "Location",
        "GPE": "Location",
        "MISC": "Entity",
    }

    def __init__(
        self,
        model: Any,
        backend: str,
        label_map: Optional[Dict[str, str]] = None,
    ) -> None:
        self._model = model
        self._backend = backend
        self._label_map: Dict[str, str] = label_map or {}

    # ------------------------------------------------------------------

    @classmethod
    def from_spacy(
        cls,
        model_name: str = "en_core_web_sm",
        label_map: Optional[Dict[str, str]] = None,
    ) -> "EntityNERExtractor":
        """Load a spaCy NER model.

        Parameters
        ----------
        model_name:
            spaCy model name, e.g. ``"en_core_web_sm"`` or
            ``"en_core_web_trf"``.  Download first with::

                python -m spacy download en_core_web_sm

        label_map:
            Extra or override mappings on top of the built-in spaCy defaults.

        Raises
        ------
        ImportError
            If the ``spacy`` package is not installed.
        OSError
            If the requested model is not downloaded.
        """
        try:
            import spacy  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "The 'spacy' package is required for EntityNERExtractor.\n"
                "Install it with: pip install spacy\n"
                "Then download a model: python -m spacy download en_core_web_sm"
            ) from exc

        nlp = spacy.load(model_name)
        merged = {**cls._SPACY_DEFAULTS, **(label_map or {})}
        return cls(nlp, backend="spacy", label_map=merged)

    @classmethod
    def from_transformers(
        cls,
        model_name: str = "dbmdz/bert-large-cased-finetuned-conll03-english",
        label_map: Optional[Dict[str, str]] = None,
        **pipeline_kwargs: Any,
    ) -> "EntityNERExtractor":
        """Load a HuggingFace Transformers NER pipeline.

        Parameters
        ----------
        model_name:
            HuggingFace model identifier.  Common choices:

            * ``"dbmdz/bert-large-cased-finetuned-conll03-english"`` — general
              English NER (default)
            * ``"dmis-lab/biobert-v1.1"`` — biomedical NER
            * ``"Jean-Baptiste/roberta-large-ner-english"`` — high-accuracy NER

        label_map:
            Extra or override mappings on top of HuggingFace defaults
            (``PER``/``ORG``/``LOC``/``MISC``).
        **pipeline_kwargs:
            Extra keyword arguments forwarded to ``transformers.pipeline()``.

        Raises
        ------
        ImportError
            If the ``transformers`` package is not installed.
        """
        try:
            from transformers import pipeline as hf_pipeline  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "The 'transformers' package is required for from_transformers.\n"
                "Install it with: pip install transformers"
            ) from exc

        pipeline_kwargs.setdefault("aggregation_strategy", "simple")
        ner_pipe = hf_pipeline(
            "ner",
            model=model_name,
            **pipeline_kwargs,
        )
        merged = {**cls._HF_DEFAULTS, **(label_map or {})}
        return cls(ner_pipe, backend="transformers", label_map=merged)

    # ------------------------------------------------------------------

    def extract(self, text: str) -> List[Dict[str, str]]:
        """Extract named entities from *text*.

        Parameters
        ----------
        text:
            Input sentence or passage.

        Returns
        -------
        list[dict]
            Each dict contains ``"text"`` (the entity surface form) and
            ``"label"`` (resolved graph node label, e.g. ``"Person"``).
        """
        if self._backend == "spacy":
            return self._extract_spacy(text)
        elif self._backend == "transformers":
            return self._extract_transformers(text)
        else:
            raise ValueError(f"Unknown backend: {self._backend!r}")

    def _extract_spacy(self, text: str) -> List[Dict[str, str]]:
        doc = self._model(text)
        return [
            {
                "text": ent.text,
                "label": self._label_map.get(ent.label_, ent.label_.capitalize()),
            }
            for ent in doc.ents
        ]

    def _extract_transformers(self, text: str) -> List[Dict[str, str]]:
        raw = self._model(text)
        results = []
        for ent in raw:
            entity_group = ent.get("entity_group", ent.get("entity", ""))
            label = self._label_map.get(entity_group, entity_group.capitalize())
            results.append({"text": ent.get("word", ""), "label": label})
        return results

    def __repr__(self) -> str:
        return f"EntityNERExtractor(backend={self._backend!r})"


# ---------------------------------------------------------------------------
# GLiNER2RelationExtractor
# ---------------------------------------------------------------------------

class GLiNER2RelationExtractor:
    """Thin wrapper around the **GLiNER2** model for zero-shot relation extraction.

    Requires the ``gliner2`` Python package::

        pip install gliner2

    Example
    -------
    ::

        extractor = GLiNER2RelationExtractor.from_pretrained(
            "fastino/gliner2-large-v1"
        )
        results = extractor.extract_relations(
            "John works for Apple Inc. and lives in San Francisco.",
            ["works_for", "lives_in"],
        )
        # {
        #   "relation_extraction": {
        #     "works_for": [("John", "Apple Inc.")],
        #     "lives_in":  [("John", "San Francisco")],
        #   }
        # }
    """

    DEFAULT_MODEL: str = "fastino/gliner2-large-v1"

    def __init__(self, model: Any, threshold: float = 0.5) -> None:
        """
        Parameters
        ----------
        model:
            A loaded ``gliner2.GLiNER2`` instance.
        threshold:
            Default confidence threshold for accepting a predicted relation (0–1).
        """
        self._model = model
        self.threshold = threshold

    # ------------------------------------------------------------------

    @classmethod
    def from_pretrained(
        cls,
        model_name: str = DEFAULT_MODEL,
        threshold: float = 0.5,
    ) -> "GLiNER2RelationExtractor":
        """Load a pretrained GLiNER2 model from the HuggingFace Hub or a local path.

        Parameters
        ----------
        model_name:
            HuggingFace model identifier or local directory.
            Defaults to ``"fastino/gliner2-large-v1"``.
        threshold:
            Default confidence threshold (0–1).

        Returns
        -------
        GLiNER2RelationExtractor

        Raises
        ------
        ImportError
            If the ``gliner2`` package is not installed.
        """
        try:
            from gliner2 import GLiNER2  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "The 'gliner2' package is required for relation extraction.\n"
                "Install it with:  pip install gliner2"
            ) from exc

        model = GLiNER2.from_pretrained(model_name)
        return cls(model, threshold=threshold)

    # ------------------------------------------------------------------

    def extract_relations(
        self,
        text: str,
        relation_types: List[str],
        threshold: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Extract relations from *text* using the loaded GLiNER2 model.

        Parameters
        ----------
        text:
            Source sentence or passage.
        relation_types:
            Relation labels to look for (e.g. ``["works_for", "lives_in"]``).
            **All** requested types appear in the output—with an empty list when
            the relation was not found.
        threshold:
            Confidence threshold for this call; overrides the instance default.

        Returns
        -------
        dict
            ::

                {
                    "relation_extraction": {
                        "works_for": [("John", "Apple Inc.")],
                        "lives_in":  [],   # not found but was requested
                    }
                }
        """
        t = threshold if threshold is not None else self.threshold
        raw: Dict[str, Any] = self._model.extract_relations(
            text, relation_types, threshold=t
        )

        # Normalise: support both raw dict and wrapped dict
        rel_data: Dict[str, List[Tuple[str, str]]] = raw.get(
            "relation_extraction", raw
        )

        # Guarantee every requested type is present (empty list if absent)
        result: Dict[str, List[Tuple[str, str]]] = {
            rt: list(rel_data.get(rt, [])) for rt in relation_types
        }
        return {"relation_extraction": result}

    def __repr__(self) -> str:
        return f"GLiNER2RelationExtractor(threshold={self.threshold})"


# ---------------------------------------------------------------------------
# NLToCypher — end-to-end pipeline
# ---------------------------------------------------------------------------

class NLToCypher:
    """End-to-end pipeline: **natural language text → Cypher query**.

    Chains :class:`GLiNER2RelationExtractor` and :class:`RelationToCypherConverter`
    into a single callable object.  Optionally executes the generated query
    directly against a Neo4j database when a :class:`Neo4jDatabase` instance
    is provided.

    Example — generation only
    -------------------------
    ::

        from cypher_validator import Schema, NLToCypher

        schema = Schema(
            nodes={"Person": ["name"], "Company": ["name"]},
            relationships={"WORKS_FOR": ("Person", "Company", [])},
        )
        pipeline = NLToCypher.from_pretrained(
            "fastino/gliner2-large-v1",
            schema=schema,
        )
        cypher = pipeline(
            "John works for Apple Inc.",
            ["works_for"],
            mode="create",
        )
        # CREATE (a0:Person {name: "John"})-[:WORKS_FOR]->(b0:Company {name: "Apple Inc."})
        # RETURN a0, b0

    Example — generation + execution (db-aware mode)
    -------------------------------------------------
    ::

        from cypher_validator import NLToCypher, Neo4jDatabase

        db = Neo4jDatabase("bolt://localhost:7687", "neo4j", "password")
        pipeline = NLToCypher.from_pretrained(
            "fastino/gliner2-large-v1",
            schema=schema,
            db=db,
        )
        cypher, results = pipeline(
            "John works for Apple Inc.",
            ["works_for"],
            mode="create",
            execute=True,
        )
        # cypher  → 'CREATE (a0:Person {name: "John"})-[:WORKS_FOR]->...'
        # results → [{"a0": {...}, "b0": {...}}]  (Neo4j records)

    Example — DB-aware mode (MATCH existing, CREATE new)
    ----------------------------------------------------
    ::

        from cypher_validator import NLToCypher, Neo4jDatabase, Schema

        schema = Schema(
            nodes={"Person": ["name"], "Company": ["name"]},
            relationships={"WORKS_FOR": ("Person", "Company", [])},
        )
        db = Neo4jDatabase("bolt://localhost:7687", "neo4j", "password")
        pipeline = NLToCypher.from_pretrained(
            "fastino/gliner2-large-v1",
            schema=schema,
            db=db,
        )

        # If "John" already exists in the DB, the pipeline MATCHes it
        # and only CREATEs the new Company node and the relationship:
        cypher, results = pipeline(
            "John works for Apple Inc.",
            ["works_for"],
            db_aware=True,
            execute=True,
        )
        # MATCH (e0:Person {name: $e0_val})
        # CREATE (e0)-[:WORKS_FOR]->(e1:Company {name: $e1_val})
        # RETURN e0, e1

    Optionally, supply a :class:`EntityNERExtractor` to enrich entity label
    detection beyond what the schema provides::

        from cypher_validator import EntityNERExtractor, NLToCypher

        ner = EntityNERExtractor.from_spacy("en_core_web_sm")
        pipeline = NLToCypher.from_pretrained(..., db=db, ner_extractor=ner)
    """

    def __init__(
        self,
        extractor: GLiNER2RelationExtractor,
        schema: Any = None,
        name_property: str = "name",
        db: Optional[Neo4jDatabase] = None,
        ner_extractor: Optional[EntityNERExtractor] = None,
    ) -> None:
        """
        Parameters
        ----------
        extractor:
            A :class:`GLiNER2RelationExtractor` instance.
        schema:
            Optional ``cypher_validator.Schema`` for label-aware Cypher generation.
        name_property:
            Node property key for entity names (default: ``"name"``).
        db:
            Optional :class:`Neo4jDatabase` connection.  Required when
            ``execute=True`` or ``db_aware=True`` is passed to :meth:`__call__`.
        ner_extractor:
            Optional :class:`EntityNERExtractor` (spaCy or HuggingFace).
            When provided, its labels enrich or override schema-based label
            resolution during DB-aware query generation.
        """
        self.extractor = extractor
        self.converter = RelationToCypherConverter(
            schema=schema, name_property=name_property
        )
        self.db = db
        self.ner_extractor = ner_extractor

    # ------------------------------------------------------------------

    @classmethod
    def from_env(
        cls,
        model_name: str = GLiNER2RelationExtractor.DEFAULT_MODEL,
        schema: Any = None,
        threshold: float = 0.5,
        name_property: str = "name",
        database: str = "neo4j",
        ner_extractor: Optional[EntityNERExtractor] = None,
    ) -> "NLToCypher":
        """Create a pipeline reading Neo4j credentials from environment variables.

        Reads ``NEO4J_URI``, ``NEO4J_USERNAME`` (default ``"neo4j"``), and
        ``NEO4J_PASSWORD`` from the process environment and creates a
        :class:`Neo4jDatabase` connection automatically.

        Parameters
        ----------
        model_name:
            HuggingFace model name or local path.
        schema:
            Optional ``cypher_validator.Schema`` for label-aware queries.
        threshold:
            Confidence threshold for the relation extractor.
        name_property:
            Node property key for entity names.
        database:
            Neo4j database name (default: ``"neo4j"``).
        ner_extractor:
            Optional :class:`EntityNERExtractor` for enriched entity labels
            during DB-aware query generation.

        Returns
        -------
        NLToCypher
            Pipeline with a live Neo4j connection ready for ``execute=True``
            and ``db_aware=True``.

        Raises
        ------
        KeyError
            If ``NEO4J_URI`` or ``NEO4J_PASSWORD`` are not set.
        ImportError
            If the ``gliner2`` or ``neo4j`` packages are not installed.
        """
        uri = os.environ["NEO4J_URI"]
        username = os.environ.get("NEO4J_USERNAME", "neo4j")
        password = os.environ["NEO4J_PASSWORD"]
        db = Neo4jDatabase(uri, username, password, database=database)
        return cls.from_pretrained(
            model_name,
            schema=schema,
            threshold=threshold,
            name_property=name_property,
            db=db,
            ner_extractor=ner_extractor,
        )

    @classmethod
    def from_pretrained(
        cls,
        model_name: str = GLiNER2RelationExtractor.DEFAULT_MODEL,
        schema: Any = None,
        threshold: float = 0.5,
        name_property: str = "name",
        db: Optional[Neo4jDatabase] = None,
        ner_extractor: Optional[EntityNERExtractor] = None,
    ) -> "NLToCypher":
        """Create a pipeline by loading a pretrained GLiNER2 model.

        Parameters
        ----------
        model_name:
            HuggingFace model name or local path.
            Defaults to ``"fastino/gliner2-large-v1"``.
        schema:
            Optional ``cypher_validator.Schema`` for label-aware queries.
        threshold:
            Confidence threshold for the relation extractor.
        name_property:
            Node property key for entity names.
        db:
            Optional :class:`Neo4jDatabase` for direct query execution.
            Pass this to enable ``execute=True`` and ``db_aware=True`` on
            :meth:`__call__`.
        ner_extractor:
            Optional :class:`EntityNERExtractor` for enriched entity labels
            during DB-aware query generation.

        Returns
        -------
        NLToCypher

        Raises
        ------
        ImportError
            If the ``gliner2`` package is not installed.
        """
        extractor = GLiNER2RelationExtractor.from_pretrained(
            model_name, threshold=threshold
        )
        return cls(
            extractor,
            schema=schema,
            name_property=name_property,
            db=db,
            ner_extractor=ner_extractor,
        )

    # ------------------------------------------------------------------

    def _collect_entity_status(
        self,
        text: str,
        relations: Dict[str, Any],
        db: "Neo4jDatabase",
    ) -> Dict[str, Dict[str, Any]]:
        """Collect unique entities, infer labels, and check DB existence.

        Iterates over all (subject, object) pairs in *relations*, assigns each
        unique entity a Cypher variable (``e0``, ``e1``, …), resolves its node
        label from the schema, and queries the database to determine whether
        the entity already exists.

        When a :class:`EntityNERExtractor` is provided at construction the
        method operates in **strict NER mode**: both the subject and object of
        every triple must be independently confirmed by the NER model before
        the triple is processed.  Spans not recognised by the NER model are
        silently dropped, which prevents schema endpoint labels from being
        blindly stamped onto non-entity words (e.g. "doctor" → ``Drug``).
        Without an extractor the original schema-fallback behaviour is
        preserved.

        Parameters
        ----------
        text:
            Original input text (used by ``ner_extractor`` when set).
        relations:
            Output from :meth:`GLiNER2RelationExtractor.extract_relations`.
        db:
            Live database connection for existence checks.

        Returns
        -------
        dict
            ``entity_name → status`` where each status dict contains:

            * ``"var"`` — Cypher variable (e.g. ``"e0"``).
            * ``"label"`` — node label string, or ``""`` if unknown.
            * ``"param_key"`` — ``$placeholder`` name (e.g. ``"e0_val"``).
            * ``"found"`` — ``True`` if the entity exists in the DB.
            * ``"introduced"`` — ``False``; managed by
              :meth:`RelationToCypherConverter.to_db_aware_query`.
        """
        rel_data: Dict[str, List[Any]] = relations.get("relation_extraction", {})
        np = self.converter.name_property
        entity_status: Dict[str, Dict[str, Any]] = {}
        idx = 0

        # ── Build NER label map (if extractor provided) ──────────────────
        ner_labels: Dict[str, str] = {}
        strict_ner = self.ner_extractor is not None
        if strict_ner:
            for ent in self.ner_extractor.extract(text):
                ner_labels[ent["text"]] = ent["label"]

        # ── Collect unique entities and resolve labels ────────────────────
        for rel_type, raw_pairs in rel_data.items():
            pairs = self.converter._clean_pairs(raw_pairs)
            if not pairs:
                continue

            cypher_rel = _to_cypher_rel_type(rel_type)
            src_label, tgt_label = self.converter._get_endpoints(cypher_rel)

            for subject, obj in pairs:
                # Resolve labels before touching entity_status so we can
                # gate the entire triple atomically.
                sub_label = (
                    ner_labels.get(subject)
                    if strict_ner
                    else ner_labels.get(subject, src_label)
                )
                obj_label = (
                    ner_labels.get(obj)
                    if strict_ner
                    else ner_labels.get(obj, tgt_label)
                )

                # Strict mode: drop the triple if either span is unconfirmed
                # by NER.  to_db_aware_query skips pairs whose entities are
                # absent from entity_status, so no downstream changes needed.
                if strict_ner and (sub_label is None or obj_label is None):
                    continue

                if subject not in entity_status:
                    var = f"e{idx}"
                    entity_status[subject] = {
                        "var": var,
                        "label": sub_label or "",
                        "param_key": f"{var}_val",
                        "found": False,
                        "introduced": False,
                    }
                    idx += 1
                elif not entity_status[subject]["label"] and sub_label:
                    # Enrich label if we learn it from a new relation type
                    entity_status[subject]["label"] = sub_label

                if obj not in entity_status:
                    var = f"e{idx}"
                    entity_status[obj] = {
                        "var": var,
                        "label": obj_label or "",
                        "param_key": f"{var}_val",
                        "found": False,
                        "introduced": False,
                    }
                    idx += 1
                elif not entity_status[obj]["label"] and obj_label:
                    entity_status[obj]["label"] = obj_label

        # ── Query DB for each unique entity ──────────────────────────────
        for entity_name, info in entity_status.items():
            label = info["label"]
            label_str = f":{label}" if label else ""
            lookup = (
                f"MATCH (n{label_str} {{{np}: $val}}) "
                f"RETURN elementId(n) AS id LIMIT 1"
            )
            try:
                rows = db.execute(lookup, {"val": entity_name})
                info["found"] = len(rows) > 0
            except Exception:
                info["found"] = False

        return entity_status

    # ------------------------------------------------------------------

    def __call__(
        self,
        text: str,
        relation_types: List[str],
        mode: str = "match",
        threshold: Optional[float] = None,
        execute: bool = False,
        db_aware: bool = False,
        **kwargs: Any,
    ) -> Union[str, Tuple[str, List[Dict[str, Any]]]]:
        """Extract relations from *text* and return a Cypher query.

        Parameters
        ----------
        text:
            Input sentence or passage.
        relation_types:
            Relation labels to extract.
        mode:
            Cypher generation mode: ``"match"``, ``"merge"``, or ``"create"``.
            Ignored when ``db_aware=True`` (db-aware mode always MATCHes
            existing entities and CREATEs new ones).
        threshold:
            Override the extractor's confidence threshold for this call.
        execute:
            When ``True``, execute the generated query against the
            :class:`Neo4jDatabase` supplied at construction and return
            ``(cypher, results)`` instead of just ``cypher``.
            Requires ``db`` to be set.
        db_aware:
            When ``True``, each entity extracted from *text* is looked up in
            the database before query generation:

            * **Existing entity** → rendered as a ``MATCH`` clause.
            * **New entity** → ``CREATE``d inline the first time it appears.

            Requires ``db`` to be set.  Can be combined with ``execute=True``
            to look up, generate, and immediately run the query.
        **kwargs:
            Extra keyword arguments forwarded to the Cypher converter
            (e.g. ``return_clause="RETURN *"``).

        Returns
        -------
        str
            Cypher query string when ``execute=False`` (default).
        tuple[str, list[dict]]
            ``(cypher, db_results)`` when ``execute=True``.

        Raises
        ------
        RuntimeError
            When ``execute=True`` or ``db_aware=True`` but no ``db`` was
            provided.
        """
        relations = self.extractor.extract_relations(
            text, relation_types, threshold=threshold
        )

        if db_aware:
            if self.db is None:
                raise RuntimeError(
                    "db_aware=True requires a database connection. "
                    "Pass db=Neo4jDatabase(...) when constructing NLToCypher "
                    "or via NLToCypher.from_pretrained(..., db=db)."
                )
            entity_status = self._collect_entity_status(text, relations, self.db)
            cypher, params = self.converter.to_db_aware_query(
                relations, entity_status, **kwargs
            )
        else:
            cypher, params = self.converter.convert(relations, mode=mode, **kwargs)

        if execute:
            if self.db is None:
                raise RuntimeError(
                    "execute=True requires a database connection. "
                    "Pass db=Neo4jDatabase(...) when constructing NLToCypher "
                    "or via NLToCypher.from_pretrained(..., db=db)."
                )
            results = self.db.execute(cypher, params) if cypher else []
            return cypher, results

        return cypher

    # ------------------------------------------------------------------

    def extract_and_convert(
        self,
        text: str,
        relation_types: List[str],
        mode: str = "match",
        threshold: Optional[float] = None,
        execute: bool = False,
        db_aware: bool = False,
        **kwargs: Any,
    ) -> Union[Tuple[Dict[str, Any], str], Tuple[Dict[str, Any], str, List[Dict[str, Any]]]]:
        """Extract relations and return both the raw dict and the Cypher string.

        Parameters
        ----------
        text:
            Input sentence or passage.
        relation_types:
            Relation labels to extract.
        mode:
            Cypher generation mode.  Ignored when ``db_aware=True``.
        threshold:
            Override extractor confidence threshold.
        execute:
            When ``True``, also execute the query against the database.
            Requires ``db`` to be set.
        db_aware:
            When ``True``, look up entities in the DB before generating the
            query (MATCH existing, CREATE new).  Requires ``db`` to be set.
        **kwargs:
            Forwarded to the Cypher converter.

        Returns
        -------
        tuple[dict, str]
            ``(relations_dict, cypher_query)`` when ``execute=False``.
        tuple[dict, str, list[dict]]
            ``(relations_dict, cypher_query, db_results)`` when ``execute=True``.

        Raises
        ------
        RuntimeError
            When ``execute=True`` or ``db_aware=True`` but no ``db`` was
            provided.
        """
        relations = self.extractor.extract_relations(
            text, relation_types, threshold=threshold
        )

        if db_aware:
            if self.db is None:
                raise RuntimeError(
                    "db_aware=True requires a database connection. "
                    "Pass db=Neo4jDatabase(...) when constructing NLToCypher."
                )
            entity_status = self._collect_entity_status(text, relations, self.db)
            cypher, params = self.converter.to_db_aware_query(
                relations, entity_status, **kwargs
            )
        else:
            cypher, params = self.converter.convert(relations, mode=mode, **kwargs)

        if execute:
            if self.db is None:
                raise RuntimeError(
                    "execute=True requires a database connection. "
                    "Pass db=Neo4jDatabase(...) when constructing NLToCypher."
                )
            results = self.db.execute(cypher, params) if cypher else []
            return relations, cypher, results

        return relations, cypher

    def __repr__(self) -> str:
        return (
            f"NLToCypher(extractor={self.extractor!r}, "
            f"converter={self.converter!r}, "
            f"db={self.db!r}, "
            f"ner_extractor={self.ner_extractor!r})"
        )
