# cypher_validator

A fast, schema-aware **Cypher query validator and generator** with optional **GLiNER2 relation-extraction** and **Graph RAG** support for LLM-driven graph database applications.

The core parser and validator are written in **Rust** (via [pyo3](https://pyo3.rs/) and [maturin](https://github.com/PyO3/maturin)) for performance. The GLiNER2 integration layer is pure Python and is an optional add-on.

📚 **Docs:** <https://plutonium-guy.github.io/cypher_validator/>

---

## Running the live integration tests

Most of the test suite runs offline. Around 60 ORM / pipeline tests exercise a real Neo4j instance and skip when no DB is reachable. To run the full suite:

```bash
docker run -d --name neo4j-cv \
    -p 7474:7474 -p 7687:7687 \
    -e NEO4J_AUTH=neo4j/testtest12 \
    neo4j:5.26-community

export NEO4J_URI=bolt://localhost:7687
export NEO4J_USERNAME=neo4j         # alias: NEO4J_USER
export NEO4J_PASSWORD=testtest12    # alias: NEO4J_PASS

pytest tests/ -q
```

Both env-name conventions (`NEO4J_USERNAME/PASSWORD` and `NEO4J_USER/PASS`) are accepted — `tests/conftest.py` mirrors them at collection time so older test modules and the newer ORM suite agree.

Stop the container when done:

```bash
docker rm -f neo4j-cv
```

---

## Table of contents

* [Features](#features)
* [Installation](#installation)
* [Quick start](#quick-start)
* [Core API](#core-api): Schema, CypherValidator, ValidationResult, CypherGenerator, parse_query / QueryInfo
* [GLiNER2 integration](#gliner2-integration): NLToCypher, DB-aware query generation, EntityNERExtractor, GLiNER2RelationExtractor, RelationToCypherConverter, Neo4jDatabase
* [LLM integration](#llm-integration): Schema prompt helpers, extract_cypher_from_text, repair_cypher, format_records, few_shot_examples, cypher_tool_spec, GraphRAGPipeline
* [LLM NL-to-Cypher pipeline](#llm-nl-to-cypher-pipeline): LLMNLToCypher, ingest_texts, ingest_document, ChunkResult, IngestionResult
* [Async & parallel ingestion](#async--parallel-ingestion): acall, aingest_texts, aingest_document, TokenBucketRateLimiter
* [Pydantic Cypher ORM](#pydantic-cypher-orm): NodeModel, RelationshipModel, Query builder, Repository, AgentTools, Traversal, BulkOps
* [What the validator checks](#what-the-validator-checks)
* [Generated query types](#generated-query-types)
* [Performance](#performance)
* [Type stubs and IDE support](#type-stubs-and-ide-support)
* [Project structure](#project-structure)
* [Examples](#examples)
* [Development](#development)

---

## Features

| Capability | Description |
|---|---|
| **Syntax validation** | Parses Cypher with a hand-written PEG grammar (Pest) and surfaces clear syntax errors |
| **Semantic validation** | Checks node labels, relationship types, properties, endpoint labels, relationship direction, and unbound variables against a user-supplied schema |
| **"Did you mean?" suggestions** | Typos in labels and relationship types produce helpful suggestions (e.g. `:Preson → did you mean :Person?`) via capped Levenshtein edit-distance |
| **Batch validation** | `validate_batch()` validates many queries in parallel using Rayon, releasing the Python GIL for the duration |
| **Query generation** | Generates syntactically correct and schema-valid Cypher queries for 13 common patterns |
| **Schema-free parsing** | Extracts labels, relationship types, and property keys from any query without requiring a schema |
| **Schema serialization** | `Schema.to_dict()`, `from_dict()`, `to_json()`, `from_json()`, and `merge()` for complete schema lifecycle management |
| **NL → Cypher** | Converts GLiNER2 relation-extraction output to MATCH / MERGE / CREATE queries with automatic deduplication |
| **DB-aware generation** | `db_aware=True` looks up every extracted entity in Neo4j before query generation — existing nodes are MATCHed, new ones are CREATEd inline, preventing duplicate nodes |
| **NER entity extraction** | `EntityNERExtractor` wraps spaCy or any HuggingFace Transformers NER pipeline to enrich entity-label resolution during DB-aware generation |
| **Zero-shot RE** | Wraps the `gliner2` model for natural-language relation extraction (optional) |
| **LLM schema context** | `to_prompt()`, `to_markdown()`, `to_cypher_context()` format the schema for LLM system prompts |
| **Cypher extraction** | `extract_cypher_from_text()` pulls Cypher out of any LLM response (fenced blocks, inline, plain text) |
| **Self-repair loop** | `repair_cypher()` feeds validation errors back to an LLM for iterative self-correction |
| **Result formatting** | `format_records()` renders Neo4j results as Markdown, CSV, JSON, or plain text for LLM context |
| **Few-shot examples** | `few_shot_examples()` auto-generates (description, Cypher) pairs for LLM prompting |
| **Tool spec builder** | `cypher_tool_spec()` produces Anthropic / OpenAI function-calling schemas for Cypher execution |
| **Graph RAG pipeline** | `GraphRAGPipeline` chains schema injection → Cypher generation → validation → execution → answer |
| **LLM NL-to-Cypher** | `LLMNLToCypher` generates Cypher from text via any OpenAI-compatible, Anthropic, or LangChain LLM with schema inference, validation, and repair |
| **Batch text ingestion** | `ingest_texts()` / `ingest_document()` — two-phase batch ingestion with auto-schema stabilization, MERGE-based deduplication, and provenance tracking |
| **Schema introspection** | `Neo4jDatabase.introspect_schema()` discovers the live DB schema automatically |
| **Pydantic ORM** | Declarative `NodeModel` / `RelationshipModel` with typed properties, validation, and Cypher generation |
| **Query builder** | Fluent chainable API: `Query().match(Person, "p").where(p.age > 18).return_(p.name)` |
| **Repository pattern** | `Repository(Person, db)` with `find_one`, `find_by`, `count`, `exists`, `create`, `merge`, `update`, `delete` |
| **AI agent tools** | Auto-generated OpenAI / Anthropic function-calling tool specs from your schema |
| **Graph traversal** | `Traversal.neighbors()`, `shortest_path()`, `subgraph()`, `degree()`, `common_neighbors()` |
| **Bulk operations** | UNWIND-based batch `create` / `merge` / `delete` for nodes and relationships |
| **Schema migrations** | `SchemaDDL` auto-generates constraints and indexes; `SchemaDiff` computes migration DDL |
| **Type stubs** | Full `.pyi` stub files for IDE autocompletion and mypy / pyright type checking |

---

## Installation

### Prerequisites

* Python ≥ 3.8
* Rust toolchain (for building from source — `rustup.rs`)
* `maturin` (install via `pip install maturin`)

### From source

```bash
# Clone the repository
git clone <repo-url>
cd cypher_validator

# Build and install in editable/development mode
maturin develop

# Or build an optimised release wheel
maturin build --release
pip install dist/cypher_validator-*.whl

```

### Optional dependencies

```bash
# Neo4j driver (required for execute=True and db_aware=True)
pip install "cypher_validator[neo4j]"

# NER with spaCy (EntityNERExtractor.from_spacy)
pip install "cypher_validator[ner-spacy]"
python -m spacy download en_core_web_sm   # or en_core_web_trf for transformer accuracy

# NER with HuggingFace Transformers (EntityNERExtractor.from_transformers)
pip install "cypher_validator[ner-transformers]"

# Everything at once
pip install "cypher_validator[neo4j,ner]"

```

---

## Quick start

```python
from cypher_validator import Schema, CypherValidator, CypherGenerator, parse_query

# 1. Define your graph schema
schema = Schema(
    nodes={
        "Person": ["name", "age"],
        "Movie":  ["title", "year"],
    },
    relationships={
        # rel_type: (source_label, target_label, [properties])
        "ACTED_IN": ("Person", "Movie", ["role"]),
        "DIRECTED": ("Person", "Movie", []),
    },
)

# 2. Validate a single query
validator = CypherValidator(schema)
result = validator.validate("MATCH (p:Person)-[:ACTED_IN]->(m:Movie) RETURN p.name, m.title")
print(result.is_valid)   # True

# 3. Validate with errors — get "did you mean?" suggestions
result = validator.validate("MATCH (p:Preson)-[:ACTEDIN]->(m:Movie) RETURN p")
print(result.is_valid)   # False
print(result.errors)
# ["Unknown node label: :Preson — did you mean :Person?",
#  "Unknown relationship type: :ACTEDIN — did you mean :ACTED_IN?"]

# 4. Validate multiple queries in parallel
results = validator.validate_batch([
    "MATCH (p:Person) RETURN p",
    "MATCH (p:Person)-[:ACTED_IN]->(m:Movie) RETURN p.name",
    "MATCH (x:BadLabel) RETURN x",
])
for r in results:
    print(r.is_valid, r.errors)

# 5. Round-trip schema serialization
d = schema.to_dict()
schema2 = Schema.from_dict(d)

# … or as a JSON string
json_str = schema.to_json()
schema3  = Schema.from_json(json_str)

# 6. Merge two schemas
s_extra = Schema({"Director": ["name"]}, {"DIRECTED": ("Director", "Movie", [])})
merged  = schema.merge(s_extra)   # union of labels, types, and properties

# 7. Generate random valid queries
gen = CypherGenerator(schema, seed=42)
print(gen.generate("match_relationship"))
# MATCH (a:Person)-[r:ACTED_IN]->(b:Movie) RETURN a, r, b

# Generate many queries at once (avoids per-call Python overhead)
batch = gen.generate_batch("match_return", 100)

# 8. NL → Cypher with GLiNER2 (no boilerplate — this is the recommended entry point)
from cypher_validator import NLToCypher
pipeline = NLToCypher.from_pretrained("fastino/gliner2-large-v1", schema=schema)
cypher = pipeline(
    "Tom Hanks acted in Cast Away.",
    ["acted_in"],
    mode="merge",
)
# MERGE (a0:Person {name: $a0_val})-[:ACTED_IN]->(b0:Movie {name: $b0_val})
# RETURN a0, b0

# 10. Parse without a schema — also extracts property keys
info = parse_query("MATCH (p:Person)-[:ACTED_IN]->(m:Movie) RETURN p.name, m.year")
print(info.is_valid)        # True
print(info.labels_used)     # ['Movie', 'Person']
print(info.rel_types_used)  # ['ACTED_IN']
print(info.properties_used) # ['name', 'year']

```

---

## Core API

### Schema

Describes the graph model: node labels with their allowed properties, and relationship types with their source label, target label, and allowed properties.

```python
from cypher_validator import Schema

schema = Schema(
    nodes={
        "Person":  ["name", "age", "email"],
        "Company": ["name", "founded"],
        "City":    ["name", "population"],
    },
    relationships={
        # "REL_TYPE": ("SourceLabel", "TargetLabel", ["prop1", "prop2"])
        "WORKS_FOR":        ("Person",  "Company", ["since", "role"]),
        "LIVES_IN":         ("Person",  "City",    []),
        "HEADQUARTERED_IN": ("Company", "City",    []),
    },
)

```

**Schema inspection methods:**

```python
schema.node_labels()               # ["City", "Company", "Person"]
schema.rel_types()                 # ["HEADQUARTERED_IN", "LIVES_IN", "WORKS_FOR"]
schema.has_node_label("Person")    # True
schema.has_rel_type("WORKS_FOR")   # True

schema.node_properties("Person")   # ["name", "age", "email"]
schema.rel_properties("WORKS_FOR") # ["since", "role"]
schema.rel_endpoints("WORKS_FOR")  # ("Person", "Company")

```

**Round-trip serialization:**

```python
# Export to a plain Python dict (JSON-serializable)
d = schema.to_dict()
# {
#   "nodes": {"Person": ["name", "age", "email"], ...},
#   "relationships": {"WORKS_FOR": ["Person", "Company", ["since", "role"]], ...}
# }

# Reconstruct from a dict (e.g. loaded from JSON)
import json
with open("schema.json") as f:
    schema2 = Schema.from_dict(json.load(f))

# or directly
schema2 = Schema.from_dict(d)

```

**JSON serialization (`to_json` / `from_json`):**

```python
# Serialise to a compact JSON string
json_str = schema.to_json()
# '{"nodes":{"Person":["age","email","name"],...},...}'

# Restore from the JSON string
schema2 = Schema.from_json(json_str)

# Store/load via a file
with open("schema.json", "w") as f:
    f.write(schema.to_json())

with open("schema.json") as f:
    schema3 = Schema.from_json(f.read())

```

**Merging schemas (`merge`):**

```python
s1 = Schema(
    nodes={"Person": ["name", "age"]},
    relationships={"KNOWS": ("Person", "Person", [])},
)
s2 = Schema(
    nodes={"Movie": ["title"], "Person": ["email"]},   # Person gets extra property
    relationships={"ACTED_IN": ("Person", "Movie", ["role"])},
)
merged = s1.merge(s2)
merged.node_labels()               # ["Movie", "Person"]
merged.node_properties("Person")   # ["age", "email", "name"]  ← union
merged.rel_types()                 # ["ACTED_IN", "KNOWS"]

```

`Schema.from_dict()` is the preferred way to restore a schema from a plain dict produced by `to_dict()`.

---

### CypherValidator

Validates Cypher queries against a `Schema` in two phases:

1. **Syntax** — Parses the query with the Cypher PEG grammar.
2. **Semantic** — Checks labels, types, properties, directions, and variable scopes against the schema. Typos in labels and relationship types trigger a "did you mean?" suggestion using capped Levenshtein edit-distance.

```python
from cypher_validator import CypherValidator

validator = CypherValidator(schema)

# Single query
result = validator.validate("MATCH (p:Person)-[:WORKS_FOR]->(c:Company) RETURN p.name")
print(result.is_valid)   # True

# Batch validation — parallel Rayon execution, GIL released for the duration
results = validator.validate_batch([
    "MATCH (p:Person) RETURN p.name",
    "MATCH (p:Person)-[:WORKS_FOR]->(c:Company) RETURN p, c",
    "MATCH (x:Employe) RETURN x",   # typo
])
for r in results:
    print(r.is_valid, r.errors)
# True  []
# True  []
# False ["Unknown node label: :Employe — did you mean :Employee?"]

```

**`validate_batch()` notes:**

* Accepts a `list[str]` and returns a `list[ValidationResult]` in the same order.
* Validation is done in parallel on the Rust side using [Rayon](https://github.com/rayon-rs/rayon).
* The Python GIL is released for the entire batch, so other Python threads (e.g. an asyncio event loop) are not blocked.
* There is no minimum batch size — it is efficient even for a single query, though the overhead is negligible for small lists.

---

### ValidationResult

Returned by both `CypherValidator.validate()` and each element of `CypherValidator.validate_batch()`.

| Attribute | Type | Description |
| --- | --- | --- |
| `is_valid` | `bool` | `True` when no errors were found |
| `errors` | `list[str]` | All errors combined (syntax + semantic) |
| `syntax_errors` | `list[str]` | Parse / grammar errors only |
| `semantic_errors` | `list[str]` | Schema-level errors only |

Also supports `bool(result)` and `len(result)`:

```python
result = validator.validate(query)

if result:
    print("Valid!")
else:
    print(f"{len(result)} error(s):")
    for err in result.errors:
        print(" -", err)

# Categorised errors
print(result.syntax_errors)   # e.g. ["Parse error: …"]
print(result.semantic_errors) # e.g. ["Unknown node label: :Foo — did you mean :Bar?"]

```

**Example error messages:**

```
# Unknown label — with suggestion
"Unknown node label: :Preson — did you mean :Person?"

# Unknown label — no close match
"Unknown node label: :Actor"

# Unknown relationship type — with suggestion
"Unknown relationship type: :ACTEDIN — did you mean :ACTED_IN?"

# Property not in schema
"Unknown property 'salary' for node label :Person"

# Wrong relationship direction / endpoints
"Relationship :ACTED_IN expects source label :Person, but node has label(s): :Movie"
"Relationship :ACTED_IN expects target label :Movie, but node has label(s): :Person"

# Unbound variable
"Variable 'x' is not bound in this scope"

# WITH scope reset
"Variable 'n' is not bound in this scope"  # used after WITH that didn't project it

# Label used in SET/REMOVE
"Unknown node label: :Managr — did you mean :Manager?"

```

"Did you mean?" suggestions appear when a misspelled label or relationship type has a Levenshtein edit-distance of ≤ 2 from a known schema entry (case-insensitive comparison).

---

### CypherGenerator

Generates syntactically correct, schema-valid Cypher queries for rapid prototyping, testing, and dataset creation.

```python
from cypher_validator import CypherGenerator

gen = CypherGenerator(schema)           # random seed each run
gen = CypherGenerator(schema, seed=42)  # deterministic / reproducible output

query = gen.generate("match_return")
# "MATCH (n:Person) RETURN n LIMIT 17"

query = gen.generate("order_by")
# "MATCH (n:Movie) RETURN n ORDER BY n.year DESC LIMIT 5"

query = gen.generate("distinct_return")
# "MATCH (n:Person) RETURN DISTINCT n.name"

query = gen.generate("unwind")
# "MATCH (n:Person) UNWIND n.name AS item RETURN item"

# List all supported patterns
CypherGenerator.supported_types()
# ['match_return', 'match_where_return', 'create', 'merge', 'aggregation',
#  'match_relationship', 'create_relationship', 'match_set', 'match_delete',
#  'with_chain', 'distinct_return', 'order_by', 'unwind']

# Generate many queries in one call (avoids per-call Python overhead)
queries = gen.generate_batch("match_return", 500)  # list[str], len == 500

```

**Supported query types (13 total):**

| Type | Example output |
| --- | --- |
| `match_return` | `MATCH (n:Movie) RETURN n` |
| `match_where_return` | `MATCH (n:Person) WHERE n.name = "Alice" RETURN n.name` |
| `create` | `CREATE (n:Person {name: "Bob", age: 42}) RETURN n` |
| `merge` | `MERGE (n:Movie {title: $value}) RETURN n` |
| `aggregation` | `MATCH (n:Person) RETURN count(n.age) AS result` |
| `match_relationship` | `OPTIONAL MATCH (a:Person)-[r:ACTED_IN]->(b:Movie) RETURN a, r, b` |
| `create_relationship` | `MATCH (a:Person),(b:Movie) CREATE (a)-[r:ACTED_IN]->(b) RETURN r` |
| `match_set` | `MATCH (n:Person) SET n.name = "Carol" RETURN n` |
| `match_delete` | `MATCH (n:Movie) DETACH DELETE n` |
| `with_chain` | `MATCH (n:Person) WITH n.name AS val RETURN count(*)` |
| `distinct_return` | `MATCH (n:Person) RETURN DISTINCT n.name LIMIT 10` |
| `order_by` | `MATCH (n:Movie) RETURN n ORDER BY n.year DESC LIMIT 25` |
| `unwind` | `MATCH (n:Person) UNWIND n.age AS item RETURN item` |

Generated scalar values cycle through string literals (`"Alice"`), integers (`42`), booleans (`true`/`false`), and parameters (`$name`). `OPTIONAL MATCH` and `LIMIT` clauses are randomly included. All generated queries are guaranteed to pass `CypherValidator` with the same schema.

---

### parse_query / QueryInfo

Parse a Cypher string and extract structural information **without needing a schema**.

```python
from cypher_validator import parse_query

info = parse_query("MATCH (p:Person)-[:ACTED_IN]->(m:Movie) RETURN p.name, m.year")

info.is_valid        # True
info.errors          # []
info.labels_used     # ["Movie", "Person"]   (sorted, deduplicated)
info.rel_types_used  # ["ACTED_IN"]          (sorted, deduplicated)
info.properties_used # ["name", "year"]      (sorted, deduplicated)

bool(info)           # True  (same as is_valid)

# Invalid query
info = parse_query("THIS IS NOT CYPHER")
info.is_valid   # False
info.errors     # ["Parse error: …"]

```

`QueryInfo` attributes:

| Attribute | Type | Description |
| --- | --- | --- |
| `is_valid` | `bool` | Syntax check result |
| `errors` | `list[str]` | Syntax error messages (empty when valid) |
| `labels_used` | `list[str]` | Sorted, deduplicated node labels referenced in the query |
| `rel_types_used` | `list[str]` | Sorted, deduplicated relationship types referenced in the query |
| `properties_used` | `list[str]` | Sorted, deduplicated property keys accessed anywhere in the query |

`properties_used` collects every property key that appears in the query — in `RETURN`, `WHERE`, `SET`, inline node/relationship maps, `WITH`, `ORDER BY`, list comprehensions, etc. This is useful for dependency analysis, schema introspection, and query auditing without a schema.

```python
# Complex query — all property accesses are captured
info = parse_query("""
    MATCH (p:Person {age: 30})-[r:WORKS_FOR {since: 2020}]->(c:Company)
    WHERE p.name = "Alice" AND c.founded > 2000
    WITH p, p.email AS contact
    RETURN contact, c.name
    ORDER BY c.name
""")
info.properties_used
# ['age', 'email', 'founded', 'name', 'since']

```

---

## GLiNER2 integration

The GLiNER2 integration converts relation-extraction results into Cypher queries.

> **Most users should start with `NLToCypher**` — it wraps all three classes into a single callable that goes from raw text to Cypher (and optionally executes it against Neo4j) in one line.
> `RelationToCypherConverter` and `GLiNER2RelationExtractor` are lower-level building blocks exposed for advanced use cases.

### RelationToCypherConverter

A **pure-Python** class that converts any dict matching the GLiNER2 output format into a Cypher query. No ML model required.

```python
from cypher_validator import RelationToCypherConverter, Schema

# GLiNER2 extraction result
results = {
    "relation_extraction": {
        "works_for": [("John", "Apple Inc.")],
        "lives_in":  [("John", "San Francisco")],
        "founded":   [],   # requested but not found in text
    }
}

# Without schema (no node labels)
converter = RelationToCypherConverter()

# All three methods return (cypher_str, params_dict) — entity values are
# passed as $param placeholders to prevent Cypher injection.

# ── MATCH mode (find existing data) ────────────────────────────────────────
cypher, params = converter.to_match_query(results)
print(cypher)
# MATCH (a0 {name: $a0_val})-[:WORKS_FOR]->(b0 {name: $b0_val})
# MATCH (a1 {name: $a1_val})-[:LIVES_IN]->(b1 {name: $b1_val})
# RETURN a0, b0, a1, b1
print(params)
# {"a0_val": "John", "b0_val": "Apple Inc.", "a1_val": "John", "b1_val": "San Francisco"}

# ── MERGE mode (upsert) ────────────────────────────────────────────────────
cypher, params = converter.to_merge_query(results)

# ── CREATE mode (insert new) ───────────────────────────────────────────────
cypher, params = converter.to_create_query(results)

# ── Unified dispatcher ─────────────────────────────────────────────────────
cypher, params = converter.convert(results, mode="merge")

# Pass both to Neo4jDatabase.execute() — the driver handles escaping:
# results = db.execute(cypher, params)

```

**With a schema** — node labels are added automatically:

```python
schema = Schema(
    nodes={"Person": ["name"], "Company": ["name"], "City": ["name"]},
    relationships={
        "WORKS_FOR": ("Person", "Company", []),
        "LIVES_IN":  ("Person", "City",    []),
    },
)
converter = RelationToCypherConverter(schema=schema)
cypher, params = converter.to_merge_query(results)
print(cypher)
# MERGE (a0:Person {name: $a0_val})-[:WORKS_FOR]->(b0:Company {name: $b0_val})
# MERGE (a1:Person {name: $a1_val})-[:LIVES_IN]->(b1:City {name: $b1_val})
# RETURN a0, b0, a1, b1

```

**Multiple pairs of the same relation type:**

```python
results = {
    "relation_extraction": {
        "works_for": [
            ("John",  "Microsoft"),
            ("Mary",  "Google"),
            ("Bob",   "Apple"),
        ],
    }
}
cypher, params = converter.to_merge_query(results)
print(cypher)
# MERGE (a0:Person {name: $a0_val})-[:WORKS_FOR]->(b0:Company {name: $b0_val})
# MERGE (a1:Person {name: $a1_val})-[:WORKS_FOR]->(b1:Company {name: $b1_val})
# MERGE (a2:Person {name: $a2_val})-[:WORKS_FOR]->(b2:Company {name: $b2_val})
# RETURN a0, b0, a1, b1, a2, b2
print(params)
# {"a0_val": "John", "b0_val": "Microsoft", "a1_val": "Mary", ...}

```

**Automatic deduplication:**

If the same `(subject, object)` pair for a given relation type appears more than once in the extraction output (which can happen with overlapping model detections), the converter silently deduplicates them — each unique triple `(subject, relation, object)` appears exactly once in the generated Cypher:

```python
results = {
    "relation_extraction": {
        "works_for": [
            ("John", "Apple"),   # first occurrence
            ("John", "Apple"),   # duplicate — skipped
            ("Mary", "Apple"),   # different subject — kept
        ]
    }
}
# Only two MERGE clauses are emitted, not three

```

**Constructor parameters:**

| Parameter | Default | Description |
| --- | --- | --- |
| `schema` | `None` | `cypher_validator.Schema` for label-aware generation |
| `name_property` | `"name"` | Node property key used for entity text spans |

**`convert()` parameters:**

| Parameter | Default | Description |
| --- | --- | --- |
| `relations` | required | GLiNER2 output dict |
| `mode` | `"match"` | `"match"`, `"merge"`, or `"create"` |
| `return_clause` | auto | Custom `RETURN …` tail (e.g. `"RETURN *"`) |

**`to_db_aware_query()` — advanced low-level use:**

If you want to generate a MATCH/CREATE query without going through `NLToCypher`, you can call `to_db_aware_query()` directly after building the entity status dict yourself:

```python
converter = RelationToCypherConverter(schema=schema)

# entity_status maps each entity name to its DB lookup result
entity_status = {
    "John":       {"var": "e0", "label": "Person",  "param_key": "e0_val",
                   "found": True,  "introduced": False},  # exists in DB
    "Apple Inc.": {"var": "e1", "label": "Company", "param_key": "e1_val",
                   "found": False, "introduced": False},  # new
}

relations = {"relation_extraction": {"works_for": [("John", "Apple Inc.")]}}
cypher, params = converter.to_db_aware_query(relations, entity_status)
# MATCH (e0:Person {name: $e0_val})
# CREATE (e0)-[:WORKS_FOR]->(e1:Company {name: $e1_val})
# RETURN e0, e1

```

`NLToCypher._collect_entity_status()` builds this dict automatically from a live DB when `db_aware=True` is used — the low-level API is exposed for cases where you control the lookup yourself.

---

### DB-aware query generation

> **`db_aware=True`** is the flag that makes `NLToCypher` graph-state-aware.
> Without it, every call blindly CREATEs all entities, producing **duplicate nodes** for entities that already exist in the database.
> With it, each entity is looked up first and either MATCHed (existing) or CREATEd (new).

#### How it works

When `db_aware=True` is passed to `__call__()` or `extract_and_convert()`:

1. Relations are extracted from the text (same as normal).
2. Each unique entity is identified and its label is resolved from the schema (and optionally enriched by a `EntityNERExtractor`).
3. A `MATCH (n:Label {name: $val}) RETURN elementId(n) LIMIT 1` query is sent to Neo4j for each entity.
4. A mixed query is generated.
5. For **existing entities**, it adds `MATCH (eN:Label {name: $eN_val})` at the top.
6. For **new entities**, it adds `CREATE (eN:Label {name: $eN_val})` inline on first use; subsequent relations reuse the bare variable `eN`.
7. For **relationship edges**, it always adds `CREATE (eA)-[:REL]->(eB)`.

#### All four entity-existence combinations

```python
from cypher_validator import NLToCypher, Neo4jDatabase, Schema

schema = Schema(
    nodes={"Person": ["name"], "Company": ["name"]},
    relationships={"WORKS_FOR": ("Person", "Company", [])},
)
db = Neo4jDatabase("bolt://localhost:7687", "neo4j", "password")
pipeline = NLToCypher.from_pretrained("fastino/gliner2-large-v1", schema=schema, db=db)

```

**Case 1 — neither entity exists:**

```python
cypher = pipeline("John works for Apple Inc.", ["works_for"], db_aware=True)
# CREATE (e0:Person {name: $e0_val})-[:WORKS_FOR]->(e1:Company {name: $e1_val})
# RETURN e0, e1

```

**Case 2 — subject (John) exists, object is new:**

```python
# (John was previously inserted into the DB)
cypher = pipeline("John works for Apple Inc.", ["works_for"], db_aware=True)
# MATCH (e0:Person {name: $e0_val})
# CREATE (e0)-[:WORKS_FOR]->(e1:Company {name: $e1_val})
# RETURN e0, e1

```

**Case 3 — object (Apple Inc.) exists, subject is new:**

```python
cypher = pipeline("John works for Apple Inc.", ["works_for"], db_aware=True)
# MATCH (e1:Company {name: $e1_val})
# CREATE (e0:Person {name: $e0_val})-[:WORKS_FOR]->(e1)
# RETURN e1, e0

```

**Case 4 — both exist:**

```python
cypher = pipeline("John works for Apple Inc.", ["works_for"], db_aware=True)
# MATCH (e0:Person {name: $e0_val})
# MATCH (e1:Company {name: $e1_val})
# CREATE (e0)-[:WORKS_FOR]->(e1)
# RETURN e0, e1

```

#### Multiple relations — shared entity reuse

The same entity variable is introduced once and reused across all relations, regardless of how many it participates in:

```python
schema = Schema(
    nodes={"Person": ["name"], "Company": ["name"], "City": ["name"]},
    relationships={
        "WORKS_FOR": ("Person", "Company", []),
        "LIVES_IN":  ("Person", "City", []),
    },
)
pipeline = NLToCypher.from_pretrained(..., schema=schema, db=db)

# John exists in DB; Apple Inc. and San Francisco are new
cypher = pipeline(
    "John works for Apple Inc. and lives in San Francisco.",
    ["works_for", "lives_in"],
    db_aware=True,
)
# MATCH (e0:Person {name: $e0_val})          ← John MATCHed once
# CREATE (e0)-[:WORKS_FOR]->(e1:Company {name: $e1_val})   ← Apple created inline
# CREATE (e0)-[:LIVES_IN]->(e2:City {name: $e2_val})       ← SF created inline, e0 reused
# RETURN e0, e1, e2

```

When all three exist:

```python
# MATCH (e0:Person {name: $e0_val})
# MATCH (e1:Company {name: $e1_val})
# MATCH (e2:City {name: $e2_val})
# CREATE (e0)-[:WORKS_FOR]->(e1)   ← only edges are created
# CREATE (e0)-[:LIVES_IN]->(e2)
# RETURN e0, e1, e2

```

#### Combine `db_aware` with `execute`

```python
# Look up entities, generate query, AND execute it — all in one call
cypher, records = pipeline(
    "John works for Apple Inc.",
    ["works_for"],
    db_aware=True,
    execute=True,
)
# cypher  → mixed MATCH/CREATE string
# records → [{"e0": <Node John>, "e1": <Node Apple Inc.>}]

```

#### Why this matters vs. plain `execute=True`

```python
# ── Without db_aware (legacy) ─────────────────────────────────────────────
# John is already in the DB — this creates a second John node:
cypher, _ = pipeline("John works for Apple Inc.", ["works_for"],
                     mode="create", execute=True)
# CREATE (a0:Person {name: $a0_val})-[:WORKS_FOR]->(b0:Company {name: $b0_val})
# → John now appears TWICE in the database ✗

# ── With db_aware ─────────────────────────────────────────────────────────
cypher, _ = pipeline("John works for Apple Inc.", ["works_for"],
                     db_aware=True, execute=True)
# MATCH (e0:Person {name: $e0_val})
# CREATE (e0)-[:WORKS_FOR]->(e1:Company {name: $e1_val})
# → John reused, no duplicate ✓

```

---

### EntityNERExtractor

An optional NER wrapper that enriches entity-label resolution during DB-aware query generation. Useful when the schema is absent, incomplete, or when you want finer-grained entity typing (e.g. distinguishing `Person` from `Organization` for entities that appear as arguments of an unknown relation type).

Supports two backends — **spaCy** (fast, CPU-friendly) and **HuggingFace Transformers** (higher accuracy, GPU-optional):

```python
from cypher_validator import EntityNERExtractor

```

#### spaCy backend

```python
# pip install "cypher_validator[ner-spacy]"
# python -m spacy download en_core_web_sm

ner = EntityNERExtractor.from_spacy("en_core_web_sm")
ner.extract("John works for Apple Inc. and lives in San Francisco.")
# [
#   {"text": "John",          "label": "Person"},
#   {"text": "Apple Inc.",    "label": "Organization"},
#   {"text": "San Francisco", "label": "Location"},
# ]

```

Built-in spaCy label → graph node-label mappings:

| spaCy type | Graph label |
| --- | --- |
| `PERSON` | `Person` |
| `ORG` | `Organization` |
| `GPE` | `Location` |
| `LOC` | `Location` |
| `FAC` | `Facility` |
| `PRODUCT` | `Product` |
| `EVENT` | `Event` |
| `NORP` | `Group` |
| *(unknown)* | *type capitalised as-is* |

Override or extend with `label_map`:

```python
ner = EntityNERExtractor.from_spacy(
    "en_core_web_trf",
    label_map={"ORG": "Company", "GPE": "City"},   # override defaults
)

```

#### HuggingFace Transformers backend

```python
# pip install "cypher_validator[ner-transformers]"

# General English NER (default model)
ner = EntityNERExtractor.from_transformers(
    "dbmdz/bert-large-cased-finetuned-conll03-english"
)

# High-accuracy general NER
ner = EntityNERExtractor.from_transformers("Jean-Baptiste/roberta-large-ner-english")

# Biomedical NER — fine-tuned model (recommended for medical/scientific graphs)
ner = EntityNERExtractor.from_transformers(
    "d4data/biomedical-ner-all",
    label_map={
        "Medication":           "Drug",
        "Disease_disorder":     "Disease",
        "Sign_symptom":         "Symptom",
        "Biological_structure": "Anatomy",
        "Diagnostic_procedure": "Procedure",
    },
    aggregation_strategy="first",   # avoids subword fragments with this model
)

ner.extract("John works for Apple Inc.")
# [{"text": "John", "label": "Person"}, {"text": "Apple Inc.", "label": "Organization"}]

```

> **Note on `dmis-lab/biobert-v1.1`:** This is a *pre-trained language model*, not a fine-tuned NER classifier. When loaded as a token-classification pipeline it outputs generic `LABEL_0` / `LABEL_1` tags with no semantic meaning. Use it with a fully custom `label_map` (e.g. `{"LABEL_0": "BioEntity", "LABEL_1": "BioEntity"}`) if you only need candidate spans, or use a fine-tuned biomedical NER model such as `d4data/biomedical-ner-all` for semantic labels. See [examples/11_biobert_ner.py](https://www.google.com/search?q=examples/11_biobert_ner.py) for a detailed comparison.

Built-in HuggingFace label → graph node-label mappings:

| HF tag | Graph label |
| --- | --- |
| `PER` / `PERSON` | `Person` |
| `ORG` | `Organization` |
| `LOC` / `GPE` | `Location` |
| `MISC` | `Entity` |
| *(unknown)* | *tag capitalised as-is* |

#### Plugging the NER extractor into `NLToCypher`

When `ner_extractor` is supplied, its labels enrich or **override** schema-based label resolution for DB lookups. This is especially helpful when the schema doesn't cover all relation types:

```python
from cypher_validator import NLToCypher, EntityNERExtractor, Neo4jDatabase

ner = EntityNERExtractor.from_spacy("en_core_web_sm")
db  = Neo4jDatabase("bolt://localhost:7687", "neo4j", "password")

pipeline = NLToCypher.from_pretrained(
    "fastino/gliner2-large-v1",
    schema=schema,
    db=db,
    ner_extractor=ner,    # ← plugged in here
)

cypher = pipeline(
    "John works for Apple Inc.",
    ["works_for"],
    db_aware=True,
)
# NER identifies "John" as Person and "Apple Inc." as Organization
# DB lookup uses those labels for the MATCH query
# Generated Cypher uses the schema's "Company" label (schema wins when both provide a label)

```

**Label resolution priority (highest first):**

1. NER extractor label (when `ner_extractor` is set and entity text matches)
2. Schema endpoint label (derived from the relation type)
3. Empty string (no label in pattern)

**`EntityNERExtractor` API:**

| Method | Description |
| --- | --- |
| `EntityNERExtractor.from_spacy(model_name, label_map=None)` | Load a spaCy `nlp` model |
| `EntityNERExtractor.from_transformers(model_name, label_map=None, **kwargs)` | Load a HuggingFace NER pipeline |
| `extractor.extract(text)` | Return `list[{"text": str, "label": str}]` |

---

### GLiNER2RelationExtractor

Wraps a loaded `gliner2.GLiNER2` model and normalises its output to the standard format.

```python
from cypher_validator import GLiNER2RelationExtractor

# Load from HuggingFace Hub
extractor = GLiNER2RelationExtractor.from_pretrained("fastino/gliner2-large-v1")

# Or set a custom threshold
extractor = GLiNER2RelationExtractor.from_pretrained(
    "fastino/gliner2-large-v1",
    threshold=0.7,
)

text = "John works for Apple Inc. and lives in San Francisco."

results = extractor.extract_relations(
    text,
    relation_types=["works_for", "lives_in", "founded"],
)
# {
#     "relation_extraction": {
#         "works_for": [("John", "Apple Inc.")],
#         "lives_in":  [("John", "San Francisco")],
#         "founded":   [],   # requested but not found
#     }
# }

# Override threshold for a single call
results = extractor.extract_relations(
    text,
    ["works_for"],
    threshold=0.85,   # high precision
)

```

**Key behaviours:**

* Every requested relation type is **always present** in the output — missing types get an empty list.
* Works with both the wrapped (`{"relation_extraction": {...}}`) and flat (`{rel_type: [...]}`) model output formats.
* `threshold` set at construction becomes the default; it can be overridden per-call.

| Method / attribute | Description |
| --- | --- |
| `GLiNER2RelationExtractor.from_pretrained(model_name, threshold=0.5)` | Load from HuggingFace Hub or local path |
| `extractor.extract_relations(text, relation_types, threshold=None)` | Extract relations from text |
| `extractor.threshold` | Instance-level default confidence threshold |
| `GLiNER2RelationExtractor.DEFAULT_MODEL` | `"fastino/gliner2-large-v1"` |

---

### NLToCypher

> **This is the recommended entry point for most users.** It wraps the extractor and converter into one callable — you only need to supply text, relation types, and a mode.

End-to-end pipeline combining `GLiNER2RelationExtractor` and `RelationToCypherConverter`.

```python
from cypher_validator import NLToCypher, Schema

schema = Schema(
    nodes={"Person": ["name"], "Company": ["name"], "City": ["name"]},
    relationships={
        "WORKS_FOR": ("Person", "Company", []),
        "LIVES_IN":  ("Person", "City",    []),
    },
)

pipeline = NLToCypher.from_pretrained(
    "fastino/gliner2-large-v1",
    schema=schema,       # optional: enables label-aware generation
    threshold=0.5,
)

# Single sentence → Cypher
cypher = pipeline(
    "John works for Apple Inc. and lives in San Francisco.",
    relation_types=["works_for", "lives_in"],
    mode="merge",
)
# MERGE (a0:Person {name: $a0_val})-[:WORKS_FOR]->(b0:Company {name: $b0_val})
# MERGE (a1:Person {name: $a1_val})-[:LIVES_IN]->(b1:City {name: $b1_val})
# RETURN a0, b0, a1, b1

# Get both the raw extraction dict and the Cypher string
relations, cypher = pipeline.extract_and_convert(
    "Alice manages the Engineering team.",
    ["manages", "reports_to"],
    mode="match",
)
print(relations)
# {"relation_extraction": {"manages": [("Alice", "Engineering team")], "reports_to": []}}
print(cypher)
# MATCH (a0 {name: $a0_val})-[:MANAGES]->(b0 {name: $b0_val})
# RETURN a0, b0

# High-precision extraction
cypher = pipeline(
    "Bob acquired TechCorp in 2019.",
    ["acquired", "merged_with"],
    mode="merge",
    threshold=0.85,
)

```

**Database execution (`execute=True`):**

Pass a `Neo4jDatabase` to execute the generated query directly and receive both the Cypher string and the Neo4j records:

```python
from cypher_validator import NLToCypher, Neo4jDatabase

db = Neo4jDatabase("bolt://localhost:7687", "neo4j", "password")
pipeline = NLToCypher.from_pretrained("fastino/gliner2-large-v1", schema=schema, db=db)

# execute=True → returns (cypher, records) instead of just cypher
cypher, records = pipeline(
    "John works for Apple Inc.",
    ["works_for"],
    mode="create",
    execute=True,
)
# cypher  → 'CREATE (a0:Person {name: $a0_val})-[:WORKS_FOR]->(b0:Company {name: $b0_val})\nRETURN a0, b0'
# records → [{"a0": {...}, "b0": {...}}]

```

**Credentials from environment variables (`from_env`):**

```bash
export NEO4J_URI=bolt://localhost:7687
export NEO4J_USERNAME=neo4j        # optional, defaults to "neo4j"
export NEO4J_PASSWORD=secret

```

```python
pipeline = NLToCypher.from_env("fastino/gliner2-large-v1", schema=schema)
cypher, records = pipeline("John works for Apple Inc.", ["works_for"],
                           mode="create", execute=True)

```

**`from_pretrained()` / `from_env()` parameters:**

| Parameter | Default | Description |
| --- | --- | --- |
| `model_name` | `"fastino/gliner2-large-v1"` | HuggingFace model ID or local path |
| `schema` | `None` | Optional schema for label-aware Cypher |
| `threshold` | `0.5` | Confidence threshold for relation extraction |
| `name_property` | `"name"` | Node property key for entity text |
| `db` | `None` | `Neo4jDatabase` connection (`from_pretrained` only) |
| `database` | `"neo4j"` | Neo4j database name (`from_env` only) |
| `ner_extractor` | `None` | Optional `EntityNERExtractor` for enriched entity labels in DB-aware mode |

**`__call__()` / `extract_and_convert()` parameters:**

| Parameter | Default | Description |
| --- | --- | --- |
| `text` | required | Input sentence or passage |
| `relation_types` | required | Relation labels to extract |
| `mode` | `"match"` | Cypher generation mode (`"match"`, `"merge"`, `"create"`). Ignored when `db_aware=True`. |
| `threshold` | `None` | Override instance threshold |
| `execute` | `False` | When `True`, run the query against the DB and return `(cypher, records)` |
| `db_aware` | `False` | When `True`, look up each entity in the DB and generate MATCH/CREATE accordingly (see below) |
| `return_clause` | auto | Custom `RETURN …` tail |

---

### Neo4jDatabase

Thin wrapper around the official [Neo4j Python driver](https://neo4j.com/docs/python-manual/current/) for executing Cypher queries. Requires `pip install "cypher_validator[neo4j]"`.

```python
from cypher_validator import Neo4jDatabase

# Direct instantiation
db = Neo4jDatabase("bolt://localhost:7687", "neo4j", "password", database="neo4j")

# Context manager — driver is closed on exit
with Neo4jDatabase("bolt://localhost:7687", "neo4j", "password") as db:
    results = db.execute("MATCH (n:Person) RETURN n.name LIMIT 5")
    # [{"n.name": "Alice"}, {"n.name": "Bob"}, ...]

# With parameters
results = db.execute(
    "MATCH (n:Person {name: $name}) RETURN n",
    {"name": "Alice"},
)

# Run multiple queries in one call
queries = [
    "MATCH (n:Person) RETURN count(n)",
    "MATCH (n:Movie) RETURN count(n)",
]
all_results = db.execute_many(queries)
# [[{"count(n)": 42}], [{"count(n)": 17}]]

# With per-query parameters
all_results = db.execute_many(
    ["MATCH (n {name: $x}) RETURN n", "MATCH (n {name: $x}) RETURN n"],
    [{"x": "Alice"}, {"x": "Bob"}],
)

```

| Method | Description |
| --- | --- |
| `execute(cypher, parameters=None)` | Run one query, return `list[dict]` |
| `execute_many(queries, parameters_list=None)` | Run multiple queries, return `list[list[dict]]` |
| `close()` | Release driver connections |

---

## LLM integration

`cypher_validator` ships a dedicated set of helpers for building LLM-driven graph applications. All utilities are importable directly from the top-level package.

```python
from cypher_validator import (
    extract_cypher_from_text,
    format_records,
    repair_cypher,
    cypher_tool_spec,
    few_shot_examples,
    GraphRAGPipeline,
)

```

---

### Schema prompt helpers

Three methods on `Schema` format the graph model for LLM system prompts. Each targets a different LLM style:

```python
from cypher_validator import Schema

schema = Schema(
    nodes={"Person": ["name", "age"], "Company": ["name", "founded"]},
    relationships={"WORKS_FOR": ("Person", "Company", ["since", "role"])},
)

# ── Readable text (best for general-purpose LLMs) ─────────────────────────
print(schema.to_prompt())
# Graph Schema
# ============
#
# Nodes
# -----
#   :Person                     name, age
#   :Company                    name, founded
#
# Relationships
# -------------
#   :WORKS_FOR                  (Person)-->(Company)   since, role

# ── Markdown table (great for docs and chat UIs) ──────────────────────────
print(schema.to_markdown())
# ### Nodes
# | Label | Properties |
# |---|---|
# | :Company | founded, name |
# | :Person | age, name |
#
# ### Relationships
# | Type | Source → Target | Properties |
# |---|---|---|
# | :WORKS_FOR | :Person → :Company | role, since |

# ── Inline Cypher patterns (best for LLMs that know Cypher) ───────────────
print(schema.to_cypher_context())
# // Node labels and their properties
# (:Company {founded, name})
# (:Person {age, name})
#
# // Relationship types
# (:Person)-[:WORKS_FOR {role, since}]->(:Company)

```

Inject the output directly into your LLM system prompt:

```python
system_prompt = f"""You are a Cypher expert. Use this schema:

{schema.to_cypher_context()}

Rules: return ONLY the Cypher query inside a ```cypher

```

---

### extract_cypher_from_text

Parses a raw LLM response and returns the Cypher query string, regardless of how the LLM formatted its output:

```python
from cypher_validator import extract_cypher_from_text

# Fenced code block (most common)
extract_cypher_from_text("""
Sure! Here is the query:
```cypher
MATCH (p:Person)-[:WORKS_FOR]->(c:Company)
RETURN p.name, c.name

```""")

# "MATCH (p:Person)-[:WORKS_FOR]->(c:Company)\nRETURN p.name, c.name"

# Inline backtick

extract_cypher_from_text("Run `MATCH (n:Person) RETURN n` against your DB.")

# "MATCH (n:Person) RETURN n"

# Line-anchored (no formatting at all)

extract_cypher_from_text("MATCH (n:Person) RETURN n LIMIT 10")

# "MATCH (n:Person) RETURN n LIMIT 10"

```

Handles ` ```cypher `, ` ```sql `, plain ` ``` `, inline backticks, and bare Cypher lines — in that priority order.

---

### repair\_cypher

Validates a query and iteratively asks an LLM to fix it when it is invalid:

```python
from cypher_validator import CypherValidator, repair_cypher

validator = CypherValidator(schema)

def call_llm(query: str, errors: list[str]) -> str:
    """Your LLM wrapper — receives the bad query and the error list."""
    ...

# Start with an LLM-generated query that may contain mistakes
bad_query = "MATCH (n:Persn)-[:WORKFOR]->(c:Company) RETURN n"

fixed_query, result = repair_cypher(validator, bad_query, call_llm, max_retries=3)
# validator calls call_llm(bad_query, ["Unknown node label :Persn — did you mean :Person?", ...])
# then re-validates, retrying up to 3 times

if result.is_valid:
    print("Repaired:", fixed_query)
else:
    print("Could not repair:", result.errors)

```

The `errors` list passed to your LLM already contains "did you mean?" hints, making self-correction highly effective even with small models.

---

### format_records

Converts Neo4j result records into a string for injecting into LLM prompts:

```python
from cypher_validator import format_records

records = db.execute("MATCH (p:Person)-[:WORKS_FOR]->(c:Company) RETURN p.name, c.name LIMIT 3")

# Markdown table (default) — great for chat UIs and Claude
print(format_records(records))
# | p.name | c.name    |
# |--------|-----------|
# | Alice  | Acme Corp |
# | Bob    | TechStart |

# CSV — compact for token-limited contexts
print(format_records(records, format="csv"))
# p.name,c.name
# Alice,Acme Corp

# JSON — for structured output or downstream parsing
print(format_records(records, format="json"))

# Plain text — numbered records
print(format_records(records, format="text"))
# Record 1:
#   p.name: Alice
#   c.name: Acme Corp

```

`Neo4jDatabase.execute_and_format()` combines `execute()` and `format_records()` in one step:

```python
table = db.execute_and_format(
    "MATCH (p:Person)-[:WORKS_FOR]->(c:Company) RETURN p.name, c.name LIMIT 5"
)

```

---

### few_shot_examples

Generates labelled `(description, cypher)` pairs from your schema for few-shot LLM prompting:

```python
from cypher_validator import CypherGenerator, few_shot_examples

gen = CypherGenerator(schema, seed=42)
examples = few_shot_examples(gen, n=6)
# [
#   ("Return all :Person and :Company",             "MATCH (n:Person) RETURN n LIMIT 3"),
#   ("Find :Person matching a property condition",  "MATCH (n:Person) WHERE n.age = 30 RETURN n"),
#   ("Find :Person connected via :WORKS_FOR",       "MATCH (a:Person)-[r:WORKS_FOR]->(b:Company) RETURN a, r, b"),
#   ...
# ]

# Restrict to a specific type
create_examples = few_shot_examples(gen, n=3, query_type="create")

# Embed in a system prompt
shots = "\n\n".join(f"Q: {d}\nA:\n```cypher\n{c}\n```" for d, c in examples)
system_prompt = f"Generate Cypher for this schema.\n\nExamples:\n{shots}"

```

---

### cypher_tool_spec

Builds a tool/function-call specification for Cypher execution that works with both the Anthropic and OpenAI APIs:

```python
from cypher_validator import cypher_tool_spec

# ── Anthropic tool_use ─────────────────────────────────────────────────────
tool = cypher_tool_spec(schema, format="anthropic")
response = client.messages.create(
    model="claude-opus-4-6",
    tools=[tool],
    messages=[{"role": "user", "content": "Who works for Acme Corp?"}],
)
# When the model calls the tool:
# tool_input["cypher"]     → the generated Cypher query
# tool_input["parameters"] → optional $param values

# ── OpenAI function calling ────────────────────────────────────────────────
tool = cypher_tool_spec(schema, format="openai")
response = openai.chat.completions.create(
    model="gpt-4o",
    tools=[tool],
    messages=[{"role": "user", "content": "Who works for Acme Corp?"}],
)

# Optional: describe the database for better LLM guidance
tool = cypher_tool_spec(schema, db_description="HR knowledge graph", format="anthropic")

```

The schema's `to_cypher_context()` output is embedded in the tool description automatically when `schema` is provided, so the LLM knows exactly which labels and types to use.

---

### GraphRAGPipeline

The highest-level interface: a complete Graph RAG loop in a single class.

```python
from cypher_validator import GraphRAGPipeline, Neo4jDatabase, Schema
import openai

client = openai.OpenAI()   # reads OPENAI_API_KEY from environment

def call_llm(prompt: str) -> str:
    """Wrap your LLM here — must accept a string and return a string."""
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content

schema = Schema(
    nodes={"Person": ["name"], "Company": ["name"]},
    relationships={"WORKS_FOR": ("Person", "Company", [])},
)
db = Neo4jDatabase("bolt://localhost:7687", "neo4j", "password")

pipeline = GraphRAGPipeline(schema=schema, db=db, llm_fn=call_llm)

# Simple call — returns a natural language answer
answer = pipeline.query("Who works for Acme Corp?")

# Full context — returns all intermediate artefacts
ctx = pipeline.query_with_context("Who works for Acme Corp?")
print(ctx["cypher"])             # The generated (and possibly repaired) Cypher
print(ctx["repair_attempts"])    # Number of LLM repair iterations (0 = first try valid)
print(ctx["records"])            # Raw Neo4j records
print(ctx["formatted_results"])  # Markdown table injected into the answer prompt
print(ctx["answer"])             # Final LLM-generated answer
print(ctx["execution_error"])    # None, or error message if Neo4j raised

```

**What happens internally on each `query()` call:**

1. Schema is formatted via `to_cypher_context()` and injected into the system prompt.
2. LLM generates a Cypher query (first call).
3. `extract_cypher_from_text()` extracts the Cypher from the response.
4. `CypherValidator` validates it — if invalid, the LLM is asked to fix it (up to `max_repair_retries` times).
5. The validated query is executed against Neo4j.
6. Results are formatted with `format_records()` and injected into the answer prompt.
7. LLM generates the final answer (second call).

**Constructor parameters:**

| Parameter | Default | Description |
| --- | --- | --- |
| `schema` | required | Graph schema for context injection and validation |
| `db` | required | `Neo4jDatabase` for executing queries |
| `llm_fn` | required | `Callable[[str], str]` — your LLM wrapper |
| `max_repair_retries` | `2` | Max LLM repair attempts for invalid queries |
| `result_format` | `"markdown"` | Format passed to `format_records()` |
| `cypher_system_prompt` | auto | Override the Cypher-generation system prompt |
| `answer_system_prompt` | auto | Override the answer-synthesis system prompt |

**Auto-discovering the schema from a live database:**

```python
db = Neo4jDatabase("bolt://localhost:7687", "neo4j", "password")
schema = db.introspect_schema()   # discovers labels, properties, and relationships
pipeline = GraphRAGPipeline(schema=schema, db=db, llm_fn=call_llm)

```

`introspect_schema()` tries the built-in `db.schema.*` procedures first (Neo4j 4.3+) and falls back to sampling existing nodes and relationships.

---

## LLM NL-to-Cypher pipeline

`LLMNLToCypher` sends natural language text directly to an LLM to produce Cypher. It supports any OpenAI-compatible API, Anthropic, or LangChain chat model. Schema can be provided explicitly, auto-discovered from a live Neo4j database, or inferred by the LLM from the input text.

### Single-text usage

```python
from cypher_validator import LLMNLToCypher, Schema

schema = Schema(
    nodes={"Person": ["name", "age"], "Company": ["name"]},
    relationships={"WORKS_FOR": ("Person", "Company", [])},
)

# Option 1: OpenAI-compatible provider
pipeline = LLMNLToCypher(model="gpt-4o", api_key="sk-...", schema=schema)

# Option 2: Anthropic
pipeline = LLMNLToCypher.from_anthropic(schema=schema)

# Option 3: From environment variables (auto-detects provider)
pipeline = LLMNLToCypher.from_env(schema=schema)

# Generate Cypher
cypher = pipeline("John works for Apple and lives in SF.", mode="create")

# Full context with all intermediate artefacts
ctx = pipeline.ingest_with_context("John works for Apple.", mode="merge")
print(ctx["cypher"])              # Generated Cypher
print(ctx["is_valid"])            # Whether it passed validation
print(ctx["validation_errors"])   # List of error strings
print(ctx["repair_attempts"])     # Number of LLM repair iterations
```

### Batch text ingestion — `ingest_texts()`

Two-phase batch ingestion for building knowledge graphs from multiple texts:

**Phase 1 — Schema stabilization** (only when no schema is available): samples a few texts to let the LLM infer the schema, accumulating it via `Schema.merge()`.

**Phase 2 — Ingestion with stable schema**: processes remaining texts using a MERGE-only prompt, validates + repairs each query, and optionally generates provenance Cypher and executes against Neo4j.

```python
from cypher_validator import LLMNLToCypher, Schema

schema = Schema(
    nodes={"Person": ["name"], "Company": ["name"], "City": ["name"]},
    relationships={
        "WORKS_FOR": ("Person", "Company", []),
        "LIVES_IN": ("Person", "City", []),
    },
)

pipeline = LLMNLToCypher.from_env(schema=schema)

texts = [
    "Alice works for Acme Corp in New York.",
    "Bob is employed at Globex and lives in Chicago.",
    "Carol joined Initech in San Francisco.",
]

result = pipeline.ingest_texts(
    texts,
    source_ids=["doc1", "doc2", "doc3"],  # optional per-text identifiers
    provenance=True,                       # generate Chunk/MENTIONED_IN Cypher
    progress_fn=lambda cur, tot: print(f"{cur}/{tot}"),
)

print(result.total)               # 3
print(result.succeeded)           # number that passed validation
print(result.failed)              # number that failed
print(result.schema_source)       # "user", "db", or "inferred"
print(result.schema_sample_texts) # 0 when schema was provided

for chunk in result.results:
    print(f"[{chunk.index}] valid={chunk.is_valid} repairs={chunk.repair_attempts}")
    print(f"  Cypher: {chunk.cypher[:80]}...")
    if chunk.provenance_cypher:
        print(f"  Provenance: {chunk.provenance_cypher[:60]}...")
```

**With execution against Neo4j:**

```python
from cypher_validator import LLMNLToCypher, Neo4jDatabase

db = Neo4jDatabase("bolt://localhost:7687", "neo4j", "password")

pipeline = LLMNLToCypher.from_env(schema=schema, db=db)

result = pipeline.ingest_texts(
    texts,
    execute=True,      # run domain + provenance Cypher against Neo4j
    on_error="skip",   # "skip" (default) or "raise"
)

for chunk in result.results:
    print(f"[{chunk.index}] executed={chunk.executed} error={chunk.execution_error}")
```

**Without a schema (auto-inference):**

```python
pipeline = LLMNLToCypher.from_env()  # no schema, no db

result = pipeline.ingest_texts(
    texts,
    schema_sample_size=2,  # use first 2 texts to infer schema
)

# The LLM inferred the schema from the sample texts
print(result.schema)               # Schema(...)
print(result.schema_source)        # "inferred"
print(result.schema_sample_texts)  # 2
```

### Document ingestion — `ingest_document()`

Convenience wrapper that chunks a long document and delegates to `ingest_texts()`. Splits on sentence boundaries with configurable chunk size and overlap.

```python
long_text = open("article.txt").read()

result = pipeline.ingest_document(
    long_text,
    source_id="article",         # chunks get IDs: article_chunk_0, article_chunk_1, ...
    chunk_size=2000,             # max characters per chunk
    chunk_overlap=200,           # overlap between consecutive chunks
    provenance=True,
)

print(f"Chunked into {result.total} pieces, {result.succeeded} succeeded")
```

### `ChunkResult` and `IngestionResult`

| `ChunkResult` field | Type | Description |
| --- | --- | --- |
| `index` | `int` | Position in the input list |
| `source_id` | `str` | Identifier for this text |
| `text_preview` | `str` | First 80 characters of the input text |
| `cypher` | `str` | Generated domain Cypher (MERGE-based) |
| `provenance_cypher` | `str` | Deterministic `Chunk` / `MENTIONED_IN` Cypher |
| `is_valid` | `bool` | Whether the Cypher passed validation |
| `validation_errors` | `list[str]` | Validation error messages |
| `repair_attempts` | `int` | Number of LLM repair iterations |
| `executed` | `bool` | Whether the Cypher was executed against the DB |
| `execution_error` | `str \| None` | Error message if execution failed |
| `records` | `list[dict]` | Records returned by Neo4j |

| `IngestionResult` field | Type | Description |
| --- | --- | --- |
| `schema` | `Schema` | Final stabilized schema |
| `schema_source` | `str` | `"user"`, `"db"`, or `"inferred"` |
| `results` | `list[ChunkResult]` | Per-text results |
| `total` | `int` | Number of texts processed |
| `succeeded` | `int` | Number that passed validation |
| `failed` | `int` | Number that failed validation |
| `schema_sample_texts` | `int` | Number of texts used for schema inference |
| `errors` | `list[tuple[int, str]]` | `(index, error_message)` for failed texts |

### `ingest_texts()` parameters

| Parameter | Default | Description |
| --- | --- | --- |
| `texts` | required | List of natural language passages |
| `source_ids` | auto | Per-text identifiers (defaults to `text_0`, `text_1`, ...) |
| `execute` | `False` | Execute Cypher against `self.db` |
| `schema_sample_size` | `3` | Texts to sample for schema inference (Phase 1) |
| `provenance` | `True` | Generate `Chunk` / `MENTIONED_IN` provenance Cypher |
| `on_error` | `"skip"` | `"skip"` or `"raise"` |
| `progress_fn` | `None` | Callback `(current, total)` after each text |

---

## Async & parallel ingestion

All synchronous methods have async counterparts that run LLM calls concurrently. Phase 1 (schema inference) stays sequential; Phase 2 runs up to `max_concurrency` LLM calls in parallel via `asyncio.Semaphore`. An optional token-bucket rate limiter prevents exceeding TPM (Tokens Per Minute) quotas.

### Async single-text — `acall()`

```python
import asyncio
from cypher_validator import LLMNLToCypher, Schema

schema = Schema(
    nodes={"Person": ["name"], "Company": ["name"]},
    relationships={"WORKS_FOR": ("Person", "Company", [])},
)

pipeline = LLMNLToCypher.from_env(schema=schema)

# acall() is the async version of __call__()
cypher = asyncio.run(pipeline.acall("John works for Apple.", mode="create"))

# With execution
cypher, records = asyncio.run(
    pipeline.acall("John works for Apple.", mode="create", execute=True)
)
```

### Async batch ingestion — `aingest_texts()`

```python
import asyncio
from cypher_validator import LLMNLToCypher, Schema

schema = Schema(
    nodes={"Person": ["name"], "Company": ["name"], "City": ["name"]},
    relationships={
        "WORKS_FOR": ("Person", "Company", []),
        "LIVES_IN": ("Person", "City", []),
    },
)

pipeline = LLMNLToCypher.from_env(schema=schema, max_concurrency=10)

texts = [
    "Alice works for Acme Corp in New York.",
    "Bob is employed at Globex and lives in Chicago.",
    "Carol joined Initech in San Francisco.",
    # ... hundreds more
]

result = asyncio.run(pipeline.aingest_texts(
    texts,
    source_ids=["doc1", "doc2", "doc3"],
    provenance=True,
    max_concurrency=10,  # up to 10 concurrent LLM calls
    progress_fn=lambda cur, tot: print(f"{cur}/{tot}"),
))

print(result.total, result.succeeded, result.failed)
```

### Async document ingestion — `aingest_document()`

```python
long_text = open("article.txt").read()

result = asyncio.run(pipeline.aingest_document(
    long_text,
    source_id="article",
    chunk_size=2000,
    chunk_overlap=200,
    max_concurrency=10,
))
```

### Native async LLM callables

By default, `acall()` / `aingest_texts()` wrap the sync `llm_fn` with `asyncio.to_thread()`. For true async I/O, pass an `async_llm_fn`:

```python
# Option 1: Custom async callable
async def my_async_llm(prompt: str) -> str:
    async with aiohttp.ClientSession() as session:
        resp = await session.post("https://api.example.com/v1/chat", json={"prompt": prompt})
        return (await resp.json())["text"]

pipeline = LLMNLToCypher(
    llm_fn=lambda p: "",       # sync fallback (required)
    async_llm_fn=my_async_llm, # used by all async methods
    schema=schema,
)
```

The library also provides built-in async SDK adapters (used internally by the async methods when `model=` is provided):

```python
from cypher_validator.llm_pipeline import _build_async_openai_fn, _build_async_anthropic_fn

# AsyncOpenAI-backed callable
async_fn = _build_async_openai_fn(model="gpt-4o", base_url=None, api_key="sk-...", temperature=0.0)

# AsyncAnthropic-backed callable
async_fn = _build_async_anthropic_fn(model="claude-sonnet-4-20250514", api_key="sk-...", temperature=0.0)
```

### TPM rate limiting — `TokenBucketRateLimiter`

Pass `tpm_limit` to throttle LLM calls so they stay within your provider's tokens-per-minute quota:

```python
pipeline = LLMNLToCypher.from_env(
    schema=schema,
    tpm_limit=100_000,     # 100k tokens per minute
    max_concurrency=10,    # up to 10 parallel calls
)

# All async methods automatically throttle via the token bucket
result = asyncio.run(pipeline.aingest_texts(texts))
```

The rate limiter estimates token consumption as `len(prompt) // 4` and blocks until the bucket has sufficient capacity. The bucket refills continuously at `tpm / 60` tokens per second.

You can also use `TokenBucketRateLimiter` standalone:

```python
from cypher_validator import TokenBucketRateLimiter

limiter = TokenBucketRateLimiter(tpm=100_000)

async def rate_limited_call(prompt: str) -> str:
    tokens = TokenBucketRateLimiter.estimate_tokens(prompt)
    await limiter.acquire(tokens)
    return await my_llm(prompt)
```

### Async context manager

```python
async with LLMNLToCypher.from_env(schema=schema) as pipeline:
    result = await pipeline.aingest_texts(texts)
# DB connection closed automatically
```

### `aingest_texts()` parameters

| Parameter | Default | Description |
| --- | --- | --- |
| `texts` | required | List of natural language passages |
| `source_ids` | auto | Per-text identifiers (defaults to `text_0`, `text_1`, ...) |
| `execute` | `False` | Execute Cypher against `self.db` |
| `schema_sample_size` | `3` | Texts to sample for schema inference (Phase 1 — sequential) |
| `provenance` | `True` | Generate `Chunk` / `MENTIONED_IN` provenance Cypher |
| `on_error` | `"skip"` | `"skip"` or `"raise"` |
| `progress_fn` | `None` | Callback `(current, total)` after each text |
| `max_concurrency` | `None` | Override instance-level `max_concurrency` for this call |

### Constructor async parameters

| Parameter | Default | Description |
| --- | --- | --- |
| `async_llm_fn` | `None` | Async callable `(str) -> Awaitable[str]`. Falls back to `asyncio.to_thread(llm_fn)` if not set |
| `tpm_limit` | `None` | Tokens-per-minute budget. `None` = no rate limiting |
| `max_concurrency` | `5` | Default max parallel LLM calls for `aingest_texts()` |

---

## Pydantic Cypher ORM

Define your graph schema as Pydantic models and build validated, parameterized Cypher queries with a fluent API.

### Define models

```python
from cypher_validator import NodeModel, RelationshipModel

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
```

Multi-label nodes: set `__labels__ = ["Person", "Actor"]` for `(:Person:Actor)` patterns.

### Query builder

```python
from cypher_validator import Query, Cond, NodeRef, fn

# Fluent API
q = (Query()
     .match(Person, "p")
     .where(Cond("p.age", ">", 18))
     .return_("p.name", "p.age")
     .order_by("p.name")
     .limit(10))
cypher, params = q.build()
# MATCH (p:Person) WHERE p.age > 18 RETURN p.name, p.age ORDER BY p.name LIMIT 10

# Type-safe property expressions
p = NodeRef(Person, "p")
m = NodeRef(Movie, "m")
q = (Query()
     .match(p)
     .where((p.age > 18) & (p.name == "$name"))
     .return_(p.name, fn.as_(fn.count("*"), "total")))

# Path patterns
from cypher_validator import PathBuilder
path = (PathBuilder(Person, "actor")
        .rel(ActedIn, "r")
        .to(Movie, "movie")
        .rel("DIRECTED", direction="in")
        .to(Person, "director"))
q = path.to_query().return_("actor.name", "director.name")
```

Supported clauses: `match`, `optional_match`, `match_path`, `where`, `create`, `merge`, `set`, `set_props`, `remove`, `delete`, `with_`, `return_`, `order_by`, `skip`, `limit`, `unwind`, `call_subquery`, `foreach`, `union`, `raw`.

### Repository pattern

```python
from cypher_validator import Repository, Neo4jDatabase

db = Neo4jDatabase("bolt://localhost:7687", "neo4j", "password")
repo = Repository(Person, db)

# CRUD
repo.create(Person(name="Alice", age=30))
alice = repo.find_one(name="Alice")         # → Person instance or None
people = repo.find_by(age=30, limit=10)     # → [Person, ...]
repo.update({"name": "Alice"}, {"age": 31})
repo.delete(name="Alice")

# Aggregation
total = repo.count()
exists = repo.exists(name="Bob")

# Bulk operations
repo.create_many([{"name": "A", "age": 1}, {"name": "B", "age": 2}])
repo.merge_many([{"name": "A", "age": 1}], merge_keys=["name"])
```

### GraphSession

```python
from cypher_validator import GraphSession, GraphSchema

schema = GraphSchema.from_models([Person, Movie, ActedIn])
session = GraphSession(db, schema)

# Model-aware queries
people = session.query(Person, where={"name": "Alice"})
session.create(Person(name="Bob", age=25))
session.bulk_create(Person, [{"name": "C"}, {"name": "D"}])
session.neighbors(Person, match_props={"name": "Alice"})

# Apply schema DDL (constraints + indexes)
session.apply_ddl()
```

Async version: `AsyncGraphSession` with `await session.query(...)`, `await session.create(...)`, etc.

### AI agent tools

```python
from cypher_validator import AgentTools, ExtendedAgentTools

tools = ExtendedAgentTools(schema)

# OpenAI function-calling specs
specs = tools.all_tool_specs("openai")
# → [execute_cypher, create_node, create_relationship, search_nodes,
#    find_neighbors, find_path, get_graph_schema, bulk_create_nodes]

# Anthropic format
specs = tools.all_tool_specs("anthropic")

# Handle tool calls from AI agents
cypher, params = tools.handle_tool_call("create_node", {
    "label": "Person",
    "properties": {"name": "Alice", "age": 30}
})
# → ('CREATE (n:Person {name: $n_name, age: $n_age}) RETURN n', {'n_name': 'Alice', 'n_age': 30})
```

### Graph traversal

```python
from cypher_validator import Traversal

cypher, params = Traversal.neighbors(Person, match_props={"name": "Alice"}, direction="out", limit=10)
cypher, params = Traversal.shortest_path(Person, Movie, {"name": "Alice"}, {"title": "Matrix"})
cypher, params = Traversal.subgraph(Person, {"name": "Alice"}, depth=3)
cypher, params = Traversal.degree(Person, match_props={"name": "Alice"})
cypher, params = Traversal.common_neighbors(Person, Person, {"name": "Alice"}, {"name": "Bob"})
cypher, params = Traversal.path_exists(Person, Movie, {"name": "Alice"}, {"title": "Matrix"})
```

### Bulk operations

```python
from cypher_validator import BulkOps

# UNWIND-based batch operations (much faster than individual statements)
cypher, params = BulkOps.bulk_create_nodes(Person, [{"name": "A"}, {"name": "B"}])
cypher, params = BulkOps.bulk_merge_nodes(Person, items, merge_keys=["name"])
cypher, params = BulkOps.bulk_create_relationships(ActedIn, items, src_key="src_name", tgt_key="tgt_title")
cypher, params = BulkOps.bulk_delete_nodes(Person, "name", ["A", "B"])
```

### Schema management

```python
from cypher_validator import GraphSchema, SchemaDDL, SchemaDiff

# From Pydantic models
schema = GraphSchema.from_models([Person, Movie, ActedIn])

# From a live Neo4j database (auto-discovers schema)
schema = GraphSchema.from_neo4j_db(db)

# From a plain dict (e.g., received from an API)
schema = GraphSchema.from_dict({
    "nodes": {"Person": ["name", "age"]},
    "relationships": {"ACTED_IN": ["Person", "Movie", ["roles"]]}
})

# Generate DDL
ddl = SchemaDDL(schema)
for stmt in ddl.generate_all():
    db.execute(stmt)

# Compare schemas for migrations
diff = SchemaDiff(old_schema, new_schema)
print(diff.summary())
for stmt in diff.migration_ddl():
    db.execute(stmt)
```

### Dynamic model factories

```python
from cypher_validator import node, relationship

# Create models at runtime (useful for agent-discovered schemas)
City = node("City", name=(str, ...), population=(int, 0))
LivesIn = relationship("LIVES_IN", Person, City, since=(int, 2024))
```

### Cypher function wrappers

```python
from cypher_validator import fn

fn.count("n")              # count(n)
fn.count_distinct(p.name)  # count(DISTINCT p.name)
fn.sum(p.age)              # sum(p.age)
fn.avg(p.age)              # avg(p.age)
fn.collect(p.name)         # collect(p.name)
fn.coalesce(p.name, "'?'") # coalesce(p.name, '?')
fn.to_lower(p.name)        # toLower(p.name)
fn.as_(fn.count("*"), "total")  # count(*) AS total
```

### Query serialization

```python
# Serialize for agent message passing
message = q.to_json()
q2 = Query.from_json(message)  # Full roundtrip
```

---

## What the validator checks

The semantic validator performs the following checks **against the provided schema**:

### Node labels

* Every node label used (`:Person`, `:Movie`, …) must exist in the schema.
* Properties accessed on a labelled node (e.g. `n.salary` on `:Person`) must be declared for that label.
* Typos trigger a "did you mean?" suggestion when a schema label is within edit-distance 2.

### Relationship types

* Every relationship type used (`[:ACTED_IN]`, …) must exist in the schema.
* Properties accessed on a labelled relationship (e.g. `r.since` on `:WORKS_FOR`) must be declared for that type.
* Typos trigger a "did you mean?" suggestion when a schema type is within edit-distance 2.

### Relationship direction and endpoints

* For **directed** relationships (`-->` or `<--`), the source and target node labels are checked against the schema's declared endpoints.
* **Undirected** patterns (`--`) skip the endpoint-direction check.
* Nodes **without labels** are skipped (open-world assumption).

```python
# Schema: ACTED_IN: (Person → Movie)
validator.validate("MATCH (m:Movie)-[:ACTED_IN]->(p:Person) RETURN m")
# Error: "Relationship :ACTED_IN expects source label :Person, but node has label(s): :Movie"
# Error: "Relationship :ACTED_IN expects target label :Movie, but node has label(s): :Person"

# Undirected — no direction error
validator.validate("MATCH (m:Movie)-[:ACTED_IN]-(p:Person) RETURN m")  # valid

```

### Variable scope and unbound variables

* Variables in `RETURN`, `WHERE`, `SET`, `DELETE`, etc. must have been bound in a preceding `MATCH`, `CREATE`, `MERGE`, or `UNWIND`.
* `WITH` enforces a **scope reset**: only variables explicitly projected through `WITH` remain accessible afterwards.

```python
validator.validate("MATCH (n:Person) RETURN m")
# Error: "Variable 'm' is not bound in this scope"

validator.validate("MATCH (n:Person) WITH n.name AS nm RETURN n")
# Error: "Variable 'n' is not bound in this scope"  (n not projected through WITH)

validator.validate("MATCH (n:Person) WITH n.name AS nm RETURN nm")
# valid — nm was projected

```

### WHERE clause boolean operators

* `AND`, `OR`, `XOR`, and `NOT` in `WHERE` clauses are fully supported, including combinations and precedence.

```python
validator.validate(
    "MATCH (p:Person) WHERE p.age > 30 AND p.name = 'Alice' OR p.name = 'Bob' RETURN p"
)
# valid

validator.validate(
    "MATCH (p:Person) WHERE NOT p.age < 18 AND p.name = 'Alice' RETURN p"
)
# valid

```

### List comprehensions and quantifiers

* Variables introduced by `[x IN list | ...]` and `ALL(x IN list WHERE ...)` are locally scoped and don't leak.

### Open-world assumption

* Nodes and relationships **without labels/types** are never flagged (e.g. `MATCH (n) RETURN n` is always valid).
* Property access on variables without known labels is not checked.

---

## Generated query types

`CypherGenerator` supports **13** query patterns. All generated queries are guaranteed to pass `CypherValidator` with the same schema.

```python
gen = CypherGenerator(schema, seed=0)
for query_type in CypherGenerator.supported_types():
    print(f"{query_type}: {gen.generate(query_type)}")

```

Generated property values cycle through four value types: string literals (`"Alice"`), integers (`42`), booleans (`true`/`false`), and parameters (`$name`). `OPTIONAL MATCH` and `LIMIT` clauses appear randomly. `ORDER BY` queries randomly include `DESC`.

---

## Performance

The Rust core is designed for low-latency, high-throughput validation:

### Parallel batch validation

`validate_batch()` uses [Rayon](https://github.com/rayon-rs/rayon) to validate queries across all available CPU cores simultaneously. The Python GIL is released for the entire batch, so asyncio and other Python threads remain unblocked:

```python
import time

queries = ["MATCH (n:Person) RETURN n"] * 10_000

start = time.perf_counter()
results = validator.validate_batch(queries)
elapsed = time.perf_counter() - start

print(f"Validated {len(results)} queries in {elapsed:.3f}s")
# Validated 10000 queries in ~0.05s  (hardware-dependent)

```

### Capped Levenshtein

"Did you mean?" suggestions use a 1D rolling-array Levenshtein implementation with two early-exit optimisations:

1. **Length-difference short-circuit** — if `|len(a) - len(b)| > cap`, return immediately without running the algorithm.
2. **Row-minimum early exit** — if the minimum value in the current DP row already exceeds `cap`, no future row can produce a distance ≤ cap, so we exit early.

This keeps suggestion lookup fast even when the schema has many labels.

### O(1) property lookup

Node and relationship property sets are stored as Rust `HashSet<String>` internally, so `node_has_property` and `rel_has_property` are O(1) regardless of how many properties a label declares.

### Construction-time caching

`CypherGenerator` and `SemanticValidator` precompute their working data sets (label lists, relationship-type lists, per-label property maps) once at construction. Repeated calls to `generate()` / `generate_batch()` and `validate()` avoid redundant allocations.

---

## Type stubs and IDE support

Full `.pyi` stub files are included in the package, providing:

* **IDE autocompletion** for all Rust-backed classes (`Schema`, `CypherValidator`, `ValidationResult`, `CypherGenerator`, `QueryInfo`, `parse_query`)
* **mypy / pyright type checking** — all methods, attributes, and return types are fully annotated
* **Inline docstrings** accessible via IDE hover / `help()`

The stubs are automatically discovered by type checkers when the package is installed. No additional configuration is needed.

```python
# mypy will verify this correctly
from cypher_validator import Schema, CypherValidator

schema: Schema = Schema(nodes={"Person": ["name"]}, relationships={})
validator: CypherValidator = CypherValidator(schema)
result = validator.validate("MATCH (p:Person) RETURN p")
reveal_type(result.is_valid)  # Revealed type is "bool"
reveal_type(result.errors)    # Revealed type is "list[str]"

```

---

## Project structure

```
cypher_validator/
├── Cargo.toml                        # Rust crate (lib name: _cypher_validator)
├── Cargo.lock                        # Locked dependency versions
├── pyproject.toml                    # maturin mixed-package config
│
├── src/                              # Rust source
│   ├── lib.rs                        # PyO3 module registration
│   ├── error.rs                      # CypherError enum
│   ├── diagnostics.rs                # ErrorCode, Severity, Suggestion, ValidationDiagnostic
│   ├── grammar/
│   │   └── cypher.pest               # PEG grammar (Pest)
│   ├── parser/
│   │   ├── mod.rs                    # parse() entry point
│   │   ├── ast.rs                    # AST types
│   │   └── builder.rs                # Pest → AST builder (shared filter-expression helper)
│   ├── schema/
│   │   └── mod.rs                    # Schema struct
│   ├── validator/
│   │   ├── mod.rs                    # CypherValidator, ValidationResult
│   │   └── semantic.rs               # SemanticValidator (labels, props, scope, suggestions)
│   ├── generator/
│   │   └── mod.rs                    # CypherGenerator (13 query types)
│   └── bindings/
│       ├── mod.rs
│       ├── py_schema.rs              # Python Schema wrapper (incl. from_dict)
│       ├── py_validator.rs           # Python CypherValidator / ValidationResult (incl. validate_batch)
│       ├── py_generator.rs           # Python CypherGenerator
│       └── py_parser.rs              # Python parse_query / QueryInfo (incl. properties_used)
│
├── python/
│   └── cypher_validator/             # Python package (maturin python-source)
│       ├── __init__.py               # Re-exports Rust core + GLiNER2 + LLM helpers
│       ├── __init__.pyi              # Package-level type stubs (all classes and functions)
│       ├── _cypher_validator.pyi     # Rust extension type stubs
│       ├── gliner2_integration.py    # EntityNERExtractor, GLiNER2RelationExtractor,
│       │                             #   RelationToCypherConverter (incl. to_db_aware_query),
│       │                             #   NLToCypher (incl. db_aware, _collect_entity_status),
│       │                             #   Neo4jDatabase (incl. introspect_schema)
│       ├── llm_utils.py              # extract_cypher_from_text, format_records,
│       │                             #   repair_cypher, cypher_tool_spec, few_shot_examples
│       ├── llm_pipeline.py           # LLMNLToCypher, ChunkResult, IngestionResult,
│       │                             #   ingest_texts, ingest_document
│       └── rag.py                    # GraphRAGPipeline
│
└── tests/                            # 395 tests total
    ├── test_syntax.py                # PEG grammar / syntax tests
    ├── test_schema.py                # Schema API tests
    ├── test_validator.py             # Validator smoke tests
    ├── test_new_features.py          # Direction, scope, error-category, parse_query tests
    ├── test_generator.py             # CypherGenerator tests (all 13 types)
    ├── test_roundtrip.py             # Generator output validated by validator
    ├── test_gliner2_integration.py   # GLiNER2 integration tests (no ML required)
    ├── test_neo4j_integration.py     # Neo4jDatabase and NLToCypher execute=True tests
    ├── test_db_aware.py              # db_aware=True, EntityNERExtractor, _collect_entity_status,
    │                                 #   to_db_aware_query — all entity-existence combinations
    ├── test_task2_features.py        # AND/OR grammar fix, Schema.from_dict, validate_batch, properties_used
    ├── test_task3_features.py        # "Did you mean", new generator types, deduplication
    ├── test_llm_utils.py             # extract_cypher_from_text, format_records, repair_cypher,
    │                                 #   cypher_tool_spec, few_shot_examples, Schema prompt methods
    ├── test_rag.py                   # GraphRAGPipeline — construction, query, repair loop, error handling
    └── test_ingest.py                # ingest_texts, ingest_document, _chunk_text, _build_provenance_cypher

```

---

## Examples

The [`examples/`](https://www.google.com/search?q=examples/) directory contains 11 self-contained scripts covering every major feature. Each script uses the **real** `fastino/gliner2-large-v1` model (no mocks) and connects to a live Neo4j instance where applicable.

| File | Topic | Requires |
| --- | --- | --- |
| [`01_basic_validation.py`](https://www.google.com/search?q=examples/01_basic_validation.py) | Schema definition, single/batch validation, "did you mean?" | core |
| [`02_schema_serialization.py`](https://www.google.com/search?q=examples/02_schema_serialization.py) | `to_dict`, `from_dict`, `to_json`, `from_json`, `merge`, prompt helpers | core |
| [`03_cypher_generator.py`](https://www.google.com/search?q=examples/03_cypher_generator.py) | All 13 `CypherGenerator` query types, batch generation | core |
| [`04_nl_to_cypher_basic.py`](https://www.google.com/search?q=examples/04_nl_to_cypher_basic.py) | `NLToCypher` with real GLiNER2 — CREATE / MERGE / MATCH modes | gliner2 |
| [`05_db_aware_all_cases.py`](https://www.google.com/search?q=examples/05_db_aware_all_cases.py) | `db_aware=True` — 3 progressive rounds showing all MATCH/CREATE combinations | neo4j + gliner2 |
| [`06_ner_extractors.py`](https://www.google.com/search?q=examples/06_ner_extractors.py) | `EntityNERExtractor` — spaCy and HuggingFace backends, custom `label_map` | ner |
| [`07_db_aware_with_ner.py`](https://www.google.com/search?q=examples/07_db_aware_with_ner.py) | `db_aware=True` + real HuggingFace NER + real GLiNER2 + live Neo4j | neo4j + ner + gliner2 |
| [`08_neo4j_database.py`](https://www.google.com/search?q=examples/08_neo4j_database.py) | `Neo4jDatabase` — execute, execute_many, execute_and_format, introspect_schema | neo4j |
| [`09_llm_utils.py`](https://www.google.com/search?q=examples/09_llm_utils.py) | `extract_cypher_from_text`, `format_records`, `repair_cypher`, `cypher_tool_spec`, `few_shot_examples` | core |
| [`10_graph_rag_pipeline.py`](https://www.google.com/search?q=examples/10_graph_rag_pipeline.py) | Schema introspection, Cypher validation + execution, result formatting | neo4j |
| [`11_biobert_ner.py`](https://www.google.com/search?q=examples/11_biobert_ner.py) | BioBERT base vs fine-tuned biomedical NER — `label_map` adapter, full db_aware pipeline | neo4j + ner + gliner2 |

Run the core examples (no extras needed):

```bash
for f in 01 02 03 09; do
    echo "=== examples/${f}_*.py ===" && /path/to/python examples/0${f}_*.py
done

```

---

## Development

### Building

```bash
# Development build (installs editable into the active venv)
maturin develop

# Optimised release build
maturin develop --release

# Build a distributable wheel
maturin build --release

```

### Running tests

```bash
# All 395 tests
pytest tests/

# Specific test modules
pytest tests/test_task2_features.py -v   # Schema.from_dict, validate_batch, properties_used
pytest tests/test_task3_features.py -v   # "did you mean", new generator types, dedup

# GLiNER2 integration only (no gliner2 package needed — uses mocks)
pytest tests/test_gliner2_integration.py -v

# DB-aware generation and EntityNERExtractor (no ML or live DB needed — uses mocks)
pytest tests/test_db_aware.py -v

# With coverage
pytest tests/ --cov=cypher_validator

```

All GLiNER2, NER, and Neo4j tests use `unittest.mock` to simulate models and the database driver, so the full test suite runs without installing `gliner2`, `spacy`, `transformers`, or a live Neo4j instance.

### Dependency management

Python dependencies are managed with `uv`:

```bash
uv pip install maturin pytest
uv pip install gliner2   # optional, for NLToCypher

```

### CI

GitHub Actions (`.github/workflows/CI.yml`) builds wheels for Linux (x86_64, x86, aarch64, armv7, s390x, ppc64le), Linux musl, Windows (x64, x86, arm64), and macOS (x86_64, aarch64) on every push. Releases to PyPI are triggered by pushing a version tag.

