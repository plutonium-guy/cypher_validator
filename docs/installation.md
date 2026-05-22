# Installation

## From PyPI

```bash
pip install cypher_validator
```

Wheels are pre-built for Linux (x86_64, aarch64, musl), macOS (x86_64, arm64), and Windows (x86_64). On unsupported platforms `pip` will fall back to source build (requires Rust ≥ 1.85 / edition 2024).

## Optional extras

The base install ships everything needed for validation, generation, parsing, and the Pydantic ORM. Heavy optional dependencies are kept separate.

| Need | Install |
|---|---|
| Neo4j driver (for `Neo4jDatabase`, `GraphSession`, `Repository`) | `pip install neo4j` |
| OpenAI / DeepSeek / Groq client | `pip install openai` |
| Anthropic client | `pip install anthropic` |
| LangChain backend | `pip install langchain-core` |
| GLiNER2 NER/RE | `pip install gliner2` |
| spaCy entity extractor | `pip install spacy` |
| HuggingFace Transformers entity extractor | `pip install transformers torch` |

The package defers these imports so missing extras don't break unrelated features — only the corresponding code path raises `ImportError` with the install instruction.

## From source

Requires Rust toolchain (`rustup default stable`) and `uv` or `pip`.

```bash
git clone https://github.com/plutonium-guy/cypher_validator.git
cd cypher_validator

# Create a venv via uv (recommended)
uv venv --python 3.11 .venv
source .venv/bin/activate

# Install build tooling
uv pip install maturin

# Build + install in editable mode (release optimizations)
maturin develop --release
```

The `--release` flag is important: the dev profile is roughly 5-10× slower.

## Verifying

```python
from cypher_validator import Schema, CypherValidator, parse_query

schema = Schema(
    nodes={"Person": ["name", "age"]},
    relationships={},
)
validator = CypherValidator(schema)
print(validator.validate("MATCH (p:Person) RETURN p.name").is_valid)  # True

info = parse_query("MATCH (p:Person)-[:KNOWS]->(q) RETURN p, q")
print(info.labels_used, info.rel_types_used)
# ['Person'] ['KNOWS']
```

## Live Neo4j tests

The repository's integration test suite expects a running Neo4j instance. The fastest way to spin one up:

```bash
docker run -d --name neo4j-cv \
    -p 7474:7474 -p 7687:7687 \
    -e NEO4J_AUTH=neo4j/testtest12 \
    neo4j:5.26-community

export NEO4J_URI=bolt://localhost:7687
export NEO4J_USERNAME=neo4j        # alias: NEO4J_USER
export NEO4J_PASSWORD=testtest12   # alias: NEO4J_PASS

pytest tests/ -q
```

Both env name conventions (`NEO4J_USERNAME`/`NEO4J_PASSWORD` and `NEO4J_USER`/`NEO4J_PASS`) are accepted — `tests/conftest.py` mirrors them at collection time.
