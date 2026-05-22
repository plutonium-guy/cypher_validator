# cypher_validator

[![CI](https://github.com/plutonium-guy/cypher_validator/actions/workflows/CI.yml/badge.svg)](https://github.com/plutonium-guy/cypher_validator/actions/workflows/CI.yml)
[![Tests](https://github.com/plutonium-guy/cypher_validator/actions/workflows/test.yml/badge.svg)](https://github.com/plutonium-guy/cypher_validator/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)

A Rust-accelerated, schema-aware **Cypher query validator and generator** with optional **GLiNER2 relation-extraction**, a **Pydantic-based graph ORM**, and a full **LLM NL-to-Cypher pipeline**.

The parser, validator, and generator are written in **Rust** (via [pyo3](https://pyo3.rs/) + [maturin](https://github.com/PyO3/maturin)) for performance. Everything above the binding layer is pure Python.

## What's in the box

| Layer | What it does |
|---|---|
| **Parser** (Rust) | PEG grammar (Pest) → typed AST. Reports syntax errors with line/column. |
| **Validator** (Rust) | Two-pass semantic check: collects bindings then validates labels, properties, endpoints, scope, aggregates, types. Includes Levenshtein "did you mean?" + auto-fix. |
| **Generator** (Rust) | 13 query-type templates: MATCH/CREATE/MERGE/SET/DELETE/WITH/ORDER BY/UNWIND/etc., seeded from a Schema. |
| **PyO3 bindings** | `Schema`, `CypherValidator`, `ValidationResult`, `CypherGenerator`, `parse_query`. Releases the GIL during batch validation. |
| **Pydantic ORM** | `NodeModel` / `RelationshipModel`, typed `Query` builder, `Repository`, `BulkOps`, `Traversal`, `SchemaDDL`, `SchemaDiff`. Bridges to the Rust validator via `GraphSchema.to_cypher_schema()`. |
| **LLM pipeline** | `LLMNLToCypher` — schema-aware prompting, JSON-fenced schema inference, validation-repair loop, batch ingestion with provenance, sync + async, OpenAI/Anthropic/DeepSeek/LangChain builders. |
| **Graph RAG** | `GraphRAGPipeline` — full NL question → Cypher → execute → format → LLM answer chain. |
| **GLiNER2 NER/RE** | Zero-shot relation extraction → `RelationToCypherConverter` → optional Neo4j execution. DB-aware mode looks up entities before query generation. |
| **Agent tools** | `AgentTools` + `ExtendedAgentTools` produce Anthropic / OpenAI function-call specs and dispatch them against a live session. |

## Performance

Microbench (release wheel, Apple M-series):

| Workload | Throughput |
|---|---|
| `CypherValidator.validate()` | **~55 000 queries/s** |
| `parse_query()` (schema-free) | **~57 000 queries/s** |

`validate_batch()` releases the GIL and parallelizes via Rayon.

## Where to next

- New here? Start with [Installation](installation.md) → [Quickstart](quickstart.md).
- Building an LLM agent? See [Agent tools](orm/agent-tools.md) and the [LLM pipeline](llm/pipeline.md).
- Ingesting documents into a graph? [LLM pipeline → ingest_texts](llm/pipeline.md#batch-ingestion).
- Already using Neo4j? Jump to [ORM overview](orm/index.md).

## Status

| | |
|---|---|
| Repository | <https://github.com/plutonium-guy/cypher_validator> |
| License | MIT |
| Python | 3.10+ |
| Rust | 2024 edition |
| Neo4j tested | 5.26-community |
