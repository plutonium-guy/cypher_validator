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
