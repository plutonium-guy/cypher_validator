"""Tests for vector property type and vector index DDL generation."""

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
