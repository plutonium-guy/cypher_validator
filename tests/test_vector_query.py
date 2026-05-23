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
        assert "doc" in cypher
        assert "sim" in cypher

    def test_vector_search_params_stored(self):
        vec = [0.5, 0.3, 0.2]
        q = Query().vector_search("my_index", vec, top_k=2)
        _, params = q.build()
        # The vector should be stored as a parameter
        stored_vectors = [v for v in params.values() if isinstance(v, list)]
        assert len(stored_vectors) == 1
        assert stored_vectors[0] == vec

    def test_vector_search_model_index_name_convention(self):
        """index name follows idx_{label_lower}_{property}_vector convention."""
        vec = [0.1] * 1536
        q = Query().vector_search_model(Document, "embedding", vec, top_k=5)
        cypher, _ = q.build()
        # Document label → document (lowercase)
        assert "idx_document_embedding_vector" in cypher

    def test_vector_search_chaining(self):
        """vector_search returns Query for fluent chaining."""
        vec = [0.1] * 5
        q = Query()
        result = q.vector_search("some_index", vec)
        assert isinstance(result, Query)

    def test_vector_search_model_chaining(self):
        """vector_search_model returns Query for fluent chaining."""
        vec = [0.1] * 1536
        q = Query()
        result = q.vector_search_model(Document, "embedding", vec)
        assert isinstance(result, Query)
