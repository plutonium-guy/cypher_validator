"""Biomedical Research Knowledge Graph — FastAPI + 3D visualization demo.

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
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from neo4j import GraphDatabase

# ---------------------------------------------------------------------------
# Neo4j wrapper
# ---------------------------------------------------------------------------

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASS = os.getenv("NEO4J_PASSWORD", "testtest12")
DEEPSEEK_KEY = os.getenv("DEEPSEEK_API_KEY", "sk-81d6ee56f11045f4b558c5e63062eeaa")
EMBED_MODEL = os.getenv("EMBED_MODEL", "all-MiniLM-L6-v2")


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
_embed_model = None


def get_embedder():
    global _embed_model
    if _embed_model is None:
        from sentence_transformers import SentenceTransformer
        _embed_model = SentenceTransformer(EMBED_MODEL)
    return _embed_model


def embed_text(text: str) -> list[float]:
    model = get_embedder()
    return model.encode(text).tolist()


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


# ---------------------------------------------------------------------------
# Routes: Graph data
# ---------------------------------------------------------------------------


@app.get("/")
async def index():
    return FileResponse("static/index.html")


@app.get("/api/graph")
async def get_full_graph(limit: int = Query(default=500, le=2000)):
    """Return all nodes and relationships for 3D visualization."""
    nodes = db.execute(
        "MATCH (n) "
        "RETURN elementId(n) AS id, labels(n) AS labels, properties(n) AS props "
        "LIMIT $limit",
        {"limit": limit},
    )

    rels = db.execute(
        "MATCH (a)-[r]->(b) "
        "RETURN elementId(r) AS id, type(r) AS type, "
        "elementId(a) AS source, elementId(b) AS target, "
        "properties(r) AS props "
        "LIMIT $limit",
        {"limit": limit * 3},
    )

    # Strip embedding vectors from props (too large for frontend)
    for n in nodes:
        if isinstance(n.get("props"), dict):
            for key in list(n["props"].keys()):
                if "embedding" in key.lower():
                    n["props"].pop(key)

    return {"nodes": nodes, "relationships": rels}


@app.get("/api/graph/filtered")
async def get_filtered_graph(
    labels: str = Query(default="", description="Comma-separated labels to include"),
    rel_types: str = Query(default="", description="Comma-separated rel types"),
):
    """Get filtered subgraph."""
    label_list = [l.strip() for l in labels.split(",") if l.strip()] if labels else []
    rel_list = [r.strip() for r in rel_types.split(",") if r.strip()] if rel_types else []

    if label_list:
        label_filter = " OR ".join(f"'{l}' IN labels(n)" for l in label_list)
        nodes = db.execute(
            f"MATCH (n) WHERE {label_filter} "
            "RETURN elementId(n) AS id, labels(n) AS labels, properties(n) AS props"
        )
    else:
        nodes = db.execute(
            "MATCH (n) RETURN elementId(n) AS id, labels(n) AS labels, properties(n) AS props"
        )

    node_ids = {n["id"] for n in nodes}

    if rel_list:
        rel_filter = " OR ".join(f"type(r) = '{r}'" for r in rel_list)
        rels = db.execute(
            f"MATCH (a)-[r]->(b) WHERE ({rel_filter}) "
            "RETURN elementId(r) AS id, type(r) AS type, "
            "elementId(a) AS source, elementId(b) AS target, properties(r) AS props"
        )
    else:
        rels = db.execute(
            "MATCH (a)-[r]->(b) "
            "RETURN elementId(r) AS id, type(r) AS type, "
            "elementId(a) AS source, elementId(b) AS target, properties(r) AS props"
        )

    rels = [r for r in rels if r["source"] in node_ids and r["target"] in node_ids]

    for n in nodes:
        if isinstance(n.get("props"), dict):
            for key in list(n["props"].keys()):
                if "embedding" in key.lower():
                    n["props"].pop(key)

    return {"nodes": nodes, "relationships": rels}


@app.get("/api/schema")
async def get_schema():
    """Return graph schema (labels, rel types, properties)."""
    labels = db.execute(
        "MATCH (n) UNWIND labels(n) AS label "
        "WITH label, keys(n) AS ks UNWIND ks AS k "
        "WITH label, collect(DISTINCT k) AS props "
        "RETURN label, props ORDER BY label"
    )
    rels = db.execute(
        "MATCH (a)-[r]->(b) "
        "WITH type(r) AS rtype, labels(a)[0] AS src, labels(b)[0] AS tgt, keys(r) AS ks "
        "UNWIND CASE WHEN size(ks) = 0 THEN [null] ELSE ks END AS k "
        "RETURN rtype, src, tgt, collect(DISTINCT k) AS props "
        "ORDER BY rtype"
    )
    return {"labels": labels, "relationships": rels}


@app.get("/api/stats")
async def get_stats():
    """Basic graph statistics."""
    result = db.execute(
        "MATCH (n) WITH labels(n)[0] AS label, count(n) AS cnt "
        "RETURN label, cnt ORDER BY cnt DESC"
    )
    rel_result = db.execute(
        "MATCH ()-[r]->() WITH type(r) AS rtype, count(r) AS cnt "
        "RETURN rtype, cnt ORDER BY cnt DESC"
    )
    total_nodes = db.execute("MATCH (n) RETURN count(n) AS total")
    total_rels = db.execute("MATCH ()-[r]->() RETURN count(r) AS total")
    return {
        "total_nodes": total_nodes[0]["total"],
        "total_relationships": total_rels[0]["total"],
        "node_counts": result,
        "rel_counts": rel_result,
    }


# ---------------------------------------------------------------------------
# Routes: CRUD
# ---------------------------------------------------------------------------


@app.post("/api/nodes")
async def create_node(req: NodeCreate):
    """Create a new node."""
    props = {k: v for k, v in req.properties.items() if v is not None}
    # Build parameterized SET clause
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

    result = db.execute(cypher, params)
    if not result:
        raise HTTPException(500, "Failed to create node")
    return result[0]


@app.put("/api/nodes")
async def update_node(req: NodeUpdate):
    """Update node properties."""
    set_parts = []
    params = {"eid": req.element_id}
    for i, (k, v) in enumerate(req.properties.items()):
        if "embedding" in k.lower():
            continue
        pname = f"p{i}"
        set_parts.append(f"n.{k} = ${pname}")
        params[pname] = v

    if not set_parts:
        raise HTTPException(400, "No properties to update")

    set_clause = ", ".join(set_parts)
    result = db.execute(
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
    result = db.execute(
        "MATCH (n) WHERE elementId(n) = $eid DETACH DELETE n RETURN count(*) AS deleted",
        {"eid": element_id},
    )
    return {"deleted": True}


@app.post("/api/relationships")
async def create_relationship(req: RelationshipCreate):
    """Create a relationship between two nodes."""
    props = req.properties
    params = {"src": req.source_id, "tgt": req.target_id}
    prop_parts = []
    for i, (k, v) in enumerate(props.items()):
        pname = f"rp{i}"
        prop_parts.append(f"{k}: ${pname}")
        params[pname] = v

    prop_clause = f" {{{', '.join(prop_parts)}}}" if prop_parts else ""
    result = db.execute(
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
    set_parts = []
    params = {"eid": req.element_id}
    for i, (k, v) in enumerate(req.properties.items()):
        pname = f"rp{i}"
        set_parts.append(f"r.{k} = ${pname}")
        params[pname] = v

    if not set_parts:
        raise HTTPException(400, "No properties to update")

    set_clause = ", ".join(set_parts)
    result = db.execute(
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
    db.execute(
        "MATCH ()-[r]->() WHERE elementId(r) = $eid DELETE r",
        {"eid": element_id},
    )
    return {"deleted": True}


# ---------------------------------------------------------------------------
# Routes: NL Query (DeepSeek)
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
- (Paper)-[:AUTHORED_BY {position}]->(Researcher)
- (Researcher)-[:AFFILIATED_WITH {role, since}]->(Institution)
- (Paper)-[:CITES {context}]->(Paper)
- (Paper)-[:STUDIES]->(Disease)
- (Disease)-[:TREATS_WITH {efficacy}]->(Drug)
- (Drug)-[:TARGETS {action}]->(Gene)
- (Disease)-[:ASSOCIATED_WITH {evidence_level}]->(Gene)
- (ClinicalTrial)-[:TESTS]->(Drug)
- (ClinicalTrial)-[:TRIAL_FOR]->(Disease)
- (Paper)-[:FUNDED_BY {grant_id, amount_usd}]->(FundingAgency)
- (Researcher)-[:COLLABORATES_WITH {paper_count, since}]->(Researcher)

Rules:
- Return ONLY the Cypher query, no explanation
- Always use parameterized queries where possible
- Use LIMIT to cap results (default 25)
- Include relevant properties in RETURN, not just nodes
- For name lookups use CONTAINS (case-sensitive) for partial matching
"""


@app.post("/api/nl-query")
async def nl_query(req: NLQueryRequest):
    """Convert natural language to Cypher via DeepSeek and execute."""
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
        records = db.execute(cypher)
        # Clean embeddings from results
        cleaned = []
        for r in records:
            row = {}
            for k, v in r.items():
                if isinstance(v, dict):
                    row[k] = {pk: pv for pk, pv in v.items() if "embedding" not in pk.lower()}
                elif isinstance(v, list) and v and isinstance(v[0], float) and len(v) > 10:
                    continue
                else:
                    row[k] = v
            cleaned.append(row)
        return {"cypher": cypher, "records": cleaned, "count": len(cleaned)}
    except Exception as e:
        return {"cypher": cypher, "error": str(e), "records": [], "count": 0}


# ---------------------------------------------------------------------------
# Routes: Semantic search
# ---------------------------------------------------------------------------


@app.post("/api/semantic-search")
async def semantic_search(req: SemanticSearchRequest):
    """Embed query text and run vector similarity search."""
    vector = embed_text(req.query)
    index_name = f"idx_{req.label.lower()}_{req.property}_vector"

    # Check if vector index exists
    try:
        results = db.execute(
            "CALL db.index.vector.queryNodes($idx, $topk, $vec) "
            "YIELD node, score "
            "RETURN node, score",
            {"idx": index_name, "topk": req.top_k, "vec": vector},
        )
        cleaned = []
        for r in results:
            node_data = r.get("node", {})
            if isinstance(node_data, dict):
                node_data = {k: v for k, v in node_data.items() if "embedding" not in k.lower()}
            cleaned.append({"node": node_data, "score": r.get("score", 0)})
        return {"results": cleaned, "query": req.query, "index": index_name}
    except Exception as e:
        return {"error": str(e), "results": [], "hint": "Vector indexes may not exist. Run seed.py with embeddings first."}


# ---------------------------------------------------------------------------
# Routes: Seed
# ---------------------------------------------------------------------------


@app.post("/api/seed")
async def seed_data(with_embeddings: bool = Query(default=False)):
    """Seed the database with sample biomedical data."""
    from seed import seed_database

    embed_fn = embed_text if with_embeddings else None
    nodes, rels = seed_database(db, embed_fn)
    return {"nodes": nodes, "relationships": rels, "embeddings": with_embeddings}


# ---------------------------------------------------------------------------
# Routes: Node neighbors (for detail panel)
# ---------------------------------------------------------------------------


@app.get("/api/nodes/{element_id}/neighbors")
async def get_neighbors(element_id: str):
    """Get immediate neighbors of a node."""
    outgoing = db.execute(
        "MATCH (n)-[r]->(m) WHERE elementId(n) = $eid "
        "RETURN type(r) AS rel_type, properties(r) AS rel_props, "
        "elementId(m) AS id, labels(m) AS labels, properties(m) AS props",
        {"eid": element_id},
    )
    incoming = db.execute(
        "MATCH (m)-[r]->(n) WHERE elementId(n) = $eid "
        "RETURN type(r) AS rel_type, properties(r) AS rel_props, "
        "elementId(m) AS id, labels(m) AS labels, properties(m) AS props",
        {"eid": element_id},
    )

    for lst in [outgoing, incoming]:
        for n in lst:
            if isinstance(n.get("props"), dict):
                for key in list(n["props"].keys()):
                    if "embedding" in key.lower():
                        n["props"].pop(key)

    return {"outgoing": outgoing, "incoming": incoming}
