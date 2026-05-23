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
