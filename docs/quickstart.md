# Quickstart

Five-minute tour of the main capabilities.

## 1. Validate a query against a schema

```python
from cypher_validator import Schema, CypherValidator

schema = Schema(
    nodes={
        "Person":  ["name", "age", "email"],
        "Company": ["name", "founded"],
    },
    relationships={
        "WORKS_FOR": ("Person", "Company", ["since"]),
    },
)

validator = CypherValidator(schema)

result = validator.validate(
    "MATCH (p:Persn)-[:WORKS_FOR]->(c:Company) RETURN p.nm"
)
print(result.is_valid)        # False
for d in result.diagnostics:
    print(d.code, d.message)
# E201 Unknown node label: :Persn, did you mean :Person?
# E303 Unknown property 'nm' on variable 'p' with label :Person, did you mean 'name'?
print(result.fixed_query)
# MATCH (p:Person)-[:WORKS_FOR]->(c:Company) RETURN p.name
```

`fixed_query` is populated only when every error has a corresponding suggestion — apply with confidence or feed back to an LLM.

## 2. Generate sample queries

```python
from cypher_validator import CypherGenerator

gen = CypherGenerator(schema, seed=42)
print(gen.generate("match_where_return"))
# MATCH (p:Person) WHERE p.age > 27 RETURN p
print(gen.generate("create_relationship"))
# CREATE (p:Person {name: $p_1})-[:WORKS_FOR {since: 2020}]->(c:Company {name: $c_2})
```

Thirteen query types are supported — see [Generator](core/generator.md).

## 3. Parse without a schema

```python
from cypher_validator import parse_query

info = parse_query(
    "MATCH (p:Person)-[:WORKS_FOR]->(c:Company) "
    "WHERE EXISTS { (p)-[:LIVES_IN]->(:City) } "
    "RETURN p.name"
)
print(info.is_valid, info.labels_used, info.rel_types_used, info.properties_used)
# True ['City', 'Company', 'Person'] ['LIVES_IN', 'WORKS_FOR'] ['name']
```

Labels and rel-types from subqueries / pattern comprehensions / `EXISTS` are included.

## 4. Build queries with the Pydantic ORM

```python
from cypher_validator import (
    NodeModel, RelationshipModel, Query, GraphSchema, CypherValidator
)

class Person(NodeModel):
    __label__ = "Person"
    name: str
    age: int = 0

class Company(NodeModel):
    __label__ = "Company"
    name: str

class WorksFor(RelationshipModel):
    __source__ = Person
    __target__ = Company
    __rel_type__ = "WORKS_FOR"
    since: int = 0

schema = GraphSchema.from_models([Person, Company, WorksFor])
validator = CypherValidator(schema.to_cypher_schema())

q = (
    Query()
    .match_path((Person, "p", None), (WorksFor, "r", None), (Company, "c", None))
    .where("p.age > $min_age")
    .params(min_age=30)
    .return_("p.name AS name", "c.name AS company", "r.since AS since")
)
cypher, params = q.build()
print(cypher)
# MATCH (p:Person)-[r:WORKS_FOR]->(c:Company) WHERE p.age > $min_age
#   RETURN p.name AS name, c.name AS company, r.since AS since
assert validator.validate(cypher).is_valid
```

See [Query builder](orm/query-builder.md) for the full API.

## 5. Repository pattern

```python
from cypher_validator import Neo4jDatabase, Repository

db = Neo4jDatabase("bolt://localhost:7687", "neo4j", "password")
repo = Repository(Person, db)

repo.create(Person(name="Alice", age=31))
repo.create_many([
    {"name": "Bob",   "age": 28},
    {"name": "Carol", "age": 45},
])

print(repo.count())                              # 3
print(repo.find_one(name="Alice").age)           # 31
repo.update({"name": "Alice"}, {"age": 32})
repo.delete(name="Bob")
```

## 6. LLM pipeline — natural language → Cypher

```python
from cypher_validator import LLMNLToCypher
from openai import OpenAI

client = OpenAI(api_key="sk-...")
def llm_fn(prompt: str) -> str:
    r = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
    )
    return r.choices[0].message.content

pipe = LLMNLToCypher(llm_fn=llm_fn, schema=schema.to_cypher_schema())
cypher = pipe(
    "John works for Apple Inc. and lives in San Francisco.",
    mode="create",
)
print(cypher)
```

The pipeline auto-runs `CypherValidator` after generation and feeds errors back to the LLM up to `max_repair_retries` times. See [LLM pipeline](llm/pipeline.md).

## 7. Full Graph RAG question answering

```python
from cypher_validator import GraphRAGPipeline

rag = GraphRAGPipeline(schema.to_cypher_schema(), db, llm_fn=llm_fn)
answer = rag.query("Who works at Apple?")
print(answer)
```

The pipeline runs the 5-step Cypher → execute → format → answer loop in `query_with_context()`; see [Graph RAG](llm/rag.md).

## Next

Pick a deeper guide:

- [Validator](core/validator.md) — error codes, suggestions, auto-fix
- [Pydantic ORM](orm/index.md) — model declarations, repository, sessions
- [LLM pipeline](llm/pipeline.md) — ingestion, repair loop, async + rate limiting
- [Graph RAG](llm/rag.md) — full question-answering pipeline
