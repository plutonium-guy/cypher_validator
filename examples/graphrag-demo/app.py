"""Biomedical Research Knowledge Graph — FastAPI + 3D visualization demo.

Demonstrates cypher_validator ORM capabilities:
- GraphSession + QueryHistory for all operations
- Query builder (fluent chaining, vector_search_model)
- BulkOps (UNWIND-based efficient batch operations)
- Traversal (shortest_path, common_neighbors, subgraph)
- Repository (typed CRUD per model)
- SchemaDDL (constraint/index generation)
- CypherValidator (Rust-powered validation)

Start Neo4j:
    docker run -d --name neo4j-demo -p 7474:7474 -p 7687:7687 \
        -e NEO4J_AUTH=neo4j/testtest12 neo4j:5.26-community

Run:
    cd examples/graphrag-demo
    uvicorn app:app --reload --port 8000
"""

from __future__ import annotations

import os
import httpx
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Query as QueryParam
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from neo4j import GraphDatabase

from models import (
    ALL_MODELS,
    Researcher, Institution, Paper, Disease, Drug, Gene,
    ClinicalTrial, FundingAgency,
)

from cypher_validator.models.session import GraphSession, BulkOps, Traversal, Repository
from cypher_validator.models.query import Query, QueryHistory
from cypher_validator.models.schema import GraphSchema, SchemaDDL, SchemaDiff
from cypher_validator.models.agents import AgentTools
from cypher_validator import CypherValidator

# ---------------------------------------------------------------------------
# Neo4j wrapper (implements the .execute() protocol GraphSession expects)
# ---------------------------------------------------------------------------

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASS = os.getenv("NEO4J_PASSWORD", "testtest12")
DEEPSEEK_KEY = os.getenv("DEEPSEEK_API_KEY", "sk-81d6ee56f11045f4b558c5e63062eeaa")
EMBED_MODEL = os.getenv("EMBED_MODEL", "all-MiniLM-L6-v2")

MODEL_MAP = {
    "Researcher": Researcher,
    "Institution": Institution,
    "Paper": Paper,
    "Disease": Disease,
    "Drug": Drug,
    "Gene": Gene,
    "ClinicalTrial": ClinicalTrial,
    "FundingAgency": FundingAgency,
}


class Neo4jDB:
    def __init__(self):
        self._driver = None

    def connect(self):
        self._driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
        self._driver.verify_connectivity()

    def close(self):
        if self._driver:
            self._driver.close()

    def execute(self, cypher: str, params: dict | None = None) -> list[dict]:
        with self._driver.session() as session:
            result = session.run(cypher, params or {})
            records = []
            for record in result:
                row = {}
                for key in record.keys():
                    val = record[key]
                    if hasattr(val, "items"):
                        row[key] = dict(val.items())
                    elif hasattr(val, "id") and hasattr(val, "type"):
                        row[key] = {
                            "id": val.element_id,
                            "type": val.type,
                            "properties": dict(val.items()),
                            "start": val.start_node.element_id,
                            "end": val.end_node.element_id,
                        }
                    else:
                        row[key] = val
                records.append(row)
            return records


db = Neo4jDB()
_schema: GraphSchema | None = None
_session: GraphSession | None = None
_history: QueryHistory | None = None
_embed_model = None


def get_schema() -> GraphSchema:
    global _schema
    if _schema is None:
        _schema = GraphSchema.from_models(ALL_MODELS)
    return _schema


def get_session() -> GraphSession:
    global _session
    if _session is None:
        _session = GraphSession(db, get_schema())
    return _session


def get_history() -> QueryHistory:
    global _history
    if _history is None:
        _history = QueryHistory(max_entries=50)
    return _history


def get_embedder():
    global _embed_model
    if _embed_model is None:
        from sentence_transformers import SentenceTransformer
        _embed_model = SentenceTransformer(EMBED_MODEL)
    return _embed_model


def embed_text(text: str) -> list[float]:
    model = get_embedder()
    return model.encode(text).tolist()


def strip_embeddings(props: dict) -> dict:
    return {k: v for k, v in props.items() if "embedding" not in k.lower()}


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.connect()
    print(f"Connected to Neo4j at {NEO4J_URI}")
    yield
    db.close()


app = FastAPI(title="Biomedical Knowledge Graph Explorer", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")


# ---------------------------------------------------------------------------
# Pydantic request/response models
# ---------------------------------------------------------------------------


class NodeUpdate(BaseModel):
    label: str
    element_id: str
    properties: dict[str, Any]


class RelationshipCreate(BaseModel):
    source_id: str
    target_id: str
    rel_type: str
    properties: dict[str, Any] = {}


class RelationshipUpdate(BaseModel):
    element_id: str
    properties: dict[str, Any]


class NLQueryRequest(BaseModel):
    question: str


class SemanticSearchRequest(BaseModel):
    query: str
    label: str = "Paper"
    property: str = "abstract_embedding"
    top_k: int = 5


class NodeCreate(BaseModel):
    label: str
    properties: dict[str, Any]


class CypherValidateRequest(BaseModel):
    cypher: str


class ShortestPathRequest(BaseModel):
    source_id: str
    target_id: str
    max_hops: int = 5


class CommonNeighborsRequest(BaseModel):
    source_id: str
    target_id: str


class RAGRequest(BaseModel):
    question: str


class BulkImportRequest(BaseModel):
    label: str
    items: list[dict[str, Any]]


class QueryPlanStep(BaseModel):
    description: str
    cypher: str
    depends_on: list[int] = []


class QueryPlanRequest(BaseModel):
    goal: str
    steps: list[QueryPlanStep]


class SchemaDiffRequest(BaseModel):
    old_labels: list[str]
    new_labels: list[str]


# ---------------------------------------------------------------------------
# Routes: Graph data (uses GraphSession + Query builder)
# ---------------------------------------------------------------------------


@app.get("/")
async def index():
    return FileResponse("static/index.html")


@app.get("/api/graph")
async def get_full_graph(limit: int = QueryParam(default=500, le=2000)):
    """Return all nodes and relationships for 3D visualization."""
    session = get_session()
    nodes = session.execute(
        "MATCH (n) "
        "RETURN elementId(n) AS id, labels(n) AS labels, properties(n) AS props "
        "LIMIT $limit",
        {"limit": limit},
    )
    rels = session.execute(
        "MATCH (a)-[r]->(b) "
        "RETURN elementId(r) AS id, type(r) AS type, "
        "elementId(a) AS source, elementId(b) AS target, "
        "properties(r) AS props "
        "LIMIT $limit",
        {"limit": limit * 3},
    )

    for n in nodes:
        if isinstance(n.get("props"), dict):
            n["props"] = strip_embeddings(n["props"])

    return {"nodes": nodes, "relationships": rels}


@app.get("/api/graph/filtered")
async def get_filtered_graph(
    labels: str = QueryParam(default="", description="Comma-separated labels to include"),
    rel_types: str = QueryParam(default="", description="Comma-separated rel types"),
):
    """Get filtered subgraph using Query builder."""
    session = get_session()
    label_list = [l.strip() for l in labels.split(",") if l.strip()] if labels else []
    rel_list = [r.strip() for r in rel_types.split(",") if r.strip()] if rel_types else []

    if label_list:
        label_filter = " OR ".join(f"'{l}' IN labels(n)" for l in label_list)
        q = Query().match(var="n").where(label_filter).return_("elementId(n) AS id", "labels(n) AS labels", "properties(n) AS props")
    else:
        q = Query().match(var="n").return_("elementId(n) AS id", "labels(n) AS labels", "properties(n) AS props")

    cypher, params = q.build()
    nodes = session.execute(cypher, params)
    node_ids = {n["id"] for n in nodes}

    if rel_list:
        rel_filter = " OR ".join(f"type(r) = '{r}'" for r in rel_list)
        rq = (Query()
              .match(var="a").raw("-[r]->(b)")
              .where(rel_filter)
              .return_("elementId(r) AS id", "type(r) AS type",
                       "elementId(a) AS source", "elementId(b) AS target",
                       "properties(r) AS props"))
    else:
        rq = (Query()
              .match(var="a").raw("-[r]->(b)")
              .return_("elementId(r) AS id", "type(r) AS type",
                       "elementId(a) AS source", "elementId(b) AS target",
                       "properties(r) AS props"))

    rcypher, rparams = rq.build()
    rels = session.execute(rcypher, rparams)
    rels = [r for r in rels if r["source"] in node_ids and r["target"] in node_ids]

    for n in nodes:
        if isinstance(n.get("props"), dict):
            n["props"] = strip_embeddings(n["props"])

    return {"nodes": nodes, "relationships": rels}


@app.get("/api/schema")
async def get_schema_info():
    """Return graph schema from ORM models (introspected via GraphSchema)."""
    schema = get_schema()
    labels_info = []
    for model_cls in schema.node_models:
        labels_info.append({
            "label": model_cls.__label__,
            "props": list(model_cls.model_fields.keys()),
        })
    rels_info = []
    for rel_cls in schema.rel_models:
        rels_info.append({
            "rtype": rel_cls.rel_type(),
            "src": rel_cls.source_label(),
            "tgt": rel_cls.target_label(),
            "props": rel_cls.property_names(),
        })
    return {"labels": labels_info, "relationships": rels_info}


@app.get("/api/stats")
async def get_stats():
    """Graph statistics using Query builder."""
    session = get_session()

    q_nodes = (Query()
               .match(var="n")
               .with_("labels(n)[0] AS label", "count(n) AS cnt")
               .return_("label", "cnt")
               .order_by("cnt DESC"))
    cypher, params = q_nodes.build()
    node_counts = session.execute(cypher, params)

    q_rels = (Query()
              .match(var="a").raw("-[r]->()")
              .with_("type(r) AS rtype", "count(r) AS cnt")
              .return_("rtype", "cnt")
              .order_by("cnt DESC"))
    rcypher, rparams = q_rels.build()
    rel_counts = session.execute(rcypher, rparams)

    total_nodes = session.execute("MATCH (n) RETURN count(n) AS total")
    total_rels = session.execute("MATCH ()-[r]->() RETURN count(r) AS total")

    return {
        "total_nodes": total_nodes[0]["total"],
        "total_relationships": total_rels[0]["total"],
        "node_counts": node_counts,
        "rel_counts": rel_counts,
    }


# ---------------------------------------------------------------------------
# Routes: CRUD (uses Repository pattern)
# ---------------------------------------------------------------------------


@app.post("/api/nodes")
async def create_node(req: NodeCreate):
    """Create a node using Repository if model exists, else raw Cypher."""
    session = get_session()
    model_cls = MODEL_MAP.get(req.label)

    if model_cls:
        repo = Repository(model_cls, session)
        instance = model_cls(**req.properties)
        result = repo.create(instance)
        if result:
            return result[0]

    # Fallback for unknown labels
    props = {k: v for k, v in req.properties.items() if v is not None}
    set_parts = []
    params = {}
    for i, (k, v) in enumerate(props.items()):
        pname = f"p{i}"
        set_parts.append(f"n.{k} = ${pname}")
        params[pname] = v

    set_clause = ", ".join(set_parts) if set_parts else ""
    cypher = f"CREATE (n:{req.label})"
    if set_clause:
        cypher += f" SET {set_clause}"
    cypher += " RETURN elementId(n) AS id, labels(n) AS labels, properties(n) AS props"

    result = session.execute(cypher, params)
    if not result:
        raise HTTPException(500, "Failed to create node")
    return result[0]


@app.put("/api/nodes")
async def update_node(req: NodeUpdate):
    """Update node properties using Repository.update()."""
    session = get_session()
    model_cls = MODEL_MAP.get(req.label)
    props = {k: v for k, v in req.properties.items() if "embedding" not in k.lower()}

    if model_cls and props:
        repo = Repository(model_cls, session)
        # Find node by element ID, then update
        result = session.execute(
            "MATCH (n) WHERE elementId(n) = $eid "
            "RETURN properties(n) AS p",
            {"eid": req.element_id},
        )
        if result:
            existing = result[0]["p"]
            key_fields = [f for f in model_cls.model_fields if f != "id"]
            match_props = {}
            for k in key_fields[:1]:
                if k in existing:
                    match_props[k] = existing[k]
            if match_props:
                repo.update(match_props, props)

    # Always return updated node
    set_parts = []
    params = {"eid": req.element_id}
    for i, (k, v) in enumerate(props.items()):
        pname = f"p{i}"
        set_parts.append(f"n.{k} = ${pname}")
        params[pname] = v

    if not set_parts:
        raise HTTPException(400, "No properties to update")

    set_clause = ", ".join(set_parts)
    result = session.execute(
        f"MATCH (n) WHERE elementId(n) = $eid "
        f"SET {set_clause} "
        "RETURN elementId(n) AS id, labels(n) AS labels, properties(n) AS props",
        params,
    )
    if not result:
        raise HTTPException(404, "Node not found")
    return result[0]


@app.delete("/api/nodes/{element_id}")
async def delete_node(element_id: str):
    """Delete a node and its relationships."""
    session = get_session()
    session.execute(
        "MATCH (n) WHERE elementId(n) = $eid DETACH DELETE n RETURN count(*) AS deleted",
        {"eid": element_id},
    )
    return {"deleted": True}


@app.post("/api/relationships")
async def create_relationship(req: RelationshipCreate):
    """Create a relationship between two nodes using Query builder."""
    session = get_session()
    params = {"src": req.source_id, "tgt": req.target_id}
    prop_parts = []
    for i, (k, v) in enumerate(req.properties.items()):
        pname = f"rp{i}"
        prop_parts.append(f"{k}: ${pname}")
        params[pname] = v

    prop_clause = f" {{{', '.join(prop_parts)}}}" if prop_parts else ""
    result = session.execute(
        f"MATCH (a) WHERE elementId(a) = $src "
        f"MATCH (b) WHERE elementId(b) = $tgt "
        f"CREATE (a)-[r:{req.rel_type}{prop_clause}]->(b) "
        "RETURN elementId(r) AS id, type(r) AS type, "
        "elementId(a) AS source, elementId(b) AS target, properties(r) AS props",
        params,
    )
    if not result:
        raise HTTPException(500, "Failed to create relationship")
    return result[0]


@app.put("/api/relationships")
async def update_relationship(req: RelationshipUpdate):
    """Update relationship properties."""
    session = get_session()
    set_parts = []
    params = {"eid": req.element_id}
    for i, (k, v) in enumerate(req.properties.items()):
        pname = f"rp{i}"
        set_parts.append(f"r.{k} = ${pname}")
        params[pname] = v

    if not set_parts:
        raise HTTPException(400, "No properties to update")

    set_clause = ", ".join(set_parts)
    result = session.execute(
        f"MATCH ()-[r]->() WHERE elementId(r) = $eid "
        f"SET {set_clause} "
        "RETURN elementId(r) AS id, type(r) AS type, properties(r) AS props",
        params,
    )
    if not result:
        raise HTTPException(404, "Relationship not found")
    return result[0]


@app.delete("/api/relationships/{element_id}")
async def delete_relationship(element_id: str):
    """Delete a relationship."""
    session = get_session()
    session.execute(
        "MATCH ()-[r]->() WHERE elementId(r) = $eid DELETE r",
        {"eid": element_id},
    )
    return {"deleted": True}


# ---------------------------------------------------------------------------
# Routes: NL Query (DeepSeek) — tracked via QueryHistory
# ---------------------------------------------------------------------------


SYSTEM_PROMPT = """You are a Cypher query expert for a biomedical research knowledge graph.

The graph has these node types and properties:
- Researcher: name, orcid, h_index, specialization, bio
- Institution: name, country, type
- Paper: title, doi, year, journal, citation_count, abstract
- Disease: name, icd_code, category, description
- Drug: name, drugbank_id, phase, mechanism
- Gene: symbol, full_name, chromosome, pathway
- ClinicalTrial: trial_id, title, phase, status, enrollment, start_year
- FundingAgency: name, country, type

Relationships:
- (Paper)-[r:AUTHORED_BY]->(Researcher)  — r.position
- (Researcher)-[r:AFFILIATED_WITH]->(Institution)  — r.role, r.since
- (Paper)-[r:CITES]->(Paper)  — r.context
- (Paper)-[:STUDIES]->(Disease)
- (Disease)-[r:TREATS_WITH]->(Drug)  — r.efficacy
- (Drug)-[r:TARGETS]->(Gene)  — r.action
- (Disease)-[r:ASSOCIATED_WITH]->(Gene)  — r.evidence_level
- (ClinicalTrial)-[:TESTS]->(Drug)
- (ClinicalTrial)-[:TRIAL_FOR]->(Disease)
- (Paper)-[r:FUNDED_BY]->(FundingAgency)  — r.grant_id, r.amount_usd
- (Researcher)-[r:COLLABORATES_WITH]->(Researcher)  — r.paper_count, r.since

Rules:
- Return ONLY the Cypher query, no explanation
- Always use parameterized queries where possible
- Use LIMIT to cap results (default 25)
- Include relevant properties in RETURN, not just nodes
- IMPORTANT: NEVER use exact match for name/title lookups. Always use WHERE n.name CONTAINS 'keyword' for partial matching, because entity names are full formal names (e.g. "Glioblastoma Multiforme" not "Glioblastoma", "Non-Small Cell Lung Cancer" not "NSCLC")
- Use toLower() with CONTAINS for case-insensitive matching when appropriate
"""


@app.post("/api/nl-query")
async def nl_query(req: NLQueryRequest):
    """Convert natural language to Cypher via DeepSeek and execute."""
    history = get_history()
    session = get_session()

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.deepseek.com/chat/completions",
            headers={
                "Authorization": f"Bearer {DEEPSEEK_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": req.question},
                ],
                "temperature": 0.1,
                "max_tokens": 500,
            },
        )

    if resp.status_code != 200:
        raise HTTPException(502, f"DeepSeek API error: {resp.text}")

    data = resp.json()
    cypher_raw = data["choices"][0]["message"]["content"].strip()
    cypher = cypher_raw.strip("`").removeprefix("cypher\n").removeprefix("cypher").strip()

    try:
        records = session.execute(cypher)
        cleaned = []
        for r in records:
            row = {}
            for k, v in r.items():
                if isinstance(v, dict):
                    row[k] = strip_embeddings(v)
                elif isinstance(v, list) and v and isinstance(v[0], float) and len(v) > 10:
                    continue
                else:
                    row[k] = v
            cleaned.append(row)

        history.add(cypher, result_count=len(cleaned), summary=req.question)
        return {"cypher": cypher, "records": cleaned, "count": len(cleaned)}
    except Exception as e:
        history.add(cypher, error=str(e), summary=req.question)
        return {"cypher": cypher, "error": str(e), "records": [], "count": 0}


# ---------------------------------------------------------------------------
# Routes: Semantic search (uses Query.vector_search_model)
# ---------------------------------------------------------------------------


VECTOR_MODELS = {"Paper": Paper, "Researcher": Researcher, "Disease": Disease}


@app.post("/api/semantic-search")
async def semantic_search(req: SemanticSearchRequest):
    """Vector similarity search using Query.vector_search_model()."""
    session = get_session()
    vector = embed_text(req.query)

    model_cls = VECTOR_MODELS.get(req.label)
    if not model_cls:
        raise HTTPException(400, f"No vector index for label: {req.label}")

    index_name = f"idx_{req.label.lower()}_{req.property}_vector"

    try:
        q = Query().vector_search_model(
            model=model_cls,
            property=req.property,
            query_vector=vector,
            top_k=req.top_k,
        ).return_("node", "score")

        cypher, params = q.build()
        results = session.execute(cypher, params)
        cleaned = []
        for r in results:
            node_data = r.get("node", {})
            if isinstance(node_data, dict):
                node_data = strip_embeddings(node_data)
            cleaned.append({"node": node_data, "score": r.get("score", 0)})
        return {"results": cleaned, "query": req.query, "index": index_name}
    except Exception as e:
        # Fallback: direct vector query call
        try:
            results = session.execute(
                "CALL db.index.vector.queryNodes($idx, $topk, $vec) "
                "YIELD node, score RETURN node, score",
                {"idx": index_name, "topk": req.top_k, "vec": vector},
            )
            cleaned = []
            for r in results:
                node_data = r.get("node", {})
                if isinstance(node_data, dict):
                    node_data = strip_embeddings(node_data)
                cleaned.append({"node": node_data, "score": r.get("score", 0)})
            return {"results": cleaned, "query": req.query, "index": index_name}
        except Exception as e2:
            return {
                "error": str(e2),
                "results": [],
                "hint": "Vector indexes may not exist. Run seed.py with embeddings first.",
            }


# ---------------------------------------------------------------------------
# Routes: Seed
# ---------------------------------------------------------------------------


@app.post("/api/seed")
async def seed_data(with_embeddings: bool = QueryParam(default=False)):
    """Seed the database with sample biomedical data."""
    from seed import seed_database

    embed_fn = embed_text if with_embeddings else None
    nodes, rels = seed_database(db, embed_fn)
    return {"nodes": nodes, "relationships": rels, "embeddings": with_embeddings}


# ---------------------------------------------------------------------------
# Routes: Node neighbors (uses Traversal.neighbors)
# ---------------------------------------------------------------------------


@app.get("/api/nodes/{element_id}/neighbors")
async def get_neighbors(element_id: str):
    """Get immediate neighbors of a node using Traversal helper."""
    session = get_session()

    # Element ID doesn't directly map to model props, use raw Cypher via session
    outgoing = session.execute(
        "MATCH (n)-[r]->(m) WHERE elementId(n) = $eid "
        "RETURN type(r) AS rel_type, properties(r) AS rel_props, "
        "elementId(m) AS id, labels(m) AS labels, properties(m) AS props",
        {"eid": element_id},
    )
    incoming = session.execute(
        "MATCH (m)-[r]->(n) WHERE elementId(n) = $eid "
        "RETURN type(r) AS rel_type, properties(r) AS rel_props, "
        "elementId(m) AS id, labels(m) AS labels, properties(m) AS props",
        {"eid": element_id},
    )

    for lst in [outgoing, incoming]:
        for n in lst:
            if isinstance(n.get("props"), dict):
                n["props"] = strip_embeddings(n["props"])

    return {"outgoing": outgoing, "incoming": incoming}


# ---------------------------------------------------------------------------
# Routes: Cypher Validation (Rust-powered validator)
# ---------------------------------------------------------------------------


@app.post("/api/validate")
async def validate_cypher(req: CypherValidateRequest):
    """Validate a Cypher query using the Rust-powered CypherValidator."""
    try:
        schema = get_schema()
        rust_schema = schema.to_cypher_schema()
        validator = CypherValidator(rust_schema)
        result = validator.validate(req.cypher)
        return {
            "valid": result.is_valid,
            "errors": [{"code": e.code, "message": e.message} for e in result.errors],
            "warnings": [{"code": w.code, "message": w.message} for w in result.warnings],
            "fixed_query": result.fixed_query if hasattr(result, "fixed_query") else None,
        }
    except Exception as e:
        raise HTTPException(400, f"Validation failed: {e}")


# ---------------------------------------------------------------------------
# Routes: Graph Traversal (uses Traversal helpers)
# ---------------------------------------------------------------------------


@app.post("/api/traversal/shortest-path")
async def shortest_path(req: ShortestPathRequest):
    """Find shortest path between two nodes."""
    session = get_session()
    try:
        cypher = (
            "MATCH path = shortestPath((a)-[*..{max_hops}]-(b)) "
            "WHERE elementId(a) = $src AND elementId(b) = $tgt "
            "RETURN path, length(path) AS hops"
        ).format(max_hops=int(req.max_hops))
        records = session.execute(cypher, {"src": req.source_id, "tgt": req.target_id})
        if not records:
            return {"path": None, "hops": 0, "message": "No path found"}

        path_data = records[0].get("path")
        hops = records[0].get("hops", 0)

        if hasattr(path_data, "nodes") and hasattr(path_data, "relationships"):
            nodes = [
                {
                    "id": n.element_id,
                    "labels": list(n.labels),
                    "props": strip_embeddings(dict(n)),
                }
                for n in path_data.nodes
            ]
            rels = [
                {
                    "id": r.element_id,
                    "type": r.type,
                    "start": r.start_node.element_id,
                    "end": r.end_node.element_id,
                    "props": dict(r),
                }
                for r in path_data.relationships
            ]
            return {"nodes": nodes, "relationships": rels, "hops": hops}

        return {"path": path_data, "hops": hops}
    except Exception as e:
        raise HTTPException(400, f"Shortest path query failed: {e}")


@app.post("/api/traversal/common-neighbors")
async def common_neighbors(req: CommonNeighborsRequest):
    """Find common neighbors between two nodes."""
    session = get_session()
    try:
        # Use Traversal if we can resolve labels from element IDs
        cypher = (
            "MATCH (a)--(common)--(b) "
            "WHERE elementId(a) = $src AND elementId(b) = $tgt "
            "AND a <> b AND common <> a AND common <> b "
            "RETURN DISTINCT elementId(common) AS id, labels(common) AS labels, "
            "properties(common) AS props"
        )
        records = session.execute(cypher, {"src": req.source_id, "tgt": req.target_id})
        for r in records:
            if isinstance(r.get("props"), dict):
                r["props"] = strip_embeddings(r["props"])
        return {"common_neighbors": records, "count": len(records)}
    except Exception as e:
        raise HTTPException(400, f"Common neighbors query failed: {e}")


@app.post("/api/traversal/subgraph")
async def get_subgraph(element_id: str = "", label: str = "", name: str = "", depth: int = 2):
    """Get N-hop subgraph around a node using Traversal.subgraph()."""
    session = get_session()
    model_cls = MODEL_MAP.get(label)

    if model_cls and name:
        # Use ORM Traversal
        key_field = list(model_cls.__fields__.keys())[0]
        cypher, params = Traversal.subgraph(model_cls, {key_field: name}, depth=depth)
        records = session.execute(cypher, params)
        return {"subgraph": records, "depth": depth}

    # Fallback: element ID based
    if element_id:
        cypher = (
            f"MATCH path = (n)-[*1..{int(depth)}]-(m) WHERE elementId(n) = $eid "
            "RETURN DISTINCT elementId(m) AS id, labels(m) AS labels, properties(m) AS props"
        )
        records = session.execute(cypher, {"eid": element_id})
        for r in records:
            if isinstance(r.get("props"), dict):
                r["props"] = strip_embeddings(r["props"])
        return {"subgraph": records, "depth": depth}

    raise HTTPException(400, "Provide element_id or label+name")


# ---------------------------------------------------------------------------
# Routes: Query History (uses ORM QueryHistory)
# ---------------------------------------------------------------------------


@app.get("/api/history")
async def get_query_history():
    """Return recent query history tracked by QueryHistory."""
    history = get_history()
    return {"history": history.to_list(), "count": len(history.to_list())}


@app.get("/api/history/context")
async def get_history_context(last_n: int = 10):
    """Return formatted context string for AI agents."""
    history = get_history()
    return {"context": history.to_context(last_n=last_n)}


@app.delete("/api/history")
async def clear_query_history():
    """Clear query history."""
    history = get_history()
    history.clear()
    return {"cleared": True}


# ---------------------------------------------------------------------------
# Routes: Schema DDL (uses SchemaDDL)
# ---------------------------------------------------------------------------


@app.get("/api/ddl")
async def get_schema_ddl():
    """Generate DDL statements (constraints, indexes) from ORM schema via SchemaDDL."""
    try:
        schema = get_schema()
        ddl = SchemaDDL(schema)
        return {
            "constraints": ddl.uniqueness_constraints(),
            "indexes": ddl.property_indexes(),
            "vector_indexes": ddl.vector_indexes(),
            "all": ddl.generate_all(),
        }
    except Exception as e:
        raise HTTPException(500, f"DDL generation failed: {e}")


@app.post("/api/ddl/apply")
async def apply_schema_ddl():
    """Apply all DDL statements to the database."""
    session = get_session()
    schema = get_schema()
    ddl = SchemaDDL(schema)
    applied = []
    errors = []
    for stmt in ddl.generate_all():
        try:
            session.execute(stmt)
            applied.append(stmt)
        except Exception as e:
            errors.append({"statement": stmt, "error": str(e)})
    return {"applied": len(applied), "errors": errors}


# ---------------------------------------------------------------------------
# Routes: Schema Diff (uses SchemaDiff)
# ---------------------------------------------------------------------------


@app.post("/api/schema/diff")
async def schema_diff(req: SchemaDiffRequest):
    """Compute DDL diff between old and new label sets."""
    try:
        old_models = [m for m in ALL_MODELS if hasattr(m, "__label__") and m.__label__ in req.old_labels]
        new_models = [m for m in ALL_MODELS if hasattr(m, "__label__") and m.__label__ in req.new_labels]

        old_schema = GraphSchema.from_models(old_models) if old_models else GraphSchema.from_models([])
        new_schema = GraphSchema.from_models(new_models) if new_models else GraphSchema.from_models([])

        diff = SchemaDiff(old_schema, new_schema)
        return {
            "has_changes": diff.has_changes,
            "diff": diff.to_dict(),
            "migration_ddl": diff.migration_ddl(),
            "summary": diff.summary(),
        }
    except Exception as e:
        raise HTTPException(500, f"Schema diff failed: {e}")


# ---------------------------------------------------------------------------
# Routes: Agent Tools (uses AgentTools)
# ---------------------------------------------------------------------------


@app.get("/api/agent-tools")
async def get_agent_tools():
    """Return OpenAI-formatted tool specs for the graph schema."""
    try:
        schema = get_schema()
        agent = AgentTools(schema)
        return {
            "tools": agent.all_tool_specs(),
            "schema_context": agent.schema_context_for_prompt(),
        }
    except Exception as e:
        raise HTTPException(500, f"Agent tools generation failed: {e}")


# ---------------------------------------------------------------------------
# Routes: Graph RAG Answer
# ---------------------------------------------------------------------------


RAG_ANSWER_PROMPT = """You are a biomedical research assistant. Given the user's question and
the database results below, provide a clear, natural language answer. Cite specific data from the results.

Question: {question}

Database results (from Cypher query: {cypher}):
{results}

Provide a concise, informative answer based solely on the data above."""


@app.post("/api/rag")
async def graph_rag_answer(req: RAGRequest):
    """Full RAG pipeline: NL -> Cypher -> execute -> LLM answer."""
    session = get_session()
    history = get_history()

    # Step 1: Generate Cypher from question
    async with httpx.AsyncClient(timeout=30) as client:
        cypher_resp = await client.post(
            "https://api.deepseek.com/chat/completions",
            headers={
                "Authorization": f"Bearer {DEEPSEEK_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": req.question},
                ],
                "temperature": 0.1,
                "max_tokens": 500,
            },
        )

    if cypher_resp.status_code != 200:
        raise HTTPException(502, f"DeepSeek API error (cypher generation): {cypher_resp.text}")

    data = cypher_resp.json()
    cypher_raw = data["choices"][0]["message"]["content"].strip()
    cypher = cypher_raw.strip("`").removeprefix("cypher\n").removeprefix("cypher").strip()

    # Step 2: Execute Cypher via GraphSession
    try:
        records = session.execute(cypher)
    except Exception as e:
        history.add(cypher, error=str(e), summary=f"RAG: {req.question}")
        return {"answer": f"Query execution failed: {e}", "cypher": cypher, "records_used": 0}

    # Clean embeddings
    cleaned = []
    for r in records:
        row = {}
        for k, v in r.items():
            if isinstance(v, dict):
                row[k] = strip_embeddings(v)
            elif isinstance(v, list) and v and isinstance(v[0], float) and len(v) > 10:
                continue
            else:
                row[k] = v
        cleaned.append(row)

    if not cleaned:
        history.add(cypher, result_count=0, summary=f"RAG: {req.question}")
        return {"answer": "No results found for your question.", "cypher": cypher, "records_used": 0}

    # Step 3: Generate natural language answer
    results_text = "\n".join(str(r) for r in cleaned[:20])
    answer_prompt = RAG_ANSWER_PROMPT.format(
        question=req.question,
        cypher=cypher,
        results=results_text,
    )

    async with httpx.AsyncClient(timeout=30) as client:
        answer_resp = await client.post(
            "https://api.deepseek.com/chat/completions",
            headers={
                "Authorization": f"Bearer {DEEPSEEK_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "deepseek-chat",
                "messages": [
                    {"role": "user", "content": answer_prompt},
                ],
                "temperature": 0.3,
                "max_tokens": 1000,
            },
        )

    if answer_resp.status_code != 200:
        raise HTTPException(502, f"DeepSeek API error (answer generation): {answer_resp.text}")

    answer_data = answer_resp.json()
    answer = answer_data["choices"][0]["message"]["content"].strip()

    history.add(cypher, result_count=len(cleaned), summary=f"RAG: {req.question}")
    return {"answer": answer, "cypher": cypher, "records_used": len(cleaned)}


# ---------------------------------------------------------------------------
# Routes: Bulk Import (uses BulkOps)
# ---------------------------------------------------------------------------


@app.post("/api/bulk-import")
async def bulk_import(req: BulkImportRequest):
    """Bulk-create nodes using BulkOps.bulk_create_nodes() — UNWIND-based."""
    if not req.items:
        raise HTTPException(400, "No items provided")

    session = get_session()
    model_cls = MODEL_MAP.get(req.label)

    if model_cls:
        cypher, params = BulkOps.bulk_create_nodes(model_cls, req.items)
        result = session.execute(cypher, params)
        count = len(result) if result else len(req.items)
        return {"created": count, "label": req.label, "method": "BulkOps.bulk_create_nodes"}

    # Fallback for unknown labels
    if not req.label.isidentifier():
        raise HTTPException(400, f"Invalid label: {req.label}")

    cypher = (
        "UNWIND $items AS item "
        f"CREATE (n:{req.label}) SET n = item "
        "RETURN count(n) AS created"
    )
    result = session.execute(cypher, {"items": req.items})
    count = result[0]["created"] if result else 0
    return {"created": count, "label": req.label, "method": "raw_unwind"}


# ---------------------------------------------------------------------------
# Routes: Query Plan (Validation + Execution)
# ---------------------------------------------------------------------------


@app.post("/api/query-plan")
async def execute_query_plan(req: QueryPlanRequest):
    """Validate and return execution order for a multi-step query plan."""
    schema = get_schema()
    rust_schema = schema.to_cypher_schema()
    validator = CypherValidator(rust_schema)
    results = []

    for i, step in enumerate(req.steps):
        step_result: dict[str, Any] = {
            "step": i,
            "description": step.description,
            "depends_on": step.depends_on,
            "valid": True,
            "errors": [],
            "warnings": [],
        }

        try:
            vresult = validator.validate(step.cypher)
            step_result["valid"] = vresult.is_valid
            step_result["errors"] = [
                {"code": e.code, "message": e.message} for e in vresult.errors
            ]
            step_result["warnings"] = [
                {"code": w.code, "message": w.message} for w in vresult.warnings
            ]
        except Exception as e:
            step_result["valid"] = False
            step_result["errors"] = [{"code": "VALIDATION_ERROR", "message": str(e)}]

        for dep in step.depends_on:
            if dep < 0 or dep >= i:
                step_result["valid"] = False
                step_result["errors"].append({
                    "code": "INVALID_DEPENDENCY",
                    "message": f"Step {i} depends on invalid step {dep}",
                })

        results.append(step_result)

    execution_order = _topological_sort(results)
    all_valid = all(r["valid"] for r in results)

    return {
        "goal": req.goal,
        "steps": results,
        "execution_order": execution_order,
        "all_valid": all_valid,
    }


def _topological_sort(steps: list[dict]) -> list[int]:
    n = len(steps)
    visited = [False] * n
    order = []

    def visit(i: int, visiting: set):
        if i in visiting:
            return
        if visited[i]:
            return
        visiting.add(i)
        for dep in steps[i]["depends_on"]:
            if 0 <= dep < n:
                visit(dep, visiting)
        visiting.discard(i)
        visited[i] = True
        order.append(i)

    for i in range(n):
        if not visited[i]:
            visit(i, set())

    return order


# ---------------------------------------------------------------------------
# Routes: Query Builder Demo
# ---------------------------------------------------------------------------


@app.get("/api/query/researchers")
async def query_researchers(
    specialization: str = "",
    min_h_index: int = 0,
    limit: int = 25,
):
    """Demo of Query builder: find researchers with filters."""
    session = get_session()
    q = Query().match(Researcher, var="r")

    filters_applied = False
    if specialization:
        q = q.where(f"r.specialization CONTAINS $spec").param("spec", specialization)
        filters_applied = True
    if min_h_index > 0:
        if filters_applied:
            q = q.and_where(f"r.h_index >= $min_h").param("min_h", min_h_index)
        else:
            q = q.where(f"r.h_index >= $min_h").param("min_h", min_h_index)

    q = q.return_("r").order_by("r.h_index DESC").limit(limit)
    cypher, params = q.build()
    results = session.execute(cypher, params)
    cleaned = []
    for r in results:
        node = r.get("r", {})
        if isinstance(node, dict):
            node = strip_embeddings(node)
        cleaned.append(node)
    return {"results": cleaned, "cypher": cypher, "count": len(cleaned)}


@app.get("/api/query/papers-by-disease")
async def query_papers_by_disease(disease: str, limit: int = 25):
    """Demo of Query builder: find papers studying a disease."""
    session = get_session()
    q = (Query()
         .match(Paper, var="p")
         .raw("-[:STUDIES]->(d:Disease)")
         .where("d.name CONTAINS $disease")
         .param("disease", disease)
         .return_("p.title AS title", "p.journal AS journal",
                  "p.year AS year", "p.citation_count AS citations", "d.name AS disease")
         .order_by("p.citation_count DESC")
         .limit(limit))

    cypher, params = q.build()
    results = session.execute(cypher, params)
    return {"results": results, "cypher": cypher, "count": len(results)}


@app.get("/api/query/drug-targets")
async def query_drug_targets(drug: str = ""):
    """Demo of Query builder: find drug → gene targets."""
    session = get_session()
    q = Query().match(Drug, var="d").raw("-[t:TARGETS]->(g:Gene)")

    if drug:
        q = q.where("d.name CONTAINS $drug").param("drug", drug)

    q = (q.return_("d.name AS drug", "g.symbol AS gene",
                   "g.full_name AS gene_name", "t.action AS action",
                   "g.pathway AS pathway")
          .order_by("d.name"))
    cypher, params = q.build()
    results = session.execute(cypher, params)
    return {"results": results, "cypher": cypher, "count": len(results)}
