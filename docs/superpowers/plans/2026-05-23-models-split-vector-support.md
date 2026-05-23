# models.py Split + Vector Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the 3641-line `models.py` into 6 focused modules while maintaining backwards compatibility, then add full-stack Neo4j vector embedding support with multi-provider adapters.

**Architecture:** Bottom-up module split (orm → query → schema → session → agents) with `__init__.py` re-exports for backwards compat. Vector support adds `VectorProperty` type, vector index DDL, `Query.vector_search()`, `GraphSession.vector_search()/semantic_search()`, embedding adapters in a new `embeddings.py`, and a CLI `vector search` command. Integration tests use Docker Neo4j 5.26.

**Tech Stack:** Python 3.10+, Pydantic v2, Neo4j 5.26 (Docker), optional: openai, sentence-transformers, cohere

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `python/cypher_validator/models/__init__.py` | Re-export all public names (backwards compat shim) |
| Create | `python/cypher_validator/models/orm.py` | `_NodeMeta`, `_RelMeta`, `NodeModel`, `RelationshipModel`, `node()`, `relationship()`, `_NODE_REGISTRY`, `_REL_REGISTRY`, `_to_upper_snake`, `_python_type_to_json_type` |
| Create | `python/cypher_validator/models/query.py` | `Op`, `Cond`, `CondGroup`, `RawExpr`, `Query`, `PropExpr`, `NodeRef`, `RelRef`, `_match_with_ref`, `_return_with_ref`, `_orig_match`, `_orig_return`, `CypherFn`, `fn`, `PathBuilder`, `QueryHistoryEntry`, `QueryHistory`, `QueryResult`, `QueryPlan`, `QueryStep` |
| Create | `python/cypher_validator/models/schema.py` | `GraphSchema`, `SchemaDDL`, `SchemaDiff`, `schema_to_pipeline_kwargs` |
| Create | `python/cypher_validator/models/session.py` | `GraphSession`, `AsyncGraphSession`, `Repository`, `Traversal`, `BulkOps`, `_validate_direction`, `_VALID_DIRECTIONS` |
| Create | `python/cypher_validator/models/agents.py` | `AgentTools`, `ExtendedAgentTools` |
| Delete | `python/cypher_validator/models.py` | Replaced by package |
| Create | `python/cypher_validator/embeddings.py` | `EmbeddingFn`, `BatchEmbeddingFn`, `OpenAIEmbeddings`, `SentenceTransformerEmbeddings`, `CohereEmbeddings` |
| Modify | `python/cypher_validator/__init__.py` | Add embedding adapter exports |
| Modify | `python/cypher_validator/cli.py` | Add `vector search` command |
| Create | `tests/test_models_split.py` | Import verification after split |
| Create | `tests/test_embeddings.py` | Mock-based adapter tests |
| Create | `tests/test_vector_query.py` | Vector query builder + DDL tests |
| Create | `tests/test_vector_integration.py` | Docker Neo4j round-trip tests |

---

### Task 1: Create `models/orm.py` — Base ORM Classes

**Files:**
- Create: `python/cypher_validator/models/orm.py`

This is the foundation module with zero internal dependencies. All other submodules import from here.

- [ ] **Step 1: Create the models directory**

```bash
mkdir -p python/cypher_validator/models
```

- [ ] **Step 2: Create `orm.py` with all ORM base classes**

Copy lines 1–62 (module docstring + imports), lines 63–248 (`_NODE_REGISTRY`, `_REL_REGISTRY`, `_NodeMeta`, `NodeModel`), lines 250–394 (`_RelMeta`, `_to_upper_snake`, `RelationshipModel`), lines 1559–1570 (`_python_type_to_json_type`), and lines 1578–1639 (`node()`, `relationship()`) from `models.py` into `python/cypher_validator/models/orm.py`.

The imports section for `orm.py`:

```python
"""Pydantic ORM base classes: NodeModel, RelationshipModel, metaclasses, registries."""

from __future__ import annotations

import re
from typing import (
    Any,
    ClassVar,
    Sequence,
    Type,
)

from pydantic import BaseModel, ConfigDict
```

The file should contain (in order):
1. `_NODE_REGISTRY`, `_REL_REGISTRY` dicts
2. `_NodeMeta` metaclass
3. `NodeModel` class (with all methods: `label`, `labels`, `labels_cypher`, `property_names`, `property_types`, `required_properties`, `optional_properties`, `from_record`, `from_records`, `to_property_map`, `to_create_cypher`, `to_merge_cypher`, `match_cypher`, `to_schema_description`)
4. `_RelMeta` metaclass
5. `_to_upper_snake` function
6. `RelationshipModel` class (with all methods)
7. `_python_type_to_json_type` function
8. `node()` factory function
9. `relationship()` factory function

- [ ] **Step 3: Verify orm.py imports cleanly**

Run: `cd /Volumes/external_storage/cypher_validator && /Volumes/external_storage/graph_rag_end_to_end/.venv/bin/python -c "from cypher_validator.models.orm import NodeModel, RelationshipModel, node, relationship, _NODE_REGISTRY, _REL_REGISTRY; print('OK')"`

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add python/cypher_validator/models/orm.py
git commit -m "refactor: extract models/orm.py — base ORM classes, metaclasses, registries"
```

---

### Task 2: Create `models/query.py` — Query Builder + Conditions

**Files:**
- Create: `python/cypher_validator/models/query.py`

- [ ] **Step 1: Create `query.py` with all query-related classes**

Copy from `models.py`:
- Lines 401–416: `Op` enum
- Lines 417–468: `Cond` class
- Lines 470–496: `CondGroup` class
- Lines 504–514: `RawExpr` class
- Lines 521–966: `Query` class (full, including `validate`, `explain`, serialization)
- Lines 2563–2636: `PropExpr` class
- Lines 2638–2674: `NodeRef` class
- Lines 2676–2706: `RelRef` class
- Lines 2714–2748: `_orig_match`, `_orig_return`, `_match_with_ref`, `_return_with_ref` + monkey-patch
- Lines 2756–2860: `QueryHistoryEntry`, `QueryHistory`
- Lines 1438–1496: `QueryPlan`, `QueryStep`
- Lines 1503–1552: `QueryResult`
- Lines 3144–3325: `CypherFn` class
- Lines 3325: `fn = CypherFn`
- Lines 3333–3474: `PathBuilder` class

The imports section for `query.py`:

```python
"""Query builder, conditions, Cypher functions, path builder, and typed references."""

from __future__ import annotations

import json
from enum import Enum
from typing import Any, Type

from pydantic import BaseModel, ConfigDict

from cypher_validator.models.orm import NodeModel, RelationshipModel
```

- [ ] **Step 2: Verify query.py imports cleanly**

Run: `cd /Volumes/external_storage/cypher_validator && /Volumes/external_storage/graph_rag_end_to_end/.venv/bin/python -c "from cypher_validator.models.query import Query, Cond, Op, NodeRef, CypherFn, PathBuilder; print('OK')"`

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add python/cypher_validator/models/query.py
git commit -m "refactor: extract models/query.py — query builder, conditions, CypherFn"
```

---

### Task 3: Create `models/schema.py` — Schema Management + DDL

**Files:**
- Create: `python/cypher_validator/models/schema.py`

- [ ] **Step 1: Create `schema.py` with GraphSchema, SchemaDDL, SchemaDiff**

Copy from `models.py`:
- Lines 973–1207: `GraphSchema` class
- Lines 1985–2094: `SchemaDDL` class
- Lines 2867–3006: `SchemaDiff` class
- Lines 3125–3137: `schema_to_pipeline_kwargs` function

The imports section for `schema.py`:

```python
"""GraphSchema, SchemaDDL, SchemaDiff — schema management, DDL generation, diffing."""

from __future__ import annotations

import json
from typing import Any, Sequence, Type

from cypher_validator.models.orm import (
    NodeModel,
    RelationshipModel,
    _NODE_REGISTRY,
    _REL_REGISTRY,
    node,
    relationship,
)
```

Note: `GraphSchema.from_dict()` calls `node()` and `relationship()` — both imported from orm.

- [ ] **Step 2: Verify schema.py imports cleanly**

Run: `cd /Volumes/external_storage/cypher_validator && /Volumes/external_storage/graph_rag_end_to_end/.venv/bin/python -c "from cypher_validator.models.schema import GraphSchema, SchemaDDL, SchemaDiff, schema_to_pipeline_kwargs; print('OK')"`

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add python/cypher_validator/models/schema.py
git commit -m "refactor: extract models/schema.py — GraphSchema, SchemaDDL, SchemaDiff"
```

---

### Task 4: Create `models/session.py` — Database Session + CRUD

**Files:**
- Create: `python/cypher_validator/models/session.py`

- [ ] **Step 1: Create `session.py` with session, traversal, bulk, repository classes**

Copy from `models.py`:
- Lines 1647–1655: `_VALID_DIRECTIONS`, `_validate_direction`
- Lines 1657–1837: `Traversal` class
- Lines 1844–1978: `BulkOps` class
- Lines 2101–2243: `GraphSession` class
- Lines 3013–3118: `AsyncGraphSession` class
- Lines 3481–3641: `Repository` class

The imports section for `session.py`:

```python
"""Database session, CRUD operations, traversal, bulk ops, repository."""

from __future__ import annotations

import inspect
from typing import Any, Sequence, Type

from cypher_validator.models.orm import NodeModel, RelationshipModel
from cypher_validator.models.query import Query, QueryHistory, QueryResult
from cypher_validator.models.schema import GraphSchema, SchemaDDL
```

Note: `GraphSession.apply_ddl()` uses `SchemaDDL` and `GraphSession.execute_query()` uses `Query`. `AsyncGraphSession` uses `QueryHistory`. Import `BulkOps` locally within file (it's defined in the same file, so no circular dep).

- [ ] **Step 2: Verify session.py imports cleanly**

Run: `cd /Volumes/external_storage/cypher_validator && /Volumes/external_storage/graph_rag_end_to_end/.venv/bin/python -c "from cypher_validator.models.session import GraphSession, AsyncGraphSession, Repository, Traversal, BulkOps; print('OK')"`

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add python/cypher_validator/models/session.py
git commit -m "refactor: extract models/session.py — GraphSession, AsyncGraphSession, Repository"
```

---

### Task 5: Create `models/agents.py` — AI Agent Tool Specs

**Files:**
- Create: `python/cypher_validator/models/agents.py`

- [ ] **Step 1: Create `agents.py` with AgentTools and ExtendedAgentTools**

Copy from `models.py`:
- Lines 1214–1431: `AgentTools` class
- Lines 2250–2556: `ExtendedAgentTools` class

The imports section for `agents.py`:

```python
"""AI agent tool spec generation for OpenAI/Anthropic function calling."""

from __future__ import annotations

from typing import Any, Type

from cypher_validator.models.orm import NodeModel, RelationshipModel, _python_type_to_json_type
from cypher_validator.models.query import Query
from cypher_validator.models.schema import GraphSchema
from cypher_validator.models.session import Traversal, BulkOps
```

- [ ] **Step 2: Verify agents.py imports cleanly**

Run: `cd /Volumes/external_storage/cypher_validator && /Volumes/external_storage/graph_rag_end_to_end/.venv/bin/python -c "from cypher_validator.models.agents import AgentTools, ExtendedAgentTools; print('OK')"`

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add python/cypher_validator/models/agents.py
git commit -m "refactor: extract models/agents.py — AgentTools, ExtendedAgentTools"
```

---

### Task 6: Create `models/__init__.py` + Delete Old `models.py`

**Files:**
- Create: `python/cypher_validator/models/__init__.py`
- Delete: `python/cypher_validator/models.py`

- [ ] **Step 1: Create `__init__.py` with re-exports**

```python
"""Pydantic-based Cypher ORM — backwards-compatible re-exports from submodules."""

from cypher_validator.models.orm import (  # noqa: F401
    _NODE_REGISTRY,
    _REL_REGISTRY,
    NodeModel,
    RelationshipModel,
    node,
    relationship,
    _python_type_to_json_type,
)
from cypher_validator.models.query import (  # noqa: F401
    Op,
    Cond,
    CondGroup,
    RawExpr,
    Query,
    PropExpr,
    NodeRef,
    RelRef,
    QueryHistoryEntry,
    QueryHistory,
    QueryPlan,
    QueryStep,
    QueryResult,
    CypherFn,
    fn,
    PathBuilder,
)
from cypher_validator.models.schema import (  # noqa: F401
    GraphSchema,
    SchemaDDL,
    SchemaDiff,
    schema_to_pipeline_kwargs,
)
from cypher_validator.models.session import (  # noqa: F401
    GraphSession,
    AsyncGraphSession,
    Repository,
    Traversal,
    BulkOps,
)
from cypher_validator.models.agents import (  # noqa: F401
    AgentTools,
    ExtendedAgentTools,
)
```

- [ ] **Step 2: Delete the old `models.py`**

```bash
rm python/cypher_validator/models.py
```

- [ ] **Step 3: Write `tests/test_models_split.py` — import verification**

```python
"""Verify all imports work after models.py split into package."""

import pytest


class TestBackwardsCompatImports:
    """All existing import paths must continue to work."""

    def test_import_from_models_package(self):
        from cypher_validator.models import (
            NodeModel, RelationshipModel, Query, Cond, CondGroup, Op,
            RawExpr, GraphSchema, AgentTools, ExtendedAgentTools,
            QueryPlan, QueryStep, QueryResult, Traversal, BulkOps,
            SchemaDDL, GraphSession, AsyncGraphSession, PropExpr,
            NodeRef, RelRef, QueryHistory, SchemaDiff, CypherFn, fn,
            PathBuilder, Repository, schema_to_pipeline_kwargs,
            node, relationship,
        )
        assert NodeModel is not None
        assert Query is not None
        assert GraphSchema is not None

    def test_import_from_top_level(self):
        from cypher_validator import (
            NodeModel, RelationshipModel, Query, Cond, Op,
            GraphSchema, AgentTools, SchemaDDL, GraphSession,
        )
        assert NodeModel is not None

    def test_import_from_submodules(self):
        from cypher_validator.models.orm import NodeModel, RelationshipModel
        from cypher_validator.models.query import Query, Cond, Op
        from cypher_validator.models.schema import GraphSchema, SchemaDDL
        from cypher_validator.models.session import GraphSession, Repository
        from cypher_validator.models.agents import AgentTools
        assert NodeModel is not None

    def test_registry_shared(self):
        """Registries in orm.py must be the same objects across all import paths."""
        from cypher_validator.models.orm import _NODE_REGISTRY as reg1
        from cypher_validator.models import _NODE_REGISTRY as reg2
        assert reg1 is reg2

    def test_node_factory(self):
        from cypher_validator.models import node, relationship
        Person = node("TestPerson_Split", name=(str, ...), age=(int, 0))
        assert Person.label() == "TestPerson_Split"
        assert "name" in Person.property_names()

    def test_query_builder_still_works(self):
        from cypher_validator.models import Query, Cond
        q = Query().match("Person", "p").where(Cond("p.age", ">", 18)).return_("p").build()
        cypher, params = q
        assert "MATCH" in cypher
        assert "Person" in cypher

    def test_graph_schema_from_dict(self):
        from cypher_validator.models import GraphSchema
        gs = GraphSchema.from_dict({
            "nodes": {"Person": ["name", "age"]},
            "relationships": {},
        })
        assert len(gs.node_models) == 1
```

- [ ] **Step 4: Run the split verification tests**

Run: `cd /Volumes/external_storage/cypher_validator && /Volumes/external_storage/graph_rag_end_to_end/.venv/bin/python -m pytest tests/test_models_split.py -v`

Expected: All 7 tests PASS

- [ ] **Step 5: Run the full existing test suite to verify no regressions**

Run: `cd /Volumes/external_storage/cypher_validator && /Volumes/external_storage/graph_rag_end_to_end/.venv/bin/python -m pytest tests/ -v --ignore=tests/test_models_integration.py -x`

Expected: All existing tests PASS

- [ ] **Step 6: Commit**

```bash
git add python/cypher_validator/models/__init__.py tests/test_models_split.py
git rm python/cypher_validator/models.py
git commit -m "refactor: replace models.py with models/ package — all imports preserved"
```

---

### Task 7: Add Vector Property Type + DDL (`orm.py` + `schema.py`)

**Files:**
- Modify: `python/cypher_validator/models/orm.py`
- Modify: `python/cypher_validator/models/schema.py`
- Create: `tests/test_vector_ddl.py`

- [ ] **Step 1: Write failing tests for VectorProperty + DDL**

Create `tests/test_vector_ddl.py`:

```python
"""Tests for vector property type and vector index DDL generation."""

from dataclasses import dataclass

from cypher_validator.models.orm import NodeModel, VectorProperty
from cypher_validator.models.schema import GraphSchema, SchemaDDL


class Document(NodeModel):
    __label__ = "Document"
    __vector_indexes__ = {
        "embedding": VectorProperty(dimensions=1536, similarity="cosine"),
    }
    title: str
    content: str
    embedding: list[float] = []


class TestVectorProperty:
    def test_vector_property_defaults(self):
        vp = VectorProperty(dimensions=1536)
        assert vp.dimensions == 1536
        assert vp.similarity == "cosine"

    def test_vector_property_euclidean(self):
        vp = VectorProperty(dimensions=768, similarity="euclidean")
        assert vp.similarity == "euclidean"

    def test_model_has_vector_indexes(self):
        assert "embedding" in Document.__vector_indexes__
        vp = Document.__vector_indexes__["embedding"]
        assert vp.dimensions == 1536


class TestVectorDDL:
    def test_vector_indexes_generates_ddl(self):
        schema = GraphSchema.from_models([Document])
        ddl = SchemaDDL(schema)
        stmts = ddl.vector_indexes()
        assert len(stmts) == 1
        stmt = stmts[0]
        assert "CREATE VECTOR INDEX" in stmt
        assert "idx_document_embedding_vector" in stmt
        assert "IF NOT EXISTS" in stmt
        assert "vector.dimensions" in stmt
        assert "1536" in stmt
        assert "vector.similarity_function" in stmt
        assert "cosine" in stmt

    def test_generate_all_includes_vector(self):
        schema = GraphSchema.from_models([Document])
        ddl = SchemaDDL(schema)
        stmts = ddl.generate_all()
        vector_stmts = [s for s in stmts if "VECTOR INDEX" in s]
        assert len(vector_stmts) == 1

    def test_no_vector_indexes_when_none_defined(self):
        from cypher_validator.models.orm import node
        Plain = node("Plain", name=(str, ...))
        schema = GraphSchema.from_models([Plain])
        ddl = SchemaDDL(schema)
        assert ddl.vector_indexes() == []

    def test_drop_all_includes_vector(self):
        schema = GraphSchema.from_models([Document])
        ddl = SchemaDDL(schema)
        stmts = ddl.drop_all()
        vector_drops = [s for s in stmts if "vector" in s.lower()]
        assert len(vector_drops) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Volumes/external_storage/cypher_validator && /Volumes/external_storage/graph_rag_end_to_end/.venv/bin/python -m pytest tests/test_vector_ddl.py -v`

Expected: FAIL — `ImportError: cannot import name 'VectorProperty'`

- [ ] **Step 3: Add `VectorProperty` dataclass to `orm.py`**

Add at the top of `orm.py` (after imports, before `_NODE_REGISTRY`):

```python
from dataclasses import dataclass

@dataclass
class VectorProperty:
    dimensions: int
    similarity: str = "cosine"
```

Add to `NodeModel` class:

```python
    __vector_indexes__: ClassVar[dict[str, VectorProperty]] = {}
```

- [ ] **Step 4: Add `vector_indexes()` to `SchemaDDL` in `schema.py`**

Add method to `SchemaDDL`:

```python
    def vector_indexes(self) -> list[str]:
        stmts: list[str] = []
        for m in self.schema.node_models:
            for prop, vec in getattr(m, "__vector_indexes__", {}).items():
                label = m.label()
                name = f"idx_{label.lower()}_{prop}_vector"
                stmts.append(
                    f"CREATE VECTOR INDEX {name} IF NOT EXISTS "
                    f"FOR (n:{label}) ON (n.{prop}) "
                    f"OPTIONS {{indexConfig: {{`vector.dimensions`: {vec.dimensions}, "
                    f"`vector.similarity_function`: '{vec.similarity}'}}}}"
                )
        return stmts
```

Update `generate_all()` to include vector indexes:

```python
    def generate_all(self, include_existence: bool = False) -> list[str]:
        stmts: list[str] = []
        stmts.extend(self.uniqueness_constraints())
        if include_existence:
            stmts.extend(self.existence_constraints())
        stmts.extend(self.property_indexes())
        stmts.extend(self.vector_indexes())
        stmts.extend(self.custom_constraints())
        stmts.extend(self.custom_indexes())
        return stmts
```

Update `drop_all()` to include vector indexes:

```python
    def drop_all(self) -> list[str]:
        stmts: list[str] = []
        for m in self.schema.node_models:
            for prop in m.required_properties():
                stmts.append(f"DROP CONSTRAINT uniq_{m.label().lower()}_{prop} IF EXISTS")
            for prop in m.property_names():
                stmts.append(f"DROP INDEX idx_{m.label().lower()}_{prop} IF EXISTS")
            for prop in getattr(m, "__vector_indexes__", {}):
                stmts.append(f"DROP INDEX idx_{m.label().lower()}_{prop}_vector IF EXISTS")
        return stmts
```

- [ ] **Step 5: Update exports**

Add `VectorProperty` to `models/__init__.py` re-exports from orm and to `__init__.py` top-level.

- [ ] **Step 6: Run tests**

Run: `cd /Volumes/external_storage/cypher_validator && /Volumes/external_storage/graph_rag_end_to_end/.venv/bin/python -m pytest tests/test_vector_ddl.py -v`

Expected: All 7 tests PASS

- [ ] **Step 7: Commit**

```bash
git add python/cypher_validator/models/orm.py python/cypher_validator/models/schema.py python/cypher_validator/models/__init__.py python/cypher_validator/__init__.py tests/test_vector_ddl.py
git commit -m "feat: add VectorProperty type and vector index DDL generation"
```

---

### Task 8: Add Vector Search to Query Builder + GraphSession

**Files:**
- Modify: `python/cypher_validator/models/query.py`
- Modify: `python/cypher_validator/models/session.py`
- Create: `tests/test_vector_query.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_vector_query.py`:

```python
"""Tests for vector search in Query builder and GraphSession."""

from cypher_validator.models.query import Query
from cypher_validator.models.orm import NodeModel, VectorProperty


class Document(NodeModel):
    __label__ = "Document"
    __vector_indexes__ = {
        "embedding": VectorProperty(dimensions=1536, similarity="cosine"),
    }
    title: str
    embedding: list[float] = []


class TestQueryVectorSearch:
    def test_vector_search_basic(self):
        vec = [0.1] * 1536
        q = Query().vector_search("idx_document_embedding_vector", vec, top_k=5)
        q = q.return_("node", "score")
        cypher, params = q.build()
        assert "db.index.vector.queryNodes" in cypher
        assert "idx_document_embedding_vector" in cypher
        assert "5" in cypher
        assert "YIELD node" in cypher
        assert "score" in cypher
        assert any(isinstance(v, list) for v in params.values())

    def test_vector_search_model(self):
        vec = [0.1] * 1536
        q = Query().vector_search_model(Document, "embedding", vec, top_k=10)
        q = q.return_("node", "score")
        cypher, params = q.build()
        assert "idx_document_embedding_vector" in cypher
        assert "10" in cypher

    def test_vector_search_with_filter(self):
        vec = [0.1] * 1536
        q = (Query()
             .vector_search("idx_document_embedding_vector", vec, top_k=20)
             .where("node.title CONTAINS $keyword")
             .param("keyword", "test")
             .return_("node", "score")
             .order_by("score DESC")
             .limit(5))
        cypher, params = q.build()
        assert "db.index.vector.queryNodes" in cypher
        assert "WHERE" in cypher
        assert "keyword" in params

    def test_vector_search_custom_vars(self):
        vec = [0.1] * 10
        q = Query().vector_search(
            "my_index", vec, top_k=3,
            node_var="doc", score_var="sim"
        )
        q = q.return_("doc", "sim")
        cypher, params = q.build()
        assert "YIELD doc AS doc, sim AS sim" in cypher or "YIELD node AS doc, score AS sim" in cypher
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Volumes/external_storage/cypher_validator && /Volumes/external_storage/graph_rag_end_to_end/.venv/bin/python -m pytest tests/test_vector_query.py -v`

Expected: FAIL — `AttributeError: 'Query' object has no attribute 'vector_search'`

- [ ] **Step 3: Add `vector_search()` and `vector_search_model()` to `Query`**

Add to `Query` class in `query.py`, after the `call_subquery()` method:

```python
    # -- Vector search --

    def vector_search(
        self,
        index_name: str,
        query_vector: list[float],
        top_k: int = 10,
        node_var: str = "node",
        score_var: str = "score",
    ) -> Query:
        pname = self._next_param("vec")
        self._params[pname] = query_vector
        self._clauses.append((
            "CALL",
            f"db.index.vector.queryNodes('{index_name}', {top_k}, ${pname}) "
            f"YIELD node AS {node_var}, score AS {score_var}"
        ))
        return self

    def vector_search_model(
        self,
        model: type,
        property: str,
        query_vector: list[float],
        top_k: int = 10,
        node_var: str = "node",
        score_var: str = "score",
    ) -> Query:
        label = model.label()
        index_name = f"idx_{label.lower()}_{property}_vector"
        return self.vector_search(index_name, query_vector, top_k, node_var, score_var)
```

- [ ] **Step 4: Add `vector_search()` and `semantic_search()` to `GraphSession` and `AsyncGraphSession`**

Add to `GraphSession` in `session.py`:

```python
    def vector_search(
        self,
        model: Type[NodeModel],
        index_property: str,
        query_vector: list[float],
        top_k: int = 10,
    ) -> list[Any]:
        from cypher_validator.models.query import Query
        label = model.label()
        index_name = f"idx_{label.lower()}_{index_property}_vector"
        q = (Query()
             .vector_search(index_name, query_vector, top_k)
             .return_("node", "score"))
        cypher, params = q.build()
        records = self.execute(cypher, params)
        return [{"node": model.from_record(r, key="node"), "score": r["score"]} for r in records]

    def semantic_search(
        self,
        model: Type[NodeModel],
        index_property: str,
        query: str,
        embedding_fn: Any,
        top_k: int = 10,
    ) -> list[Any]:
        vector = embedding_fn(query)
        return self.vector_search(model, index_property, vector, top_k)
```

Add equivalent async methods to `AsyncGraphSession`:

```python
    async def vector_search(
        self,
        model: Type[NodeModel],
        index_property: str,
        query_vector: list[float],
        top_k: int = 10,
    ) -> list[Any]:
        from cypher_validator.models.query import Query
        label = model.label()
        index_name = f"idx_{label.lower()}_{index_property}_vector"
        q = (Query()
             .vector_search(index_name, query_vector, top_k)
             .return_("node", "score"))
        cypher, params = q.build()
        records = await self.execute(cypher, params)
        return [{"node": model.from_record(r, key="node"), "score": r["score"]} for r in records]

    async def semantic_search(
        self,
        model: Type[NodeModel],
        index_property: str,
        query: str,
        embedding_fn: Any,
        top_k: int = 10,
    ) -> list[Any]:
        vector = embedding_fn(query)
        return await self.vector_search(model, index_property, vector, top_k)
```

- [ ] **Step 5: Run tests**

Run: `cd /Volumes/external_storage/cypher_validator && /Volumes/external_storage/graph_rag_end_to_end/.venv/bin/python -m pytest tests/test_vector_query.py -v`

Expected: All 4 tests PASS

- [ ] **Step 6: Run full test suite**

Run: `cd /Volumes/external_storage/cypher_validator && /Volumes/external_storage/graph_rag_end_to_end/.venv/bin/python -m pytest tests/ -v --ignore=tests/test_models_integration.py -x`

Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add python/cypher_validator/models/query.py python/cypher_validator/models/session.py tests/test_vector_query.py
git commit -m "feat: add vector_search() to Query builder and GraphSession"
```

---

### Task 9: Create Embedding Adapters (`embeddings.py`)

**Files:**
- Create: `python/cypher_validator/embeddings.py`
- Create: `tests/test_embeddings.py`
- Modify: `python/cypher_validator/__init__.py`

- [ ] **Step 1: Write failing tests for embedding adapters**

Create `tests/test_embeddings.py`:

```python
"""Tests for embedding adapters — all mocked, no SDK needed."""

from unittest.mock import MagicMock, patch
import pytest

from cypher_validator.embeddings import (
    EmbeddingFn,
    BatchEmbeddingFn,
    OpenAIEmbeddings,
    SentenceTransformerEmbeddings,
    CohereEmbeddings,
)


class TestEmbeddingProtocols:
    def test_callable_satisfies_embedding_fn(self):
        def my_fn(text: str) -> list[float]:
            return [0.1, 0.2]
        assert isinstance(my_fn, EmbeddingFn)


class TestOpenAIEmbeddings:
    def test_init_requires_openai(self):
        with patch.dict("sys.modules", {"openai": None}):
            with pytest.raises(ImportError, match="pip install openai"):
                OpenAIEmbeddings()

    def test_call(self):
        mock_openai = MagicMock()
        mock_embedding = MagicMock()
        mock_embedding.embedding = [0.1, 0.2, 0.3]
        mock_response = MagicMock()
        mock_response.data = [mock_embedding]
        mock_openai.OpenAI.return_value.embeddings.create.return_value = mock_response

        with patch.dict("sys.modules", {"openai": mock_openai}):
            emb = OpenAIEmbeddings(model="text-embedding-3-small")
            result = emb("hello")
            assert result == [0.1, 0.2, 0.3]

    def test_batch(self):
        mock_openai = MagicMock()
        mock_e1 = MagicMock(); mock_e1.embedding = [0.1]
        mock_e2 = MagicMock(); mock_e2.embedding = [0.2]
        mock_response = MagicMock()
        mock_response.data = [mock_e1, mock_e2]
        mock_openai.OpenAI.return_value.embeddings.create.return_value = mock_response

        with patch.dict("sys.modules", {"openai": mock_openai}):
            emb = OpenAIEmbeddings()
            result = emb.batch(["a", "b"])
            assert result == [[0.1], [0.2]]


class TestSentenceTransformerEmbeddings:
    def test_init_requires_package(self):
        with patch.dict("sys.modules", {"sentence_transformers": None}):
            with pytest.raises(ImportError, match="pip install sentence-transformers"):
                SentenceTransformerEmbeddings()

    def test_call(self):
        import numpy as np
        mock_st = MagicMock()
        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([0.1, 0.2])
        mock_st.SentenceTransformer.return_value = mock_model

        with patch.dict("sys.modules", {"sentence_transformers": mock_st}):
            emb = SentenceTransformerEmbeddings()
            result = emb("hello")
            assert result == [0.1, 0.2]


class TestCohereEmbeddings:
    def test_init_requires_cohere(self):
        with patch.dict("sys.modules", {"cohere": None}):
            with pytest.raises(ImportError, match="pip install cohere"):
                CohereEmbeddings()

    def test_call(self):
        mock_cohere = MagicMock()
        mock_response = MagicMock()
        mock_response.embeddings = [[0.1, 0.2, 0.3]]
        mock_cohere.Client.return_value.embed.return_value = mock_response

        with patch.dict("sys.modules", {"cohere": mock_cohere}):
            emb = CohereEmbeddings(api_key="test")
            result = emb("hello")
            assert result == [0.1, 0.2, 0.3]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Volumes/external_storage/cypher_validator && /Volumes/external_storage/graph_rag_end_to_end/.venv/bin/python -m pytest tests/test_embeddings.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'cypher_validator.embeddings'`

- [ ] **Step 3: Create `embeddings.py`**

Create `python/cypher_validator/embeddings.py`:

```python
"""Embedding adapters for vector search — OpenAI, Sentence-Transformers, Cohere.

All adapters are optional. They raise ImportError with install instructions
if the provider SDK is missing.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingFn(Protocol):
    def __call__(self, text: str) -> list[float]: ...


class BatchEmbeddingFn(Protocol):
    def __call__(self, text: str) -> list[float]: ...
    def batch(self, texts: list[str]) -> list[list[float]]: ...


class OpenAIEmbeddings:
    def __init__(self, model: str = "text-embedding-3-small", api_key: str | None = None):
        try:
            import openai
        except ImportError:
            raise ImportError("pip install openai")
        self._client = openai.OpenAI(api_key=api_key)
        self._model = model

    def __call__(self, text: str) -> list[float]:
        resp = self._client.embeddings.create(input=[text], model=self._model)
        return resp.data[0].embedding

    def batch(self, texts: list[str]) -> list[list[float]]:
        resp = self._client.embeddings.create(input=texts, model=self._model)
        return [d.embedding for d in resp.data]


class SentenceTransformerEmbeddings:
    def __init__(self, model: str = "all-MiniLM-L6-v2"):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise ImportError("pip install sentence-transformers")
        self._model = SentenceTransformer(model)

    def __call__(self, text: str) -> list[float]:
        return self._model.encode(text).tolist()

    def batch(self, texts: list[str]) -> list[list[float]]:
        return self._model.encode(texts).tolist()


class CohereEmbeddings:
    def __init__(self, model: str = "embed-english-v3.0", api_key: str | None = None):
        try:
            import cohere
        except ImportError:
            raise ImportError("pip install cohere")
        self._client = cohere.Client(api_key)
        self._model = model

    def __call__(self, text: str) -> list[float]:
        resp = self._client.embed(texts=[text], model=self._model, input_type="search_query")
        return resp.embeddings[0]

    def batch(self, texts: list[str]) -> list[list[float]]:
        resp = self._client.embed(texts=texts, model=self._model, input_type="search_document")
        return resp.embeddings
```

- [ ] **Step 4: Add exports to `__init__.py`**

Add to `python/cypher_validator/__init__.py`:

```python
from cypher_validator.embeddings import (  # noqa: F401
    EmbeddingFn,
    BatchEmbeddingFn,
    OpenAIEmbeddings,
    SentenceTransformerEmbeddings,
    CohereEmbeddings,
)
```

Also add `VectorProperty` to the models import block if not already done in Task 7.

- [ ] **Step 5: Run tests**

Run: `cd /Volumes/external_storage/cypher_validator && /Volumes/external_storage/graph_rag_end_to_end/.venv/bin/python -m pytest tests/test_embeddings.py -v`

Expected: All 7 tests PASS

- [ ] **Step 6: Commit**

```bash
git add python/cypher_validator/embeddings.py python/cypher_validator/__init__.py tests/test_embeddings.py
git commit -m "feat: add embedding adapters — OpenAI, SentenceTransformers, Cohere"
```

---

### Task 10: Add CLI `vector search` Command

**Files:**
- Modify: `python/cypher_validator/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_cli.py`:

```python
# ── vector search ──────────────────────────────────────────────────────


class TestVectorSearch:
    def test_vector_search_requires_index(self):
        result = runner.invoke(app, ["vector", "search", "--vector", "[0.1, 0.2]"])
        assert result.exit_code == 1

    def test_vector_search_raw_vector_no_db(self):
        result = runner.invoke(
            app,
            [
                "vector", "search",
                "--index", "idx_document_embedding_vector",
                "--vector", "[0.1, 0.2, 0.3]",
                "--uri", "bolt://localhost:7687",
                "--password", "test",
            ],
        )
        # Will fail to connect but should parse args successfully
        assert result.exit_code != 0

    def test_vector_search_missing_both_query_and_vector(self):
        result = runner.invoke(
            app,
            [
                "vector", "search",
                "--index", "idx_test_vector",
                "--uri", "bolt://localhost:7687",
                "--password", "test",
            ],
        )
        assert result.exit_code == 1
        assert "query" in result.output.lower() or "vector" in result.output.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Volumes/external_storage/cypher_validator && /Volumes/external_storage/graph_rag_end_to_end/.venv/bin/python -m pytest tests/test_cli.py::TestVectorSearch -v`

Expected: FAIL — no `vector` command

- [ ] **Step 3: Add vector search CLI command**

Add to `python/cypher_validator/cli.py`:

```python
vector_app = typer.Typer(name="vector", help="Vector search operations.")
app.add_typer(vector_app, name="vector")


@vector_app.command("search")
def vector_search(
    index: str = typer.Option(..., "--index", help="Vector index name or 'Model.property'."),
    query: Optional[str] = typer.Option(None, "--query", "-q", help="Text to embed and search for."),
    vector: Optional[str] = typer.Option(None, "--vector", help="Raw vector as JSON array."),
    top_k: int = typer.Option(10, "--top-k", "-k", help="Number of results."),
    embedding_provider: Optional[str] = typer.Option(
        None, "--embedding-provider", help="'openai', 'sentence-transformers', or 'cohere'."
    ),
    embedding_model: Optional[str] = typer.Option(None, "--embedding-model", help="Model name for provider."),
    uri: Optional[str] = typer.Option(None, "--uri", help="Neo4j URI (or NEO4J_URI env)."),
    password: Optional[str] = typer.Option(None, "--password", help="Neo4j password."),
    username: str = typer.Option("neo4j", "--username", help="Neo4j username."),
    database: str = typer.Option("neo4j", "--database", help="Neo4j database name."),
    format: OutputFormat = typer.Option(OutputFormat.text, "--format", "-f", help="Output format."),
) -> None:
    """Search a Neo4j vector index by embedding or raw vector."""
    import os

    uri_resolved = uri or os.environ.get("NEO4J_URI")
    password_resolved = password or os.environ.get("NEO4J_PASSWORD")

    if not uri_resolved or not password_resolved:
        typer.echo("ERROR: --uri and --password required (or NEO4J_URI/NEO4J_PASSWORD env).", err=True)
        raise typer.Exit(code=1)

    if not query and not vector:
        typer.echo("ERROR: Provide --query (text to embed) or --vector (raw JSON array).", err=True)
        raise typer.Exit(code=1)

    # Resolve vector
    if vector:
        query_vec = json.loads(vector)
    else:
        if not embedding_provider:
            typer.echo("ERROR: --embedding-provider required with --query.", err=True)
            raise typer.Exit(code=1)

        from cypher_validator.embeddings import (
            OpenAIEmbeddings,
            SentenceTransformerEmbeddings,
            CohereEmbeddings,
        )
        providers = {
            "openai": lambda: OpenAIEmbeddings(model=embedding_model or "text-embedding-3-small"),
            "sentence-transformers": lambda: SentenceTransformerEmbeddings(model=embedding_model or "all-MiniLM-L6-v2"),
            "cohere": lambda: CohereEmbeddings(model=embedding_model or "embed-english-v3.0"),
        }
        if embedding_provider not in providers:
            typer.echo(f"ERROR: Unknown provider '{embedding_provider}'. Use: {', '.join(providers)}", err=True)
            raise typer.Exit(code=1)
        emb_fn = providers[embedding_provider]()
        query_vec = emb_fn(query)

    # Resolve index name (support "Model.property" syntax)
    index_name = index
    if "." in index and not index.startswith("idx_"):
        parts = index.split(".", 1)
        index_name = f"idx_{parts[0].lower()}_{parts[1]}_vector"

    # Execute search
    from neo4j import GraphDatabase
    driver = GraphDatabase.driver(uri_resolved, auth=(username, password_resolved))
    try:
        with driver.session(database=database) as session:
            cypher = (
                f"CALL db.index.vector.queryNodes('{index_name}', {top_k}, $vec) "
                f"YIELD node, score RETURN node, score"
            )
            result = session.run(cypher, {"vec": query_vec})
            records = [{"node": dict(r["node"]), "score": r["score"]} for r in result]
    except Exception as e:
        typer.echo(f"ERROR: {e}", err=True)
        raise typer.Exit(code=1)
    finally:
        driver.close()

    if format == OutputFormat.json:
        typer.echo(json.dumps({"results": records, "count": len(records)}, indent=2, default=str))
    else:
        if not records:
            typer.echo("No results found.")
        else:
            for i, r in enumerate(records, 1):
                typer.echo(f"{i}. score={r['score']:.4f}  {r['node']}")

    raise typer.Exit(code=0)
```

- [ ] **Step 4: Run CLI tests**

Run: `cd /Volumes/external_storage/cypher_validator && /Volumes/external_storage/graph_rag_end_to_end/.venv/bin/python -m pytest tests/test_cli.py::TestVectorSearch -v`

Expected: All 3 tests PASS

- [ ] **Step 5: Run full test suite**

Run: `cd /Volumes/external_storage/cypher_validator && /Volumes/external_storage/graph_rag_end_to_end/.venv/bin/python -m pytest tests/ -v --ignore=tests/test_models_integration.py -x`

Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add python/cypher_validator/cli.py tests/test_cli.py
git commit -m "feat: add 'cypher vector search' CLI command"
```

---

### Task 11: Docker Neo4j Integration Tests

**Files:**
- Create: `tests/test_vector_integration.py`

- [ ] **Step 1: Write integration test file**

Create `tests/test_vector_integration.py`:

```python
"""Integration tests for vector support — requires Docker Neo4j 5.26+.

Run: docker run -d --name neo4j-vector-test \
    -p 7474:7474 -p 7687:7687 \
    -e NEO4J_AUTH=neo4j/testtest12 \
    neo4j:5.26-community

Skip with: pytest -m "not integration"
"""

import time
import pytest
from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable

from cypher_validator.models.orm import NodeModel, VectorProperty, node
from cypher_validator.models.query import Query
from cypher_validator.models.schema import GraphSchema, SchemaDDL
from cypher_validator.models.session import GraphSession

NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASS = "testtest12"


class Neo4jWrapper:
    """Minimal wrapper so GraphSession.execute() works with neo4j driver."""

    def __init__(self, driver, database="neo4j"):
        self._driver = driver
        self._database = database

    def execute(self, cypher, params=None):
        with self._driver.session(database=self._database) as session:
            result = session.run(cypher, params or {})
            return [dict(r) for r in result]


def _wait_for_neo4j(uri, auth, timeout=30):
    """Wait for Neo4j to be ready."""
    driver = GraphDatabase.driver(uri, auth=auth)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            driver.verify_connectivity()
            return driver
        except (ServiceUnavailable, Exception):
            time.sleep(1)
    raise RuntimeError(f"Neo4j not ready after {timeout}s")


@pytest.fixture(scope="module")
def neo4j_driver():
    try:
        driver = _wait_for_neo4j(NEO4J_URI, (NEO4J_USER, NEO4J_PASS), timeout=10)
    except RuntimeError:
        pytest.skip("Neo4j not available — start with: docker run -d --name neo4j-vector-test -p 7474:7474 -p 7687:7687 -e NEO4J_AUTH=neo4j/testtest12 neo4j:5.26-community")
    yield driver
    driver.close()


@pytest.fixture(autouse=True)
def clean_db(neo4j_driver):
    """Clean up test data before each test."""
    with neo4j_driver.session() as session:
        session.run("MATCH (n:TestDoc) DETACH DELETE n")
    yield
    with neo4j_driver.session() as session:
        session.run("MATCH (n:TestDoc) DETACH DELETE n")


class TestDoc(NodeModel):
    __label__ = "TestDoc"
    __vector_indexes__ = {
        "embedding": VectorProperty(dimensions=3, similarity="cosine"),
    }
    title: str
    embedding: list[float] = []


@pytest.mark.integration
class TestVectorIntegration:
    def test_create_vector_index(self, neo4j_driver):
        schema = GraphSchema.from_models([TestDoc])
        ddl = SchemaDDL(schema)
        stmts = ddl.vector_indexes()
        assert len(stmts) == 1
        with neo4j_driver.session() as session:
            session.run(stmts[0])
        # Wait for index to populate
        time.sleep(2)
        with neo4j_driver.session() as session:
            result = session.run("SHOW INDEXES YIELD name WHERE name = 'idx_testdoc_embedding_vector' RETURN name")
            names = [r["name"] for r in result]
            assert "idx_testdoc_embedding_vector" in names

    def test_insert_and_vector_search(self, neo4j_driver):
        schema = GraphSchema.from_models([TestDoc])
        ddl = SchemaDDL(schema)

        with neo4j_driver.session() as session:
            for stmt in ddl.vector_indexes():
                session.run(stmt)

        db = Neo4jWrapper(neo4j_driver)
        gs = GraphSession(db, schema)

        # Insert documents with embeddings
        gs.create(TestDoc(title="cats", embedding=[1.0, 0.0, 0.0]))
        gs.create(TestDoc(title="dogs", embedding=[0.9, 0.1, 0.0]))
        gs.create(TestDoc(title="planes", embedding=[0.0, 0.0, 1.0]))

        # Wait for index
        time.sleep(3)

        # Search for vectors similar to "cats"
        q = (Query()
             .vector_search("idx_testdoc_embedding_vector", [1.0, 0.0, 0.0], top_k=2)
             .return_("node", "score"))
        cypher, params = q.build()
        records = db.execute(cypher, params)
        assert len(records) == 2
        titles = [dict(r["node"])["title"] for r in records]
        assert titles[0] == "cats"
        assert titles[1] == "dogs"

    def test_graph_session_vector_search(self, neo4j_driver):
        schema = GraphSchema.from_models([TestDoc])
        ddl = SchemaDDL(schema)

        with neo4j_driver.session() as session:
            for stmt in ddl.vector_indexes():
                session.run(stmt)

        db = Neo4jWrapper(neo4j_driver)
        gs = GraphSession(db, schema)

        gs.create(TestDoc(title="alpha", embedding=[1.0, 0.0, 0.0]))
        gs.create(TestDoc(title="beta", embedding=[0.0, 1.0, 0.0]))

        time.sleep(3)

        results = gs.vector_search(TestDoc, "embedding", [1.0, 0.0, 0.0], top_k=1)
        assert len(results) == 1
        assert results[0]["node"].title == "alpha"
        assert results[0]["score"] > 0.9

    def test_semantic_search_with_mock_embedder(self, neo4j_driver):
        schema = GraphSchema.from_models([TestDoc])
        ddl = SchemaDDL(schema)

        with neo4j_driver.session() as session:
            for stmt in ddl.vector_indexes():
                session.run(stmt)

        db = Neo4jWrapper(neo4j_driver)
        gs = GraphSession(db, schema)

        gs.create(TestDoc(title="python", embedding=[0.8, 0.2, 0.0]))
        gs.create(TestDoc(title="rust", embedding=[0.0, 0.8, 0.2]))

        time.sleep(3)

        def mock_embed(text: str) -> list[float]:
            return [0.8, 0.2, 0.0]

        results = gs.semantic_search(TestDoc, "embedding", "python programming", mock_embed, top_k=1)
        assert len(results) == 1
        assert results[0]["node"].title == "python"
```

- [ ] **Step 2: Start Docker Neo4j**

Run: `docker run -d --name neo4j-vector-test -p 7474:7474 -p 7687:7687 -e NEO4J_AUTH=neo4j/testtest12 neo4j:5.26-community`

Wait ~10 seconds for startup.

- [ ] **Step 3: Run integration tests**

Run: `cd /Volumes/external_storage/cypher_validator && /Volumes/external_storage/graph_rag_end_to_end/.venv/bin/python -m pytest tests/test_vector_integration.py -v -m integration`

Expected: All 4 tests PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_vector_integration.py
git commit -m "test: add Docker Neo4j vector search integration tests"
```

- [ ] **Step 5: Cleanup Docker container**

```bash
docker stop neo4j-vector-test && docker rm neo4j-vector-test
```

---

### Task 12: Update `.pyi` Stub File

**Files:**
- Modify: `python/cypher_validator/__init__.pyi`

- [ ] **Step 1: Add new exports to stub file**

Add `VectorProperty` to the models import section and add the embedding adapter classes. Add `vector_search()` and `semantic_search()` method stubs to `GraphSession` and `AsyncGraphSession` if they're defined in the `.pyi`.

Specifically add:

```python
# In models section
class VectorProperty:
    dimensions: int
    similarity: str
    def __init__(self, dimensions: int, similarity: str = "cosine") -> None: ...

# In embeddings section
class EmbeddingFn(Protocol):
    def __call__(self, text: str) -> list[float]: ...

class BatchEmbeddingFn(Protocol):
    def __call__(self, text: str) -> list[float]: ...
    def batch(self, texts: list[str]) -> list[list[float]]: ...

class OpenAIEmbeddings:
    def __init__(self, model: str = ..., api_key: str | None = ...) -> None: ...
    def __call__(self, text: str) -> list[float]: ...
    def batch(self, texts: list[str]) -> list[list[float]]: ...

class SentenceTransformerEmbeddings:
    def __init__(self, model: str = ...) -> None: ...
    def __call__(self, text: str) -> list[float]: ...
    def batch(self, texts: list[str]) -> list[list[float]]: ...

class CohereEmbeddings:
    def __init__(self, model: str = ..., api_key: str | None = ...) -> None: ...
    def __call__(self, text: str) -> list[float]: ...
    def batch(self, texts: list[str]) -> list[list[float]]: ...
```

Add `vector_search` and `vector_search_model` to `Query` stub. Add `vector_search`, `semantic_search` to `GraphSession`/`AsyncGraphSession` stubs. Add `vector_indexes` to `SchemaDDL` stub.

- [ ] **Step 2: Run full test suite one final time**

Run: `cd /Volumes/external_storage/cypher_validator && /Volumes/external_storage/graph_rag_end_to_end/.venv/bin/python -m pytest tests/ -v --ignore=tests/test_models_integration.py --ignore=tests/test_vector_integration.py -x`

Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add python/cypher_validator/__init__.pyi
git commit -m "chore: update .pyi stubs for vector support and embedding adapters"
```
