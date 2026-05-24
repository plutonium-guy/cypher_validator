# Vector search & embeddings

Neo4j 5.11+ supports native vector indexes for similarity search. The ORM provides
end-to-end support: declare vector properties on your models, generate DDL, search
via the query builder or sessions, and plug in any embedding provider.

## Declare vector properties

Add `__vector_indexes__` to a `NodeModel`. Each key is a property name, each value is a
`VectorProperty` descriptor:

```python
from cypher_validator import NodeModel, VectorProperty

class Document(NodeModel):
    __label__ = "Document"
    __vector_indexes__ = {
        "embedding": VectorProperty(dimensions=1536, similarity="cosine"),
    }
    title: str
    content: str
    embedding: list[float] = []
```

`VectorProperty` accepts `dimensions` (required) and `similarity` (`"cosine"` or
`"euclidean"`, default `"cosine"`).

## Create the vector index

`SchemaDDL.vector_indexes()` generates the DDL. `generate_all()` includes it
automatically:

```python
from cypher_validator import GraphSchema, SchemaDDL

schema = GraphSchema.from_models([Document])
ddl = SchemaDDL(schema)

for stmt in ddl.generate_all():
    db.execute(stmt)

# Or just the vector indexes:
for stmt in ddl.vector_indexes():
    db.execute(stmt)
```

The generated statement:

```cypher
CREATE VECTOR INDEX idx_document_embedding_vector IF NOT EXISTS
FOR (n:Document) ON (n.embedding)
OPTIONS {indexConfig: {`vector.dimensions`: 1536, `vector.similarity_function`: 'cosine'}}
```

## Search with the Query builder

### `vector_search()`

```python
from cypher_validator import Query

q = (Query()
     .vector_search("idx_document_embedding_vector", query_vector, top_k=5)
     .where("score > 0.8")
     .return_("node.title", "score"))

cypher, params = q.build()
```

### `vector_search_model()`

Derives the index name from the model automatically:

```python
q = (Query()
     .vector_search_model(Document, "embedding", query_vector, top_k=5)
     .return_("node", "score"))
```

## Search with sessions

`GraphSession` and `AsyncGraphSession` provide high-level methods that execute the
search and hydrate results into Pydantic models:

```python
from cypher_validator import GraphSession

session = GraphSession(db, schema)

# Vector search — pass a pre-computed vector
results = session.vector_search(Document, "embedding", query_vector, top_k=5)
for r in results:
    print(r["node"].title, r["score"])  # r["node"] is a Document instance

# Semantic search — pass text, let the embedding function handle it
results = session.semantic_search(
    Document, "embedding", "what is graph RAG?", embedding_fn=embed, top_k=5
)
```

Async version:

```python
from cypher_validator import AsyncGraphSession

async with AsyncGraphSession(db, schema) as session:
    results = await session.vector_search(Document, "embedding", query_vector)
    results = await session.semantic_search(
        Document, "embedding", "graph databases", embedding_fn=embed
    )
```

## Embedding adapters

The `cypher_validator.embeddings` module provides adapters for common embedding providers.
All implement the `EmbeddingFn` protocol (`__call__(text: str) -> list[float]`) and the
`BatchEmbeddingFn` protocol (adds `.batch(texts) -> list[list[float]]`).

### OpenAI

```python
from cypher_validator.embeddings import OpenAIEmbeddings

embed = OpenAIEmbeddings(model="text-embedding-3-small")
# or with explicit API key:
embed = OpenAIEmbeddings(model="text-embedding-3-small", api_key="sk-...")

vector = embed("what is a knowledge graph?")
vectors = embed.batch(["text one", "text two"])
```

Requires: `pip install openai`

### Sentence Transformers

```python
from cypher_validator.embeddings import SentenceTransformerEmbeddings

embed = SentenceTransformerEmbeddings(model="all-MiniLM-L6-v2")
vector = embed("local embedding model")
```

Requires: `pip install sentence-transformers`

### Cohere

```python
from cypher_validator.embeddings import CohereEmbeddings

embed = CohereEmbeddings(model="embed-english-v3.0", api_key="...")
vector = embed("cohere embedding")
```

Requires: `pip install cohere`

### Custom adapters

Any callable matching the protocol works:

```python
from cypher_validator.embeddings import EmbeddingFn

def my_embed(text: str) -> list[float]:
    return [0.0] * 384  # your embedding logic

assert isinstance(my_embed, EmbeddingFn)  # runtime_checkable
session.semantic_search(Document, "embedding", "query", embedding_fn=my_embed)
```

## CLI

The `cypher vector-search` command runs vector searches from the terminal:

```bash
# With a pre-computed vector (JSON array)
cypher vector-search --index idx_document_embedding_vector \
    --vector '[0.1, 0.2, ...]' --top-k 5

# With text + embedding provider
cypher vector-search --index idx_document_embedding_vector \
    --text "graph databases" --provider openai --top-k 5
```

Requires `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD` environment variables and
(for `--provider openai`) an `OPENAI_API_KEY`.

## End-to-end example

```python
from cypher_validator import (
    NodeModel, VectorProperty, GraphSchema, SchemaDDL, GraphSession,
)
from cypher_validator.embeddings import OpenAIEmbeddings

# 1. Define model with vector index
class Article(NodeModel):
    __label__ = "Article"
    __vector_indexes__ = {
        "embedding": VectorProperty(dimensions=1536, similarity="cosine"),
    }
    title: str
    embedding: list[float] = []

# 2. Create schema + apply DDL
schema = GraphSchema.from_models([Article])
session = GraphSession(db, schema)
session.apply_ddl()

# 3. Ingest with embeddings
embed = OpenAIEmbeddings()
for title in ["Graph RAG overview", "Neo4j fundamentals"]:
    vec = embed(title)
    session.create(Article(title=title, embedding=vec))

# 4. Search
results = session.semantic_search(
    Article, "embedding", "how do knowledge graphs work?",
    embedding_fn=embed, top_k=3
)
for r in results:
    print(f"{r['node'].title} (score: {r['score']:.3f})")
```
