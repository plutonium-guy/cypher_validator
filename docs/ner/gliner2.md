# GLiNER2 integration

`cypher_validator.gliner2_integration` is the **non-LLM** NL → Cypher pipeline.
It uses [GLiNER2](https://huggingface.co/fastino/gliner2-large-v1) for zero-shot
relation extraction, converts the relations to Cypher via
`RelationToCypherConverter`, and optionally executes against Neo4j through the
included `Neo4jDatabase` wrapper.

Use this layer when you want fast, deterministic, low-cost extraction from
controlled relation vocabularies — and the LLM layer ([`LLMNLToCypher`](../llm/pipeline.md))
when you need open-ended schema inference.

## Pipeline shape

```text
text  ──►  GLiNER2RelationExtractor  ──►  {relation_extraction: {...}}
                                                    │
                                                    ▼
                              RelationToCypherConverter
                                  (match / merge / create / db-aware)
                                                    │
                                                    ▼
                                            (cypher, params)
                                                    │
                                                    ▼
                                       Neo4jDatabase.execute
```

All wired together by `NLToCypher`.

## `Neo4jDatabase`

```python
Neo4jDatabase(
    uri: str,
    username: str = "neo4j",
    password: str,
    database: str = "neo4j",
)
```

Thin wrapper around the official `neo4j` Python driver. Use as a context
manager or close manually:

```python
from cypher_validator import Neo4jDatabase

with Neo4jDatabase("bolt://localhost:7687", "neo4j", "password") as db:
    rows = db.execute("MATCH (n:Person) RETURN n LIMIT 5")
```

### Methods

| Method | Signature | Notes |
|---|---|---|
| `execute` | `(cypher: str, parameters: dict \| None = None) -> list[dict]` | One dict per record. Empty list when the query returns no rows. |
| `execute_and_format` | `(cypher, format="markdown", parameters=None) -> str` | Combines `execute` + [`format_records`](../llm/tools.md#format_records). |
| `execute_many` | `(queries: list[str], parameters_list: list[dict] \| None = None) -> list[list[dict]]` | Sequential execution; missing parameter dicts default to `None`. |
| `introspect_schema` | `(sample_limit: int = 1000) -> Schema` | Live schema discovery — see below. |
| `close` | `() -> None` | Closes the driver. |

### `introspect_schema`

Tries multiple strategies:

1. **`CALL db.schema.nodeTypeProperties()`** (Neo4j 4.3+) — fastest, exact.
2. **Fallback sampling** for node labels — `MATCH (n) UNWIND labels(n), keys(n) RETURN DISTINCT label, prop LIMIT $sample_limit`.
3. **`CALL db.schema.relTypeProperties()`** for relationship-property metadata.
4. **Endpoint sampling** — `MATCH (a)-[r]->(b) RETURN type(r), head(labels(a)), head(labels(b))` — always runs so endpoints are discovered even when the procedure isn't available.
5. **Fallback relationship-property sampling** when no rel props were found via the procedure.

Returns a `Schema` populated from the live graph — drop it straight into a
`CypherValidator` or `LLMNLToCypher`:

```python
db = Neo4jDatabase("bolt://localhost:7687", "neo4j", "password")
schema = db.introspect_schema(sample_limit=2000)
```

!!! tip "Cache the introspected schema"
    `introspect_schema` does up to four round-trips. If you're going to use
    the schema many times, run it once and pass the result around.

## `EntityNERExtractor`

Optional NER step for **enriching entity labels** during DB-aware query
generation. Supports two backends:

```python
EntityNERExtractor.from_spacy(model_name="en_core_web_sm", label_map=None)
EntityNERExtractor.from_transformers(
    model_name="dbmdz/bert-large-cased-finetuned-conll03-english",
    label_map=None,
    **pipeline_kwargs,
)
```

Built-in mappings translate model labels into PascalCase graph labels:

- spaCy: `PERSON → Person`, `ORG → Organization`, `GPE/LOC → Location`,
  `FAC → Facility`, `PRODUCT → Product`, `EVENT → Event`, `WORK_OF_ART → Work`,
  `LAW → Law`, `LANGUAGE → Language`, `DATE → Date`, `TIME → Time`,
  `MONEY → Money`, `QUANTITY → Quantity`, `NORP → Group`.
- HuggingFace: `PER/PERSON → Person`, `ORG → Organization`, `LOC/GPE → Location`,
  `MISC → Entity`.

`label_map=` is **merged on top** of the defaults; pass any override there.

`extract(text)` returns a list of `{"text": ..., "label": ...}` dicts. When
this extractor is wired into `NLToCypher`, it operates in **strict NER mode**
— relation triples with at least one unconfirmed endpoint are silently dropped,
which prevents schema endpoint labels from being stamped onto non-entity words
("doctor" → "Drug", etc.).

## `GLiNER2RelationExtractor`

```python
GLiNER2RelationExtractor.from_pretrained(
    model_name: str = "fastino/gliner2-large-v1",
    threshold: float = 0.5,
)
```

Wraps the GLiNER2 model. Single method to call:

```python
extractor = GLiNER2RelationExtractor.from_pretrained()
relations = extractor.extract_relations(
    "John works for Apple Inc. and lives in San Francisco.",
    ["works_for", "lives_in"],
    threshold=0.6,             # overrides instance default
)
# {
#   "relation_extraction": {
#       "works_for": [("John", "Apple Inc.")],
#       "lives_in":  [("John", "San Francisco")],
#   }
# }
```

The output always lists **every requested** relation type — missing
relations show up as empty lists, never absent keys.

## `RelationToCypherConverter`

```python
RelationToCypherConverter(
    schema: Schema | None = None,
    name_property: str = "name",
)
```

Renders relation dicts into Cypher. Four modes via dedicated methods plus
the dispatcher `convert(relations, mode)`:

| Method | Mode | Produces |
|---|---|---|
| `to_match_query(relations, return_clause=None)` | read | `MATCH (a0 {name: $a0_val})-[:REL]->(b0 {name: $b0_val})` |
| `to_merge_query(relations, return_clause=None)` | upsert | `MERGE (a0:Src {name: $a0_val}) MERGE (b0:Tgt {name: $b0_val}) MERGE (a0)-[:REL]->(b0)` |
| `to_create_query(relations, return_clause=None)` | insert | `CREATE (a0:Src {name: $a0_val})-[:REL]->(b0:Tgt {name: $b0_val})` |
| `to_db_aware_query(relations, entity_status, return_clause=None)` | mixed | MATCH for existing entities, CREATE for new ones — single round-trip. |
| `convert(relations, mode, **kwargs)` | dispatcher | Calls one of the above. Raises `ValueError` on unknown mode. |

### Internal helpers

- `_clean_pairs(pairs) -> list[tuple[str, str]]` drops falsy entries and
  coerces both sides to `str`.
- `_get_endpoints(cypher_rel) -> (src_label, tgt_label)` looks up the
  schema's relationship endpoints. Returns `("", "")` when the schema is
  absent or the rel type is unknown.
- `_build_clause(...)` constructs a single MERGE/CREATE clause given
  endpoint labels, variable names, and parameter keys.

!!! tip "Always parameterise"
    `RelationToCypherConverter` **never** interpolates entity values into
    Cypher — every value flows through `$a0_val` / `$b0_val` placeholders.
    That makes the result safe to execute even when entity text comes from
    untrusted sources.

## `NLToCypher`

```python
NLToCypher(
    extractor: GLiNER2RelationExtractor,
    schema: Schema | None = None,
    name_property: str = "name",
    db: Neo4jDatabase | None = None,
    ner_extractor: EntityNERExtractor | None = None,
)

# Builders
NLToCypher.from_pretrained(
    model_name="fastino/gliner2-large-v1",
    schema=None, threshold=0.5, name_property="name",
    db=None, ner_extractor=None,
)
NLToCypher.from_env(
    model_name="fastino/gliner2-large-v1",
    schema=None, threshold=0.5, name_property="name",
    database="neo4j", ner_extractor=None,
)
```

`from_env` reads `NEO4J_URI`, `NEO4J_USERNAME` (default `"neo4j"`), and
`NEO4J_PASSWORD` from the environment.

### `__call__`

```python
pipeline(
    text: str,
    relation_types: list[str],
    mode: str = "match",
    threshold: float | None = None,
    execute: bool = False,
    db_aware: bool = False,
    **kwargs,
) -> str | tuple[str, list[dict]]
```

- `mode` — `"match"` / `"merge"` / `"create"`. Ignored when `db_aware=True`.
- `execute=True` — also run the query against `self.db` and return
  `(cypher, results)`. Requires `db` to be set.
- `db_aware=True` — call `_collect_entity_status` first to find which
  entities already exist in the DB, then emit a hybrid MATCH/CREATE query.
  Requires `db` to be set.
- `**kwargs` — passed through to the converter (e.g. `return_clause="RETURN *"`).

### `extract_and_convert`

Same signature, but also returns the raw `relations` dict so you can inspect
what the extractor produced:

```python
relations, cypher = pipeline.extract_and_convert(text, ["works_for"], mode="merge")
relations, cypher, results = pipeline.extract_and_convert(
    text, ["works_for"], mode="merge", execute=True,
)
```

### `_collect_entity_status`

Internal helper used by `db_aware` mode. For each unique entity in the
extracted relations:

1. Assign a Cypher variable (`e0`, `e1`, …).
2. Resolve its label — from `EntityNERExtractor` if provided (strict mode),
   else from the schema's relationship endpoints.
3. Query the DB to determine whether the entity exists (`found: bool`).
4. Track an `introduced` flag — set when the variable has been emitted into
   the query, so subsequent references can reuse it without re-declaring
   label or properties.

The function returns `{entity_name: {var, label, param_key, found, introduced}}`
which `to_db_aware_query` consumes.

When `ner_extractor` is set, the helper runs in **strict NER mode**: a
relation triple is silently dropped if either endpoint isn't independently
confirmed by the NER model. This prevents spurious labels on common nouns.

## End-to-end example

```python
from cypher_validator import (
    NLToCypher, EntityNERExtractor, Neo4jDatabase, Schema,
)

schema = Schema(
    nodes={"Person": ["name"], "Company": ["name"], "Location": ["name"]},
    relationships={
        "WORKS_FOR":  ("Person",  "Company",  []),
        "LIVES_IN":   ("Person",  "Location", []),
    },
)
db = Neo4jDatabase("bolt://localhost:7687", "neo4j", "password")
ner = EntityNERExtractor.from_spacy("en_core_web_sm")

pipeline = NLToCypher.from_pretrained(
    "fastino/gliner2-large-v1",
    schema=schema,
    db=db,
    ner_extractor=ner,
)

# 1) Generation-only — no DB touch
cypher = pipeline(
    "John works for Apple Inc. and lives in San Francisco.",
    ["works_for", "lives_in"],
    mode="merge",
)

# 2) DB-aware: MATCH existing entities, CREATE missing ones
cypher, results = pipeline(
    "John works for Apple Inc. and lives in San Francisco.",
    ["works_for", "lives_in"],
    db_aware=True,
    execute=True,
)
# MATCH (e0:Person {name: $e0_val})
# CREATE (e0)-[:WORKS_FOR]->(e1:Company {name: $e1_val})
# CREATE (e0)-[:LIVES_IN]->(e2:Location {name: $e2_val})
# RETURN e0, e1, e2
```

## When to pick this over `LLMNLToCypher`

| Need | Pick |
|---|---|
| Closed relation vocabulary, predictable cost | GLiNER2 `NLToCypher` |
| Open-ended schema inference from prose | `LLMNLToCypher` |
| Strict NER gating (no labels on common nouns) | GLiNER2 + `EntityNERExtractor` |
| Schema-agnostic best-effort extraction | `LLMNLToCypher` Mode B |
| Sub-100 ms latency per text | GLiNER2 |
| Multi-sentence document ingest with provenance | `LLMNLToCypher.ingest_document` |

## Related

- [LLM pipeline](../llm/pipeline.md) — the LLM alternative.
- [Tool specs](../llm/tools.md) — `format_records` works on the records
  `Neo4jDatabase.execute` returns.
- [Schema](../core/schema.md) — the `Schema` type both pipelines accept.
