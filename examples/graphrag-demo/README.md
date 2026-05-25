# Biomedical Knowledge Graph Explorer

Interactive 3D graph visualization demo with NL→Cypher (DeepSeek), semantic vector search (HuggingFace), and full CRUD editing.

## Features

- **3D Force Graph** — all nodes and relationships rendered in 3D with WebGL
- **Natural Language Query** — ask questions in English, DeepSeek converts to Cypher
- **Semantic Search** — vector similarity search on papers, researchers, diseases
- **Graph Editing** — create/edit/delete nodes and relationships from the UI
- **Filtering** — toggle node types and relationship types
- **Node Inspector** — click any node to see properties, edit them, view connections

## Domain: Biomedical Research

68 nodes, 108 relationships across 8 entity types:

| Entity | Count | Examples |
|--------|-------|---------|
| Researcher | 8 | Dr. Sarah Chen (Computational Genomics), Prof. James Okafor (Immuno-Oncology) |
| Institution | 8 | MIT, Stanford, Oxford, Memorial Sloan Kettering, RIKEN |
| Paper | 12 | EGFR resistance review (Nature Reviews Cancer), Lecanemab Phase III (NEJM) |
| Disease | 8 | NSCLC, Alzheimer's, Glioblastoma, AML, Rheumatoid Arthritis |
| Drug | 10 | Osimertinib, Pembrolizumab, Sotorasib, Lecanemab, Semaglutide |
| Gene | 12 | EGFR, TP53, BRCA1, KRAS, FLT3, APP, MAPT |
| ClinicalTrial | 5 | Phase 2-3 trials for NSCLC, Alzheimer's, AML, Glioma |
| FundingAgency | 5 | NIH/NCI, ERC, Wellcome Trust, DARPA |

11 relationship types: AUTHORED_BY, AFFILIATED_WITH, CITES, STUDIES, TREATS_WITH, TARGETS, ASSOCIATED_WITH, TESTS, TRIAL_FOR, FUNDED_BY, COLLABORATES_WITH.

## Quick Start

```bash
# 1. Start Neo4j
docker run -d --name neo4j-demo -p 7474:7474 -p 7687:7687 \
    -e NEO4J_AUTH=neo4j/testtest12 neo4j:5.26-community

# 2. Install deps
pip install -r requirements.txt

# 3. Seed data (with embeddings for vector search)
python seed.py

# 4. Create vector indexes (run after seeding)
python -c "
from neo4j import GraphDatabase
d = GraphDatabase.driver('bolt://localhost:7687', auth=('neo4j','testtest12'))
with d.session() as s:
    for idx in [
        \"CREATE VECTOR INDEX idx_paper_abstract_embedding_vector IF NOT EXISTS FOR (n:Paper) ON (n.abstract_embedding) OPTIONS {indexConfig: {\\\`vector.dimensions\\\`: 384, \\\`vector.similarity_function\\\`: 'cosine'}}\",
        \"CREATE VECTOR INDEX idx_researcher_bio_embedding_vector IF NOT EXISTS FOR (n:Researcher) ON (n.bio_embedding) OPTIONS {indexConfig: {\\\`vector.dimensions\\\`: 384, \\\`vector.similarity_function\\\`: 'cosine'}}\",
        \"CREATE VECTOR INDEX idx_disease_description_embedding_vector IF NOT EXISTS FOR (n:Disease) ON (n.description_embedding) OPTIONS {indexConfig: {\\\`vector.dimensions\\\`: 384, \\\`vector.similarity_function\\\`: 'cosine'}}\",
    ]:
        s.run(idx)
d.close()
"

# 5. Run
cd examples/graphrag-demo
uvicorn app:app --reload --port 8000

# 6. Open http://localhost:8000
```

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `NEO4J_URI` | `bolt://localhost:7687` | Neo4j connection |
| `NEO4J_USERNAME` | `neo4j` | Neo4j user |
| `NEO4J_PASSWORD` | `testtest12` | Neo4j password |
| `DEEPSEEK_API_KEY` | (built-in) | DeepSeek API key for NL→Cypher |
| `EMBED_MODEL` | `all-MiniLM-L6-v2` | HuggingFace embedding model |

## Tech Stack

- **Backend**: FastAPI + Neo4j Python driver
- **NL→Cypher**: DeepSeek API (`deepseek-chat`)
- **Embeddings**: Sentence-Transformers (`all-MiniLM-L6-v2`, 384-dim)
- **Vector Search**: Neo4j 5.11+ native vector indexes
- **3D Visualization**: [3d-force-graph](https://github.com/vasturiano/3d-force-graph) + Three.js
- **Graph CRUD**: Full create/update/delete via REST API
